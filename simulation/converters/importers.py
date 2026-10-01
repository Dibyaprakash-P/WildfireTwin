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
labelled data_class = "simulated", simulator = "FARSITE" / "FlamMap" (as
declared by the user). Nothing is generated or interpolated beyond the
supplied file.
"""

from __future__ import annotations

import json
import zipfile
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


def import_arrival_raster(path: Path, units: str, simulator: str) -> ImportedSimulation:
    if units not in ("minutes", "hours"):
        raise ImportErrorInvalid("units must be 'minutes' or 'hours'")
    with rasterio.open(path) as src:
        if src.crs is None:
            raise ImportErrorInvalid("raster has no CRS (supply a .prj with the .asc or a georeferenced GeoTIFF)")
        a = src.read(1).astype(np.float32)
        nod = src.nodata
        valid = np.isfinite(a) & (a >= 0)
        if nod is not None:
            valid &= a != nod
        a = np.where(valid, a * (60.0 if units == "hours" else 1.0), -1.0).astype(np.float32)
        meta = {"source_file": path.name, "simulator": simulator, "data_class": "simulated", "input_units": units,
                "shape": list(a.shape), "crs": src.crs.to_string(), "res": list(src.res),
                "burned_cells": int(valid.sum()), "max_arrival_min": float(a[valid].max()) if valid.any() else None}
        return ImportedSimulation(a, src.transform, src.crs.to_string(), meta)


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
    gdf["_t"] = gdf[time_field].astype(float) * (60.0 if units == "hours" else 1.0)
    xmin, ymin, xmax, ymax = gdf.total_bounds
    pad = 5 * cell_m
    xmin, ymin, xmax, ymax = xmin - pad, ymin - pad, xmax + pad, ymax + pad
    w, h = int(np.ceil((xmax - xmin) / cell_m)), int(np.ceil((ymax - ymin) / cell_m))
    tr = from_origin(xmin, ymax, cell_m, cell_m)
    arrival = np.full((h, w), -1.0, dtype=np.float32)
    for _, r in gdf.sort_values("_t", ascending=False).iterrows():   # earliest written last
        m = rasterize([(r.geometry, 1)], out_shape=(h, w), transform=tr, fill=0, dtype="uint8").astype(bool)
        arrival[m] = r["_t"]
    meta = {"source_file": path.name, "simulator": simulator, "data_class": "simulated", "input_units": units,
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
