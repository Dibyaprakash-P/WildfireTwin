"""WildfireTwin Reference Simulator (WTRS).

Physics-based reference simulation = Rothermel surface spread + Anderson
elliptical shape + minimum-travel-time growth on the local landscape, driven
by an hourly weather series.

This is an in-repo, open implementation of the same model family used by
FARSITE/FlamMap (surface fire only: no crown fire, spotting, suppression or
fuel-moisture conditioning). Its outputs are labelled
    data_class = "simulated", simulator = "WTRS-Rothermel-MTT"
and are reference simulations — NOT observed ground truth and NOT FARSITE
output. Exported FARSITE/FlamMap results can be imported through
simulation/converters and used in their place.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from geo.landscape import Landscape
from geo.weather import FuelMoisture, dead_fuel_moisture, wind_speed_dir
from simulation.rothermel import SpreadField, spread_field
from simulation.spread import SpreadResult, simulate

SIMULATOR_NAME = "WTRS-Rothermel-MTT"
SIMULATOR_VERSION = "1.0.0"


@dataclass
class WeatherSeries:
    """Hourly weather; index 0 = simulation start. `history_*` = hours before start (most recent last)."""
    temperature_c: np.ndarray
    rh_pct: np.ndarray
    wind_u_ms: np.ndarray
    wind_v_ms: np.ndarray
    precip_mm: np.ndarray
    history_temperature_c: np.ndarray
    history_rh_pct: np.ndarray
    history_precip_mm: np.ndarray
    source: str
    start_iso: str
    meta: dict = field(default_factory=dict)

    @property
    def hours(self) -> int:
        return len(self.temperature_c)

    def moisture_at(self, k: int, live_herb: float, live_woody: float) -> FuelMoisture:
        t = np.concatenate([self.history_temperature_c, self.temperature_c[: k + 1]])
        rh = np.concatenate([self.history_rh_pct, self.rh_pct[: k + 1]])
        p = np.concatenate([self.history_precip_mm, self.precip_mm[: k + 1]])
        return dead_fuel_moisture(t, rh, p, live_herb, live_woody)

    def summary(self, k0: int = 0, k1: int | None = None) -> dict[str, float]:
        k1 = self.hours if k1 is None else max(k1, k0 + 1)
        sl = slice(k0, min(k1, self.hours))
        u, v = float(np.mean(self.wind_u_ms[sl])), float(np.mean(self.wind_v_ms[sl]))
        spd, d = wind_speed_dir(u, v)
        return {"temperature_c": float(np.mean(self.temperature_c[sl])), "rh_pct": float(np.mean(self.rh_pct[sl])),
                "wind_u_ms": u, "wind_v_ms": v, "wind_speed_ms": float(spd), "wind_from_deg": float(d),
                "precip_mm": float(np.sum(self.precip_mm[sl]))}


@dataclass
class ReferenceRun:
    result: SpreadResult
    fields_used: dict[int, SpreadField]
    meta: dict


def run_reference(landscape: Landscape, weather: WeatherSeries, initial_arrival_min: np.ndarray,
                  max_hours: float, live_herb: float = 0.60, live_woody: float = 0.90) -> ReferenceRun:
    cache: dict[int, SpreadField] = {}

    def field_for_hour(k: int) -> SpreadField:
        k = min(k, weather.hours - 1)
        if k not in cache:
            spd, wdir = wind_speed_dir(weather.wind_u_ms[k], weather.wind_v_ms[k])
            moist = weather.moisture_at(k, live_herb, live_woody)
            cache[k] = spread_field(landscape.fuel_code, landscape.slope_deg, landscape.aspect_deg,
                                    float(spd), float(wdir), moist)
        return cache[k]

    res = simulate(initial_arrival_min, field_for_hour, landscape.grid.cell, max_hours * 60.0)
    meta = {
        "data_class": "simulated",
        "simulator": SIMULATOR_NAME, "simulator_version": SIMULATOR_VERSION,
        "weather_source": weather.source, "weather_start": weather.start_iso,
        "live_herb_moisture": live_herb, "live_woody_moisture": live_woody,
        "grid": landscape.grid.to_dict(), "runtime_s": res.runtime_s, "max_hours": max_hours,
        "transforms": landscape.transforms.entries,
        "limitations": ["surface fire only", "no spotting", "no crown fire", "no suppression",
                        "spatially uniform weather within the window"],
    }
    res.meta = meta
    return ReferenceRun(res, cache, meta)


def point_ignition(shape: tuple[int, int], row: int, col: int) -> np.ndarray:
    a = np.full(shape, np.inf, dtype=np.float32)
    a[row, col] = 0.0
    return a


def mask_ignition(mask: np.ndarray) -> np.ndarray:
    a = np.full(mask.shape, np.inf, dtype=np.float32)
    a[mask.astype(bool)] = 0.0
    return a
