"""Historical wildfire examples and replay validation.

Data classes used here:
  observed   FIRMS detections (local archive) and burned-area perimeters (MTBS/BAER/RAVG)
  predicted  WildfireTwin forecast from the observed state at t0 with ERA5 weather
  validated  comparison of the prediction with the OBSERVED cumulative FIRMS
             footprint at t0 + h (satellite-pixel footprints; coarse, overpass-limited)

A replay is only offered when it is defensible: the fire lies inside the local
landscape domain and ERA5 covers t0 - 72 h ... t0 + horizon.
"""

from __future__ import annotations

import json
import math
import uuid
from functools import lru_cache

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import mapping, shape

from backend.app.config import get_settings
from backend.app.ml.registry import model_registry
from backend.app.services.firms import in_study_region
from geo import registry
from geo.footprint import rasterize_detections
from geo.landscape import LandscapeUnavailable, build_landscape
from geo.overlay import front_png, mask_png, probability_png, write_geotiff
from geo.rasters import AnalysisGrid
from geo.weather import wind_speed_dir
from ml.evaluation.metrics import mask_metrics
from ml.features import BAND_CELL_M, BAND_OF_HORIZON, HORIZON_LABELS, WeatherState, build_input
from simulation.weather_sources import era5_series, era5_store

PROGRAM_PRIORITY = {"MTBS": 0, "BAER": 1, "RAVG": 2, "Provisional IA": 3}
REPLAY_HORIZONS = [360, 720, 1440, 2880, 4320]


@lru_cache(maxsize=1)
def perimeters() -> gpd.GeoDataFrame:
    p = registry.path(registry.sources()["mtbs"]["processed_perimeters"])
    if not p.exists():
        return gpd.GeoDataFrame()
    fc = json.loads(p.read_text(encoding="utf-8"))
    g = gpd.GeoDataFrame([f["properties"] for f in fc["features"]], geometry=[shape(f["geometry"]) for f in fc["features"]],
                         crs="EPSG:4326")
    g["ig"] = pd.to_datetime(g["ig_date"], errors="coerce")
    g = g[(g["incid_type"] == "Wildfire") & g["ig"].notna()].copy()
    g["prio"] = g["map_prog"].map(PROGRAM_PRIORITY).fillna(9)
    g = g.sort_values(["prio", "burnbndac"], ascending=[True, False]).drop_duplicates(["incid_name", "ig_date"])
    c = g.to_crs("EPSG:5070").geometry.centroid.to_crs("EPSG:4326")
    g["clon"], g["clat"] = c.x, c.y
    g["hist_id"] = [f"H-{str(n).upper().replace(' ', '_')[:24]}-{d}" for n, d in zip(g["incid_name"], g["ig_date"])]
    return g.reset_index(drop=True)


@lru_cache(maxsize=1)
def firms_region() -> pd.DataFrame:
    p = registry.path(registry.sources()["firms"]["processed_region"])
    df = pd.read_parquet(p)
    df["acq_datetime"] = pd.to_datetime(df["acq_datetime"], utc=True)
    return df[(df["fire_type"].isna()) | (df["fire_type"] == 0)]   # presumed vegetation fires


def fire_detections(row: pd.Series, days_after: int = 60) -> pd.DataFrame:
    df = firms_region()
    minx, miny, maxx, maxy = row.geometry.bounds
    pad = 0.03
    ig = pd.Timestamp(row["ig"]).tz_localize("UTC")
    sel = df[(df["longitude"].between(minx - pad, maxx + pad)) & (df["latitude"].between(miny - pad, maxy + pad))
             & (df["acq_datetime"] >= ig - pd.Timedelta(days=1)) & (df["acq_datetime"] <= ig + pd.Timedelta(days=days_after))]
    if sel.empty:
        return sel
    buf = gpd.GeoSeries([row.geometry], crs="EPSG:4326").to_crs("EPSG:5070").buffer(2000).to_crs("EPSG:4326").iloc[0]
    pts = gpd.points_from_xy(sel["longitude"], sel["latitude"])
    return sel[[buf.contains(p) for p in pts]].sort_values("acq_datetime")


def list_fires(min_year: int = 2020) -> list[dict]:
    g = perimeters()
    if g.empty:
        return []
    g = g[g["ig"].dt.year >= min_year]
    t0, t1 = era5_store().time_range() if era5_store().available else (None, None)
    out = []
    for _, r in g.sort_values("ig", ascending=False).iterrows():
        ig = np.datetime64(r["ig"].to_datetime64(), "h")
        era_ok = t0 is not None and t0 + np.timedelta64(72, "h") <= ig and ig + np.timedelta64(30, "D") <= t1
        dom = in_study_region(float(r["clon"]), float(r["clat"]))
        out.append({"hist_id": r["hist_id"], "name": str(r["incid_name"]).title(), "ignition_date": r["ig_date"],
                    "acres": float(r["burnbndac"]), "area_km2": float(r["burnbndac"]) * 0.00404686,
                    "program": r["map_prog"], "latitude": float(r["clat"]), "longitude": float(r["clon"]),
                    "in_model_domain": dom, "era5_available": bool(era_ok), "replay_available": bool(dom and era_ok),
                    "data_class": "observed"})
    return out


def _row(hist_id: str) -> pd.Series | None:
    g = perimeters()
    m = g[g["hist_id"] == hist_id]
    return None if m.empty else m.iloc[0]


def fire_detail(hist_id: str) -> dict | None:
    r = _row(hist_id)
    if r is None:
        return None
    det = fire_detections(r)
    by_day = det.groupby(det["acq_datetime"].dt.date).size() if len(det) else pd.Series(dtype=int)
    info = next(x for x in list_fires(0) if x["hist_id"] == hist_id)
    return info | {
        "perimeter_geojson": {"type": "Feature", "geometry": mapping(r.geometry),
                              "properties": {"source": f"{r['map_prog']} burned-area perimeter", "data_class": "observed"}},
        "firms_detections": int(len(det)),
        "firms_first": det["acq_datetime"].min().isoformat() if len(det) else None,
        "firms_last": det["acq_datetime"].max().isoformat() if len(det) else None,
        "detections_by_day": {str(k): int(v) for k, v in by_day.items()},
        "validation_note": "Replay validation compares predictions with the observed cumulative FIRMS footprint "
                           "(375 m / 1 km pixels, limited by satellite overpasses). The burned-area perimeter is the "
                           "final extent, shown for context only.",
    }


def _weather_state(ws, hz_min: int) -> WeatherState:
    kh = max(1, math.ceil(hz_min / 60))
    sl = slice(0, kh)
    return WeatherState(float(ws.temperature_c[0]), float(ws.rh_pct[0]), float(ws.wind_u_ms[0]), float(ws.wind_v_ms[0]),
                        float(np.mean(ws.temperature_c[sl])), float(np.mean(ws.rh_pct[sl])),
                        float(np.mean(ws.wind_u_ms[sl])), float(np.mean(ws.wind_v_ms[sl])),
                        float(np.sum(ws.precip_mm[sl])), float(ws.meta["soil_moisture_m3m3"][0]))


def replay(hist_id: str, t0_iso: str, model_type: str | None) -> dict:
    """Synchronous; returns a replay result with predicted overlays and validation metrics."""
    import torch
    r = _row(hist_id)
    if r is None:
        raise KeyError("historical fire not found")
    mtype = model_type or model_registry.default_type()
    lm = model_registry.get(mtype) if mtype else None
    if lm is None:
        raise RuntimeError("Model not trained.")
    det = fire_detections(r)
    t0 = pd.Timestamp(t0_iso)
    t0 = t0.tz_localize("UTC") if t0.tzinfo is None else t0.tz_convert("UTC")
    t0 = t0.floor("h")
    st = era5_store()
    tmin, tmax = st.time_range()
    if not (tmin + np.timedelta64(72, "h") <= np.datetime64(t0.tz_localize(None)) <= tmax - np.timedelta64(73, "h")):
        raise ValueError("ERA5 does not cover t0 - 72 h ... t0 + 72 h for this date.")
    init_det = det[det["acq_datetime"] <= t0]
    if init_det.empty:
        raise ValueError("No FIRMS detections before t0 - choose a later time.")
    lon, lat = float(init_det["longitude"].mean()), float(init_det["latitude"].mean())
    ws = era5_series(lon, lat, np.datetime64(t0.tz_localize(None)), 73)
    rid = f"RP-{uuid.uuid4().hex[:10].upper()}"
    out_dir = get_settings().predictions_dir / rid
    steps = []
    lands: dict[str, object] = {}
    for hz in REPLAY_HORIZONS:
        band = BAND_OF_HORIZON[hz]
        label = HORIZON_LABELS[hz]
        if band not in lands:
            g = AnalysisGrid.centered(lon, lat, BAND_CELL_M[band], 128)
            try:
                lands[band] = build_landscape(g)
            except LandscapeUnavailable as exc:
                lands[band] = str(exc)
        land = lands[band]
        if isinstance(land, str):
            steps.append({"horizon_min": hz, "label": label, "status": "unavailable", "reason": land})
            continue
        m0, _ = rasterize_detections(init_det, land.grid)
        obs_det = det[det["acq_datetime"] <= t0 + pd.Timedelta(minutes=hz)]
        m1, _ = rasterize_detections(obs_det, land.grid)
        w = _weather_state(ws, hz)
        x = build_input(m0, land.elevation_m, land.slope_deg, land.aspect_deg, land.fuel_code, land.landcover, w, hz, land.grid.cell)
        with torch.no_grad():
            prob = torch.sigmoid(lm.model(torch.from_numpy(x)[None].to(lm.device)))[0, 0].cpu().numpy()
        write_geotiff(out_dir / f"{label}_prob.tif", prob.astype(np.float32), land.grid)
        b = probability_png(out_dir / f"{label}_prob.png", prob, land.grid)
        front_png(out_dir / f"{label}_front.png", prob, land.grid)
        mask_png(out_dir / f"{label}_observed.png", m1, land.grid, (120, 220, 140))
        mask_png(out_dir / f"footprint_{band}.png", m0, land.grid, (90, 200, 255))
        met = mask_metrics(prob, m1 > 0.5, m0 > 0.5, land.grid.cell)
        spd, wdir = wind_speed_dir(w.u_mean_ms, w.v_mean_ms)
        steps.append({"horizon_min": hz, "label": label, "status": "ok", "band": band, "cell_m": land.grid.cell,
                      "bounds_wgs84": list(b), "overlay_url": f"/files/predictions/{rid}/{label}_prob.png",
                      "observed_url": f"/files/predictions/{rid}/{label}_observed.png",
                      "front_url": f"/files/predictions/{rid}/{label}_front.png",
                      "footprint_url": f"/files/predictions/{rid}/footprint_{band}.png",
                      "observed_detections": int(len(obs_det)), "metrics_vs_observed": met,
                      "weather": {"temperature_mean_c": w.temp_mean_c, "rh_mean_pct": w.rh_mean_pct,
                                  "wind_mean_ms": float(spd), "wind_from_deg": float(wdir), "precip_sum_mm": w.precip_sum_mm}})
    return {"replay_id": rid, "hist_id": hist_id, "t0": t0.isoformat(), "model": {"type": lm.model_type, "version": lm.version},
            "initial_detections": int(len(init_det)), "weather_source": ws.source, "steps": steps,
            "data_classes": {"initial": "observed", "prediction": "predicted", "comparison": "validated (vs observed FIRMS footprint)"}}
