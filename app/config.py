"""Centralized configuration using pydantic-settings.

All environment variables are validated at import time.
Usage: `from app.config import settings`
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── Telegram API ─────────────────────────────────────────────
    api_id: int = 0
    api_hash: str = ""
    bot_token: str = ""
    subscribe_bot_token: str = ""

    # ── Database ─────────────────────────────────────────────────
    database_url: str = ""

    # ── Admin ────────────────────────────────────────────────────
    admin_id: int = 0

    # ── Channel / URLs ───────────────────────────────────────────
    channel_id: str = ""
    affiliate_url: str = ""
    vip_url: str = "https://1wwtgq.com/?p=mskf"
    tracking_server_url: str = ""

    # ── External API keys ────────────────────────────────────────
    gemini_api_key: str = ""
    brightdata_api_token: str = ""

    # ── DM send tuning ───────────────────────────────────────────
    user_delay_min: float = 15.0
    user_delay_max: float = 45.0
    long_break_every: int = 50
    long_break_min: float = 300.0
    long_break_max: float = 600.0
    batch_size: int = 50
    daily_limit_per_account: int = 100

    # ── Security ─────────────────────────────────────────────────
    debug_secret: str = ""
    affiliate_webhook_secret: str = ""
    railway_proxy_secret: str = ""

    # ── Optional integrations ────────────────────────────────────
    sentry_dsn: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
