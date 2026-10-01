"""System event log: real application events -> stdout + MongoDB `system_logs` + live subscribers (SSE)."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app import db

log = logging.getLogger("wildfiretwin.events")

_SECRET_PATTERNS = [
    (re.compile(r"(MAP_KEY|map_key|api[_-]?key|token|secret|password)=([^&\s]+)", re.I), r"\1=***"),
    (re.compile(r"/api/area/csv/[A-Za-z0-9]+/"), "/api/area/csv/***/"),
]
LOG_RETENTION_DAYS = 30


def sanitize(text: str) -> str:
    for pat, rep in _SECRET_PATTERNS:
        text = pat.sub(rep, text)
    return text


class EventBus:
    """In-process fan-out of events (logs, alerts, prediction updates) to SSE clients."""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, kind: str, payload: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait({"kind": kind, "payload": payload})
            except asyncio.QueueFull:
                pass


bus = EventBus()


async def emit(component: str, message: str, level: str = "INFO", **context: Any) -> dict:
    now = datetime.now(timezone.utc)
    msg = sanitize(message)
    doc = {"ts": now, "level": level.upper(), "component": component, "message": msg,
           "context": {k: (sanitize(v) if isinstance(v, str) else v) for k, v in context.items()},
           "ts_expire": now + timedelta(days=LOG_RETENTION_DAYS)}
    getattr(log, level.lower(), log.info)("[%s] %s", component, msg)
    if db.db_available():
        try:
            await db.get_db().system_logs.insert_one(dict(doc))
        except Exception as exc:  # logging must never break a request
            log.warning("system_logs insert failed: %s", exc)
    out = {"ts": now.isoformat(), "level": doc["level"], "component": component, "message": msg, "context": doc["context"]}
    bus.publish("log", out)
    return out
