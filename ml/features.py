"""Model input feature specification - shared by training and inference.

Every model (U-Net, FNO, PI-FNO) receives the same C x H x W tensor.
Weather fields are spatially uniform within the window (ERA5 / Open-Meteo
point values) and are broadcast to constant channels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from geo import fuels, landcover
from geo.weather import emc_simard

HORIZONS_MIN = [10, 30, 60, 360, 720, 1440, 2880, 4320]
HORIZON_LABELS = {10: "10m", 30: "30m", 60: "1h", 360: "6h", 720: "12h", 1440: "24h", 2880: "48h", 4320: "72h"}
BAND_OF_HORIZON = {10: "short", 30: "short", 60: "short", 360: "medium", 720: "medium",
                   1440: "long", 2880: "long", 4320: "long"}
BAND_CELL_M = {"short": 30.0, "medium": 60.0, "long": 120.0}

CHANNELS = (
    ["fire_t0", "elev_rel", "slope", "aspect_sin", "aspect_cos", "burnable"]
    + [f"fuel_{g}" for g in fuels.FUEL_GROUPS]
    + ["fine_dead_load", "fuel_depth"]
    + [f"lc_{g}" for g in landcover.LC_GROUPS]
    + ["temp_now", "rh_now", "u_now", "v_now", "temp_mean", "rh_mean", "u_mean", "v_mean",
       "precip_sum", "soil_moisture", "dead_fm_1h", "horizon", "cell_size"]
)
N_CHANNELS = len(CHANNELS)


@dataclass
class WeatherState:
    """Spatially uniform weather inputs for one sample (SI units)."""
    temp_now_c: float
    rh_now_pct: float
    u_now_ms: float
    v_now_ms: float
    temp_mean_c: float
    rh_mean_pct: float
    u_mean_ms: float
    v_mean_ms: float
    precip_sum_mm: float
    soil_moisture_m3m3: float | None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def build_input(fire_t0: np.ndarray, elevation_m: np.ndarray, slope_deg: np.ndarray, aspect_deg: np.ndarray,
                fuel_code: np.ndarray, landcover_code: np.ndarray | None, w: WeatherState,
                horizon_min: float, cell_m: float) -> np.ndarray:
    h, wd = fire_t0.shape
    x = np.zeros((N_CHANNELS, h, wd), dtype=np.float32)
    flat = aspect_deg < 0
    a = np.radians(np.where(flat, 0, aspect_deg))
    x[0] = fire_t0
    x[1] = (elevation_m - float(np.mean(elevation_m))) / 500.0
    x[2] = slope_deg / 45.0
    x[3] = np.where(flat, 0, np.sin(a))
    x[4] = np.where(flat, 0, np.cos(a))
    x[5] = fuels.is_burnable(fuel_code)
    gi = fuels.group_index(fuel_code)
    for k in range(len(fuels.FUEL_GROUPS)):
        x[6 + k] = gi == k
    o = 6 + len(fuels.FUEL_GROUPS)
    x[o] = fuels.lookup(fuel_code, "fine_dead_load") / 5.0
    x[o + 1] = fuels.lookup(fuel_code, "depth_ft") / 3.0
    o += 2
    if landcover_code is not None:
        li = landcover.group_index(landcover_code)
        for k in range(len(landcover.LC_GROUPS)):
            x[o + k] = li == k
    o += len(landcover.LC_GROUPS)
    consts = [
        w.temp_now_c / 40.0, w.rh_now_pct / 100.0, w.u_now_ms / 10.0, w.v_now_ms / 10.0,
        w.temp_mean_c / 40.0, w.rh_mean_pct / 100.0, w.u_mean_ms / 10.0, w.v_mean_ms / 10.0,
        math.log1p(max(w.precip_sum_mm, 0.0)) / math.log1p(50.0),
        (w.soil_moisture_m3m3 if w.soil_moisture_m3m3 is not None else 0.25) / 0.5,
        float(emc_simard(w.temp_now_c, w.rh_now_pct)) / 20.0,
        math.log1p(horizon_min) / math.log1p(4320.0),
        cell_m / 120.0,
    ]
    for k, v in enumerate(consts):
        x[o + k] = v
    return x
