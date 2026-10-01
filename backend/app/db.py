"""MongoDB connection (PyMongo async API) and index management.

MongoDB holds metadata and operational records only. Rasters and tensors live
on the filesystem (GeoTIFF / PNG / NPZ) and are referenced by path.
"""

from __future__ import annotations

import logging

from pymongo import ASCENDING, DESCENDING, GEOSPHERE, AsyncMongoClient, IndexModel
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.config import get_settings

log = logging.getLogger(__name__)

_client: AsyncMongoClient | None = None
_db: AsyncDatabase | None = None

COLLECTIONS = ["users", "email_verifications", "fire_events", "weather_conditions", "predictions",
               "alerts", "model_runs", "system_logs", "simulations"]

INDEXES: dict[str, list[IndexModel]] = {
    "users": [IndexModel([("email", ASCENDING)], unique=True), IndexModel([("google_sub", ASCENDING)], sparse=True)],
    "email_verifications": [IndexModel([("email", ASCENDING)], unique=True),
                            IndexModel([("purge_at", ASCENDING)], expireAfterSeconds=0)],
    "fire_events": [IndexModel([("event_id", ASCENDING)], unique=True), IndexModel([("centroid", GEOSPHERE)]),
                    IndexModel([("last_seen", DESCENDING)]), IndexModel([("status", ASCENDING)])],
    "weather_conditions": [IndexModel([("fire_id", ASCENDING), ("fetched_at", DESCENDING)]),
                           IndexModel([("location", GEOSPHERE)]), IndexModel([("fetched_at", DESCENDING)])],
    "predictions": [IndexModel([("prediction_id", ASCENDING)], unique=True),
                    IndexModel([("fire_id", ASCENDING), ("created_at", DESCENDING)]),
                    IndexModel([("input_hash", ASCENDING)]), IndexModel([("user_id", ASCENDING)]),
                    IndexModel([("created_at", DESCENDING)])],
    "alerts": [IndexModel([("created_at", DESCENDING)]), IndexModel([("fire_id", ASCENDING), ("created_at", DESCENDING)]),
               IndexModel([("severity", ASCENDING)])],
    "model_runs": [IndexModel([("run_id", ASCENDING)], unique=True), IndexModel([("model_type", ASCENDING), ("created_at", DESCENDING)])],
    "system_logs": [IndexModel([("ts", DESCENDING)]), IndexModel([("ts_expire", ASCENDING)], expireAfterSeconds=0),
                    IndexModel([("component", ASCENDING)])],
    "simulations": [IndexModel([("simulation_id", ASCENDING)], unique=True), IndexModel([("created_at", DESCENDING)])],
}


async def connect() -> AsyncDatabase:
    global _client, _db
    s = get_settings()
    _client = AsyncMongoClient(s.mongodb_uri, serverSelectionTimeoutMS=3000, tz_aware=True)
    _db = _client[s.mongodb_db]
    await _client.admin.command("ping")
    for name, idx in INDEXES.items():
        await _db[name].create_indexes(idx)
    log.info("MongoDB connected: %s/%s", s.mongodb_uri.split("@")[-1], s.mongodb_db)
    return _db


async def close() -> None:
    global _client, _db
    if _client is not None:
        await _client.close()
    _client, _db = None, None


def get_db() -> AsyncDatabase:
    if _db is None:
        raise RuntimeError("database not connected")
    return _db


def db_available() -> bool:
    return _db is not None
