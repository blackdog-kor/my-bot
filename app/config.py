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

    # ── Channel / Group / URLs ───────────────────────────────────
    channel_id: str = ""
    group_id: str = ""  # Forum-enabled group for topic-based content
    affiliate_url: str = ""
    vip_url: str = "https://1wwtgq.com/?p=mskf"
    tracking_server_url: str = ""

    # ── External API keys ────────────────────────────────────────
    anthropic_api_key: str = ""
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

    # ── DB Pool ──────────────────────────────────────────────────
    db_pool_min_conn: int = 2
    db_pool_max_conn: int = 10

    # ── Security ─────────────────────────────────────────────────
    debug_secret: str = ""
    affiliate_webhook_secret: str = ""
    railway_proxy_secret: str = ""

    # ── Content Automation ────────────────────────────────────────
    content_scrape_sources: str = ""  # comma-separated Telegram channel usernames
    content_post_interval_hours: int = 4  # hours between auto-posts
    content_max_daily_posts: int = 6  # max posts per day
    content_rewrite_enabled: bool = True  # AI rewrite before posting
    openai_api_key: str = ""  # for content rewriting

    # ── Web Scraping (Layer 1 — zero ban risk) ────────────────────
    web_scrape_sources: str = ""  # comma-separated extra URLs to scrape
    web_scrape_enabled: bool = True  # enable external web scraping
    telegram_scrape_enabled: bool = False  # disable risky Telethon scraping by default

    # ── TeraBox Agent (browser-use AI agent) ─────────────────────
    terabox_share_urls: str = ""  # comma-separated TeraBox share URLs
    terabox_enabled: bool = False  # enable TeraBox content pipeline
    terabox_cookies: str = ""  # optional login cookies for private files

    # ── Sports Content Automation ─────────────────────────────────
    sports_enabled: bool = True  # enable sports content pipeline
    sports_api_key: str = ""  # API-Football key (api-sports.io)
    # League strategy by period (FD free plan supported only):
    #   May-Jun:  WC(1) + CL(2) + EL(3) + EU big5(39,140,135,61,78)
    #             → CL Final May 30, WC starts Jun 12, EU season ends May 24
    #   Jul-Aug:  WC(1) + CL/EL qualifiers(2,3)  → EU leagues restart Aug
    #   Sep-May:  WC(1) + EU big5 + CL/EL  → full season
    # Note: K리그(292)/MLS(253)/J1(98)/Brasileirao(71) NOT on FD free plan;
    #       API-Football free plan only covers 2022-2024 seasons — 2026 blocked.
    sports_leagues: str = "1,2,3,39,140,135,61,78"
    sports_post_interval_hours: int = 6  # hours between sports posts
    sports_max_daily_posts: int = 6  # max sports posts per day (min 6 for dedicated board)
    sports_topic_content_type: str = "sports"  # content_type for forum topic routing
    pexels_api_key: str = ""          # Pexels API key for sports post images (free: 200 req/hr)
    odds_api_key: str = ""            # The Odds API key for real betting odds (free: 500 req/month)
    football_data_api_key: str = ""   # api.football-data.org free key (current season, 10 comp)

    # ── Match Scheduler (real-time 30-min job) ────────────────────
    match_preview_hours_before: int = 3   # post preview this many hours before kickoff
    match_review_mins_after: int = 110    # post review this many minutes after kickoff
    match_schedule_days_ahead: int = 3    # days ahead to populate match schedule table

    # ── Optional integrations ────────────────────────────────────
    sentry_dsn: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
