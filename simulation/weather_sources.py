"""Build WeatherSeries objects from ERA5 (historical) or Open-Meteo-style hourly arrays."""

from __future__ import annotations

import numpy as np

from geo import registry
from geo.weather import Era5Store, wind_uv
from simulation.reference import WeatherSeries

HISTORY_HOURS = 72
_store: Era5Store | None = None


def era5_store() -> Era5Store:
    global _store
    if _store is None:
        _store = Era5Store(registry.path(registry.sources()["era5"]["processed"]))
    return _store


def era5_series(lon: float, lat: float, start: np.datetime64, hours: int) -> WeatherSeries:
    st = era5_store()
    s = st.point_series(lon, lat, start - np.timedelta64(HISTORY_HOURS, "h"), HISTORY_HOURS + hours)
    H = HISTORY_HOURS
    return WeatherSeries(
        temperature_c=s["temperature_c"][H:], rh_pct=s["relative_humidity_pct"][H:],
        wind_u_ms=s["wind_u_ms"][H:], wind_v_ms=s["wind_v_ms"][H:], precip_mm=s["precip_mm"][H:],
        history_temperature_c=s["temperature_c"][:H], history_rh_pct=s["relative_humidity_pct"][:H],
        history_precip_mm=s["precip_mm"][:H],
        source="ERA5 hourly reanalysis (0.25 deg, bilinear at window centre)",
        start_iso=str(start),
        meta={"soil_moisture_m3m3": s["soil_moisture_m3m3"][H:]},
    )


def hourly_series(times_iso: list[str], temperature_c: list[float], rh_pct: list[float],
                  wind_speed_10m_ms: list[float], wind_from_deg: list[float], precip_mm: list[float],
                  start_index: int, source: str) -> WeatherSeries:
    """From hourly arrays (e.g. Open-Meteo past_days + forecast); `start_index` = the 'now' hour."""
    t = np.asarray(temperature_c, dtype=np.float32)
    rh = np.asarray(rh_pct, dtype=np.float32)
    u, v = wind_uv(np.asarray(wind_speed_10m_ms), np.asarray(wind_from_deg))
    p = np.nan_to_num(np.asarray(precip_mm, dtype=np.float32))
    k = start_index
    return WeatherSeries(t[k:], rh[k:], u[k:].astype(np.float32), v[k:].astype(np.float32), p[k:],
                         t[max(0, k - HISTORY_HOURS):k] if k > 0 else t[:1],
                         rh[max(0, k - HISTORY_HOURS):k] if k > 0 else rh[:1],
                         p[max(0, k - HISTORY_HOURS):k] if k > 0 else p[:1] * 0,
                         source=source, start_iso=times_iso[k])


def constant_series(hours: int, temperature_c: float, rh_pct: float, wind_speed_10m_ms: float,
                    wind_from_deg: float, source: str = "user-specified constant conditions") -> WeatherSeries:
    u, v = wind_uv(wind_speed_10m_ms, wind_from_deg)
    full = lambda x: np.full(hours, x, dtype=np.float32)  # noqa: E731
    return WeatherSeries(full(temperature_c), full(rh_pct), full(u), full(v), full(0.0),
                         full(temperature_c)[:24], full(rh_pct)[:24], np.zeros(24, np.float32),
                         source=source, start_iso="n/a")
