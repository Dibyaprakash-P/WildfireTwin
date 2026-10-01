"""/api/predictions — WildfireTwin neural forecasts (data_class = predicted)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.app.auth.deps import current_user
from backend.app.db import get_db
from backend.app.ml.registry import model_registry
from backend.app.services.predictions import create_prediction, prediction_out
from backend.app.utils.errors import APIError
from ml.features import HORIZONS_MIN

router = APIRouter(prefix="/predictions", tags=["predictions"])


class PredictionRequest(BaseModel):
    fire_id: str = Field(min_length=3, max_length=40)
    horizons_min: list[int] | None = None
    model_type: str | None = Field(None, pattern="^(unet|fno|physics_fno)$")


@router.post("")
async def create(req: PredictionRequest, user: dict = Depends(current_user)):
    if req.horizons_min:
        bad = [h for h in req.horizons_min if h not in HORIZONS_MIN]
        if bad:
            raise APIError(400, "invalid_horizon", f"Unsupported horizons {bad}; allowed {HORIZONS_MIN}")
    if req.model_type and not any(m["model_type"] == req.model_type and m["trained"] for m in model_registry.status()):
        raise APIError(409, "model_not_trained", f"Model '{req.model_type}' is not trained.")
    return await create_prediction(req.fire_id, str(user["_id"]), req.horizons_min, req.model_type)


@router.get("")
async def list_predictions(fire_id: str | None = None, limit: int = Query(20, ge=1, le=100)):
    q = {"fire_id": fire_id} if fire_id else {}
    cur = get_db().predictions.find(q, sort=[("created_at", -1)], limit=limit)
    return {"predictions": [prediction_out(d) async for d in cur]}


@router.get("/{prediction_id}")
async def get_prediction(prediction_id: str):
    d = await get_db().predictions.find_one({"prediction_id": prediction_id})
    if not d:
        raise APIError(404, "prediction_not_found", "Prediction unavailable.")
    return prediction_out(d)


@router.get("/{prediction_id}/timeline")
async def timeline(prediction_id: str):
    d = await get_db().predictions.find_one({"prediction_id": prediction_id})
    if not d:
        raise APIError(404, "prediction_not_found", "Prediction unavailable.")
    by = {s["horizon_min"]: s for s in d["steps"]}
    steps = []
    for h in HORIZONS_MIN:
        s = by.get(h)
        if s is None:
            steps.append({"horizon_min": h, "status": "not_requested", "message": "Forecast unavailable"})
        elif s["status"] != "ok":
            steps.append({"horizon_min": h, "label": s["label"], "status": s["status"],
                          "message": "Forecast unavailable", "reason": s.get("reason")})
        else:
            steps.append(s)
    return {"prediction_id": prediction_id, "fire_id": d["fire_id"], "model": d["model"], "created_at": d["created_at"].isoformat(),
            "uncertainty": d.get("uncertainty"), "steps": steps}
