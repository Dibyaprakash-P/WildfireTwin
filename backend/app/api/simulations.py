"""/api/simulations — REFERENCE simulations (WTRS) and FARSITE/FlamMap imports (data_class = simulated)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field

from backend.app.auth.deps import current_user
from backend.app.db import get_db
from backend.app.services.simulations import import_simulation, sim_out, start_simulation
from backend.app.utils.errors import APIError

router = APIRouter(prefix="/simulations", tags=["simulations"])
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


class ConstantWeather(BaseModel):
    temperature_c: float = Field(ge=-30, le=55)
    rh_pct: float = Field(ge=1, le=100)
    wind_speed_ms: float = Field(ge=0, le=40)
    wind_from_deg: float = Field(ge=0, lt=360)


class SimulationRequest(BaseModel):
    fire_id: str | None = None
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    ignition: Literal["fire_footprint", "point"] = "fire_footprint"
    duration_hours: int = Field(24, ge=1, le=72)
    cell_m: float = 60.0
    weather_source: Literal["open_meteo", "era5", "constant"] = "open_meteo"
    era5_start: str | None = None
    constant: ConstantWeather | None = None
    live_herb: float = Field(0.6, ge=0.3, le=2.5)
    live_woody: float = Field(0.9, ge=0.6, le=2.5)


@router.post("")
async def create(req: SimulationRequest, user: dict = Depends(current_user)):
    return await start_simulation(req.model_dump(), str(user["_id"]))


@router.post("/import")
async def import_result(file: UploadFile = File(...), kind: Literal["arrival_raster", "perimeters"] = Form(...),
                        simulator: Literal["FARSITE", "FlamMap", "other"] = Form(...),
                        units: Literal["minutes", "hours"] = Form("minutes"), time_field: str | None = Form(None),
                        user: dict = Depends(current_user)):
    name = Path(file.filename or "upload").name
    if not name.lower().endswith((".tif", ".tiff", ".asc", ".zip", ".geojson", ".json", ".gpkg")):
        raise APIError(400, "invalid_import", "Accepted: .tif .tiff .asc .zip .geojson .gpkg")
    tmp = Path(tempfile.mkdtemp(prefix="wt_import_")) / name
    size = 0
    with open(tmp, "wb") as fh:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise APIError(413, "too_large", "Upload exceeds 200 MB.")
            fh.write(chunk)
    try:
        return await import_simulation(tmp, name, kind, simulator, units, time_field, str(user["_id"]))
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)


@router.get("")
async def list_sims(limit: int = Query(20, ge=1, le=100)):
    cur = get_db().simulations.find({}, sort=[("created_at", -1)], limit=limit)
    return {"simulations": [sim_out(d) async for d in cur]}


@router.get("/{simulation_id}")
async def get_sim(simulation_id: str):
    d = await get_db().simulations.find_one({"simulation_id": simulation_id})
    if not d:
        raise APIError(404, "simulation_not_found", "Simulation not found.")
    return sim_out(d)
