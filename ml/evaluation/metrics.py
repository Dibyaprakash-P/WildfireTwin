"""Segmentation / spread metrics. All computed on binary masks (threshold 0.5 by default).

* iou, dice, precision, recall          on the full burned mask at t0 + h
* growth_iou, growth_f1                 on the NEWLY burned region (target minus
                                        initial fire) — the initial fire is given
                                        as input, so full-mask scores are inflated
                                        by it; growth scores are the stricter test.
* hausdorff_m, hd95_m                   symmetric Hausdorff distance (and its 95th
                                        percentile) between mask boundaries, metres
* mae                                   mean |p - y| of the probability field
* area_error_pct                        (pred area - true area) / true area * 100
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage


def _safe_div(a: float, b: float) -> float:
    return float(a / b) if b > 0 else float("nan")


def boundary(mask: np.ndarray) -> np.ndarray:
    return mask & ~ndimage.binary_erosion(mask, border_value=0)


def hausdorff(pred: np.ndarray, true: np.ndarray, cell_m: float) -> tuple[float, float]:
    bp, bt = boundary(pred), boundary(true)
    if not bp.any() or not bt.any():
        return float("nan"), float("nan")
    dt_t = ndimage.distance_transform_edt(~bt) * cell_m
    dt_p = ndimage.distance_transform_edt(~bp) * cell_m
    d = np.concatenate([dt_t[bp], dt_p[bt]])
    return float(d.max()), float(np.percentile(d, 95))


def mask_metrics(prob: np.ndarray, true: np.ndarray, initial: np.ndarray, cell_m: float,
                 threshold: float = 0.5) -> dict[str, float]:
    pred = prob >= threshold
    t = true.astype(bool)
    m0 = initial.astype(bool)
    tp = float((pred & t).sum()); fp = float((pred & ~t).sum()); fn = float((~pred & t).sum())
    out = {
        "iou": _safe_div(tp, tp + fp + fn),
        "dice": _safe_div(2 * tp, 2 * tp + fp + fn),
        "precision": _safe_div(tp, tp + fp),
        "recall": _safe_div(tp, tp + fn),
    }
    gp, gt = pred & ~m0, t & ~m0
    gtp = float((gp & gt).sum()); gfp = float((gp & ~gt).sum()); gfn = float((~gp & gt).sum())
    out["growth_iou"] = _safe_div(gtp, gtp + gfp + gfn) if (gt.any() or gp.any()) else 1.0
    out["growth_f1"] = _safe_div(2 * gtp, 2 * gtp + gfp + gfn) if (gt.any() or gp.any()) else 1.0
    out["hausdorff_m"], out["hd95_m"] = hausdorff(pred, t, cell_m)
    out["mae"] = float(np.mean(np.abs(prob - t.astype(np.float32))))
    out["area_true_km2"] = float(t.sum() * cell_m ** 2 / 1e6)
    out["area_pred_km2"] = float(pred.sum() * cell_m ** 2 / 1e6)
    out["area_error_pct"] = _safe_div((pred.sum() - t.sum()) * 100.0, float(t.sum()))
    return out


def aggregate(rows: list[dict[str, float]]) -> dict[str, float]:
    keys = rows[0].keys() if rows else []
    return {k: float(np.nanmean([r[k] for r in rows])) for k in keys if isinstance(rows[0][k], (int, float))}
