"""Application settings from environment variables (see .env.example)."""

from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
log = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "production", "test"] = "development"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    mongodb_uri: str = "mongodb://127.0.0.1:27017"
    mongodb_db: str = "wildfiretwin"

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 120

    otp_ttl_seconds: int = 300
    otp_resend_cooldown_seconds: int = 60
    otp_max_attempts: int = 5
    otp_max_resends: int = 5

    email_provider: Literal["console", "smtp", "resend", "sendgrid"] = "console"
    email_from: str = "WildfireTwin <no-reply@wildfiretwin.local>"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    resend_api_key: str = ""
    sendgrid_api_key: str = ""

    google_client_id: str = ""

    firms_map_key: str = ""
    firms_api_source: str = "VIIRS_NOAA20_NRT"
    firms_api_days: int = 2
    firms_active_hours: int = 48

    open_meteo_url: str = "https://api.open-meteo.com/v1/forecast"
    weather_cache_seconds: int = 900
    http_timeout_seconds: float = 15.0

    monitor_enabled: bool = True
    monitor_interval_seconds: int = 900

    default_model: str = "physics_fno"
    inference_device: Literal["auto", "cpu", "cuda"] = "auto"

    predictions_dir: Path = Field(default=REPO_ROOT / "data" / "predictions")
    simulations_dir: Path = Field(default=REPO_ROOT / "data" / "simulations")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    if not s.jwt_secret:
        if s.app_env == "production":
            raise RuntimeError("JWT_SECRET must be set in production")
        s.jwt_secret = secrets.token_urlsafe(48)
        log.warning("JWT_SECRET not set - using an ephemeral development secret (sessions end on restart)")
    s.predictions_dir.mkdir(parents=True, exist_ok=True)
    s.simulations_dir.mkdir(parents=True, exist_ok=True)
    return s
