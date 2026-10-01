"""WildfireTwin FastAPI application.

Run (from repository root):
    .venv/Scripts/python -m uvicorn backend.app.main:app --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app import db
from backend.app.api import auth, fires, historical, predictions, simulations, system, terrain, weather
from backend.app.config import get_settings
from backend.app.services.firms import firms_service
from backend.app.services.monitor import monitor_loop, persist_events
from backend.app.utils.errors import install_handlers
from backend.app.utils.events import emit


async def sync_model_runs() -> None:
    """Register completed training runs (data/models/*/*/summary.json) in the model_runs collection."""
    import json
    from datetime import datetime, timezone

    from geo import registry
    if not db.db_available():
        return
    for summ in registry.path("data/models").glob("*/*/summary.json"):
        d = json.loads(summ.read_text())
        d["created_at"] = datetime.now(timezone.utc)
        d["path"] = str(summ.parent.relative_to(registry.REPO_ROOT))
        await db.get_db().model_runs.update_one({"run_id": d["run_id"]}, {"$setOnInsert": d}, upsert=True)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wildfiretwin")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    try:
        await db.connect()
    except Exception as exc:
        log.error("MongoDB unavailable (%s) - API runs in degraded mode", exc)
    await emit("system", f"WildfireTwin backend starting (env={s.app_env})")
    tasks = []

    async def startup_ingest():
        await sync_model_runs()
        await firms_service.refresh()
        n = await persist_events()
        await emit("firms", f"fire_events collection synchronised ({n} events)")

    tasks.append(asyncio.create_task(startup_ingest()))
    if s.monitor_enabled and s.app_env != "test":
        tasks.append(asyncio.create_task(monitor_loop()))
    yield
    for t in tasks:
        t.cancel()
    await db.close()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="WildfireTwin API", version="1.0.0", lifespan=lifespan,
                  description="Physics-informed neural-operator wildfire spread prediction - research prototype.")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    install_handlers(app)
    for r in (system.router, auth.router, fires.router, weather.router, predictions.router, simulations.router,
              terrain.router, historical.router):
        app.include_router(r, prefix=s.api_prefix)
    app.mount("/files/predictions", StaticFiles(directory=str(s.predictions_dir)), name="prediction-files")
    app.mount("/files/simulations", StaticFiles(directory=str(s.simulations_dir)), name="simulation-files")
    return app


app = create_app()
