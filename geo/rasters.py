"""Raster grid definition, mosaicking and logged window extraction.

Every local analysis grid is an `AnalysisGrid`: square, north-up, in the
analysis CRS (EPSG:5070), with its origin snapped to the LANDFIRE 30 m grid so
that fuel cells are never shifted. All sources are warped onto this grid with
an explicit resampling method, and every warp is recorded in a
`TransformLog` that ends up in sample / prediction metadata.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.warp import reproject

from geo import registry

log = logging.getLogger(__name__)

LANDFIRE_ORIGIN = (-2375775.0, 2459865.0)  # upper-left of the local LANDFIRE download (EPSG:5070)


@dataclass
class TransformLog:
    entries: list[dict] = field(default_factory=list)

    def add(self, source: str, src_crs: str, dst_crs: str, resampling: str, src_res: float, dst_res: float) -> None:
        entry = {"source": source, "src_crs": src_crs, "dst_crs": dst_crs, "resampling": resampling,
                 "src_res": src_res, "dst_res": dst_res, "reprojected": src_crs != dst_crs}
        self.entries.append(entry)
        log.info("warp %s %s->%s (%s, %.6g->%.6g)", source, src_crs, dst_crs, resampling, src_res, dst_res)


@dataclass(frozen=True)
class AnalysisGrid:
    crs: str
    x0: float          # upper-left x
    y0: float          # upper-left y
    cell: float        # metres
    size: int          # cells per side

    @property
    def transform(self) -> Affine:
        return Affine(self.cell, 0, self.x0, 0, -self.cell, self.y0)

    @property
    def shape(self) -> tuple[int, int]:
        return self.size, self.size

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.x0, self.y0 - self.cell * self.size, self.x0 + self.cell * self.size, self.y0

    def bounds_wgs84(self) -> tuple[float, float, float, float]:
        tr = Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True)
        xmin, ymin, xmax, ymax = self.bounds
        xs = np.array([xmin, xmax, xmin, xmax]); ys = np.array([ymin, ymin, ymax, ymax])
        lo, la = tr.transform(xs, ys)
        return float(lo.min()), float(la.min()), float(lo.max()), float(la.max())

    def corners_wgs84(self) -> list[list[float]]:
        """[lon, lat] of UL, UR, LR, LL - used to drape overlays on the globe."""
        tr = Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True)
        xmin, ymin, xmax, ymax = self.bounds
        pts = [(xmin, ymax), (xmax, ymax), (xmax, ymin), (xmin, ymin)]
        return [list(map(float, tr.transform(x, y))) for x, y in pts]

    def cell_centers_wgs84(self) -> tuple[np.ndarray, np.ndarray]:
        tr = Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True)
        idx = (np.arange(self.size) + 0.5) * self.cell
        xx, yy = np.meshgrid(self.x0 + idx, self.y0 - idx)
        lon, lat = tr.transform(xx, yy)
        return np.asarray(lon), np.asarray(lat)

    def to_dict(self) -> dict:
        return {"crs": self.crs, "x0": self.x0, "y0": self.y0, "cell": self.cell, "size": self.size}

    @classmethod
    def centered(cls, lon: float, lat: float, cell: float, size: int, crs: str | None = None) -> "AnalysisGrid":
        crs = crs or registry.analysis_crs()
        x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)
        half = cell * size / 2.0
        ox, oy = LANDFIRE_ORIGIN
        x0 = ox + np.floor((x - half - ox) / 30.0) * 30.0
        y0 = oy + np.ceil((y + half - oy) / 30.0) * 30.0
        return cls(crs, float(x0), float(y0), float(cell), int(size))


def warp_to_grid(src_path: Path, grid: AnalysisGrid, resampling: Resampling, tlog: TransformLog,
                 label: str, dtype: str = "float32", band: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Warp one band to the grid. Returns (array, valid_mask)."""
    with rasterio.open(src_path) as src:
        nodata = src.nodata
        dst = np.zeros(grid.shape, dtype=dtype)
        dst_nodata = -9999 if np.issubdtype(np.dtype(dtype), np.floating) or np.dtype(dtype).kind == "i" else 0
        dst.fill(dst_nodata)
        reproject(
            source=rasterio.band(src, band), destination=dst,
            src_transform=src.transform, src_crs=src.crs, src_nodata=nodata,
            dst_transform=grid.transform, dst_crs=grid.crs, dst_nodata=dst_nodata,
            resampling=resampling,
        )
        tlog.add(label, src.crs.to_string(), grid.crs, resampling.name, abs(src.res[0]), grid.cell)
    valid = dst != dst_nodata
    return dst, valid


def build_srtm_mosaic(force: bool = False) -> Path:
    cfg = registry.sources()["srtm"]
    out = registry.path(cfg["processed_mosaic"])
    if out.exists() and not force:
        return out
    tiles = registry.glob_paths(cfg["glob"])
    srcs = [rasterio.open(p) for p in tiles]
    arr, transform = merge(srcs)
    profile = srcs[0].profile | {"height": arr.shape[1], "width": arr.shape[2], "transform": transform,
                                 "compress": "deflate", "tiled": True, "blockxsize": 512, "blockysize": 512,
                                 "driver": "GTiff", "BIGTIFF": "IF_SAFER"}
    for s in srcs:
        s.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(arr)
        dst.build_overviews([2, 4, 8, 16, 32], Resampling.average)
    log.info("SRTM mosaic %s from %d tiles", out, len(tiles))
    return out


def build_worldcover_mosaic(factor: int = 10, force: bool = False) -> Path:
    """Mode-aggregate the 10 m WorldCover tiles by `factor` (10 -> ~100 m) into one 4326 mosaic."""
    cfg = registry.sources()["worldcover"]
    out = registry.path(cfg["processed_mosaic"])
    if out.exists() and not force:
        return out
    tiles = registry.glob_paths(cfg["glob"])
    parts, transforms = [], []
    for p in tiles:
        with rasterio.open(p) as src:
            h, w = src.height // factor, src.width // factor
            data = src.read(1, out_shape=(h, w), resampling=Resampling.mode)
            parts.append((data, src.transform * Affine.scale(factor), src.crs))
    west = min(t.c for _, t, _ in parts)
    north = max(t.f for _, t, _ in parts)
    res = parts[0][1].a
    east = max(t.c + d.shape[1] * res for d, t, _ in parts)
    south = min(t.f - d.shape[0] * res for d, t, _ in parts)
    W, H = int(round((east - west) / res)), int(round((north - south) / res))
    mosaic = np.zeros((H, W), dtype=np.uint8)
    for d, t, _ in parts:
        c0, r0 = int(round((t.c - west) / res)), int(round((north - t.f) / res))
        mosaic[r0:r0 + d.shape[0], c0:c0 + d.shape[1]] = np.where(d > 0, d, mosaic[r0:r0 + d.shape[0], c0:c0 + d.shape[1]])
    out.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out, "w", driver="GTiff", height=H, width=W, count=1, dtype="uint8", crs=parts[0][2],
                       transform=Affine(res, 0, west, 0, -res, north), nodata=0, compress="deflate", tiled=True) as dst:
        dst.write(mosaic, 1)
    log.info("WorldCover mosaic %s (%dx%d, %.6f deg)", out, W, H, res)
    return out


def worldcover_tiles() -> list[Path]:
    return registry.glob_paths(registry.sources()["worldcover"]["glob"])
