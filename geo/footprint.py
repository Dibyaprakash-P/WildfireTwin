"""Observed active-fire footprint rasterisation (initial fire state from FIRMS).

Each detection is drawn as its satellite pixel footprint: an axis-aligned
rectangle of `scan_km` (east-west) x `track_km` (north-south) centred on the
detection. Real pixel footprints are rotated with the orbit track; the
axis-aligned approximation is documented. When scan/track are missing the
nominal sensor resolution (VIIRS 0.375 km, MODIS 1 km) is used.

The result is an OBSERVED ACTIVE-FIRE FOOTPRINT used to initialise the model,
not an official fire perimeter.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pyproj import Transformer

from geo.rasters import AnalysisGrid

NOMINAL_KM = {"VIIRS": 0.375, "MODIS": 1.0}


def rasterize_detections(det: pd.DataFrame, grid: AnalysisGrid) -> tuple[np.ndarray, dict]:
    mask = np.zeros(grid.shape, dtype=np.float32)
    if det.empty:
        return mask, {"detections_used": 0}
    tr = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    xs, ys = tr.transform(det["longitude"].to_numpy(), det["latitude"].to_numpy())
    inst = det.get("instrument", pd.Series(["VIIRS"] * len(det))).astype(str).str.upper()
    default = np.where(inst.str.contains("MODIS"), NOMINAL_KM["MODIS"], NOMINAL_KM["VIIRS"])
    scan = pd.to_numeric(det.get("scan_km"), errors="coerce").fillna(pd.Series(default, index=det.index)).to_numpy()
    track = pd.to_numeric(det.get("track_km"), errors="coerce").fillna(pd.Series(default, index=det.index)).to_numpy()
    used = 0
    for x, y, sk, tk in zip(xs, ys, scan, track):
        hx, hy = sk * 500.0, tk * 500.0
        c0 = int(np.floor((x - hx - grid.x0) / grid.cell)); c1 = int(np.ceil((x + hx - grid.x0) / grid.cell))
        r0 = int(np.floor((grid.y0 - (y + hy)) / grid.cell)); r1 = int(np.ceil((grid.y0 - (y - hy)) / grid.cell))
        c0, c1 = max(c0, 0), min(c1, grid.size)
        r0, r1 = max(r0, 0), min(r1, grid.size)
        if c0 < c1 and r0 < r1:
            mask[r0:r1, c0:c1] = 1.0
            used += 1
    return mask, {"detections_used": used, "method": "axis-aligned scan x track pixel footprints",
                  "label": "observed active-fire footprint (initialisation, not an official perimeter)"}
