"""/api/terrain — SRTM heightmap tiles for Cesium's CustomHeightmapTerrainProvider.

Geographic tiling scheme (EPSG:4326): level L has 2^(L+1) x 2^L tiles; x from
-180 eastward, y from +90 southward. Each tile returns TILE x TILE float32
little-endian heights (metres) sampled on an inclusive grid (edges shared with
neighbours). Outside the local SRTM mosaic the response is all zeros (= ellipsoid)
with header X-Terrain-Coverage: none — terrain height is never invented.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

import numpy as np
import rasterio
from fastapi import APIRouter, Path, Response
from rasterio.windows import from_bounds
from scipy.ndimage import map_coordinates

from geo.rasters import build_srtm_mosaic

router = APIRouter(prefix="/terrain", tags=["terrain"])
TILE = 65


@lru_cache(maxsize=1)
def _mosaic_info():
    p = build_srtm_mosaic()
    with rasterio.open(p) as src:
        return str(p), tuple(src.bounds), src.res[0], src.nodata


def _sample(w: float, s: float, e: float, n: float, cols: int, rows: int) -> tuple[np.ndarray, np.ndarray] | None:
    """Bilinear SRTM heights on an inclusive lon/lat lattice; None when the box misses the mosaic."""
    path, (bw, bs, be, bn), _res, nodata = _mosaic_info()
    if e <= bw or w >= be or s >= bn or n <= bs:
        return None
    lons = np.linspace(w, e, cols)
    lats = np.linspace(n, s, rows)
    iw, i_s, ie, i_n = max(w, bw), max(s, bs), min(e, be), min(n, bn)
    step = (e - w) / (cols - 1)
    with rasterio.open(path) as src:
        win = from_bounds(iw, i_s, ie, i_n, src.transform).round_offsets().round_lengths()
        out_w = max(2, min(int(win.width), int(np.ceil((ie - iw) / step)) * 2 + 2))
        out_h = max(2, min(int(win.height), int(np.ceil((i_n - i_s) / step)) * 2 + 2))
        arr = src.read(1, window=win, out_shape=(out_h, out_w), resampling=rasterio.enums.Resampling.bilinear).astype(np.float32)
        wt = src.window_transform(win)
    if nodata is not None:
        arr[arr == nodata] = 0
    sx, sy = win.width / out_w, win.height / out_h
    lon_g, lat_g = np.meshgrid(lons, lats)
    col = (lon_g - wt.c) / (wt.a * sx) - 0.5
    row = (lat_g - wt.f) / (wt.e * sy) - 0.5
    inside = (lon_g >= bw) & (lon_g <= be) & (lat_g >= bs) & (lat_g <= bn)
    h = map_coordinates(arr, [row, col], order=1, mode="nearest")
    return np.where(inside, h, 0.0), inside


def _tile_bounds(level: int, x: int, y: int) -> tuple[float, float, float, float]:
    size = 180.0 / (2 ** level)
    w, n = -180.0 + x * size, 90.0 - y * size
    return w, n - size, w + size, n


@lru_cache(maxsize=2048)
def _tile(level: int, x: int, y: int) -> tuple[bytes, str]:
    w, s, e, n = _tile_bounds(level, x, y)
    res = _sample(w, s, e, n, TILE, TILE)
    if res is None:
        return np.zeros((TILE, TILE), "<f4").tobytes(), "none"
    h, inside = res
    return h.astype("<f4").tobytes(), "partial" if not inside.all() else "full"


HILLSHADE_PX = 256
SUN_AZIMUTH_DEG, SUN_ALTITUDE_DEG = 315.0, 45.0   # standard cartographic hillshade illumination (NW, 45 deg)


@lru_cache(maxsize=1024)
def _hillshade(level: int, x: int, y: int) -> bytes | None:
    """Relief shading from SRTM (Horn gradients, NW illumination) as a transparent PNG overlay.

    Shadowed slopes are darkened and lit slopes slightly brightened; flat terrain is transparent, so the
    satellite imagery stays readable. Values are derived from the DEM only - nothing is invented.
    """
    w, s, e, n = _tile_bounds(level, x, y)
    px = HILLSHADE_PX
    d = (e - w) / px                                   # pixel size (deg); sample pixel centres + 1-pixel border
    res = _sample(w - d / 2, s - d / 2, e + d / 2, n + d / 2, px + 2, px + 2)
    if res is None:
        return None
    z, inside = res
    lat_mid = np.radians((s + n) / 2)
    dx = d * 111320.0 * max(np.cos(lat_mid), 0.05)
    dy = d * 110574.0
    zp = z
    a, b, c = zp[:-2, :-2], zp[:-2, 1:-1], zp[:-2, 2:]
    dd, f = zp[1:-1, :-2], zp[1:-1, 2:]
    g, hh, i = zp[2:, :-2], zp[2:, 1:-1], zp[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * dd + g)) / (8 * dx)
    dzdy = ((a + 2 * b + c) - (g + 2 * hh + i)) / (8 * dy)
    slope = np.arctan(np.hypot(dzdx, dzdy))
    aspect = np.arctan2(-dzdx, -dzdy)                  # downslope azimuth (rad, from north)
    zen = np.radians(90.0 - SUN_ALTITUDE_DEG)
    az = np.radians(SUN_AZIMUTH_DEG)
    shade = np.cos(zen) * np.cos(slope) + np.sin(zen) * np.sin(slope) * np.cos(az - aspect)
    flat = np.cos(zen)
    rel = shade - flat                                  # <0 shadow, >0 lit, 0 flat
    rgba = np.zeros((px, px, 4), np.uint8)
    dark = rel < 0
    rgba[..., 3] = np.where(dark, np.clip(-rel * 1.6, 0, 1) * 200, np.clip(rel * 1.2, 0, 1) * 70).astype(np.uint8)
    rgba[~dark, :3] = 255
    rgba[~inside[1:-1, 1:-1], 3] = 0
    from io import BytesIO

    from PIL import Image
    buf = BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@router.get("/info")
async def info():
    _, b, res, _ = await asyncio.to_thread(_mosaic_info)
    return {"source": "NASA SRTM 1 arc-second v3 (local tiles)", "bounds_wgs84": list(b), "resolution_deg": res,
            "tile_size": TILE, "tiling_scheme": "geographic", "outside_coverage": "ellipsoid (height 0)",
            "hillshade": {"url": "/api/terrain/hillshade/{z}/{x}/{y}.png", "sun_azimuth_deg": SUN_AZIMUTH_DEG,
                          "sun_altitude_deg": SUN_ALTITUDE_DEG, "tile_px": HILLSHADE_PX}}


@router.get("/hillshade/{level}/{x}/{y}.png")
async def hillshade(level: int = Path(ge=0, le=16), x: int = Path(ge=0), y: int = Path(ge=0)):
    if x >= 2 ** (level + 1) or y >= 2 ** level:
        return Response(status_code=404)
    data = await asyncio.to_thread(_hillshade, level, x, y)
    if data is None:   # outside SRTM coverage: transparent (204 lets Cesium skip the tile)
        return Response(status_code=204, headers={"Cache-Control": "public, max-age=86400"})
    return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{level}/{x}/{y}.bin")
async def tile(level: int = Path(ge=0, le=16), x: int = Path(ge=0), y: int = Path(ge=0)):
    if x >= 2 ** (level + 1) or y >= 2 ** level:
        return Response(status_code=404)
    data, cov = await asyncio.to_thread(_tile, level, x, y)
    return Response(data, media_type="application/octet-stream",
                    headers={"X-Terrain-Coverage": cov, "Cache-Control": "public, max-age=86400"})
