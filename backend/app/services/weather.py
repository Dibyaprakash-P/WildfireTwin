"""Open-Meteo current + forecast weather (no API key required).

Requested (Open-Meteo forecast API parameter names):
  current: temperature_2m, relative_humidity_2m, wind_speed_10m, wind_direction_10m,
           wind_gusts_10m, precipitation
  hourly:  temperature_2m, relative_humidity_2m, dew_point_2m, wind_speed_10m,
           wind_direction_10m, wind_gusts_10m, precipitation, soil_moisture_3_to_9cm,
           vapour_pressure_deficit
  wind_speed_unit=ms, timezone=GMT, past_days=3 (for fuel-moisture history),
  forecast_days=4 (covers the 72 h horizon).
Units returned by the API are kept and recorded alongside each value.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone

import httpx
import numpy as np

from backend.app.config import get_settings
from backend.app.db import db_available, get_db
from backend.app.utils.events import emit

log = logging.getLogger(__name__)

CURRENT_VARS = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
                "precipitation"]
HOURLY_VARS = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "wind_speed_10m", "wind_direction_10m",
               "wind_gusts_10m", "precipitation", "soil_moisture_3_to_9cm", "vapour_pressure_deficit"]
SOURCE = "Open-Meteo Forecast API (best-match NWP models)"


def _fix_unit(u: str | None) -> str | None:
    """Repair UTF-8 text that was decoded as Latin-1 somewhere upstream (e.g. 'Â°C' -> '°C')."""
    if not isinstance(u, str):
        return u
    try:
        return u.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return u


class WeatherUnavailable(RuntimeError):
    pass


class WeatherService:
    def __init__(self) -> None:
        self._cache: dict[tuple[float, float], tuple[float, dict]] = {}
        self._lock = asyncio.Lock()

    async def fetch(self, lat: float, lon: float, force: bool = False) -> dict:
        s = get_settings()
        key = (round(lat, 2), round(lon, 2))
        hit = self._cache.get(key)
        if hit and not force and time.time() - hit[0] < s.weather_cache_seconds:
            return hit[1]
        params = {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "current": ",".join(CURRENT_VARS),
                  "hourly": ",".join(HOURLY_VARS), "wind_speed_unit": "ms", "timezone": "GMT",
                  "past_days": 3, "forecast_days": 4}
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=s.http_timeout_seconds) as c:
                    r = await c.get(s.open_meteo_url, params=params)
                    r.raise_for_status()
                    data = json.loads(r.content.decode("utf-8"))
                break
            except Exception as exc:  # retry: GET is idempotent
                last_exc = exc
                await asyncio.sleep(0.5 * (attempt + 1))
        else:
            await emit("weather", f"Weather service unavailable ({type(last_exc).__name__})", "WARNING")
            raise WeatherUnavailable("Weather service unavailable.")
        out = self._normalize(data, lat, lon)
        self._cache[key] = (time.time(), out)
        return out

    @staticmethod
    def _normalize(data: dict, lat: float, lon: float) -> dict:
        cur = data.get("current", {})
        cu = {k: _fix_unit(v) for k, v in data.get("current_units", {}).items()}
        hourly = data.get("hourly", {})
        hu = {k: _fix_unit(v) for k, v in data.get("hourly_units", {}).items()}
        fetched = datetime.now(timezone.utc)
        times = [t + "Z" if not t.endswith("Z") else t for t in hourly.get("time", [])]
        # index of the hour containing "now"
        now_iso = cur.get("time", "")
        now_idx = 0
        if times:
            now_dt = datetime.fromisoformat((now_iso or times[0]).replace("Z", "")).replace(tzinfo=timezone.utc)
            arr = np.array([datetime.fromisoformat(t.replace("Z", "")).replace(tzinfo=timezone.utc).timestamp() for t in times])
            now_idx = int(np.clip(np.searchsorted(arr, now_dt.timestamp(), side="right") - 1, 0, len(arr) - 1))
        fingerprint = hashlib.sha1(json.dumps({k: hourly.get(k) for k in HOURLY_VARS}, sort_keys=True).encode()).hexdigest()[:16]
        return {
            "source": SOURCE, "data_class": "observed/forecast (NWP)", "fetched_at": fetched.isoformat(),
            "latitude": data.get("latitude", lat), "longitude": data.get("longitude", lon),
            "grid_elevation_m": data.get("elevation"),
            "current": {"time": (now_iso + "Z") if now_iso and not now_iso.endswith("Z") else now_iso,
                        "values": {k: cur.get(k) for k in CURRENT_VARS}, "units": {k: cu.get(k) for k in CURRENT_VARS}},
            "hourly": {"time": times, **{k: hourly.get(k) for k in HOURLY_VARS}},
            "hourly_units": {k: hu.get(k) for k in HOURLY_VARS},
            "now_index": now_idx, "fingerprint": fingerprint,
        }

    async def record(self, fire_id: str | None, wx: dict) -> None:
        """Persist a compact snapshot (current values + forecast summary) for change detection."""
        if not db_available():
            return
        doc = {"fire_id": fire_id, "fetched_at": datetime.fromisoformat(wx["fetched_at"]),
               "location": {"type": "Point", "coordinates": [float(wx["longitude"]), float(wx["latitude"])]},
               "source": wx["source"], "current": wx["current"], "fingerprint": wx["fingerprint"],
               "forecast_summary": forecast_summary(wx)}
        await get_db().weather_conditions.insert_one(doc)


def forecast_summary(wx: dict, horizons_h: tuple[int, ...] = (1, 6, 12, 24, 48, 72)) -> dict:
    """Means over [now, now + h) for each horizon from the hourly series."""
    h = wx["hourly"]
    k = wx["now_index"]
    out = {}
    for hz in horizons_h:
        sl = slice(k, k + max(1, hz))
        def mean(name):
            vals = [v for v in (h.get(name) or [])[sl] if v is not None]
            return float(np.mean(vals)) if vals else None
        ws = [v for v in (h.get("wind_speed_10m") or [])[sl] if v is not None]
        wd = [v for v in (h.get("wind_direction_10m") or [])[sl] if v is not None]
        u = v_ = None
        if ws and wd and len(ws) == len(wd):
            rad = np.radians(wd)
            u, v_ = float(np.mean(-np.array(ws) * np.sin(rad))), float(np.mean(-np.array(ws) * np.cos(rad)))
        precip = [v for v in (h.get("precipitation") or [])[sl] if v is not None]
        out[f"{hz}h"] = {"temperature_2m": mean("temperature_2m"), "relative_humidity_2m": mean("relative_humidity_2m"),
                         "wind_speed_10m": mean("wind_speed_10m"), "wind_u": u, "wind_v": v_,
                         "precipitation_sum": float(np.sum(precip)) if precip else None,
                         "soil_moisture_3_to_9cm": mean("soil_moisture_3_to_9cm"), "hours_available": len(ws)}
    return out


weather_service = WeatherService()
