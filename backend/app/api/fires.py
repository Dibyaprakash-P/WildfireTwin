"""/api/fires — observed FIRMS fire events (global) and their detections."""

from __future__ import annotations

import math

import numpy as np
from fastapi import APIRouter, Query

from backend.app.services.firms import detection_to_dict, event_to_dict, firms_service
from backend.app.utils.errors import APIError

router = APIRouter(prefix="/fires", tags=["fires"])


def _snap():
    snap = firms_service.snapshot
    if snap is None or snap.events.empty:
        raise APIError(503, "no_firms_data", "No FIRMS data available.")
    return snap


def _meta(snap) -> dict:
    return {"source": snap.source, "latest_acquisition": snap.latest_acq.isoformat() if snap.latest_acq else None,
            "window_start": snap.window_start.isoformat() if snap.window_start else None,
            "loaded_at": snap.loaded_at.isoformat(), "data_class": "observed",
            "note": "Events are clusters of FIRMS active-fire detections (observed footprint), not official perimeters."}


@router.get("/active")
async def active_fires(min_detections: int = Query(1, ge=1), status: str | None = Query(None, pattern="^(active|recent)$"),
                       in_domain: bool | None = None):
    """Compact columnar payload for the globe (one point per fire event)."""
    snap = _snap()
    ev = snap.events
    sel = ev["count"] >= min_detections
    if status:
        sel &= ev["status"] == status
    if in_domain is not None:
        sel &= ev["in_model_domain"] == in_domain
    e = ev[sel]
    frp = e["frp_sum"].to_numpy(dtype=float)
    return {
        "meta": _meta(snap) | {"count": int(len(e)), "total_events": int(len(ev)), "total_detections": int(len(snap.detections))},
        "columns": ["event_id", "lat", "lon", "detections", "frp_sum_mw", "last_seen_epoch", "status", "in_domain"],
        "rows": [
            [i, round(float(la), 5), round(float(lo), 5), int(c), None if math.isnan(f) else round(float(f), 1),
             int(t.timestamp()), s, bool(d)]
            for i, la, lo, c, f, t, s, d in zip(e["event_id"], e["lat"], e["lon"], e["count"], frp, e["last_seen"],
                                               e["status"], e["in_model_domain"])
        ],
    }


@router.get("/nearby")
async def nearby(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
                 radius_km: float = Query(50, gt=0, le=1000), limit: int = Query(20, ge=1, le=200)):
    snap = _snap()
    ev = snap.events
    la1, lo1 = np.radians(lat), np.radians(lon)
    la2, lo2 = np.radians(ev["lat"].to_numpy()), np.radians(ev["lon"].to_numpy())
    d = 2 * 6371.0088 * np.arcsin(np.sqrt(np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2))
    idx = np.argsort(d)
    idx = idx[d[idx] <= radius_km][:limit]
    return {"meta": _meta(snap), "events": [event_to_dict(ev.iloc[i], snap) | {"distance_km": float(d[i])} for i in idx]}


@router.get("")
async def list_fires(sort: str = Query("frp", pattern="^(frp|detections|last_seen)$"), limit: int = Query(50, ge=1, le=500),
                     offset: int = Query(0, ge=0), in_domain: bool | None = None):
    snap = _snap()
    ev = snap.events
    if in_domain is not None:
        ev = ev[ev["in_model_domain"] == in_domain]
    col = {"frp": "frp_sum", "detections": "count", "last_seen": "last_seen"}[sort]
    ev = ev.sort_values(col, ascending=False, na_position="last")
    page = ev.iloc[offset:offset + limit]
    return {"meta": _meta(snap) | {"total": int(len(ev))}, "events": [event_to_dict(r, snap) for _, r in page.iterrows()]}


@router.get("/{fire_id}")
async def get_fire(fire_id: str, max_detections: int = Query(2000, ge=1, le=20000)):
    snap = _snap()
    row = firms_service.event_row(fire_id)
    if row is None:
        raise APIError(404, "fire_not_found", "Fire event not found in the current FIRMS snapshot.")
    det = firms_service.event_detections(fire_id)
    return {"meta": _meta(snap), "event": event_to_dict(row, snap),
            "detections": [detection_to_dict(r) for _, r in det.tail(max_detections).iterrows()],
            "detections_truncated": bool(len(det) > max_detections)}
