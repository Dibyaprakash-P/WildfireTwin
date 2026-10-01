"""Build a local, co-registered landscape stack around a point.

Layers (all on one AnalysisGrid, EPSG:5070):
  REQUIRED  elevation_m   SRTM 1-arcsec, bilinear (<=30 m) / average (coarser)
            fuel_code     LANDFIRE 2025 FBFM40, nearest (30 m) / mode (coarser)
  DERIVED   slope_deg, aspect_deg   Horn (1981) on the warped DEM
  OPTIONAL  landcover     ESA WorldCover 2021, mode (10 m tiles or ~100 m mosaic)

Raises LandscapeUnavailable when a required layer does not cover the grid.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from rasterio.enums import Resampling

from geo import registry
from geo.rasters import AnalysisGrid, TransformLog, build_srtm_mosaic, build_worldcover_mosaic, warp_to_grid, worldcover_tiles
from geo.terrain import slope_aspect

log = logging.getLogger(__name__)

MIN_VALID_FRACTION = 0.98


class LandscapeUnavailable(RuntimeError):
    pass


@dataclass
class Landscape:
    grid: AnalysisGrid
    elevation_m: np.ndarray
    slope_deg: np.ndarray
    aspect_deg: np.ndarray
    fuel_code: np.ndarray
    landcover: np.ndarray | None
    transforms: TransformLog = field(default_factory=TransformLog)

    def stack(self) -> dict[str, np.ndarray]:
        d = {"elevation_m": self.elevation_m, "slope_deg": self.slope_deg, "aspect_deg": self.aspect_deg,
             "fuel_code": self.fuel_code.astype(np.int16)}
        if self.landcover is not None:
            d["landcover"] = self.landcover.astype(np.uint8)
        return d


def build_landscape(grid: AnalysisGrid, with_landcover: bool = True) -> Landscape:
    tlog = TransformLog()
    # Pad by one cell so slope/aspect at the window edge use real neighbours.
    pad = AnalysisGrid(grid.crs, grid.x0 - grid.cell, grid.y0 + grid.cell, grid.cell, grid.size + 2)

    dem_rs = Resampling.bilinear if grid.cell <= 30 else Resampling.average
    dem, dem_ok = warp_to_grid(build_srtm_mosaic(), pad, dem_rs, tlog, "SRTM_1arc_v3", "float32")
    if dem_ok.mean() < MIN_VALID_FRACTION:
        raise LandscapeUnavailable("Terrain data not available for this region (SRTM coverage).")
    dem = np.where(dem_ok, dem, np.nanmean(np.where(dem_ok, dem, np.nan)))
    slope, aspect = slope_aspect(dem, grid.cell)
    dem, slope, aspect = dem[1:-1, 1:-1], slope[1:-1, 1:-1], aspect[1:-1, 1:-1]

    fuel_rs = Resampling.nearest if grid.cell <= 30 else Resampling.mode
    fuel_path = registry.path(registry.sources()["landfire_fbfm40"]["path"])
    fuel, fuel_ok = warp_to_grid(fuel_path, grid, fuel_rs, tlog, "LANDFIRE_FBFM40_2025", "int16")
    if fuel_ok.mean() < MIN_VALID_FRACTION:
        raise LandscapeUnavailable("Fuel-model data (LANDFIRE FBFM40) not available for this region.")
    fuel = np.where(fuel_ok, fuel, 99)  # outside-coverage slivers treated as NB9 (logged via fraction)

    lc = None
    if with_landcover:
        if grid.cell < 100:
            lc = _landcover_from_tiles(grid, tlog)
        else:
            lc, lc_ok = warp_to_grid(build_worldcover_mosaic(), grid, Resampling.mode, tlog, "ESA_WorldCover_2021_100m", "uint8")
            if lc_ok.mean() < MIN_VALID_FRACTION:
                lc = None
    return Landscape(grid, dem.astype(np.float32), slope, aspect, fuel.astype(np.int16), lc, tlog)


def _landcover_from_tiles(grid: AnalysisGrid, tlog: TransformLog) -> np.ndarray | None:
    w, s, e, n = grid.bounds_wgs84()
    out = np.zeros(grid.shape, dtype=np.uint8)
    import rasterio
    for p in worldcover_tiles():
        with rasterio.open(p) as src:
            b = src.bounds
            if b.right < w or b.left > e or b.top < s or b.bottom > n:
                continue
        part, ok = warp_to_grid(p, grid, Resampling.mode, tlog, "ESA_WorldCover_2021_10m", "uint8")
        out = np.where(ok & (part > 0), part, out)
    return out if (out > 0).mean() >= MIN_VALID_FRACTION else None
