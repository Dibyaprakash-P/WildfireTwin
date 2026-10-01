"""Environmental conditions for a selected fire. Every value carries source, timestamp and units."""

from __future__ import annotations

import math
from collections import Counter

import numpy as np

from geo.fuels import FUEL_MODELS, NON_BURNABLE
from geo.landcover import WORLDCOVER_CLASSES
from geo.landscape import LandscapeUnavailable, build_landscape
from geo.rasters import AnalysisGrid

SRTM = "NASA SRTM 1 arc-second v3 (local)"
LANDFIRE = "LANDFIRE 2025 FBFM40 (local, 30 m)"
WORLDCOVER = "ESA WorldCover 2021 v200 (local, 10 m)"


def _v(value, units, source, timestamp=None):
    return {"value": value, "units": units, "source": source, "timestamp": timestamp}


def fuel_name(code: int) -> str:
    if code in FUEL_MODELS:
        return f"{FUEL_MODELS[code].name} ({code})"
    if code in NON_BURNABLE:
        return f"{NON_BURNABLE[code]} ({code})"
    return f"unknown ({code})"


def local_environment(lon: float, lat: float) -> dict:
    """Terrain, fuel and land cover from local rasters in a 1.9 km window (30 m) around the point."""
    grid = AnalysisGrid.centered(lon, lat, 30.0, 65)
    try:
        land = build_landscape(grid)
    except LandscapeUnavailable as exc:
        return {"available": False, "reason": str(exc)}
    c = 32
    asp = float(land.aspect_deg[c, c])
    burnable = np.isin(land.fuel_code, list(FUEL_MODELS))
    counts = Counter(map(int, land.fuel_code.ravel()))
    total = land.fuel_code.size
    fuels = [{"code": k, "name": fuel_name(k), "fraction": v / total} for k, v in counts.most_common(6)]
    lc = None
    if land.landcover is not None:
        lcc = Counter(map(int, land.landcover.ravel()))
        lc = [{"code": k, "name": WORLDCOVER_CLASSES.get(k, str(k)), "fraction": v / total} for k, v in lcc.most_common(5)]
    # circular mean aspect over non-flat cells
    a = land.aspect_deg[land.aspect_deg >= 0]
    mean_aspect = float((math.degrees(math.atan2(np.sin(np.radians(a)).mean(), np.cos(np.radians(a)).mean())) + 360) % 360) if a.size else None
    return {
        "available": True, "window_m": grid.cell * grid.size,
        "terrain": {
            "elevation": _v(float(land.elevation_m[c, c]), "m", SRTM),
            "elevation_range": _v([float(land.elevation_m.min()), float(land.elevation_m.max())], "m", SRTM),
            "slope": _v(float(land.slope_deg[c, c]), "deg", SRTM + " -> Horn (1981) slope"),
            "slope_mean": _v(float(land.slope_deg.mean()), "deg", SRTM + " -> Horn (1981) slope"),
            "aspect": _v(None if asp < 0 else asp, "deg from N (downslope)", SRTM + " -> Horn (1981) aspect"),
            "aspect_mean": _v(mean_aspect, "deg from N (circular mean)", SRTM),
        },
        "fuel": {
            "fuel_model": _v(fuel_name(int(land.fuel_code[c, c])), "FBFM40 code", LANDFIRE, "LF2025"),
            "burnable_fraction": _v(float(burnable.mean()), "fraction of window", LANDFIRE, "LF2025"),
            "composition": _v(fuels, "fraction of window", LANDFIRE, "LF2025"),
        },
        "land_cover": {
            "class": _v(WORLDCOVER_CLASSES.get(int(land.landcover[c, c]), "n/a") if land.landcover is not None else None,
                        "class", WORLDCOVER, "2021"),
            "composition": _v(lc, "fraction of window", WORLDCOVER, "2021"),
        },
        "transforms": land.transforms.entries,
    }
