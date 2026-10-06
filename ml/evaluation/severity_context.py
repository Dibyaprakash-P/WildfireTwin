"""MTBS post-fire burn severity as independent observed CONTEXT for a historical replay window.

What MTBS is (from the product metadata): a categorical, analyst-thresholded post-fire severity map of each fire's
final extent. It has no timing, so it cannot score the spread at a forecast horizon — the FIRMS-based metrics in
`metrics.mask_metrics` remain the spread validation. This module reports only quantities whose semantics hold:

  * final mapped severity in the window, by producer class (km²);
  * the severity composition of the predicted area (p ≥ threshold), by class (km²);
  * share of the predicted area lying OUTSIDE the fire's final mapped extent (a fire cannot be beyond its final
    extent at any time, so this is a valid consistency check of over-prediction, not an accuracy score);
  * share of the final low/moderate/high-severity area already inside the forecast extent at this horizon
    (descriptive — MTBS is the end state, so values < 1 are expected at short horizons).

No mapping between burn probability and severity class is made; no confusion matrix is computed.
"""

from __future__ import annotations

import re

import numpy as np

BURNED_RE = re.compile(r"^(low|moderate|high) burn severity$", re.IGNORECASE)
NONPROC_RE = re.compile(r"non-processing", re.IGNORECASE)


def class_roles(classes: dict[int, str], nodata: int) -> dict[str, list[int]]:
    """Group producer classes by their definitions (read from the MTBS XML; nothing hard-coded by value)."""
    burned = [v for v, d in classes.items() if BURNED_RE.match(d.strip())]
    nonproc = [v for v, d in classes.items() if NONPROC_RE.search(d)]
    mapped = [v for v in classes if v != nodata and v not in nonproc]
    return {"burned_low_to_high": sorted(burned), "non_processing": sorted(nonproc), "mapped": sorted(mapped)}


def severity_context(severity: np.ndarray, classes: dict[int, str], nodata: int, pred_mask: np.ndarray,
                     cell_m: float, fire_mask: np.ndarray | None = None) -> dict:
    """Context statistics for one window. `fire_mask` restricts MTBS pixels to this fire's final perimeter."""
    sev = severity.copy()
    if fire_mask is not None:
        sev[~fire_mask.astype(bool)] = nodata          # pixels of other fires in the same yearly mosaic are ignored
    roles = class_roles(classes, nodata)
    km2 = cell_m * cell_m / 1e6
    pred = pred_mask.astype(bool)
    known = ~np.isin(sev, roles["non_processing"])
    mapped = np.isin(sev, roles["mapped"])
    burned = np.isin(sev, roles["burned_low_to_high"])

    def by_class(mask: np.ndarray) -> dict[str, float]:
        vals, cnt = np.unique(sev[mask], return_counts=True)
        return {classes.get(int(v), str(int(v))) if v != nodata else "Outside final mapped extent": round(float(c) * km2, 4)
                for v, c in zip(vals, cnt)}

    pred_known = int((pred & known).sum())
    out = {
        "mapped_fire_in_window": bool(mapped.any()),
        "final_mapped_area_km2": round(float(mapped.sum()) * km2, 4),
        "final_severity_area_km2": {k: v for k, v in by_class(mapped).items()},
        "predicted_area_by_final_severity_km2": by_class(pred) if pred.any() else {},
        "predicted_outside_final_extent_frac": (round(float((pred & known & ~mapped).sum()) / pred_known, 4)
                                                if pred_known else None),
        "final_low_to_high_area_in_forecast_frac": (round(float((pred & burned).sum()) / float(burned.sum()), 4)
                                                    if burned.any() else None),
        "class_roles": {k: [classes.get(v, str(v)) for v in vs] for k, vs in roles.items()},
    }
    return out
