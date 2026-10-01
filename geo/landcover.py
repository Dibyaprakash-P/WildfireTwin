"""ESA WorldCover 2021 v200 class handling.

Land cover is used as an *additional descriptive* model input. It is NOT a
substitute for the LANDFIRE fire-behavior fuel model, which remains the fuel
input to the reference simulator.
"""

from __future__ import annotations

import numpy as np

WORLDCOVER_CLASSES = {
    10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland",
    50: "Built-up", 60: "Bare / sparse vegetation", 70: "Snow and ice",
    80: "Permanent water bodies", 90: "Herbaceous wetland", 95: "Mangroves",
    100: "Moss and lichen",
}

# Grouping used for model channels (documented in docs/data_pipeline.md).
LC_GROUPS = ["tree", "shrub", "grass", "crop", "built", "bare", "water_wet"]
_GROUP_OF = {10: 0, 95: 0, 20: 1, 30: 2, 100: 2, 40: 3, 50: 4, 60: 5, 70: 5, 80: 6, 90: 6}


def group_index(codes: np.ndarray) -> np.ndarray:
    lut = np.full(256, -1, dtype=np.int8)
    for k, v in _GROUP_OF.items():
        lut[k] = v
    return lut[np.clip(codes.astype(np.int32), 0, 255)]
