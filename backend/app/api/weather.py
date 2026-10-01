"""/api/weather and /api/environment."""

from __future__ import annotations

import asyncio

import httpx
import pandas as pd
from fastapi import APIRouter, Query

from backend.app.services.environment import local_environment
from backend.app.services.firms import event_to_dict, firms_service
from backend.app.services.weather import WeatherUnavailable, forecast_summary, weather_service
from backend.app.utils.errors import APIError

router = APIRouter(tags=["weather"])


async def _wx(lat: float, lon: float) -> dict:
    try:
        return await weather_service.fetch(lat, lon)
    except WeatherUnavailable:
        raise APIError(503, "weather_unavailable", "Weather service unavailable.")


@router.get("/weather/current")
async def current(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    wx = await _wx(lat, lon)
    return {"source": wx["source"], "fetched_at": wx["fetched_at"], "latitude": wx["latitude"],
            "longitude": wx["longitude"], "current": wx["current"]}


@router.get("/weather/forecast")
async def forecast(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    wx = await _wx(lat, lon)
    return wx | {"summary": forecast_summary(wx)}


@router.get("/environment/{fire_id}")
async def environment(fire_id: str):
    snap = firms_service.snapshot
    row = firms_service.event_row(fire_id)
    if snap is None or row is None:
        raise APIError(404, "fire_not_found", "Fire event not found.")
    lat, lon = float(row["lat"]), float(row["lon"])
    weather, weather_error = None, None
    try:
        wx = await weather_service.fetch(lat, lon)
        await weather_service.record(fire_id, wx)
        weather = {"source": wx["source"], "fetched_at": wx["fetched_at"], "current": wx["current"],
                   "summary": forecast_summary(wx), "grid_elevation_m": wx["grid_elevation_m"]}
    except WeatherUnavailable:
        weather_error = "Weather service unavailable."
    local = await asyncio.to_thread(local_environment, lon, lat)
    det = firms_service.event_detections(fire_id)
    ev = event_to_dict(row, snap)
    fire = {
        "active_fire_count": ev["detection_count"], "high_confidence_count": ev["high_confidence_count"],
        "frp_sum_mw": ev["frp_sum_mw"], "frp_max_mw": ev["frp_max_mw"], "latest_observation": ev["last_seen"],
        "first_observation": ev["first_seen"], "satellites": ev["satellites"], "footprint_method": ev["footprint_method"],
        "detections_by_day": {str(k): int(v) for k, v in det.groupby(pd.to_datetime(det["acq_datetime"]).dt.date).size().items()},
        "source": snap.source,
    }
    return {"fire_id": fire_id, "latitude": lat, "longitude": lon, "weather": weather, "weather_error": weather_error,
            "local": local, "fire": fire}


@router.get("/search")
async def search(q: str = Query(..., min_length=2, max_length=100)):
    """Coordinates ("lat, lon"), fire IDs, or place names (Open-Meteo geocoding)."""
    q = q.strip()
    parts = [p for p in q.replace(";", ",").replace(" ", ",").split(",") if p]
    if len(parts) == 2:
        try:
            la, lo = float(parts[0]), float(parts[1])
            if -90 <= la <= 90 and -180 <= lo <= 180:
                return {"results": [{"type": "coordinate", "name": f"{la:.4f}, {lo:.4f}", "latitude": la, "longitude": lo}]}
        except ValueError:
            pass
    if q.upper().startswith("FE-"):
        row = firms_service.event_row(q.upper())
        if row is not None:
            return {"results": [{"type": "fire", "name": q.upper(), "latitude": float(row["lat"]), "longitude": float(row["lon"])}]}
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": q, "count": 8})
            r.raise_for_status()
        res = r.json().get("results") or []
    except Exception:
        raise APIError(503, "geocoding_unavailable", "Place search unavailable.")
    return {"results": [{"type": "place", "name": ", ".join(x for x in (p.get("name"), p.get("admin1"), p.get("country")) if x),
                         "latitude": p["latitude"], "longitude": p["longitude"]} for p in res]}
