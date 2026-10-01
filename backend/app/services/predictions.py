"""Prediction orchestration: cache lookup, inference, persistence, comparison, alerts."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import rasterio

from backend.app.alerts import engine
from backend.app.alerts.store import create_alert
from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.ml.registry import model_registry
from backend.app.services.firms import firms_service
from backend.app.services.inference import FireContext, ModelNotTrained, input_hash, run_prediction
from backend.app.services.weather import weather_service
from backend.app.utils.errors import APIError
from backend.app.utils.events import bus, emit

log = logging.getLogger(__name__)
_running: dict[str, asyncio.Lock] = {}


def prediction_out(doc: dict) -> dict:
    d = {k: v for k, v in doc.items() if k != "_id"}
    if isinstance(d.get("created_at"), datetime):
        d["created_at"] = d["created_at"].isoformat()
    return d


def fire_context(event_id: str) -> FireContext:
    row = firms_service.event_row(event_id)
    if row is None:
        raise APIError(404, "fire_not_found", "Fire event not found in the current FIRMS snapshot.")
    det = firms_service.event_detections(event_id)
    latest = pd.Timestamp(det["acq_datetime"].max()).isoformat() if len(det) else None
    return FireContext(event_id, float(row["lat"]), float(row["lon"]), det, latest)


def _mean_abs_diff(prev: dict, new: dict, root) -> dict[str, float]:
    out = {}
    prev_steps = {s["label"]: s for s in prev.get("steps", []) if s.get("status") == "ok"}
    for s in new.get("steps", []):
        p = prev_steps.get(s["label"])
        if s.get("status") != "ok" or not p or p.get("grid") != s.get("grid"):
            continue
        try:
            with rasterio.open(root / p["geotiff_path"]) as a, rasterio.open(root / s["geotiff_path"]) as b:
                out[s["label"]] = float(np.mean(np.abs(a.read(1) - b.read(1))))
        except Exception:
            continue
    return out


async def create_prediction(event_id: str, user_id: str | None, horizons: list[int] | None = None,
                            model_type: str | None = None, trigger: str = "user", cause: str | None = None,
                            force_weather: bool = False) -> dict:
    db = get_db()
    ctx = fire_context(event_id)
    lock = _running.setdefault(event_id, asyncio.Lock())
    async with lock:
        await emit("prediction", f"Preparing inputs for {event_id} ({len(ctx.detections)} detections)")
        weather_err = None
        try:
            wx = await weather_service.fetch(ctx.lat, ctx.lon, force=force_weather)
            await weather_service.record(event_id, wx)
        except Exception as exc:
            weather_err = str(exc)
        if weather_err:
            raise APIError(503, "weather_unavailable", "Weather service unavailable. Prediction requires forecast weather.")
        mtype = model_type or model_registry.default_type()
        lm = model_registry.get(mtype) if mtype else None
        if lm is None:
            raise APIError(409, "model_not_trained", "Model not trained. Run the training pipeline first.")
        h = input_hash(ctx, wx, lm, horizons or [])
        cached = await db.predictions.find_one({"input_hash": h})
        if cached:
            await emit("prediction", f"Inputs unchanged for {event_id}; returning cached prediction {cached['prediction_id']}")
            return prediction_out(cached) | {"cached": True}
        await emit("prediction", f"Running WildfireTwin prediction ({lm.version}) for {event_id}...")
        try:
            doc = await asyncio.to_thread(run_prediction, ctx, wx, horizons, mtype)
        except ModelNotTrained as exc:
            raise APIError(409, "model_not_trained", str(exc))
        ok = [s for s in doc["steps"] if s["status"] == "ok"]
        if not ok:
            reasons = sorted({s.get("reason", "") for s in doc["steps"]})
            await emit("prediction", f"Prediction unavailable for {event_id}: {reasons[0] if reasons else ''}", "WARNING")
        doc.update({"input_hash": h, "user_id": user_id, "trigger": trigger, "cause": cause,
                    "created_at": datetime.now(timezone.utc)})
        prev = await db.predictions.find_one({"fire_id": event_id, "model.type": doc["model"]["type"]},
                                             sort=[("created_at", -1)])
        doc["previous_prediction_id"] = prev["prediction_id"] if prev else None
        await db.predictions.insert_one(dict(doc))
        await emit("prediction", f"Prediction completed: {doc['prediction_id']} ({len(ok)}/{len(doc['steps'])} horizons, "
                                 f"{doc['total_runtime_ms']:.0f} ms)")
        alerts = []
        if prev and ok:
            root = get_settings().predictions_dir.parent.parent
            diffs = await asyncio.to_thread(_mean_abs_diff, prev, doc, root)
            for cand in (engine.prediction_change(prev["steps"], doc["steps"], diffs, cause),
                         engine.spread_risk_change(prev["steps"], doc["steps"])):
                if cand:
                    alerts.append(await create_alert(cand, event_id, doc["prediction_id"], prev["prediction_id"], trigger))
        out = prediction_out(doc) | {"cached": False, "alerts": alerts}
        bus.publish("prediction", {"prediction_id": doc["prediction_id"], "fire_id": event_id, "trigger": trigger})
        return out
