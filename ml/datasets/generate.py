"""Generate the reference-simulation training dataset.

For every band, random ignitions on the real study-region landscape
(SRTM + LANDFIRE + WorldCover) are simulated with WTRS driven by real ERA5
hourly weather. Each scenario yields several (t0 -> t0 + horizon) samples.

Outputs (data/processed/training/<dataset_version>/):
    scenarios/<scenario_id>.npz   landscape stack, arrival time, hourly weather
    scenarios.parquet             one row per scenario (metadata)
    samples.parquet               one row per sample (index + validity flags)
    manifest.json                 config snapshot, split blocks, counts

Usage:
    python -m ml.datasets.generate [--bands short,medium,long] [--scenarios N] [--workers 6]
"""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing as mp
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from geo import registry
from geo.fuels import is_burnable
from geo.landscape import LandscapeUnavailable, build_landscape
from geo.rasters import AnalysisGrid
from geo.weather import ffwi
from ml.datasets.provenance import PROVENANCE_COLUMNS, WTRS_PROVENANCE
from simulation.reference import SIMULATOR_NAME, SIMULATOR_VERSION, point_ignition, run_reference
from simulation.weather_sources import HISTORY_HOURS, era5_series

log = logging.getLogger("generate")
CONFIG = registry.REPO_ROOT / "ml" / "configs" / "dataset.yaml"
EDGE_MARGIN = 2


def load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def out_dir(cfg: dict) -> Path:
    return registry.path(f"data/processed/training/{cfg['dataset_version']}")


def split_blocks(cfg: dict) -> dict[tuple[int, int], str]:
    w, s, e, n = registry.study_bbox()
    bd = cfg["split"]["block_deg"]
    blocks = [(i, j) for i in range(int(round((e - w) / bd))) for j in range(int(round((n - s) / bd)))]
    rng = np.random.default_rng(cfg["seed"])
    order = rng.permutation(len(blocks))
    nt, nv = cfg["split"]["test_blocks"], cfg["split"]["val_blocks"]
    assign = {}
    for rank, k in enumerate(order):
        assign[blocks[k]] = "test" if rank < nt else "val" if rank < nt + nv else "train"
    return assign


def block_of(lon: float, lat: float, cfg: dict) -> tuple[int, int]:
    w, s, _, _ = registry.study_bbox()
    bd = cfg["split"]["block_deg"]
    return int((lon - w) // bd), int((lat - s) // bd)


def _candidate_hours(cfg: dict) -> np.ndarray:
    hrs = []
    for y in cfg["weather"]["years"]:
        for m in cfg["weather"]["months"]:
            start = np.datetime64(f"{y}-{m:02d}-01T00:00")
            end = np.datetime64(f"{y + (m == 12)}-{(m % 12) + 1:02d}-01T00:00")
            hrs.append(np.arange(start, end, np.timedelta64(1, "h")))
    return np.concatenate(hrs)


def _run_one(args: tuple) -> dict | None:
    band, idx, bcfg, cfg, assign, seed = args
    rng = np.random.default_rng(seed)
    w, s, e, n = registry.study_bbox()
    size = cfg["grid_size"]
    cell = float(bcfg["cell_m"])
    hours_all = _candidate_hours(cfg)
    max_hours = max(bcfg["t0_hours"]) + max(bcfg["horizons_min"]) / 60.0
    tlast = np.datetime64(f"{max(cfg['weather']['years'])}-12-31T23:00")
    for _attempt in range(200):
        lon, lat = rng.uniform(w, e), rng.uniform(s, n)
        split = assign.get(block_of(lon, lat, cfg))
        if split is None:
            continue
        grid = AnalysisGrid.centered(lon, lat, cell, size)
        try:
            land = build_landscape(grid)
        except LandscapeUnavailable:
            continue
        c0, c1 = int(size * 0.4), int(size * 0.6)
        core = is_burnable(land.fuel_code[c0:c1, c0:c1])
        cand = np.argwhere(core)
        if len(cand) == 0:
            continue
        r, c = cand[rng.integers(len(cand))] + c0
        start = hours_all[rng.integers(len(hours_all))]
        if start + np.timedelta64(int(np.ceil(max_hours)) + 1, "h") > tlast:
            continue
        ws = era5_series(lon, lat, start, int(np.ceil(max_hours)) + 1)
        wc = cfg["weather"]
        k = int(wc["ffwi_hours"])
        f = float(np.mean(ffwi(ws.temperature_c[:k], ws.rh_pct[:k], np.hypot(ws.wind_u_ms[:k], ws.wind_v_ms[:k]))))
        if rng.random() > min(max(f / wc["ffwi_scale"], wc["ffwi_min_accept"]), 1.0):
            continue
        herb = float(rng.uniform(*cfg["weather"]["live_herb_moisture"]))
        woody = float(rng.uniform(*cfg["weather"]["live_woody_moisture"]))
        run = run_reference(land, ws, point_ignition(grid.shape, r, c), max_hours, herb, woody)
        sid = f"{band}-{idx:05d}"
        dst = out_dir(cfg) / "scenarios" / f"{sid}.npz"
        np.savez_compressed(
            dst,
            elevation_m=land.elevation_m.astype(np.float32), slope_deg=land.slope_deg.astype(np.float16),
            aspect_deg=land.aspect_deg.astype(np.float16), fuel_code=land.fuel_code.astype(np.int16),
            landcover=(land.landcover if land.landcover is not None else np.zeros(grid.shape, np.uint8)),
            has_landcover=np.array(land.landcover is not None),
            arrival_min=run.result.arrival_min.astype(np.float32),
            w_temp=np.concatenate([ws.history_temperature_c, ws.temperature_c]).astype(np.float32),
            w_rh=np.concatenate([ws.history_rh_pct, ws.rh_pct]).astype(np.float32),
            w_precip=np.concatenate([ws.history_precip_mm, ws.precip_mm]).astype(np.float32),
            w_u=ws.wind_u_ms.astype(np.float32), w_v=ws.wind_v_ms.astype(np.float32),
            w_soil=ws.meta["soil_moisture_m3m3"].astype(np.float32),
        )
        arr = run.result.arrival_min
        samples = []
        for t0h in bcfg["t0_hours"]:
            t0 = t0h * 60.0
            m0 = arr <= t0
            for hz in bcfg["horizons_min"]:
                m1 = arr <= t0 + hz
                edge = bool(m1[:EDGE_MARGIN].any() or m1[-EDGE_MARGIN:].any() or m1[:, :EDGE_MARGIN].any() or m1[:, -EDGE_MARGIN:].any())
                samples.append({
                    "scenario_id": sid, "band": band, "split": split, "t0_min": t0, "horizon_min": hz,
                    "cell_m": cell, "initial_cells": int(m0.sum()), "target_cells": int(m1.sum()),
                    "growth_cells": int(m1.sum() - m0.sum()), "edge_touch": edge,
                    "valid": bool(m0.sum() > 0 and not edge),
                    **{c: WTRS_PROVENANCE[c] for c in PROVENANCE_COLUMNS},
                })
        g = grid.bounds_wgs84()
        scen = {
            "scenario_id": sid, "band": band, "split": split, "lon": lon, "lat": lat, "ign_row": int(r), "ign_col": int(c),
            "start_utc": str(start), "cell_m": cell, "size": size, "grid": json.dumps(grid.to_dict()),
            "bbox_wgs84": json.dumps(g), "live_herb": herb, "live_woody": woody, "sim_hours": max_hours,
            "sim_runtime_s": run.result.runtime_s, "burned_cells_end": int(np.isfinite(arr).sum()),
            "has_landcover": land.landcover is not None, "ffwi_start": f, "simulator": SIMULATOR_NAME,
            "simulator_version": SIMULATOR_VERSION, "weather_source": ws.source,
            **{c: WTRS_PROVENANCE[c] for c in PROVENANCE_COLUMNS},
        }
        return {"scenario": scen, "samples": samples}
    return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("geo.rasters").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--bands", default="short,medium,long")
    ap.add_argument("--scenarios", type=int, default=None, help="override scenarios per band")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    cfg = load_config()
    od = out_dir(cfg)
    (od / "scenarios").mkdir(parents=True, exist_ok=True)
    assign = split_blocks(cfg)
    jobs = []
    for bi, band in enumerate(a.bands.split(",")):
        bcfg = cfg["bands"][band]
        n = a.scenarios or bcfg["scenarios"]
        for i in range(n):
            jobs.append((band, i, bcfg, cfg, assign, cfg["seed"] + bi * 1_000_003 + i))
    t0 = time.time()
    scen_rows, sample_rows = [], []
    with mp.Pool(a.workers) as pool:
        for k, res in enumerate(pool.imap_unordered(_run_one, jobs, chunksize=4)):
            if res:
                scen_rows.append(res["scenario"])
                sample_rows.extend(res["samples"])
            if (k + 1) % 50 == 0:
                log.info("%d/%d scenarios (%.0fs)", k + 1, len(jobs), time.time() - t0)
    sc = pd.DataFrame(scen_rows).sort_values("scenario_id")
    sa = pd.DataFrame(sample_rows).sort_values(["scenario_id", "t0_min", "horizon_min"])
    # merge with any previously generated bands
    for name, df in (("scenarios", sc), ("samples", sa)):
        p = od / f"{name}.parquet"
        if p.exists():
            old = pd.read_parquet(p)
            old = old[~old["band"].isin(df["band"].unique())]
            df = pd.concat([old, df], ignore_index=True)
        df.to_parquet(p, index=False)
    sa_all = pd.read_parquet(od / "samples.parquet")
    manifest = {
        "dataset_version": cfg["dataset_version"], "generated_utc": datetime.now(timezone.utc).isoformat(),
        "config": cfg, "history_hours": HISTORY_HOURS,
        "split_blocks": {f"{i},{j}": v for (i, j), v in assign.items()},
        "counts": sa_all.groupby(["band", "split"])["valid"].agg(["count", "sum"]).reset_index().to_dict("records"),
        "data_class": "simulated", "simulator": SIMULATOR_NAME, "simulator_version": SIMULATOR_VERSION,
        "provenance": WTRS_PROVENANCE,
    }
    (od / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    log.info("done in %.0fs: %d scenarios, %d samples (%d valid)", time.time() - t0, len(sc), len(sa), int(sa["valid"].sum()))


if __name__ == "__main__":
    main()
