import math

import numpy as np

from geo.fuels import FUEL_MODELS
from geo.weather import FuelMoisture
from simulation.reference import point_ignition
from simulation.rothermel import fuel_terms, spread_field
from simulation.spread import simulate

DRY = FuelMoisture(0.06, 0.07, 0.08, 0.6, 0.9)
WET = FuelMoisture(0.20, 0.21, 0.22, 1.2, 1.5)
CH_PER_H = 60 / 20.1168   # m/min -> chains/h


def _ros(code, wind=0.0, slope=0.0, moist=DRY, aspect=-1.0, wind_from=270.0):
    f = spread_field(np.array([[code]]), np.array([[slope]], np.float32), np.array([[aspect]], np.float32),
                     wind, wind_from, moist)
    return float(f.r_head_mmin[0, 0]), f


def test_scott_burgan_spread_classes_at_5mph():
    """Head-fire ROS at 5 mi/h mid-flame wind falls in the S&B (2005) descriptive classes."""
    classes = {"GR2": (20, 50), "SH5": (50, 150), "TL3": (0, 2), "SH2": (2, 5), "TU5": (5, 20)}
    for code, fm in FUEL_MODELS.items():
        if fm.name in classes:
            waf = fuel_terms(fm, DRY).waf
            u10 = 5 * 0.44704 / waf * 1.15
            r, _ = _ros(code, wind=u10)
            lo, hi = classes[fm.name]
            assert lo <= r * CH_PER_H <= hi, (fm.name, r * CH_PER_H)


def test_monotonic_responses():
    base, _ = _ros(102)
    assert _ros(102, wind=5)[0] > base
    assert _ros(102, slope=30, aspect=180)[0] > base
    assert _ros(102, moist=WET)[0] < base


def test_direction_downwind_and_upslope():
    _, f = _ros(102, wind=6, wind_from=0.0)          # wind from north -> spreads south
    assert abs(math.degrees(float(f.theta_max[0, 0])) - 180) < 1e-3
    _, f = _ros(102, slope=25, aspect=90.0)          # faces east -> upslope is west
    assert abs(math.degrees(float(f.theta_max[0, 0])) - 270) < 1e-3


def test_nonburnable_blocks_spread():
    fuel = np.full((21, 21), 102, np.int16)
    fuel[:, 14] = 98                                  # water column
    zeros = np.zeros_like(fuel, dtype=np.float32)
    sf = spread_field(fuel, zeros, zeros - 1, 4.0, 270.0, DRY)
    res = simulate(point_ignition(fuel.shape, 10, 5), lambda k: sf, 30.0, 600.0)
    burned = np.isfinite(res.arrival_min)
    assert burned[:, :14].any()
    assert not burned[:, 14].any()


def test_spread_elongated_downwind():
    fuel = np.full((41, 41), 102, np.int16)
    zeros = np.zeros_like(fuel, dtype=np.float32)
    sf = spread_field(fuel, zeros, zeros - 1, 5.0, 270.0, DRY)   # from west -> east
    res = simulate(point_ignition(fuel.shape, 20, 20), lambda k: sf, 30.0, 25.0)
    b = np.isfinite(res.arrival_min)
    cols = np.where(b.any(0))[0]
    assert cols.max() - 20 > 20 - cols.min()                         # head runs further than back
