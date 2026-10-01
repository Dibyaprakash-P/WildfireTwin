"""Convert imported FARSITE / FlamMap runs into a SEPARATE training/evaluation dataset version.

The output has exactly the WTRS sample format (so the same loader, models and evaluation work), but:
  * dataset_version = "<engine>-<tag>" (e.g. "farsite-ncal-v1"), never "wtrs-*";
  * every scenario/sample row carries simulation_source = "FARSITE" | "FlamMap" (from the import metadata);
  * the loader refuses datasets that mix engines.

Per imported run:
  1. the arrival raster is resampled onto a 128x128 AnalysisGrid (EPSG:5070, LANDFIRE-snapped) centred on the
     earliest-burning cells, using MIN resampling (earliest arrival in a cell; nothing interpolated);
  2. the landscape (SRTM/LANDFIRE/WorldCover) is built for the same grid;
  3. weather channels come from local ERA5 at the run's ignition time. The run must have been driven by
     comparable weather - this is the user's responsibility and is recorded as an assumption;
  4. samples (t0 -> t0 + h) are cut from the arrival field exactly like WTRS.

Usage:
python -m simulation.converters.build_dataset --runs run01 run02 --tag ncal-v1 --cell 60 \
    --t0-hours 2 6 12 --horizons 360 720 --split test
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject

from geo import registry
from geo.landscape import build_landscape
from geo.rasters import AnalysisGrid
from ml.datasets.provenance import PROVENANCE_COLUMNS
from simulation.converters.import_cli import load_index
from simulation.weather_sources import HISTORY_HOURS, era5_series

EDGE_MARGIN = 2


def _grid_for(arrival: np.ndarray, transform, crs: str, cell: float, size: int) -> AnalysisGrid:
    from pyproj import Transformer
    valid = arrival >= 0
    first = valid & (arrival <= arrival[valid].min() + 1e-6)
    r, c = np.argwhere(first).mean(0)
    x, y = transform * (c + 0.5, r + 0.5)
    lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(x, y)
    return AnalysisGrid.centered(lon, lat, cell, size)


def build(runs: list[str], tag: str, cell: float, t0_hours: list[float], horizons: list[int], split: str,
          size: int = 128, sim_root=None, out_root=None) -> dict:
    from pathlib import Path
    index = {e["name"]: e for e in load_index(sim_root)}
    missing = [r for r in runs if r not in index]
    if missing:
        raise ValueError(f"not imported: {missing}")
    engines = {index[r]["simulation_source"] for r in runs}
    if len(engines) != 1:
        raise ValueError(f"runs come from different engines {engines}; build one dataset per engine")
    engine = engines.pop()
    version = f"{engine.lower()}-{tag}"
    if version.startswith("wtrs"):
        raise ValueError("refusing to write an imported dataset under a WTRS name")
    out = Path(out_root or registry.path("data/processed/training")) / version
    (out / "scenarios").mkdir(parents=True, exist_ok=True)
    prov = {"simulation_source": engine, "reference_engine": f"{engine} (external, imported)",
            "simulation_method": f"{engine} run(s) exported by the user and imported via simulation/converters",
            "source_version": "user export"}
    scen_rows, sample_rows = [], []
    for name in runs:
        meta = json.loads((Path(index[name]["path"]) / "meta.json").read_text())
        if not meta.get("ignition_time_utc"):
            raise ValueError(f"{name}: ignition time unknown - re-import with --ignition-time to attach weather")
        with rasterio.open(Path(index[name]["path"]) / "arrival_min.tif") as src:
            arr_src, tr, crs = src.read(1), src.transform, src.crs.to_string()
        grid = _grid_for(arr_src, tr, crs, cell, size)
        arr = np.full(grid.shape, -1.0, np.float32)
        reproject(arr_src, arr, src_transform=tr, src_crs=crs, dst_transform=grid.transform, dst_crs=grid.crs,
                  src_nodata=-1.0, dst_nodata=-1.0, resampling=Resampling.min if cell > abs(tr.a) else Resampling.nearest)
        arrival = np.where(arr >= 0, arr, np.inf).astype(np.float32)
        land = build_landscape(grid)
        w, s, e, n = grid.bounds_wgs84()
        start = np.datetime64(meta["ignition_time_utc"].replace("Z", "")[:16])
        hours = int(np.ceil(max(t0_hours) + max(horizons) / 60.0)) + 1
        ws = era5_series((w + e) / 2, (s + n) / 2, start, hours)
        sid = f"{engine.lower()}-{name}-{int(cell)}"
        np.savez_compressed(
            out / "scenarios" / f"{sid}.npz",
            elevation_m=land.elevation_m, slope_deg=land.slope_deg.astype(np.float16), aspect_deg=land.aspect_deg.astype(np.float16),
            fuel_code=land.fuel_code, landcover=(land.landcover if land.landcover is not None else np.zeros(grid.shape, np.uint8)),
            has_landcover=np.array(land.landcover is not None), arrival_min=arrival,
            w_temp=np.concatenate([ws.history_temperature_c, ws.temperature_c]), w_rh=np.concatenate([ws.history_rh_pct, ws.rh_pct]),
            w_precip=np.concatenate([ws.history_precip_mm, ws.precip_mm]), w_u=ws.wind_u_ms, w_v=ws.wind_v_ms,
            w_soil=ws.meta["soil_moisture_m3m3"])
        for t0h in t0_hours:
            m0 = arrival <= t0h * 60
            for hz in horizons:
                m1 = arrival <= t0h * 60 + hz
                edge = bool(m1[:EDGE_MARGIN].any() or m1[-EDGE_MARGIN:].any() or m1[:, :EDGE_MARGIN].any() or m1[:, -EDGE_MARGIN:].any())
                sample_rows.append({"scenario_id": sid, "band": f"{int(cell)}m", "split": split, "t0_min": t0h * 60.0,
                                    "horizon_min": hz, "cell_m": cell, "initial_cells": int(m0.sum()), "target_cells": int(m1.sum()),
                                    "growth_cells": int(m1.sum() - m0.sum()), "edge_touch": edge,
                                    "valid": bool(m0.sum() > 0 and not edge), **{c: prov[c] for c in PROVENANCE_COLUMNS}})
        scen_rows.append({"scenario_id": sid, "band": f"{int(cell)}m", "split": split, "lon": (w + e) / 2, "lat": (s + n) / 2,
                          "start_utc": str(start), "cell_m": cell, "size": size, "grid": json.dumps(grid.to_dict()),
                          "bbox_wgs84": json.dumps([w, s, e, n]), "live_herb": float("nan"), "live_woody": float("nan"),
                          "simulator": engine, "simulator_version": "user export", "source_sha256": meta.get("source_sha256"),
                          "weather_source": ws.source + " (assumed comparable to the run's weather inputs)",
                          **{c: prov[c] for c in PROVENANCE_COLUMNS}})
    pd.DataFrame(scen_rows).to_parquet(out / "scenarios.parquet", index=False)
    pd.DataFrame(sample_rows).to_parquet(out / "samples.parquet", index=False)
    man = {"dataset_version": version, "generated_utc": datetime.now(timezone.utc).isoformat(), "data_class": "simulated",
           "simulator": engine, "provenance": prov | {"data_class": "simulated", "is_farsite": engine == "FARSITE"},
           "runs": runs, "history_hours": HISTORY_HOURS,
           "config": {"grid_size": size, "bands": {f"{int(cell)}m": {"cell_m": cell, "t0_hours": t0_hours, "horizons_min": horizons}}},
           "assumptions": ["weather channels from local ERA5 at the run's ignition time",
                           "live fuel moisture of the external run is not known to WildfireTwin"]}
    (out / "manifest.json").write_text(json.dumps(man, indent=2))
    return {"dataset_version": version, "scenarios": len(scen_rows), "samples": len(sample_rows),
            "valid": int(sum(r["valid"] for r in sample_rows))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--cell", type=float, default=60.0)
    ap.add_argument("--t0-hours", nargs="+", type=float, default=[2, 6, 12])
    ap.add_argument("--horizons", nargs="+", type=int, default=[360, 720])
    ap.add_argument("--split", default="test", choices=["train", "val", "test"],
                    help="default 'test': imported runs are a benchmark unless you deliberately train on them")
    a = ap.parse_args()
    print(build(a.runs, a.tag, a.cell, a.t0_hours, a.horizons, a.split))


if __name__ == "__main__":
    main()
