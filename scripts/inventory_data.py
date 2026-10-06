"""Extract real metadata from every local dataset and write the data catalog.

Outputs:
  data/metadata/catalog.json   (served by /api/data/catalog, shown on the Data page)
  data/DATA_INVENTORY.md       (human-readable inventory)

Usage: python -m scripts.inventory_data
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import rasterio

from geo import mtbs_severity, registry

R = registry.REPO_ROOT


def rel(p: Path) -> str:
    return str(Path(p).relative_to(R)).replace("\\", "/")


def size(paths: list[Path]) -> str:
    b = sum(p.stat().st_size for p in paths if p.exists())
    return f"{b / 1e9:.2f} GB" if b > 1e9 else f"{b / 1e6:.1f} MB"


def raster_meta(p: Path) -> dict:
    with rasterio.open(p) as r:
        return {"crs": r.crs.to_string() if r.crs else "none", "res": [abs(r.res[0]), abs(r.res[1])],
                "shape": [r.height, r.width], "bounds": [round(x, 4) for x in r.bounds], "dtype": r.dtypes[0],
                "nodata": r.nodata, "bands": r.count}


def firms_entry() -> list[dict]:
    cfg = registry.sources()["firms"]
    files = registry.glob_paths(cfg["raw_glob"])
    rep_p = R / "data/metadata/firms_preprocess_report.json"
    rep = json.loads(rep_p.read_text()) if rep_p.exists() else {}
    by_prod: dict[str, list[Path]] = {}
    for f in files:
        prod = f.name.split("_")[2]
        by_prod.setdefault(prod, []).append(f)
    out = []
    for prod, fs in sorted(by_prod.items()):
        info = cfg["products"].get(prod, {})
        years = sorted({pd.read_csv(f, nrows=1)["acq_date"].iloc[0][:4] for f in fs})
        out.append({
            "source": f"NASA FIRMS {info.get('instrument', '')} {info.get('satellite', prod)} ({prod})",
            "type": "Active fire (point detections)", "status": "Available",
            "date_range": f"{years[0]} – 2026-09-30" if years else "?",
            "spatial_resolution": f"{info.get('nominal_resolution_m', '?')} m pixel", "crs": "EPSG:4326 (WGS84 points)",
            "purpose": "Active-fire monitoring, inference fire-state initialisation, historical replay comparison (not a training input)",
            "format": f"CSV ({len(fs)} files, {size(fs)})", "local_path": rel(fs[0].parent.parent) + f"/DL_FIRE_{prod}_*",
            "preprocessing": "Normalised + de-duplicated to Parquet (region subset and 10-day global NRT)",
            "data_class": "observed",
        })
    if rep:
        out[0]["notes"] = (f"Region subset: {rep['region']['rows']:,} detections ({rep['region']['min'][:10]} – {rep['region']['max'][:10]}); "
                           f"global recent: {rep['recent_global']['rows']:,} ({rep['recent_global']['min'][:10]} – {rep['recent_global']['max'][:10]})")
    return out


def mtbs_severity_entry(mosaics: list[Path]) -> dict:
    """Status derived from the raw ZIPs, the preprocessing report and the GeoTIFFs actually on disk."""
    status, detail = mtbs_severity.inventory_status()
    rep = mtbs_severity.load_report() or {"years": []}
    done = [r for r in rep["years"] if r["status"] == "processed"]
    years = sorted({int(p.name.split("_")[-1][:4]) for p in mosaics})
    crs = done[0]["source"]["crs"] if done else "see embedded metadata"
    classes = done[0]["class_definitions"] if done else {}
    msgs = "; ".join(r["message"] for r in rep["years"] if r["status"] != "processed")
    return {
        "source": "MTBS thematic burn-severity mosaics (California)", "type": "Burn severity raster (categorical classes)",
        "status": status,
        "date_range": f"{years[0]} – {years[-1]}" if years else "—", "spatial_resolution": "30 m",
        "crs": f"{crs} (source)" + (f" → {done[0]['output_crs']} (processed)" if done else ""),
        "purpose": "Observed post-fire severity context for historical replays (not a training target or input)",
        "format": f"Zipped GeoTIFF + FGDC XML ({len(mosaics)} files, {size(mosaics)})",
        "local_path": "datasets/bsp_*/mtbs_CA_<year>.zip",
        "preprocessing": (f"Clipped to the study region, nearest-neighbour onto the LANDFIRE-aligned 30 m EPSG:5070 grid "
                          f"(exact pixel copy); processed years {detail.get('processed_years')} → "
                          f"{registry.sources()['mtbs']['processed_severity_dir']}/" if done else "not processed"),
        "data_class": "observed",
        "notes": (f"Classes (from XML): {', '.join(f'{k}={v}' for k, v in classes.items())}." if classes else "")
                 + (f" {msgs}." if msgs else ""),
    }


def main() -> None:
    src = registry.sources()
    entries: list[dict] = []
    entries += firms_entry()

    era = json.loads((R / "data/metadata/era5_preprocess_report.json").read_text())
    efiles = [registry.path(f["path"]) for f in src["era5"]["files"]]
    entries.append({
        "source": "ECMWF ERA5 hourly single levels", "type": "Weather reanalysis (gridded)", "status": "Available",
        "date_range": f"{era['time_min'][:10]} – {era['time_max'][:10]}", "spatial_resolution": "0.25° (~25 km), hourly",
        "crs": "EPSG:4326 regular lat/lon", "purpose": "Historical weather for reference simulations, training and replay",
        "format": f"GRIB ({len(efiles)} files, {size(efiles)})", "local_path": "datasets/<cds-request-id>/data.grib",
        "preprocessing": f"Subset to {era['lat']}N {era['lon']}E; K→°C, Td→RH, m→mm; NetCDF {era['output']}",
        "data_class": "observed", "notes": "Variables: 10u, 10v, 2t, 2d, tp, swvl1, lai_hv, lai_lv, cvh, cvl, avg_tprate (California extent 32.5–42N, 124.5–114.25W).",
    })

    srtm = registry.glob_paths(src["srtm"]["glob"])
    m = raster_meta(srtm[0])
    entries.append({
        "source": "NASA SRTM v3 1 arc-second", "type": "Digital elevation model", "status": "Available",
        "date_range": "2000 (mission)", "spatial_resolution": f"{m['res'][0] * 3600:.0f}″ (~30 m)", "crs": m["crs"],
        "purpose": "Elevation; derived slope and aspect; 3D terrain tiles", "format": f"GeoTIFF int16 ({len(srtm)} tiles, {size(srtm)})",
        "local_path": "datasets/n4*_w12*_1arc_v3.tif", "preprocessing": "Mosaic → per-window warp to EPSG:5070 (bilinear/average); Horn slope/aspect",
        "data_class": "observed", "notes": f"Tiles cover 40–42°N, 125–122°W; nodata {m['nodata']}",
    })

    lf = registry.path(src["landfire_fbfm40"]["path"])
    m = raster_meta(lf)
    entries.append({
        "source": "LANDFIRE 2025 FBFM40", "type": "Surface fuel model (Scott & Burgan 40)", "status": "Available",
        "date_range": "LF 2025 (version LF2025)", "spatial_resolution": f"{m['res'][0]:.0f} m", "crs": m["crs"],
        "purpose": "Fire-behaviour fuel model input (Rothermel) and model features", "format": f"GeoTIFF int16 + VAT ({size([lf])})",
        "local_path": rel(lf), "preprocessing": "Native grid; nearest (30 m) or mode (60/120 m) aggregation",
        "data_class": "observed", "notes": "Extent 40–42°N, 124.5–122°W (download box). Defines the model domain.",
    })

    wc = registry.glob_paths(src["worldcover"]["glob"])
    m = raster_meta(wc[0])
    entries.append({
        "source": "ESA WorldCover 2021 v200", "type": "Land cover (11 classes)", "status": "Available",
        "date_range": "2021", "spatial_resolution": f"10 m nominal ({m['res'][0]:.3g}°)", "crs": m["crs"],
        "purpose": "Descriptive land-cover input (not a fuel-model substitute)", "format": f"GeoTIFF uint8 ({len(wc)} tiles, {size(wc)})",
        "local_path": "datasets/terrascope_download_*/WORLDCOVER/...", "preprocessing": "Mode resampling to grid; ~100 m mosaic for coarse windows",
        "data_class": "observed", "notes": "Tiles N39W123, N39W126 (39–42°N, 126–120°W)",
    })

    mrep = json.loads((R / "data/metadata/mtbs_preprocess_report.json").read_text())
    zp = registry.path(src["mtbs"]["perimeters_zip"])
    mosaics = registry.glob_paths(src["mtbs"]["severity_mosaic_zips"])
    entries.append({
        "source": "MTBS / burned-area perimeters (MTBS, BAER, RAVG, CBI)", "type": "Burned-area perimeters (vector)", "status": "Available",
        "date_range": f"{mrep.get('range_ig_date', ['?', '?'])[0]} – {mrep.get('range_ig_date', ['?', '?'])[1]}",
        "spatial_resolution": "vector (Landsat-derived, 30 m)", "crs": "EPSG:4269 (NAD83 geographic)",
        "purpose": "Historical-fire catalogue and final-perimeter context (not used for metrics or training)", "format": f"Zipped shapefile ({size([zp])})",
        "local_path": rel(zp), "preprocessing": f"BBox-filtered {mrep['rows']} perimeters → GeoJSON (pure-Python shapefile reader)",
        "data_class": "observed",
    })
    entries.append(mtbs_severity_entry(mosaics))
    entries.append({
        "source": "Open-Meteo Forecast API", "type": "Current + forecast weather (NWP)", "status": "Online (no key)",
        "date_range": "past 3 days + 4-day forecast", "spatial_resolution": "model-dependent (best match, ~1–11 km)", "crs": "EPSG:4326",
        "purpose": "Live weather for predictions, monitoring and alerts", "format": "JSON API", "local_path": "—",
        "preprocessing": "Cached 15 min; snapshots in MongoDB weather_conditions", "data_class": "observed",
    })
    ds_m = R / "data/processed/training/wtrs-ncal-v1/manifest.json"
    if ds_m.exists():
        man = json.loads(ds_m.read_text())
        sa = pd.read_parquet(R / "data/processed/training/wtrs-ncal-v1/samples.parquet")
        entries.append({
            "source": f"WTRS reference simulations ({man['dataset_version']})", "type": "Simulated fire-spread dataset", "status": "Generated",
            "date_range": "ERA5 2024–2025 fire seasons (Jun–Oct)", "spatial_resolution": "30 / 60 / 120 m, 128×128",
            "crs": "EPSG:5070", "purpose": "Training / validation / test of U-Net, FNO, PI-FNO",
            "format": "NPZ per scenario + Parquet index", "local_path": rel(ds_m.parent),
            "preprocessing": f"{sa['scenario_id'].nunique()} scenarios, {int(sa['valid'].sum())} valid samples; spatial-block split",
            "data_class": "simulated", "notes": "Internal Rothermel + MTT reference simulator (not FARSITE/FlamMap); FFWI-weighted start-time sampling.",
        })
    entries.append({
        "source": "FARSITE / FlamMap outputs", "type": "External reference simulations", "status": "Not present",
        "date_range": "—", "spatial_resolution": "—", "crs": "—", "purpose": "Optional reference / benchmark data",
        "format": "arrival-time raster or timed perimeters", "local_path": "simulation/outputs/ (import via CLI, UI or API)",
        "preprocessing": "simulation/converters/importers.py", "data_class": "simulated",
    })

    out = {"generated_utc": datetime.now(timezone.utc).isoformat(), "entries": entries}
    (R / "data/metadata").mkdir(parents=True, exist_ok=True)
    (R / "data/metadata/catalog.json").write_text(json.dumps(out, indent=2))

    lines = ["# Data Inventory", "", f"_Generated {out['generated_utc'][:19]}Z by `python -m scripts.inventory_data` from file metadata._", "",
             "Raw files remain in `datasets/` exactly as downloaded (nothing moved or copied). Processed products live in `data/processed/`.", ""]
    for e in entries:
        lines += [f"## {e['source']}", "", "| field | value |", "|---|---|"]
        for k in ("type", "status", "date_range", "spatial_resolution", "crs", "format", "local_path", "purpose", "preprocessing", "data_class", "notes"):
            if e.get(k):
                lines.append(f"| {k.replace('_', ' ')} | {str(e[k]).replace('|', '/')} |")
        lines.append("")
    (R / "data/DATA_INVENTORY.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"catalog: {len(entries)} entries")


if __name__ == "__main__":
    main()
