"""Persist alerts and push them to live clients."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.app.alerts.engine import AlertCandidate
from backend.app.db import get_db
from backend.app.utils.events import bus, emit


def alert_out(doc: dict) -> dict:
    d = {k: v for k, v in doc.items() if k != "_id"}
    d["created_at"] = doc["created_at"].isoformat()
    return d


async def create_alert(c: AlertCandidate, fire_id: str | None, prediction_id: str | None = None,
                       previous_prediction_id: str | None = None, trigger: str = "monitor") -> dict:
    doc = {"alert_id": f"AL-{uuid.uuid4().hex[:10].upper()}", "type": c.type, "severity": c.severity, "title": c.title,
           "lines": c.lines, "details": c.details, "fire_id": fire_id, "prediction_id": prediction_id,
           "previous_prediction_id": previous_prediction_id, "trigger": trigger, "acknowledged": False,
           "created_at": datetime.now(timezone.utc),
           "disclaimer": "Decision-support output from a research prototype; not an official warning."}
    await get_db().alerts.insert_one(dict(doc))
    out = alert_out(doc)
    bus.publish("alert", out)
    await emit("alerts", f"{c.severity} {c.type} for {fire_id}: " + "; ".join(c.lines[:2]), "WARNING" if c.severity != "INFO" else "INFO")
    return out
