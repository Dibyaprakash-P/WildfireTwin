"""Import externally produced reference simulations (FARSITE / FlamMap) — offline research workflow.

Supported inputs
----------------
1. Arrival-time raster (preferred)
   * FlamMap MTT  "Arrival Time" output, or FARSITE "Time of Arrival" grid
   * GeoTIFF (.tif) or ESRI ASCII grid (.asc with a sidecar .prj)
   * values: time since ignition; units given by the user (minutes or hours);
     nodata / negative values = not burned
2. Timed perimeters (vector)
   * FARSITE perimeter shapefile (zipped) or GeoJSON with an elapsed-time
     attribute (`time_field`, in minutes or hours since ignition)
   * rasterised to arrival time on a grid of `cell_m` metres in EPSG:5070
     (earliest perimeter containing each cell centre)

Output: arrival-time GeoTIFF in minutes (float32, nodata = -1) + metadata,
labelled data_class = "simulated", simulation_source = "FARSITE" / "FlamMap"
(as declared by the user), with the SHA-256 of the source file for traceability.
Nothing is generated or interpolated beyond the supplied file.

Time-stamped frames are DERIVED from the arrival field (`arrival_to_frames`):
burned(t) = arrival <= t. No other frame format is assumed.
Imported runs never enter the WTRS dataset; `build_dataset.py` converts them into a separate dataset version.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin

ALLOWED_SIMULATORS = ("FARSITE", "FlamMap", "other")


@dataclass
class ImportedSimulation:
    arrival_min: np.ndarray
    transform: object
    crs: str
    meta: dict


class ImportErrorInvalid(ValueError):
    pass


def _provenance(path: Path, simulator: str) -> dict:
    if simulator not in ALLOWED_SIMULATORS:
        raise ImportErrorInvalid(f"simulator must be one of {ALLOWED_SIMULATORS}")
    h = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return {"simulator": simulator, "simulation_source": simulator, "reference_engine": f"{simulator} (external, imported)",
            "data_class": "simulated", "source_sha256": h, "imported_utc": datetime.now(timezone.utc).isoformat()}


def arrival_to_frames(arrival_min: np.ndarray, times_min: list[float]) -> dict[float, np.ndarray]:
    """Burned masks at the requested times, derived exactly from the arrival field (no interpolation)."""
    valid = arrival_min >= 0
    return {t: (valid & (arrival_min <= t)) for t in times_min}


def import_arrival_raster(path: Path, units: str, simulator: str, crs: str | None = None) -> ImportedSimulation:
    """`crs` is used ONLY when the file has no CRS (e.g. an .asc exported without .prj) and must be given explicitly."""
    if units not in ("minutes", "hours"):
        raise ImportErrorInvalid("units must be 'minutes' or 'hours'")
    with rasterio.open(path) as src:
        file_crs = src.crs.to_string() if src.crs else None
        if file_crs is None and not crs:
            raise ImportErrorInvalid("raster has no CRS: supply the .prj with the .asc, a georeferenced GeoTIFF, "
                                     "or pass the landscape CRS explicitly (e.g. EPSG:5070 for LANDFIRE-based landscapes)")
        a = src.read(1).astype(np.float32)
        nod = src.nodata
        valid = np.isfinite(a) & (a >= 0)
        if nod is not None:
            valid &= a != nod
        a = np.where(valid, a * (60.0 if units == "hours" else 1.0), -1.0).astype(np.float32)
        use_crs = file_crs or crs
        meta = {"source_file": path.name, **_provenance(path, simulator), "kind": "arrival_raster", "input_units": units,
                "shape": list(a.shape), "crs": use_crs, "crs_from": "file" if file_crs else "user-specified",
                "res": list(src.res), "burned_cells": int(valid.sum()),
                "max_arrival_min": float(a[valid].max()) if valid.any() else None}
        return ImportedSimulation(a, src.transform, use_crs, meta)


def import_perimeters(path: Path, time_field: str, units: str, simulator: str, cell_m: float = 60.0,
                      crs: str = "EPSG:5070") -> ImportedSimulation:
    from geo.vectors import read_vector
    if units not in ("minutes", "hours"):
        raise ImportErrorInvalid("units must be 'minutes' or 'hours'")
    gdf = read_vector(path)
    if time_field not in gdf.columns:
        raise ImportErrorInvalid(f"time field '{time_field}' not found; available: {list(gdf.columns)}")
    if gdf.crs is None:
        raise ImportErrorInvalid("perimeter file has no CRS")
    gdf = gdf.to_crs(crs)
    try:
        gdf["_t"] = gdf[time_field].astype(float) * (60.0 if units == "hours" else 1.0)
    except (TypeError, ValueError):
        raise ImportErrorInvalid(f"time field '{time_field}' must hold elapsed time since ignition ({units}); "
                                 "convert date/time attributes to elapsed time before importing")
    xmin, ymin, xmax, ymax = gdf.total_bounds
    pad = 5 * cell_m
    xmin, ymin, xmax, ymax = xmin - pad, ymin - pad, xmax + pad, ymax + pad
    w, h = int(np.ceil((xmax - xmin) / cell_m)), int(np.ceil((ymax - ymin) / cell_m))
    tr = from_origin(xmin, ymax, cell_m, cell_m)
    arrival = np.full((h, w), -1.0, dtype=np.float32)
    for _, r in gdf.sort_values("_t", ascending=False).iterrows():   # earliest written last
        m = rasterize([(r.geometry, 1)], out_shape=(h, w), transform=tr, fill=0, dtype="uint8").astype(bool)
        arrival[m] = r["_t"]
    meta = {"source_file": path.name, **_provenance(path, simulator), "kind": "perimeters", "input_units": units,
            "time_field": time_field, "perimeters": int(len(gdf)), "cell_m": cell_m, "crs": crs,
            "shape": [h, w], "burned_cells": int((arrival >= 0).sum())}
    return ImportedSimulation(arrival, tr, crs, meta)


def save(sim: ImportedSimulation, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "arrival_min.tif"
    with rasterio.open(p, "w", driver="GTiff", height=sim.arrival_min.shape[0], width=sim.arrival_min.shape[1], count=1,
                       dtype="float32", crs=sim.crs, transform=sim.transform, nodata=-1.0, compress="deflate") as dst:
        dst.write(sim.arrival_min, 1)
    (out_dir / "meta.json").write_text(json.dumps(sim.meta, indent=2))
    return p


def extract_upload(zip_path: Path, dest: Path) -> list[Path]:
    """Safely extract an uploaded zip (no path traversal)."""
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if not name or info.is_dir():
                continue
            target = dest / name
            with z.open(info) as s, open(target, "wb") as d:
                d.write(s.read())
            out.append(target)
    return out
