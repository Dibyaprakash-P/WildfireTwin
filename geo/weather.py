"""Weather handling: ERA5 (historical, local GRIB) and shared unit conversions.

Unit conversions (all documented in docs/data_pipeline.md):
  * temperature           K -> degC                     T_c = T_k - 273.15
  * relative humidity     from T and dewpoint Td (degC) with the Magnus form
                          (Alduchov & Eskridge 1996):  e_s(T) = 6.1094 exp(17.625 T / (T + 243.04))
                          RH = 100 * e_s(Td) / e_s(T), clipped to [0, 100]
  * precipitation         ERA5 `tp` hourly accumulation, metres -> mm   (x 1000)
  * wind                  u, v (m/s, direction the air moves TOWARD east/north)
                          speed = hypot(u, v); meteorological direction (FROM, deg)
                          = (270 - atan2(v, u)) mod 360
  * 10 m -> 20 ft wind    U20ft = U10m / 1.15 (standard US fire-behavior conversion)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import xarray as xr

log = logging.getLogger(__name__)

ERA5_VARS = ["10u", "10v", "2t", "2d", "tp", "swvl1", "lai_hv", "lai_lv", "cvh", "cvl"]


# ---------------------------------------------------------------- conversions
def kelvin_to_c(t_k):
    return np.asarray(t_k) - 273.15


def rh_from_dewpoint(t_c, td_c):
    def es(t):
        return 6.1094 * np.exp(17.625 * t / (t + 243.04))
    return np.clip(100.0 * es(np.asarray(td_c)) / es(np.asarray(t_c)), 0.0, 100.0)


def wind_speed_dir(u, v):
    u, v = np.asarray(u, dtype=float), np.asarray(v, dtype=float)
    speed = np.hypot(u, v)
    direction_from = (270.0 - np.degrees(np.arctan2(v, u))) % 360.0
    return speed, direction_from


def wind_uv(speed, direction_from_deg):
    rad = np.radians(np.asarray(direction_from_deg, dtype=float))
    s = np.asarray(speed, dtype=float)
    return -s * np.sin(rad), -s * np.cos(rad)


def emc_simard(t_c, rh):
    """Equilibrium moisture content (%) of fine dead fuel, Simard (1968) as used in NFDRS."""
    t_f = np.asarray(t_c) * 9.0 / 5.0 + 32.0
    h = np.asarray(rh, dtype=float)
    low = 0.03229 + 0.281073 * h - 0.000578 * h * t_f
    mid = 2.22749 + 0.160107 * h - 0.01478 * t_f
    high = 21.0606 + 0.005565 * h ** 2 - 0.00035 * h * t_f - 0.483199 * h
    return np.clip(np.where(h < 10, low, np.where(h < 50, mid, high)), 1.0, 60.0)


def ffwi(t_c, rh, wind_ms):
    """Fosberg (1978) Fire Weather Index from temperature, RH and wind (wind in mph internally)."""
    m = emc_simard(t_c, rh)
    r = np.asarray(m) / 30.0
    eta = 1.0 - 2.0 * r + 1.5 * r ** 2 - 0.5 * r ** 3
    u_mph = np.asarray(wind_ms) * 2.23694
    return np.clip(eta * np.sqrt(1.0 + u_mph ** 2) / 0.3002, 0.0, 100.0)


@dataclass
class FuelMoisture:
    """Dead/live fuel moisture as fractions (Rothermel model input)."""
    m1: float
    m10: float
    m100: float
    m_herb: float
    m_woody: float

    def as_dict(self) -> dict[str, float]:
        return {"m1": self.m1, "m10": self.m10, "m100": self.m100, "m_herb": self.m_herb, "m_woody": self.m_woody}


def dead_fuel_moisture(t_c_hist: np.ndarray, rh_hist: np.ndarray, precip_mm_hist: np.ndarray,
                       live_herb: float = 0.60, live_woody: float = 0.90,
                       rain_wetting_mm: float = 1.0, rain_floor: float = 0.25) -> FuelMoisture:
    """Time-lag approximation of dead fuel moisture from an hourly history (most recent LAST).

    * 1-h  = EMC at the current hour
    * 10-h = mean EMC over the previous 24 h
    * 100-h= mean EMC over the previous 72 h
    * Heuristic wetting: if >= `rain_wetting_mm` fell in the previous 24 h, dead
      moistures are floored at `rain_floor` (fraction). This is a documented,
      configurable simplification - not a calibrated fuel-moisture model.
    Live moistures are scenario parameters (defaults 60 % herb / 90 % woody,
    i.e. a cured-to-partially-cured fire-season state), not observations.
    """
    emc = emc_simard(t_c_hist, rh_hist) / 100.0
    m1 = float(emc[-1])
    m10 = float(np.mean(emc[-24:]))
    m100 = float(np.mean(emc[-72:]))
    if float(np.sum(precip_mm_hist[-24:])) >= rain_wetting_mm:
        m1, m10, m100 = max(m1, rain_floor), max(m10, rain_floor), max(m100, rain_floor)
    return FuelMoisture(m1, m10, m100, live_herb, live_woody)


# ---------------------------------------------------------------- ERA5
def extract_era5_region(grib_path: Path, bbox: tuple[float, float, float, float]) -> xr.Dataset:
    """Read an ERA5 single-levels GRIB (hourly) and subset to bbox, message by message.

    Uses eccodes directly because cfgrib indexing of the 340 MB multi-variable
    file is very slow on Windows.
    """
    import eccodes

    w, s, e, n = bbox
    data: dict[str, dict[np.datetime64, np.ndarray]] = {v: {} for v in ERA5_VARS}
    lats = lons = None
    sel_lat = sel_lon = None
    with open(grib_path, "rb") as fh:
        while True:
            g = eccodes.codes_grib_new_from_file(fh)
            if g is None:
                break
            try:
                short = eccodes.codes_get(g, "shortName")
                if short not in data:
                    continue
                if lats is None:
                    ni, nj = eccodes.codes_get(g, "Ni"), eccodes.codes_get(g, "Nj")
                    la0 = eccodes.codes_get(g, "latitudeOfFirstGridPointInDegrees")
                    lo0 = eccodes.codes_get(g, "longitudeOfFirstGridPointInDegrees")
                    dla = eccodes.codes_get(g, "jDirectionIncrementInDegrees")
                    dlo = eccodes.codes_get(g, "iDirectionIncrementInDegrees")
                    all_lats = la0 - dla * np.arange(nj)
                    all_lons = lo0 + dlo * np.arange(ni)
                    sel_lat = np.where((all_lats >= s - 0.25) & (all_lats <= n + 0.25))[0]
                    sel_lon = np.where((all_lons >= w - 0.25) & (all_lons <= e + 0.25))[0]
                    lats, lons = all_lats[sel_lat], all_lons[sel_lon]
                    shape = (nj, ni)
                vd = eccodes.codes_get(g, "validityDate")
                vt = eccodes.codes_get(g, "validityTime")
                ts = np.datetime64(f"{str(vd)[:4]}-{str(vd)[4:6]}-{str(vd)[6:]}T{vt // 100:02d}:00")
                vals = eccodes.codes_get_values(g).reshape(shape)
                vals = np.where(vals == eccodes.codes_get(g, "missingValue"), np.nan, vals)
                data[short][ts] = vals[np.ix_(sel_lat, sel_lon)].astype(np.float32)
            finally:
                eccodes.codes_release(g)
    times = sorted(data["2t"].keys())
    ds = xr.Dataset(coords={"time": np.array(times), "latitude": lats, "longitude": lons})
    for v, by_t in data.items():
        if not by_t:
            continue
        arr = np.stack([by_t.get(t, np.full((len(lats), len(lons)), np.nan, np.float32)) for t in times])
        ds[v] = (("time", "latitude", "longitude"), arr)
    return ds


def derive_era5_fields(ds: xr.Dataset) -> xr.Dataset:
    out = xr.Dataset(coords=ds.coords)
    out["temperature_c"] = ds["2t"] - 273.15
    out["dewpoint_c"] = ds["2d"] - 273.15
    out["relative_humidity_pct"] = xr.apply_ufunc(rh_from_dewpoint, out["temperature_c"], out["dewpoint_c"])
    out["wind_u_ms"] = ds["10u"]
    out["wind_v_ms"] = ds["10v"]
    out["precip_mm"] = (ds["tp"] * 1000.0).clip(min=0)
    out["soil_moisture_m3m3"] = ds["swvl1"]
    for v in ["lai_hv", "lai_lv", "cvh", "cvl"]:
        if v in ds:
            out[v] = ds[v]
    units = {"temperature_c": "degC", "dewpoint_c": "degC", "relative_humidity_pct": "%",
             "wind_u_ms": "m s-1", "wind_v_ms": "m s-1", "precip_mm": "mm (hourly accumulation)",
             "soil_moisture_m3m3": "m3 m-3", "lai_hv": "m2 m-2", "lai_lv": "m2 m-2", "cvh": "0-1", "cvl": "0-1"}
    for k, u in units.items():
        if k in out:
            out[k].attrs["units"] = u
    out.attrs["source"] = "ECMWF ERA5 hourly single levels (Copernicus CDS), local GRIB"
    return out


class Era5Store:
    """Lazy access to the processed regional ERA5 NetCDF."""

    def __init__(self, nc_path: Path):
        self.nc_path = nc_path
        self._ds: xr.Dataset | None = None

    @property
    def available(self) -> bool:
        return self.nc_path.exists()

    @property
    def ds(self) -> xr.Dataset:
        if self._ds is None:
            self._ds = xr.open_dataset(self.nc_path).load()
        return self._ds

    def time_range(self) -> tuple[np.datetime64, np.datetime64]:
        t = self.ds["time"].values
        return t.min(), t.max()

    def point_series(self, lon: float, lat: float, start: np.datetime64, hours: int) -> dict[str, np.ndarray]:
        """Bilinear interpolation at a point for `hours` consecutive hours starting at `start`."""
        times = start + np.arange(hours).astype("timedelta64[h]")
        sub = self.ds.interp(latitude=lat, longitude=lon, method="linear").sel(time=times, method="nearest")
        return {k: sub[k].values.astype(np.float32) for k in sub.data_vars} | {"time": sub["time"].values}
