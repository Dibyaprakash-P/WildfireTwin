"""Scott & Burgan (2005) 40 standard fire-behavior fuel models (FBFM40).

Source of parameters: Scott, J.H., Burgan, R.E. (2005). Standard fire behavior
fuel models: a comprehensive set for use with Rothermel's surface fire spread
model. USDA Forest Service RMRS-GTR-153, Table 7.

Units in the table are those of the publication:
  loads      tons/acre   (1-h, 10-h, 100-h dead, live herbaceous, live woody)
  SAV        1/ft        (1-h dead, live herbaceous, live woody); 10-h = 109, 100-h = 30
  depth      ft
  mx_dead    percent     (dead fuel moisture of extinction)
  heat       8000 BTU/lb for all dead and live classes
A SAV of None means the class carries no load.

LANDFIRE FBFM40 grid codes: 91 urban, 92 snow/ice, 93 agriculture,
98 water, 99 barren are non-burnable (NB1-NB9).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TONS_PER_ACRE_TO_LB_PER_FT2 = 2000.0 / 43560.0
SAV_10H = 109.0
SAV_100H = 30.0
HEAT_CONTENT_BTU_LB = 8000.0

NON_BURNABLE = {91: "NB1 urban/developed", 92: "NB2 snow/ice", 93: "NB3 agricultural",
                98: "NB8 open water", 99: "NB9 bare ground"}


@dataclass(frozen=True)
class FuelModel:
    code: int
    name: str
    loads: tuple[float, float, float, float, float]
    sav_1h: float
    sav_herb: float | None
    sav_woody: float | None
    depth_ft: float
    mx_dead_pct: float
    dynamic: bool

    @property
    def group(self) -> str:
        return self.name[:2]


def _fm(code, name, l1, l10, l100, lh, lw, s1, sh, sw, depth, mx, dyn=False):
    return FuelModel(code, name, (l1, l10, l100, lh, lw), s1, sh, sw, depth, mx, dyn)


FUEL_MODELS: dict[int, FuelModel] = {m.code: m for m in [
    # Grass (GR) - dynamic
    _fm(101, "GR1", 0.10, 0.00, 0.00, 0.30, 0.00, 2200, 2000, None, 0.4, 15, True),
    _fm(102, "GR2", 0.10, 0.00, 0.00, 1.00, 0.00, 2000, 1800, None, 1.0, 15, True),
    _fm(103, "GR3", 0.10, 0.40, 0.00, 1.50, 0.00, 1500, 1300, None, 2.0, 30, True),
    _fm(104, "GR4", 0.25, 0.00, 0.00, 1.90, 0.00, 2000, 1800, None, 2.0, 15, True),
    _fm(105, "GR5", 0.40, 0.00, 0.00, 2.50, 0.00, 1800, 1600, None, 1.5, 40, True),
    _fm(106, "GR6", 0.10, 0.00, 0.00, 3.40, 0.00, 2200, 2000, None, 1.5, 40, True),
    _fm(107, "GR7", 1.00, 0.00, 0.00, 5.40, 0.00, 2000, 1800, None, 3.0, 15, True),
    _fm(108, "GR8", 0.50, 1.00, 0.00, 7.30, 0.00, 1500, 1300, None, 4.0, 30, True),
    _fm(109, "GR9", 1.00, 1.00, 0.00, 9.00, 0.00, 1800, 1600, None, 5.0, 40, True),
    # Grass-shrub (GS) - dynamic
    _fm(121, "GS1", 0.20, 0.00, 0.00, 0.50, 0.65, 2000, 1800, 1800, 0.9, 15, True),
    _fm(122, "GS2", 0.50, 0.50, 0.00, 0.60, 1.00, 2000, 1800, 1800, 1.5, 15, True),
    _fm(123, "GS3", 0.30, 0.25, 0.00, 1.45, 1.25, 1800, 1600, 1600, 1.8, 40, True),
    _fm(124, "GS4", 1.90, 0.30, 0.10, 3.40, 7.10, 1800, 1600, 1600, 2.1, 40, True),
    # Shrub (SH)
    _fm(141, "SH1", 0.25, 0.25, 0.00, 0.15, 1.30, 2000, 1800, 1600, 1.0, 15, True),
    _fm(142, "SH2", 1.35, 2.40, 0.75, 0.00, 3.85, 2000, None, 1600, 1.0, 15),
    _fm(143, "SH3", 0.45, 3.00, 0.00, 0.00, 6.20, 1600, None, 1400, 2.4, 40),
    _fm(144, "SH4", 0.85, 1.15, 0.20, 0.00, 2.55, 2000, None, 1600, 3.0, 30),
    _fm(145, "SH5", 3.60, 2.10, 0.00, 0.00, 2.90, 750, None, 1600, 6.0, 15),
    _fm(146, "SH6", 2.90, 1.45, 0.00, 0.00, 1.40, 750, None, 1600, 2.0, 30),
    _fm(147, "SH7", 3.50, 5.30, 2.20, 0.00, 3.40, 750, None, 1600, 6.0, 15),
    _fm(148, "SH8", 2.05, 3.40, 0.85, 0.00, 4.35, 750, None, 1600, 3.0, 40),
    _fm(149, "SH9", 4.50, 2.45, 0.00, 1.55, 7.00, 750, 1800, 1500, 4.4, 40, True),
    # Timber-understory (TU)
    _fm(161, "TU1", 0.20, 0.90, 1.50, 0.20, 0.90, 2000, 1800, 1600, 0.6, 20, True),
    _fm(162, "TU2", 0.95, 1.80, 1.25, 0.00, 0.20, 2000, None, 1600, 1.0, 30),
    _fm(163, "TU3", 1.10, 0.15, 0.25, 0.65, 1.10, 1800, 1600, 1400, 1.3, 30, True),
    _fm(164, "TU4", 4.50, 0.00, 0.00, 0.00, 2.00, 2300, None, 2000, 0.5, 12),
    _fm(165, "TU5", 4.00, 4.00, 3.00, 0.00, 3.00, 1500, None, 750, 1.0, 25),
    # Timber litter (TL)
    _fm(181, "TL1", 1.00, 2.20, 3.60, 0.00, 0.00, 2000, None, None, 0.2, 30),
    _fm(182, "TL2", 1.40, 2.30, 2.20, 0.00, 0.00, 2000, None, None, 0.2, 25),
    _fm(183, "TL3", 0.50, 2.20, 2.80, 0.00, 0.00, 2000, None, None, 0.3, 20),
    _fm(184, "TL4", 0.50, 1.50, 4.20, 0.00, 0.00, 2000, None, None, 0.4, 25),
    _fm(185, "TL5", 1.15, 2.50, 4.40, 0.00, 0.00, 2000, None, None, 0.6, 25),
    _fm(186, "TL6", 2.40, 1.20, 1.20, 0.00, 0.00, 2000, None, None, 0.3, 25),
    _fm(187, "TL7", 0.30, 1.40, 8.10, 0.00, 0.00, 2000, None, None, 0.4, 25),
    _fm(188, "TL8", 5.80, 1.40, 1.10, 0.00, 0.00, 1800, None, None, 0.3, 35),
    _fm(189, "TL9", 6.65, 3.30, 4.15, 0.00, 0.00, 1800, None, None, 0.6, 35),
    # Slash-blowdown (SB)
    _fm(201, "SB1", 1.50, 3.00, 11.00, 0.00, 0.00, 2000, None, None, 1.0, 25),
    _fm(202, "SB2", 4.50, 4.25, 4.00, 0.00, 0.00, 2000, None, None, 1.0, 25),
    _fm(203, "SB3", 5.50, 2.75, 3.00, 0.00, 0.00, 2000, None, None, 1.2, 25),
    _fm(204, "SB4", 5.25, 3.50, 5.25, 0.00, 0.00, 2000, None, None, 2.7, 25),
]}

FUEL_GROUPS = ["GR", "GS", "SH", "TU", "TL", "SB"]


def is_burnable(codes: np.ndarray) -> np.ndarray:
    return np.isin(codes, list(FUEL_MODELS.keys()))


def group_index(codes: np.ndarray) -> np.ndarray:
    """Return index into FUEL_GROUPS per cell, -1 for non-burnable / unknown."""
    lut = np.full(256, -1, dtype=np.int8)
    for code, fm in FUEL_MODELS.items():
        lut[code] = FUEL_GROUPS.index(fm.group)
    c = np.clip(codes.astype(np.int32), 0, 255)
    out = lut[c]
    out[(codes < 0) | (codes > 255)] = -1
    return out


def property_lut(prop: str) -> np.ndarray:
    """Lookup table code -> continuous fuel property (0 for non-burnable)."""
    lut = np.zeros(256, dtype=np.float32)
    for code, fm in FUEL_MODELS.items():
        if prop == "fine_dead_load":  # 1-h load, tons/acre
            lut[code] = fm.loads[0]
        elif prop == "total_load":
            lut[code] = sum(fm.loads)
        elif prop == "depth_ft":
            lut[code] = fm.depth_ft
        elif prop == "mx_dead":
            lut[code] = fm.mx_dead_pct
        else:
            raise KeyError(prop)
    return lut


def lookup(codes: np.ndarray, prop: str) -> np.ndarray:
    c = np.clip(codes.astype(np.int32), 0, 255)
    return property_lut(prop)[c]
