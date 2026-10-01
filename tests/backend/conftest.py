"""Backend test fixtures: real local MongoDB (isolated test database), no external network."""

from __future__ import annotations

import os
import re
import uuid

os.environ["APP_ENV"] = "test"
os.environ["MONGODB_DB"] = f"wildfiretwin_test_{uuid.uuid4().hex[:8]}"
os.environ["JWT_SECRET"] = "test-secret-" + "x" * 40
os.environ["EMAIL_PROVIDER"] = "console"
os.environ["MONITOR_ENABLED"] = "false"
os.environ["FIRMS_MAP_KEY"] = ""

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from backend.app.config import get_settings
from backend.app.services import email as email_mod
from backend.app.services.firms import FirmsService, firms_service
from backend.app.utils.ratelimit import limiter


def _mongo_up() -> bool:
    try:
        MongoClient(get_settings().mongodb_uri, serverSelectionTimeoutMS=1500).admin.command("ping")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _mongo_up(), reason="MongoDB not running")


class Outbox:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def last_code(self, email: str) -> str:
        for to, body in reversed(self.sent):
            if to == email:
                return re.search(r"\b(\d{6})\b", body).group(1)
        raise AssertionError("no email sent")


@pytest.fixture(scope="session")
def outbox():
    return Outbox()


@pytest.fixture(scope="session")
def client(outbox):
    async def fake_send(self, to, subject, body):
        outbox.sent.append((to, body))

    email_mod.ConsoleEmailService.send = fake_send

    sample = pd.DataFrame({
        "latitude": [41.0, 41.002, 41.004, -10.0], "longitude": [-123.2, -123.201, -123.199, 20.0],
        "brightness": [330, 335, 340, 310], "scan": [0.4] * 4, "track": [0.4] * 4,
        "acq_date": ["2026-09-30"] * 4, "acq_time": ["1000", "1010", "1020", "0900"],
        "satellite": ["N20"] * 4, "instrument": ["VIIRS"] * 4, "confidence": ["h", "n", "h", "l"],
        "version": ["2.0NRT"] * 4, "bright_t31": [290] * 4, "frp": [5.0, 7.0, 9.0, 1.0], "daynight": ["D"] * 4,
    })
    from geo.firms import normalize_dataframe

    def fake_local(self):
        df, _ = normalize_dataframe(sample, "test_fixture")
        return df

    FirmsService._load_local = fake_local
    from backend.app.main import create_app
    app = create_app()
    with TestClient(app) as c:
        import asyncio
        c.portal.call(firms_service.refresh) if hasattr(c, "portal") else asyncio.run(firms_service.refresh())
        yield c
    MongoClient(get_settings().mongodb_uri).drop_database(get_settings().mongodb_db)


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()
    yield
