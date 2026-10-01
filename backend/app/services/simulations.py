"""On-demand REFERENCE simulations (WTRS) and imports of external FARSITE/FlamMap results.

Reference simulations are physics-based (Rothermel + MTT) and labelled
data_class="simulated". They are distinct from WildfireTwin neural predictions.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.services.firms import firms_service
from backend.app.services.weather import weather_service
from backend.app.utils.errors import APIError
from backend.app.utils.events import bus, emit
from geo.footprint import rasterize_detections
from geo.landscape import LandscapeUnavailable, build_landscape
from geo.overlay import arrival_png, mask_png, write_geotiff
from geo.rasters import AnalysisGrid
from simulation.reference import SIMULATOR_NAME, SIMULATOR_VERSION, mask_ignition, point_ignition, run_reference
from simulation.weather_sources import constant_series, era5_series, era5_store, hourly_series

MAX_HOURS = 72
CELLS = (30.0, 60.0, 120.0)


def sim_out(doc: dict) -> dict:
    d = {k: v for k, v in doc.items() if k != "_id"}
    for k in ("created_at", "finished_at"):
        if isinstance(d.get(k), datetime):
            d[k] = d[k].isoformat()
    return d


def _weather(req: dict, lon: float, lat: float, hours: int, wx: dict | None):
    src = req["weather_source"]
    if src == "constant":
        c = req.get("constant") or {}
        try:
            return constant_series(hours + 1, float(c["temperature_c"]), float(c["rh_pct"]),
                                   float(c["wind_speed_ms"]), float(c["wind_from_deg"]))
        except (KeyError, TypeError, ValueError):
            raise APIError(400, "invalid_weather", "constant weather requires temperature_c, rh_pct, wind_speed_ms, wind_from_deg")
    if src == "era5":
        st = era5_store()
        if not st.available:
            raise APIError(409, "era5_unavailable", "Local ERA5 data not processed.")
        start = np.datetime64(str(req.get("era5_start", "")).replace("Z", "")[:16])
        t0, t1 = st.time_range()
        if not (t0 + np.timedelta64(72, "h") <= start <= t1 - np.timedelta64(hours + 1, "h")):
            raise APIError(400, "era5_out_of_range", f"ERA5 start must be within {t0} + 72 h and {t1} - duration.")
        return era5_series(lon, lat, start, hours + 1)
    if src == "open_meteo":
        if wx is None:
            raise APIError(503, "weather_unavailable", "Weather service unavailable.")
        h = wx["hourly"]
        k = wx["now_index"]
        if k + hours + 1 > len(h["time"]):
            raise APIError(400, "forecast_too_short", "Forecast unavailable for the requested duration.")
        return hourly_series(h["time"], h["temperature_2m"], h["relative_humidity_2m"], h["wind_speed_10m"],
                             h["wind_direction_10m"], h["precipitation"], k, wx["source"])
    raise APIError(400, "invalid_weather", "weather_source must be open_meteo, era5 or constant")


def _run(sim_id: str, req: dict, lon: float, lat: float, det, wx: dict | None) -> dict:
    s = get_settings()
    hours = int(req["duration_hours"])
    cell = float(req["cell_m"])
    grid = AnalysisGrid.centered(lon, lat, cell, int(req.get("grid_size", 128)))
    land = build_landscape(grid)
    if req["ignition"] == "fire_footprint":
        m0, fmeta = rasterize_detections(det, grid)
        if m0.sum() == 0:
            raise APIError(400, "empty_footprint", "No detections inside the simulation window.")
        init = mask_ignition(m0 > 0)
    else:
        r = c = grid.size // 2
        init, fmeta, m0 = point_ignition(grid.shape, r, c), {"method": "point ignition at window centre"}, None
    ws = _weather(req, lon, lat, hours, wx)
    run = run_reference(land, ws, init, hours, float(req.get("live_herb", 0.6)), float(req.get("live_woody", 0.9)))
    arr = run.result.arrival_min
    out_dir = s.simulations_dir / sim_id
    write_geotiff(out_dir / "arrival_min.tif", np.where(np.isfinite(arr), arr, -1).astype(np.float32), grid, nodata=-1.0,
                  tags={"product": "WTRS reference arrival time (minutes)", "simulator": SIMULATOR_NAME})
    bounds = arrival_png(out_dir / "arrival.png", arr, grid, hours * 60.0)
    fp_url = None
    if m0 is not None:
        mask_png(out_dir / "footprint.png", m0, grid, (90, 200, 255))
        fp_url = f"/files/simulations/{sim_id}/footprint.png"
    cell_km2 = cell ** 2 / 1e6
    series = [{"hour": h, "burned_area_km2": float((arr <= h * 60).sum() * cell_km2)} for h in range(hours + 1)]
    burnt = np.isfinite(arr)
    edge = bool(burnt[:2].any() or burnt[-2:].any() or burnt[:, :2].any() or burnt[:, -2:].any())
    return {"status": "done", "runtime_s": run.result.runtime_s, "area_series": series,
            "final_area_km2": series[-1]["burned_area_km2"], "touches_window_edge": edge,
            "overlay_url": f"/files/simulations/{sim_id}/arrival.png", "bounds_wgs84": list(bounds),
            "footprint_url": fp_url, "grid": grid.to_dict(), "ignition_meta": fmeta,
            "weather_summary": ws.summary(0, hours), "weather_source_label": ws.source, "meta": run.meta}


async def start_simulation(req: dict, user_id: str) -> dict:
    if not 1 <= int(req.get("duration_hours", 0)) <= MAX_HOURS:
        raise APIError(400, "invalid_duration", f"duration_hours must be 1..{MAX_HOURS}")
    if float(req.get("cell_m", 0)) not in CELLS:
        raise APIError(400, "invalid_cell", f"cell_m must be one of {CELLS}")
    det = None
    if req.get("fire_id"):
        row = firms_service.event_row(req["fire_id"])
        if row is None:
            raise APIError(404, "fire_not_found", "Fire event not found.")
        lon, lat = float(row["lon"]), float(row["lat"])
        det = firms_service.event_detections(req["fire_id"])
    else:
        try:
            lon, lat = float(req["longitude"]), float(req["latitude"])
        except (KeyError, TypeError, ValueError):
            raise APIError(400, "invalid_location", "Provide fire_id or latitude/longitude.")
        if req.get("ignition") == "fire_footprint":
            raise APIError(400, "invalid_ignition", "fire_footprint ignition requires fire_id")
    wx = None
    if req.get("weather_source") == "open_meteo":
        try:
            wx = await weather_service.fetch(lat, lon)
        except Exception:
            raise APIError(503, "weather_unavailable", "Weather service unavailable.")
    sim_id = f"SIM-{uuid.uuid4().hex[:10].upper()}"
    doc = {"simulation_id": sim_id, "kind": "reference_wtrs", "data_class": "simulated", "simulator": SIMULATOR_NAME,
           "simulator_version": SIMULATOR_VERSION, "status": "running", "request": req, "fire_id": req.get("fire_id"),
           "latitude": lat, "longitude": lon, "user_id": user_id, "created_at": datetime.now(timezone.utc)}
    db = get_db()
    await db.simulations.insert_one(dict(doc))
    await emit("simulation", f"Reference simulation {sim_id} started ({req['duration_hours']} h, {req['cell_m']} m, {req['weather_source']})")

    async def runner():
        try:
            res = await asyncio.to_thread(_run, sim_id, req, lon, lat, det, wx)
            upd = res | {"finished_at": datetime.now(timezone.utc)}
            await emit("simulation", f"Reference simulation {sim_id} completed in {res['runtime_s']:.2f}s, "
                                     f"area {res['final_area_km2']:.2f} km2")
        except APIError as exc:
            upd = {"status": "failed", "error": exc.message, "finished_at": datetime.now(timezone.utc)}
            await emit("simulation", f"Reference simulation {sim_id} failed: {exc.message}", "WARNING")
        except LandscapeUnavailable as exc:
            upd = {"status": "failed", "error": str(exc), "finished_at": datetime.now(timezone.utc)}
            await emit("simulation", f"Reference simulation {sim_id} failed: {exc}", "WARNING")
        except Exception as exc:
            upd = {"status": "failed", "error": f"internal error: {type(exc).__name__}", "finished_at": datetime.now(timezone.utc)}
            await emit("simulation", f"Reference simulation {sim_id} failed: {type(exc).__name__}", "ERROR")
        await db.simulations.update_one({"simulation_id": sim_id}, {"$set": upd})
        bus.publish("simulation", {"simulation_id": sim_id, "status": upd["status"]})

    asyncio.create_task(runner())
    return sim_out(doc)


async def import_simulation(file_path: Path, filename: str, kind: str, simulator: str, units: str,
                            time_field: str | None, user_id: str) -> dict:
    from simulation.converters import importers
    sim_id = f"SIM-{uuid.uuid4().hex[:10].upper()}"
    out_dir = get_settings().simulations_dir / sim_id
    work = out_dir / "upload"
    work.mkdir(parents=True, exist_ok=True)
    try:
        if kind == "arrival_raster":
            src = file_path
            if filename.lower().endswith(".zip"):
                files = importers.extract_upload(file_path, work)
                cand = [f for f in files if f.suffix.lower() in (".tif", ".tiff", ".asc")]
                if not cand:
                    raise importers.ImportErrorInvalid("zip contains no .tif/.asc raster")
                src = cand[0]
            sim = await asyncio.to_thread(importers.import_arrival_raster, src, units, simulator)
        elif kind == "perimeters":
            if not time_field:
                raise importers.ImportErrorInvalid("time_field is required for perimeter imports")
            sim = await asyncio.to_thread(importers.import_perimeters, file_path, time_field, units, simulator)
        else:
            raise importers.ImportErrorInvalid("kind must be arrival_raster or perimeters")
    except importers.ImportErrorInvalid as exc:
        raise APIError(400, "invalid_import", str(exc))
    except Exception as exc:
        raise APIError(400, "invalid_import", f"Could not read file: {type(exc).__name__}")
    tif = await asyncio.to_thread(importers.save, sim, out_dir)
    # Display overlay (reproject to the globe)
    import rasterio
    from rasterio.warp import transform_bounds
    with rasterio.open(tif) as src:
        b = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
    from PIL import Image
    from rasterio.warp import Resampling, calculate_default_transform, reproject
    with rasterio.open(tif) as src:
        tr, w, h = calculate_default_transform(src.crs, "EPSG:4326", src.width, src.height, *src.bounds)
        dst = np.full((h, w), -1.0, np.float32)
        reproject(rasterio.band(src, 1), dst, dst_transform=tr, dst_crs="EPSG:4326", resampling=Resampling.nearest,
                  src_nodata=-1.0, dst_nodata=-1.0)
    mx = float(dst.max()) if (dst >= 0).any() else 1.0
    t = np.clip(dst / max(mx, 1e-6), 0, 1)
    rgba = np.zeros(dst.shape + (4,), np.uint8)
    cols = np.array([[255, 236, 160], [255, 140, 40], [150, 20, 20]], np.float32)
    for ch in range(3):
        rgba[..., ch] = np.interp(t, [0, 0.5, 1], cols[:, ch]).astype(np.uint8)
    rgba[..., 3] = np.where(dst >= 0, 190, 0).astype(np.uint8)
    Image.fromarray(rgba, "RGBA").save(out_dir / "arrival.png")
    west, south = tr.c, tr.f + tr.e * h
    east, north = tr.c + tr.a * w, tr.f
    doc = {"simulation_id": sim_id, "kind": "imported", "data_class": "simulated", "simulator": simulator,
           "status": "done", "import_meta": sim.meta, "user_id": user_id, "created_at": datetime.now(timezone.utc),
           "overlay_url": f"/files/simulations/{sim_id}/arrival.png", "bounds_wgs84": [west, south, east, north],
           "bounds_native_wgs84": list(b), "max_arrival_min": mx}
    await get_db().simulations.insert_one(dict(doc))
    await emit("simulation", f"Imported {simulator} result {filename} as {sim_id}")
    (out_dir / "upload_info.json").write_text(json.dumps({"filename": filename, "kind": kind}))
    return sim_out(doc)
