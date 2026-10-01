"""/api/health, /api/models, /api/alerts, /api/logs, /api/data, /api/events (SSE)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from backend.app.alerts.store import alert_out
from backend.app.auth.deps import current_user
from backend.app.config import get_settings
from backend.app.db import db_available, get_db
from backend.app.ml.registry import model_registry
from backend.app.services.firms import firms_service
from backend.app.utils.errors import APIError
from backend.app.utils.events import bus
from geo import registry

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    s = get_settings()
    mongo = False
    if db_available():
        try:
            await get_db().command("ping")
            mongo = True
        except Exception:
            mongo = False
    snap = firms_service.snapshot
    import torch
    return {
        "status": "ok" if mongo else "degraded", "time": datetime.now(timezone.utc).isoformat(), "env": s.app_env,
        "mongodb": mongo,
        "firms": {"source": snap.source if snap else None, "events": int(len(snap.events)) if snap else 0,
                  "latest_acquisition": snap.latest_acq.isoformat() if snap and snap.latest_acq else None},
        "models": {m["model_type"]: m["trained"] for m in model_registry.status()},
        "cuda": torch.cuda.is_available(),
        "integrations": {"firms_api": bool(s.firms_map_key), "google_oauth": bool(s.google_client_id),
                         "email_provider": s.email_provider, "monitor": s.monitor_enabled,
                         "monitor_interval_s": s.monitor_interval_seconds},
        "study_region": registry.sources()["study_region"],
    }


@router.get("/models")
async def models():
    return {"models": model_registry.status()}


@router.get("/models/compare")
async def compare():
    p = registry.path("data/models/evaluation/results.json")
    if not p.exists():
        return {"status": "not_evaluated", "message": "Not evaluated", "models": {
            m["model_type"]: {"name": m["name"], "status": "not_evaluated"} for m in model_registry.status()}}
    res = json.loads(p.read_text())
    evaluated = any(m.get("status") == "evaluated" for m in res.get("models", {}).values())
    return {"status": "evaluated" if evaluated else "not_evaluated"} | res


@router.get("/alerts")
async def alerts(fire_id: str | None = None, severity: str | None = None, limit: int = Query(50, ge=1, le=500)):
    q: dict = {}
    if fire_id:
        q["fire_id"] = fire_id
    if severity:
        q["severity"] = severity.upper()
    cur = get_db().alerts.find(q, sort=[("created_at", -1)], limit=limit)
    return {"alerts": [alert_out(d) async for d in cur]}


@router.get("/alerts/{alert_id}")
async def alert(alert_id: str):
    d = await get_db().alerts.find_one({"alert_id": alert_id})
    if not d:
        raise APIError(404, "alert_not_found", "Alert not found.")
    return alert_out(d)


@router.post("/alerts/{alert_id}/ack")
async def ack(alert_id: str, user: dict = Depends(current_user)):
    r = await get_db().alerts.update_one({"alert_id": alert_id}, {"$set": {"acknowledged": True, "acknowledged_by": str(user["_id"])}})
    if not r.matched_count:
        raise APIError(404, "alert_not_found", "Alert not found.")
    return {"ok": True}


@router.post("/monitor/run")
async def run_monitor(user: dict = Depends(current_user)):
    """Run one dynamic-update cycle now (FIRMS refresh, change detection, re-forecast, alerts)."""
    from backend.app.services.monitor import monitor_cycle
    from backend.app.utils.events import emit
    await emit("monitor", "Manual refresh requested")
    await monitor_cycle()
    return {"ok": True}


@router.get("/logs")
async def logs(limit: int = Query(200, ge=1, le=1000), component: str | None = None, level: str | None = None):
    q: dict = {}
    if component:
        q["component"] = component
    if level:
        q["level"] = level.upper()
    cur = get_db().system_logs.find(q, {"_id": 0, "ts_expire": 0}, sort=[("ts", -1)], limit=limit)
    out = []
    async for d in cur:
        d["ts"] = d["ts"].isoformat()
        out.append(d)
    return {"logs": out}


@router.get("/data/catalog")
async def catalog():
    """Catalogue with live status (files checked per request) and audited roles."""
    if not registry.path("data/metadata/catalog.json").exists():
        raise APIError(404, "catalog_missing", "Data catalog not generated. Run: python -m scripts.inventory_data")
    from backend.app.services.catalog import live_catalog
    return await live_catalog()


@router.get("/events/stream")
async def stream(request: Request):
    """Server-sent events: log, alert, prediction, simulation, fires."""
    q = bus.subscribe()

    async def gen():
        try:
            yield "retry: 5000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=20)
                    yield f"event: {ev['kind']}\ndata: {json.dumps(ev['payload'], default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
