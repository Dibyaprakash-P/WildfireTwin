"""Write analysis-grid rasters as GeoTIFF (native CRS) and as EPSG:4326 PNG overlays for the globe."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject

from geo.rasters import AnalysisGrid

# Fire-spread probability ramp (overlay style v2): low = dark translucent red, medium = orange,
# high = warm orange-yellow, p -> 1 = small bright hot cores. Cells with p < 0.05 are fully transparent.
OVERLAY_STYLE_VERSION = 4
_STOPS = np.array([0.05, 0.3, 0.6, 0.9, 0.98, 1.0])
_COLORS = np.array([[110, 18, 12], [185, 40, 18], [235, 90, 25], [250, 125, 32], [255, 160, 55], [255, 200, 110]], dtype=np.float32)
_ALPHA = np.array([50, 95, 140, 170, 185, 195], dtype=np.float32)


def write_geotiff(path: Path, arr: np.ndarray, grid: AnalysisGrid, nodata: float | None = None, tags: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", height=grid.size, width=grid.size, count=1, dtype=arr.dtype.name,
                       crs=grid.crs, transform=grid.transform, nodata=nodata, compress="deflate") as dst:
        dst.write(arr, 1)
        if tags:
            dst.update_tags(**{k: str(v) for k, v in tags.items()})


def to_wgs84(arr: np.ndarray, grid: AnalysisGrid, resampling: Resampling = Resampling.bilinear,
             out_size: int | None = None) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    w, s, e, n = grid.bounds_wgs84()
    size = out_size or grid.size
    dst = np.zeros((size, size), dtype=np.float32)
    reproject(arr.astype(np.float32), dst, src_transform=grid.transform, src_crs=grid.crs,
              dst_transform=from_bounds(w, s, e, n, size, size), dst_crs="EPSG:4326", resampling=resampling,
              src_nodata=None, dst_nodata=0)
    return dst, (w, s, e, n)


def probability_png(path: Path, prob: np.ndarray, grid: AnalysisGrid, max_alpha: int = 210) -> tuple[float, float, float, float]:
    p, bounds = to_wgs84(prob, grid, out_size=grid.size * 2)
    rgba = np.zeros(p.shape + (4,), dtype=np.uint8)
    show = p >= _STOPS[0]
    for ch in range(3):
        rgba[..., ch] = np.interp(p, _STOPS, _COLORS[:, ch]).astype(np.uint8)
    alpha = np.interp(p, _STOPS, _ALPHA) * (max_alpha / 210.0)
    rgba[..., 3] = np.where(show, alpha, 0).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(path)
    return bounds


def front_png(path: Path, prob: np.ndarray, grid: AnalysisGrid, threshold: float = 0.5) -> tuple[float, float, float, float]:
    """Outer boundary of the predicted burned region (p >= threshold) - the forecast fire front of this frame.

    Interior holes are filled first so only the outer front is drawn. Pure geometry of the model output:
    no smoothing beyond the reprojection, nothing extrapolated.
    """
    from scipy import ndimage
    m, bounds = to_wgs84((prob >= threshold).astype(np.float32), grid, Resampling.nearest, out_size=grid.size * 2)
    mb = ndimage.binary_fill_holes(m > 0.5)
    edge = mb & ~ndimage.binary_erosion(mb, iterations=1)
    glow = ndimage.binary_dilation(edge, iterations=1) & ~edge
    rgba = np.zeros(m.shape + (4,), dtype=np.uint8)
    rgba[glow] = (255, 150, 50, 90)
    rgba[edge] = (255, 225, 150, 235)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(path)
    return bounds


def mask_png(path: Path, mask: np.ndarray, grid: AnalysisGrid, rgb: tuple[int, int, int], alpha: int = 200,
             outline_only: bool = True) -> tuple[float, float, float, float]:
    m, bounds = to_wgs84(mask.astype(np.float32), grid, Resampling.nearest, out_size=grid.size * 2)
    mb = m > 0.5
    if outline_only:
        from scipy import ndimage
        mb = mb & ~ndimage.binary_erosion(mb, iterations=1)
    rgba = np.zeros(m.shape + (4,), dtype=np.uint8)
    rgba[mb] = (*rgb, alpha)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(path)
    return bounds


def arrival_png(path: Path, arrival_min: np.ndarray, grid: AnalysisGrid, max_min: float) -> tuple[float, float, float, float]:
    """Arrival-time map: early = pale yellow, late = dark red; unburned transparent."""
    a = np.where(np.isfinite(arrival_min), arrival_min, -1.0).astype(np.float32)
    frac = np.where(a >= 0, np.clip(a / max(max_min, 1e-6), 0, 1), -1.0)
    f, bounds = to_wgs84(frac + 1.0, grid, Resampling.nearest, out_size=grid.size * 2)  # +1 keeps 0 = nodata
    burned = f > 0.5
    t = np.clip(f - 1.0, 0, 1)
    stops = np.array([0.0, 0.5, 1.0])
    cols = np.array([[255, 236, 160], [255, 140, 40], [150, 20, 20]], dtype=np.float32)
    rgba = np.zeros(f.shape + (4,), dtype=np.uint8)
    for ch in range(3):
        rgba[..., ch] = np.interp(t, stops, cols[:, ch]).astype(np.uint8)
    rgba[..., 3] = np.where(burned, 190, 0).astype(np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(path)
    return bounds
