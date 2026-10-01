"""WildfireTwin model inference for a selected fire (localized, never global).

Pipeline per forecast horizon:
  FIRMS event -> local AnalysisGrid (cell size of the horizon band) ->
  landscape stack (SRTM/LANDFIRE/WorldCover) + observed footprint mask +
  Open-Meteo weather state -> model -> fire-spread probability field.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from backend.app.config import get_settings
from backend.app.ml.registry import LoadedModel, model_registry
from geo.footprint import rasterize_detections
from geo.landscape import Landscape, LandscapeUnavailable, build_landscape
from geo.overlay import OVERLAY_STYLE_VERSION, front_png, mask_png, probability_png, write_geotiff
from geo.rasters import AnalysisGrid
from geo.weather import wind_uv
from ml.features import BAND_CELL_M, BAND_OF_HORIZON, HORIZON_LABELS, HORIZONS_MIN, WeatherState, build_input

GRID_SIZE = 128
THRESHOLD = 0.5


class ModelNotTrained(RuntimeError):
    pass


@dataclass
class FireContext:
    event_id: str
    lat: float
    lon: float
    detections: pd.DataFrame
    latest_detection: str | None


def weather_state_from_openmeteo(wx: dict, horizon_min: int) -> tuple[WeatherState | None, dict]:
    h = wx["hourly"]
    k = wx["now_index"]
    hz = max(1, math.ceil(horizon_min / 60))
    n = len(h.get("time", []))
    if k + hz > n:
        return None, {"reason": f"forecast covers {n - k} h, horizon needs {hz} h"}

    def series(name):
        vals = (h.get(name) or [])[k:k + hz]
        return None if len(vals) < hz or any(v is None for v in vals) else np.asarray(vals, dtype=float)

    t, rh, ws, wd, pr = (series(v) for v in ("temperature_2m", "relative_humidity_2m", "wind_speed_10m",
                                             "wind_direction_10m", "precipitation"))
    if any(v is None for v in (t, rh, ws, wd, pr)):
        return None, {"reason": "required forecast variables missing"}
    u, v = wind_uv(ws, wd)
    soil = (h.get("soil_moisture_3_to_9cm") or [None] * n)[k]
    state = WeatherState(float(t[0]), float(rh[0]), float(u[0]), float(v[0]), float(t.mean()), float(rh.mean()),
                         float(u.mean()), float(v.mean()), float(pr.sum()), None if soil is None else float(soil))
    meta = {"weather_time": h["time"][k], "hours_used": hz, "source": wx["source"], "fingerprint": wx["fingerprint"],
            "soil_moisture": "Open-Meteo soil_moisture_3_to_9cm" if soil is not None else
                             "unavailable - model default 0.25 m3/m3 used (flagged)",
            "note": "ERA5 swvl1 (0-7 cm) was used in training; Open-Meteo 3-9 cm is the closest available layer"}
    return state, meta


def _bearing_deg(dx: float, dy: float) -> float:
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def spread_stats(prob: np.ndarray, m0: np.ndarray, grid: AnalysisGrid) -> dict:
    pred = prob >= THRESHOLD
    cell_km2 = grid.cell ** 2 / 1e6
    init = m0 > 0.5
    new = pred & ~init
    out = {"predicted_area_km2": float(pred.sum() * cell_km2), "initial_area_km2": float(init.sum() * cell_km2),
           "growth_area_km2": float(new.sum() * cell_km2), "mean_probability_in_window": float(prob.mean()),
           "spread_bearing_deg": None, "max_spread_distance_km": None, "touches_window_edge": bool(
               pred[:2].any() or pred[-2:].any() or pred[:, :2].any() or pred[:, -2:].any())}
    if new.any() and init.any():
        r0, c0 = np.argwhere(init).mean(0)
        r1, c1 = np.argwhere(new).mean(0)
        out["spread_bearing_deg"] = _bearing_deg(c1 - c0, -(r1 - r0))
        from scipy import ndimage
        d = ndimage.distance_transform_edt(~init) * grid.cell / 1000.0
        out["max_spread_distance_km"] = float(d[new].max())
    return out


def input_hash(ctx: FireContext, wx: dict, lm: LoadedModel, horizons: list[int]) -> str:
    det_ids = hashlib.md5("".join(sorted(map(str, ctx.detections["detection_id"]))).encode()).hexdigest()
    key = json.dumps({"fire": ctx.event_id, "det": det_ids, "wx": wx["fingerprint"], "wx_now": wx["now_index"],
                      "model": lm.version, "h": sorted(horizons),
                      "overlay_style": OVERLAY_STYLE_VERSION}, sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()


def run_prediction(ctx: FireContext, wx: dict, horizons: list[int] | None = None, model_type: str | None = None,
                   prediction_id: str | None = None) -> dict:
    """Synchronous (call via asyncio.to_thread). Returns the prediction document (without DB ids)."""
    s = get_settings()
    horizons = sorted(horizons or HORIZONS_MIN)
    mtype = model_type or model_registry.default_type()
    lm = model_registry.get(mtype) if mtype else None
    if lm is None:
        raise ModelNotTrained("Model not trained. Run the training pipeline (see docs/setup.md).")
    pid = prediction_id or f"PR-{uuid.uuid4().hex[:12].upper()}"
    out_dir = s.predictions_dir / pid
    out_dir.mkdir(parents=True, exist_ok=True)
    landscapes: dict[str, Landscape | str] = {}
    footprints: dict[str, tuple[np.ndarray, dict, list]] = {}
    steps = []
    t_total = time.perf_counter()
    for hz in horizons:
        band = BAND_OF_HORIZON[hz]
        label = HORIZON_LABELS[hz]
        step = {"horizon_min": hz, "label": label, "band": band, "cell_m": BAND_CELL_M[band], "status": "unavailable"}
        if band not in landscapes:
            grid = AnalysisGrid.centered(ctx.lon, ctx.lat, BAND_CELL_M[band], GRID_SIZE)
            try:
                landscapes[band] = build_landscape(grid)
            except LandscapeUnavailable as exc:
                landscapes[band] = str(exc)
        land = landscapes[band]
        if isinstance(land, str):
            step["reason"] = land
            steps.append(step)
            continue
        if band not in footprints:
            m0, fmeta = rasterize_detections(ctx.detections, land.grid)
            fb = mask_png(out_dir / f"footprint_{band}.png", m0, land.grid, (90, 200, 255))
            footprints[band] = (m0, fmeta, list(fb))
        m0, fmeta, fbounds = footprints[band]
        if m0.sum() == 0:
            step["reason"] = "no FIRMS detections fall inside the analysis window"
            steps.append(step)
            continue
        w, wmeta = weather_state_from_openmeteo(wx, hz)
        if w is None:
            step["reason"] = "Forecast unavailable: " + wmeta["reason"]
            steps.append(step)
            continue
        x = build_input(m0, land.elevation_m, land.slope_deg, land.aspect_deg, land.fuel_code, land.landcover, w,
                        hz, land.grid.cell)
        xt = torch.from_numpy(x)[None].to(lm.device)
        with torch.no_grad():
            if lm.device.type == "cuda":
                torch.cuda.synchronize()
            t0 = time.perf_counter()
            prob = torch.sigmoid(lm.model(xt))[0, 0].float().cpu().numpy()
            if lm.device.type == "cuda":
                torch.cuda.synchronize()
            ms = (time.perf_counter() - t0) * 1000
        tif = out_dir / f"{label}_prob.tif"
        write_geotiff(tif, prob.astype(np.float32), land.grid, tags={"product": "WildfireTwin model fire-spread probability",
                                                                     "model": lm.version, "horizon_min": hz})
        bounds = probability_png(out_dir / f"{label}_prob.png", prob, land.grid)
        front_png(out_dir / f"{label}_front.png", prob, land.grid, THRESHOLD)
        step.update({
            "status": "ok", "inference_ms": ms, "weather": w.to_dict(), "weather_meta": wmeta,
            "grid": land.grid.to_dict(), "bounds_wgs84": list(bounds),
            "overlay_url": f"/files/predictions/{pid}/{label}_prob.png",
            "front_url": f"/files/predictions/{pid}/{label}_front.png", "overlay_style": OVERLAY_STYLE_VERSION,
            "geotiff_path": str(tif.relative_to(s.predictions_dir.parent.parent)),
            "footprint_url": f"/files/predictions/{pid}/footprint_{band}.png", "footprint_bounds_wgs84": fbounds,
            **spread_stats(prob, m0, land.grid),
        })
        steps.append(step)
    first_land = next((v for v in landscapes.values() if not isinstance(v, str)), None)
    return {
        "prediction_id": pid, "fire_id": ctx.event_id, "data_class": "predicted",
        "product": "Model fire-spread probability",
        "model": {"type": lm.model_type, "name": {"unet": "U-Net", "fno": "FNO", "physics_fno": "Physics-Informed FNO"}[lm.model_type],
                  "version": lm.version, "run_id": lm.run_id, "checkpoint": lm.checkpoint,
                  "dataset_version": lm.dataset_version, "device": str(lm.device)},
        "inputs": {"fire_latest_detection": ctx.latest_detection, "detections": int(len(ctx.detections)),
                   "weather_source": wx["source"], "weather_fetched_at": wx["fetched_at"],
                   "weather_now": wx["hourly"]["time"][wx["now_index"]], "weather_fingerprint": wx["fingerprint"],
                   "footprint": footprints[next(iter(footprints))][1] if footprints else None,
                   "transforms": first_land.transforms.entries if first_land else []},
        "threshold": THRESHOLD, "steps": steps,
        "uncertainty": "not quantified by this model; forecast skill generally decreases with horizon",
        "total_runtime_ms": (time.perf_counter() - t_total) * 1000,
        "limitations": ["trained on WTRS reference simulations (Rothermel surface spread), not observed fire progression",
                        "initial state from satellite active-fire pixels, not a mapped perimeter",
                        "spatially uniform weather in the analysis window",
                        "valid only inside the local data domain (N. California study region)"],
    }
