"""Terrain derivatives on a projected (metre) grid.

Slope and aspect use Horn's (1981) 3x3 finite-difference method, the same
operator used by GDAL `gdaldem` and ArcGIS.

Conventions
-----------
slope_deg   0..90 degrees
aspect_deg  direction the slope FACES (downslope), clockwise from grid north,
            0..360; -1 for flat cells (slope < 0.1 deg).
The grid's "north" is the projected y-axis. In EPSG:5070 this differs from
true north by the meridian convergence (< ~4 deg over the study area); this
is logged as a known approximation in docs/data_pipeline.md.
"""

from __future__ import annotations

import numpy as np


def slope_aspect(dem: np.ndarray, cell_size_m: float) -> tuple[np.ndarray, np.ndarray]:
    z = np.pad(dem.astype(np.float64), 1, mode="edge")
    a, b, c = z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:]
    d, f = z[1:-1, :-2], z[1:-1, 2:]
    g, h, i = z[2:, :-2], z[2:, 1:-1], z[2:, 2:]
    # Row index increases southward; dz/dx east-positive, dz/dy north-positive.
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8.0 * cell_size_m)
    dzdy = ((a + 2 * b + c) - (g + 2 * h + i)) / (8.0 * cell_size_m)
    grad = np.hypot(dzdx, dzdy)
    slope = np.degrees(np.arctan(grad))
    # Downslope direction is -gradient: east component -dzdx, north component -dzdy.
    aspect = (np.degrees(np.arctan2(-dzdx, -dzdy)) + 360.0) % 360.0
    aspect = np.where(slope < 0.1, -1.0, aspect)
    return slope.astype(np.float32), aspect.astype(np.float32)


def upslope_direction_rad(aspect_deg: np.ndarray) -> np.ndarray:
    """Upslope azimuth (radians clockwise from north). Flat cells -> 0."""
    up = np.where(aspect_deg < 0, 0.0, (aspect_deg + 180.0) % 360.0)
    return np.radians(up)
