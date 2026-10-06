"""Data-source catalogue with LIVE status and verified roles.

Descriptive metadata (date ranges, sizes, CRS) comes from data/metadata/catalog.json, which
`python -m scripts.inventory_data` extracts from the files. Status is recomputed on every request from what
actually exists, so nothing is shown as "Available" when files are missing. Roles reflect the audited code paths
(docs/scientific_audit.md), not intentions:

  used_in_training  the variable/data enters the training samples (inputs or targets)
  roles             where the code actually uses it
Installed software (FlamMap) is reported separately from available data.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from backend.app.db import db_available, get_db
from geo import registry

GROUP_ORDER = ["observed", "simulated", "external"]
GROUP_LABEL = {"observed": "Observed data", "simulated": "Simulated / reference data",
               "external": "External optional reference"}

# (match on catalogue "source" prefix) -> verified role description
ROLES: list[tuple[str, dict]] = [
    ("NASA FIRMS", {"group": "observed", "used_in_training": False, "roles": [
        "global fire discovery and monitoring (globe, fire events)",
        "inference: observed active-fire footprint as the initial fire state",
        "historical replay: initial state at t0 and observed footprint at t0+h for validation"],
        "note": "Training fire states come from WTRS simulations, not from FIRMS."}),
    ("ECMWF ERA5", {"group": "observed", "used_in_training": True, "roles": [
        "weather forcing of WTRS reference simulations", "training input channels (temperature, RH, wind u/v, precipitation, soil moisture)",
        "historical replay weather"]}),
    ("NASA SRTM", {"group": "observed", "used_in_training": True, "roles": [
        "elevation + derived slope/aspect input channels", "Rothermel slope effect in WTRS", "3D terrain and relief tiles"]}),
    ("LANDFIRE", {"group": "observed", "used_in_training": True, "roles": [
        "FBFM40 fuel models for the Rothermel spread rates in WTRS", "fuel input channels (group, 1-h load, depth, burnable)"]}),
    ("ESA WorldCover", {"group": "observed", "used_in_training": True, "roles": [
        "land-cover input channels (descriptive; not a fuel-model substitute)"]}),
    ("MTBS / burned-area", {"group": "observed", "used_in_training": False, "roles": [
        "historical fire catalogue (which fires can be replayed)", "final-perimeter display for context"],
        "note": "Replay metrics are computed against the observed FIRMS footprint, not against these perimeters."}),
    ("MTBS thematic", {"group": "observed", "used_in_training": False, "roles": [
        "historical replay context: post-fire severity of the predicted area and share predicted beyond the final mapped extent"],
        "note": "Categorical post-fire product without timing; not a spread metric, training target or model input."}),
    ("Open-Meteo", {"group": "observed", "used_in_training": False, "roles": [
        "current/forecast weather for live inference, environment panel, monitoring and alerts"],
        "note": "NWP forecast/analysis data; not used in training."}),
    ("NOAA GFS", {"group": "observed", "used_in_training": False, "roles": [
        "globe wind-flow layer: animated particles following the global 10 m U/V field (visualisation only)"],
        "note": "Model analysis (GFS f000), not an observation; not an input of the spread models."}),
    ("WTRS reference", {"group": "simulated", "used_in_training": True, "roles": [
        "training / validation / test targets and fire states for U-Net, FNO, PI-FNO"]}),
    ("FARSITE / FlamMap", {"group": "external", "used_in_training": False, "roles": [
        "optional external reference / benchmark (import pipeline)"]}),
]

GFS_WIND_ENTRY = {
    "source": "NOAA GFS 10 m wind (global analysis)", "type": "Gridded U/V wind, GFS analysis f000 (NWP)",
    "status": "Online (no key)", "date_range": "latest 6-hourly cycle", "spatial_resolution": "1.0° (360 × 181)",
    "crs": "EPSG:4326", "purpose": "Wind-flow visualisation on the globe", "format": "GRIB2 via NOMADS filter",
    "local_path": "data/processed/weather/wind/ (last cycle cache)",
    "preprocessing": "Decoded with eccodes; served as int16 (0.01 m/s) by /api/wind/field; refreshed ≤ every 30 min",
    "data_class": "observed",
}

FLAMMAP_CANDIDATES = [r"C:\Workspace\FlamMap6", r"C:\Program Files\FlamMap6", r"C:\Program Files (x86)\FlamMap6",
                      r"C:\FlamMap6"]


def _role(source: str) -> dict:
    for prefix, r in ROLES:
        if source.startswith(prefix):
            return r
    return {"group": "observed", "used_in_training": False, "roles": []}


def _exists(pattern: str) -> int:
    return len(registry.glob_paths(pattern))


def detect_flammap() -> dict:
    env = os.environ.get("FLAMMAP_HOME")
    for c in ([env] if env else []) + FLAMMAP_CANDIDATES:
        if c and Path(c, "FlamMap6.exe").exists():
            engines = [e for e in ("farsite.dll", "flammap.dll") if Path(c, e).exists()]
            return {"installed": True, "path": c, "engines": engines}
    return {"installed": False, "path": None, "engines": []}


async def imported_simulations() -> list[dict]:
    if not db_available():
        return []
    cur = get_db().simulations.find({"kind": "imported"}, {"_id": 0, "simulation_id": 1, "simulator": 1, "created_at": 1})
    return [d async for d in cur]


def _live_status(source: str, entry: dict, imported: list[dict]) -> tuple[str, dict]:
    src = registry.sources()
    extra: dict = {}
    if source.startswith("NASA FIRMS"):
        prod = source.split("(")[-1].rstrip(")")
        n = _exists(f"datasets/DL_FIRE_{prod}_*/*.csv")
        return ("Available" if n else "Missing"), {"files_found": n}
    if source.startswith("ECMWF ERA5"):
        ok = all(registry.path(f["path"]).exists() for f in src["era5"]["files"])
        proc = registry.path(src["era5"]["processed"]).exists()
        return ("Available" if ok and proc else "Missing" if not ok else "Raw only (not processed)"), {}
    if source.startswith("NASA SRTM"):
        return ("Available" if _exists(src["srtm"]["glob"]) else "Missing"), {}
    if source.startswith("LANDFIRE"):
        return ("Available" if registry.path(src["landfire_fbfm40"]["path"]).exists() else "Missing"), {}
    if source.startswith("ESA WorldCover"):
        return ("Available" if _exists(src["worldcover"]["glob"]) else "Missing"), {}
    if source.startswith("MTBS / burned-area"):
        ok = registry.path(src["mtbs"]["perimeters_zip"]).exists()
        return ("Available" if ok else "Missing"), {}
    if source.startswith("MTBS thematic"):
        from geo import mtbs_severity
        status, detail = mtbs_severity.inventory_status()
        return status, detail
    if source.startswith("Open-Meteo"):
        from backend.app.services.weather import weather_service
        return ("Online (recent successful request)" if weather_service._cache else "Online service · not yet queried"), {}
    if source.startswith("NOAA GFS"):
        from backend.app.services.wind_field import wind_field_service
        f = wind_field_service._field
        if f is None:
            return "Online service · not yet queried", {}
        return "Online (cached field)", {"cycle": f.cycle.isoformat().replace("+00:00", "Z"), "grid": f"{f.nx}×{f.ny}"}
    if source.startswith("WTRS reference"):
        d = registry.path("data/processed/training/wtrs-ncal-v1")
        if not (d / "manifest.json").exists():
            return "Not generated", {}
        sa = pd.read_parquet(d / "samples.parquet", columns=["scenario_id", "valid", "split"])
        man = json.loads((d / "manifest.json").read_text())
        prov = man.get("provenance", {})
        extra = {"scenarios": int(sa["scenario_id"].nunique()), "samples": int(len(sa)), "valid_samples": int(sa["valid"].sum()),
                 "valid_by_split": {k: int(v) for k, v in sa[sa["valid"]].groupby("split").size().items()},
                 "reference_engine": prov.get("reference_engine", man.get("simulator")),
                 "simulation_source": prov.get("simulation_source", "WTRS"),
                 "simulation_method": prov.get("simulation_method"), "dataset_version": man.get("dataset_version")}
        return "Generated", extra
    if source.startswith("FARSITE / FlamMap"):
        files = [p for p in registry.glob_paths("simulation/outputs/**/*") if p.is_file() and p.name.lower() != "readme.md"]
        from simulation.converters.import_cli import load_index
        cli = load_index()
        imported = imported + [{"simulation_id": e["name"], "simulator": e["simulator"]} for e in cli]
        if imported:
            return "Imported", {"imported_runs": len(imported), "simulators": sorted({i.get("simulator") for i in imported})}
        if files:
            return "Files present · not imported", {"files": [str(p.relative_to(registry.REPO_ROOT)) for p in files[:10]]}
        return "Not present", {"expected_location": "simulation/outputs/ (then import via UI/API/CLI)", "import_supported": True}
    return entry.get("status", "Unknown"), extra


async def live_catalog() -> dict:
    base = json.loads(registry.path("data/metadata/catalog.json").read_text())
    imported = await imported_simulations()
    entries = []
    for e in base["entries"] + [GFS_WIND_ENTRY]:
        role = _role(e["source"])
        status, extra = _live_status(e["source"], e, imported)
        e = dict(e)
        e.update({"status": status, "group": role["group"], "used_in_training": role["used_in_training"],
                  "roles": role.get("roles", []), "role_note": role.get("note"), **({"live": extra} if extra else {})})
        if e["source"].startswith("WTRS reference"):
            e["source"] = f"WTRS reference simulations ({extra.get('dataset_version', 'wtrs-ncal-v1')})"
            e["engine"] = "Rothermel + MTT"
            e["notes"] = ("Internal WildfireTwin simulation pipeline (simulation/rothermel.py + simulation/spread.py). "
                          "Not FARSITE/FlamMap output. FFWI-weighted start-time sampling.")
        if e["source"].startswith("FARSITE / FlamMap"):
            e["engine"] = "FARSITE / FlamMap (external)"
        entries.append(e)
    entries.sort(key=lambda x: GROUP_ORDER.index(x["group"]))
    fm = detect_flammap()
    software = [{"name": "FlamMap 6 (includes FARSITE engine)", "status": "Installed" if fm["installed"] else "Not detected",
                 "path": fm["path"], "engines": fm["engines"],
                 "note": "Installed software is not data: FARSITE/FlamMap outputs stay 'Not present' until runs are exported "
                         "and imported. Never required by end users."}]
    return {"generated_utc": base["generated_utc"], "groups": GROUP_LABEL, "entries": entries, "software": software}
