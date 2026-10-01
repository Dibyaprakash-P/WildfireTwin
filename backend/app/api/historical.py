"""/api/historical — historical wildfires (observed) and replay validation."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.app.auth.deps import current_user
from backend.app.services import historical
from backend.app.utils.errors import APIError
from backend.app.utils.events import emit

router = APIRouter(prefix="/historical", tags=["historical"])


class ReplayRequest(BaseModel):
    t0: str = Field(min_length=10, max_length=40)
    model_type: str | None = Field(None, pattern="^(unet|fno|physics_fno)$")


@router.get("")
async def list_historical(min_year: int = Query(2020, ge=1984, le=2100)):
    fires = await asyncio.to_thread(historical.list_fires, min_year)
    return {"fires": fires, "source": "MTBS / BAER / RAVG burned-area perimeters (local), deduplicated per incident"}


@router.get("/{hist_id}")
async def get_historical(hist_id: str):
    d = await asyncio.to_thread(historical.fire_detail, hist_id)
    if not d:
        raise APIError(404, "not_found", "Historical fire not found.")
    return d


@router.post("/{hist_id}/replay")
async def replay(hist_id: str, req: ReplayRequest, user: dict = Depends(current_user)):
    await emit("historical", f"Replay {hist_id} from {req.t0}")
    try:
        res = await asyncio.to_thread(historical.replay, hist_id, req.t0, req.model_type)
    except KeyError:
        raise APIError(404, "not_found", "Historical fire not found.")
    except ValueError as exc:
        raise APIError(400, "replay_unavailable", str(exc))
    except RuntimeError as exc:
        raise APIError(409, "model_not_trained", str(exc))
    await emit("historical", f"Replay {res['replay_id']} completed for {hist_id}")
    return res
