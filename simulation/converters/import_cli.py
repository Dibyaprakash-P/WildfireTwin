"""Offline import of FARSITE / FlamMap outputs (no web server needed).

Usage
-----
python -m simulation.converters.import_cli --file simulation/outputs/run01_arrival.asc --kind arrival_raster \
    --simulator FlamMap --units minutes [--crs EPSG:5070] --name run01 \
    [--ignition-time 2024-08-10T18:00]

python -m simulation.converters.import_cli --file simulation/outputs/run01_perims.zip --kind perimeters \
    --simulator FARSITE --units minutes --time-field <elapsed-time attribute> --name run01

Writes data/simulations/IMPORT-<name>/ (arrival_min.tif + meta.json) and appends to
data/simulations/imported_index.json. Imported runs are labelled with their own engine and never mixed into WTRS.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from geo import registry
from simulation.converters.importers import ImportErrorInvalid, import_arrival_raster, import_perimeters, save

SIM_ROOT = registry.path("data/simulations")


def load_index(root: Path | None = None) -> list[dict]:
    idx = (root or SIM_ROOT) / "imported_index.json"
    return json.loads(idx.read_text()) if idx.exists() else []


def run(file: Path, kind: str, simulator: str, units: str, name: str, crs: str | None = None,
        time_field: str | None = None, ignition_time: str | None = None, root: Path | None = None) -> dict:
    root = root or SIM_ROOT
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        raise ImportErrorInvalid("name must be 1-40 characters [A-Za-z0-9_-]")
    if kind == "arrival_raster":
        sim = import_arrival_raster(file, units, simulator, crs=crs)
    elif kind == "perimeters":
        if not time_field:
            raise ImportErrorInvalid("--time-field is required for perimeters")
        sim = import_perimeters(file, time_field, units, simulator)
    else:
        raise ImportErrorInvalid("kind must be arrival_raster or perimeters")
    sim.meta["name"] = name
    sim.meta["ignition_time_utc"] = ignition_time  # needed later to attach matching weather (build_dataset)
    out = root / f"IMPORT-{name}"
    save(sim, out)
    idx = [e for e in load_index(root) if e["name"] != name]
    idx.append({"name": name, "path": out.as_posix(), **{k: sim.meta[k] for k in (
        "simulator", "simulation_source", "kind", "source_file", "source_sha256", "imported_utc", "burned_cells")}})
    root.mkdir(parents=True, exist_ok=True)
    (root / "imported_index.json").write_text(json.dumps(idx, indent=2))
    return sim.meta | {"output": out.as_posix()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True, type=Path)
    ap.add_argument("--kind", required=True, choices=["arrival_raster", "perimeters"])
    ap.add_argument("--simulator", required=True, choices=["FARSITE", "FlamMap", "other"])
    ap.add_argument("--units", required=True, choices=["minutes", "hours"], help="time units of the export (check your run settings)")
    ap.add_argument("--name", required=True)
    ap.add_argument("--crs", help="only for rasters without CRS (e.g. .asc without .prj)")
    ap.add_argument("--time-field", help="elapsed-time attribute of the perimeter file")
    ap.add_argument("--ignition-time", help="UTC ignition/start time of the run (ISO), used to attach weather")
    a = ap.parse_args()
    meta = run(a.file, a.kind, a.simulator, a.units, a.name, a.crs, a.time_field, a.ignition_time)
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
