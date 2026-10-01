import httpx

from backend.app.alerts import engine
from backend.app.services import weather as weather_mod


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["mongodb"] is True


def test_fires_clustered(client):
    r = client.get("/api/fires/active")
    body = r.json()
    assert r.status_code == 200 and body["meta"]["data_class"] == "observed"
    counts = sorted(row[3] for row in body["rows"])
    assert counts == [1, 3]           # three nearby detections form one event; the distant one is separate
    big = max(body["rows"], key=lambda row: row[3])
    d = client.get(f"/api/fires/{big[0]}").json()
    assert d["event"]["detection_count"] == 3 and len(d["detections"]) == 3
    assert d["event"]["in_model_domain"] is True


def test_fire_not_found(client):
    r = client.get("/api/fires/FE-DOESNOTEXIST")
    assert r.status_code == 404 and r.json()["error"]["code"] == "fire_not_found"


def test_nearby(client):
    r = client.get("/api/fires/nearby", params={"lat": 41.0, "lon": -123.2, "radius_km": 10})
    assert len(r.json()["events"]) == 1


def test_weather_unavailable_is_reported(client, monkeypatch):
    async def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx.AsyncClient, "get", boom)
    weather_mod.weather_service._cache.clear()
    r = client.get("/api/weather/current", params={"lat": 10, "lon": 10})
    assert r.status_code == 503 and r.json()["error"]["message"] == "Weather service unavailable."


def test_models_compare_without_evaluation_never_fabricates(client, monkeypatch, tmp_path):
    from geo import registry
    monkeypatch.setattr(registry, "path", lambda rel: tmp_path / rel)
    r = client.get("/api/models/compare").json()
    assert r["status"] == "not_evaluated"


def test_validation_error_shape(client):
    r = client.get("/api/fires/nearby", params={"lat": 200, "lon": 0})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


# ------------------------------------------------------------- alert logic (pure)
def test_small_weather_change_no_alert():
    prev = {"wind_speed_10m": 3.3, "wind_direction_10m": 45, "temperature_2m": 31, "relative_humidity_2m": 38}
    new = {"wind_speed_10m": 4.0, "wind_direction_10m": 60, "temperature_2m": 32, "relative_humidity_2m": 35}
    assert engine.weather_change(prev, new) is None


def test_material_weather_change_alert():
    prev = {"wind_speed_10m": 3.3, "wind_direction_10m": 45, "temperature_2m": 31, "relative_humidity_2m": 38}
    new = {"wind_speed_10m": 7.5, "wind_direction_10m": 225, "temperature_2m": 35, "relative_humidity_2m": 21}
    a = engine.weather_change(prev, new)
    assert a is not None and a.type == "WEATHER_CHANGE" and a.severity == "HIGH"
    assert any("NE -> SW" in line for line in a.lines)
    assert any("38% -> 21%" in line for line in a.lines)


def test_prediction_change_thresholds():
    prev = [{"label": "24h", "status": "ok", "predicted_area_km2": 1.20, "horizon_min": 1440}]
    same = [{"label": "24h", "status": "ok", "predicted_area_km2": 1.25, "horizon_min": 1440}]
    big = [{"label": "24h", "status": "ok", "predicted_area_km2": 1.86, "horizon_min": 1440}]
    assert engine.prediction_change(prev, same) is None
    a = engine.prediction_change(prev, big, cause="Significant weather change detected.")
    assert a.severity == "WARNING" and "1.20 -> 1.86" in a.lines[0] and a.lines[-1].startswith("Cause:")


def test_fire_activity_change():
    assert engine.fire_activity_change({"detection_count": 10}, {"detection_count": 12}) is None
    a = engine.fire_activity_change({"detection_count": 10, "frp_sum_mw": 50}, {"detection_count": 45, "frp_sum_mw": 300})
    assert a.severity == "HIGH"


def test_severity_ordering():
    assert engine.max_sev("INFO", None, "HIGH", "WARNING") == "HIGH"
    assert engine.level_for(5.0, {"INFO": 3, "WARNING": 5}) == "WARNING"
