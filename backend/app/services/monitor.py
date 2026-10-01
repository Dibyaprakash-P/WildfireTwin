"""Dynamic forecast updating (polling).

Every `monitor_interval_seconds`:
  1. refresh FIRMS observations (API if configured, else local files)
  2. for each WATCHED fire (a prediction was made in the last 24 h):
       a. compare fire activity with the stored state  -> FIRE_ACTIVITY_CHANGE
       b. refresh Open-Meteo, compare with the last snapshot -> WEATHER_CHANGE
       c. if (a) or (b) is material, or the forecast run changed, re-run the
          model; the prediction service compares old vs new forecast and emits
          PREDICTION_CHANGE / SPREAD_RISK_CHANGE alerts.
  3. publish updates to live clients (SSE).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from pymongo import UpdateOne

from backend.app.alerts import engine
from backend.app.alerts.engine import AlertCandidate
from backend.app.alerts.store import create_alert
from backend.app.config import get_settings
from backend.app.db import db_available, get_db
from backend.app.services.firms import event_to_dict, firms_service
from backend.app.services.predictions import create_prediction
from backend.app.services.weather import weather_service
from backend.app.utils.events import bus, emit

log = logging.getLogger(__name__)


async def persist_events() -> int:
    snap = firms_service.snapshot
    if not db_available() or snap is None or snap.events.empty:
        return 0
    now = datetime.now(timezone.utc)
    ops = []
    for _, r in snap.events.iterrows():
        d = event_to_dict(r, snap)
        d["centroid"] = {"type": "Point", "coordinates": [d["longitude"], d["latitude"]]}
        d["updated_at"] = now
        ops.append(UpdateOne({"event_id": d["event_id"]}, {"$set": d}, upsert=True))
    db = get_db()
    for i in range(0, len(ops), 5000):
        await db.fire_events.bulk_write(ops[i:i + 5000], ordered=False)
    await db.fire_events.update_many({"updated_at": {"$lt": now}}, {"$set": {"status": "inactive"}})
    return len(ops)


async def watched_fires() -> list[str]:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    return await get_db().predictions.distinct("fire_id", {"created_at": {"$gte": since}})


async def check_fire(event_id: str) -> None:
    db = get_db()
    row = firms_service.event_row(event_id)
    if row is None:
        await emit("monitor", f"{event_id} no longer in FIRMS active window", "INFO")
        return
    reasons: list[str] = []
    state = await db.fire_events.find_one({"event_id": event_id}, {"monitor_state": 1})
    new_state = {"detection_count": int(row["count"]), "frp_sum_mw": float(row["frp_sum"]) if row["frp_sum"] == row["frp_sum"] else None,
                 "last_seen": row["last_seen"].isoformat()}
    prev_state = (state or {}).get("monitor_state")
    if prev_state:
        cand = engine.fire_activity_change(prev_state, new_state)
        if cand:
            await create_alert(cand, event_id)
            reasons.append("fire activity change")
        elif prev_state.get("last_seen") != new_state["last_seen"]:
            reasons.append("new FIRMS detections")
    await db.fire_events.update_one({"event_id": event_id}, {"$set": {"monitor_state": new_state}})

    last_wx = await db.weather_conditions.find_one({"fire_id": event_id}, sort=[("fetched_at", -1)])
    try:
        wx = await weather_service.fetch(float(row["lat"]), float(row["lon"]), force=True)
    except Exception:
        await emit("monitor", f"weather refresh failed for {event_id}", "WARNING")
        return
    await weather_service.record(event_id, wx)
    if last_wx:
        cand = engine.weather_change(last_wx["current"]["values"], wx["current"]["values"])
        if cand:
            await create_alert(cand, event_id)
            reasons.append("significant weather change")
        elif last_wx.get("fingerprint") != wx["fingerprint"]:
            reasons.append("forecast updated")
    if reasons:
        cause = "; ".join(reasons)
        await emit("monitor", f"Re-running forecast for {event_id}: {cause}")
        try:
            await create_prediction(event_id, None, trigger="monitor", cause=cause)
        except Exception as exc:
            await emit("monitor", f"auto-prediction failed for {event_id}: {getattr(exc, 'message', exc)}", "WARNING")
    else:
        await emit("monitor", f"{event_id}: no material change")


async def monitor_cycle() -> None:
    snap_before = firms_service.snapshot.latest_acq if firms_service.snapshot else None
    snap = await firms_service.refresh()
    n = await persist_events()
    if snap and snap_before and snap.latest_acq and snap.latest_acq != snap_before:
        await create_alert(AlertCandidate("DATA_UPDATE", "INFO", "DATA UPDATE",
                                          [f"New FIRMS acquisitions up to {snap.latest_acq:%Y-%m-%d %H:%M} UTC"]), None)
    bus.publish("fires", {"latest_acq": snap.latest_acq.isoformat() if snap and snap.latest_acq else None, "events": n})
    for fid in await watched_fires():
        await check_fire(fid)


async def monitor_loop() -> None:
    s = get_settings()
    while True:
        await asyncio.sleep(s.monitor_interval_seconds)
        try:
            await emit("monitor", "Scheduled refresh: FIRMS + weather")
            await monitor_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("monitor cycle failed")
            await emit("monitor", f"monitor cycle failed: {type(exc).__name__}", "ERROR")
