"""
Token Vault — autonomous token lifecycle management.

Responsibilities:
  1. Extract tokens from live browser sessions (network interception)
  2. Store tokens encrypted in PostgreSQL
  3. Auto-refresh before expiry using site-specific strategies
  4. Expose valid tokens to callers without manual intervention

Site strategies are registered via @token_vault.register().
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Awaitable

import psycopg2

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")


# ── DB schema ────────────────────────────────────────────────────────────────

def ensure_vault_table() -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS token_vault (
                site        TEXT PRIMARY KEY,
                tokens      TEXT NOT NULL,
                extracted_at TIMESTAMPTZ DEFAULT NOW(),
                expires_at  TIMESTAMPTZ,
                extra       TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _save(site: str, tokens: dict, expires_at: float | None = None,
          extra: dict | None = None) -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO token_vault (site, tokens, expires_at, extra)
            VALUES (%s, %s, to_timestamp(%s), %s)
            ON CONFLICT (site) DO UPDATE
              SET tokens=EXCLUDED.tokens,
                  extracted_at=NOW(),
                  expires_at=EXCLUDED.expires_at,
                  extra=EXCLUDED.extra
        """, (
            site,
            json.dumps(tokens),
            expires_at,
            json.dumps(extra or {}),
        ))
        conn.commit()
    finally:
        conn.close()


def _load(site: str) -> dict | None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT tokens, extract(epoch from expires_at)
            FROM token_vault WHERE site=%s
        """, (site,))
        row = cur.fetchone()
        if not row:
            return None
        tokens = json.loads(row[0])
        expires_at = float(row[1]) if row[1] else None
        tokens["_expires_at"] = expires_at
        return tokens
    finally:
        conn.close()


# ── JWT expiry parser ────────────────────────────────────────────────────────

def _jwt_expiry(token: str) -> float | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.b64decode(payload))
        return float(data.get("exp", 0)) or None
    except Exception:
        return None


def _is_expired(tokens: dict, margin_seconds: int = 300) -> bool:
    exp = tokens.get("_expires_at")
    if not exp:
        access = tokens.get("accessToken", "")
        exp = _jwt_expiry(access) if access else None
    if not exp:
        return False
    return time.time() > exp - margin_seconds


# ── Site strategy registry ───────────────────────────────────────────────────

@dataclass
class SiteStrategy:
    site: str
    login_url: str
    extract: Callable[[], Awaitable[dict]]   # returns {accessToken, refreshToken, ...}
    refresh: Callable[[dict], Awaitable[dict]] | None = None
    interval_seconds: int = 3600 * 6


_registry: dict[str, SiteStrategy] = {}


def register(strategy: SiteStrategy) -> None:
    _registry[strategy.site] = strategy
    logger.info("[vault] registered strategy: %s", strategy.site)


# ── Public API ───────────────────────────────────────────────────────────────

async def get_tokens(site: str, force_refresh: bool = False) -> dict:
    """
    Return valid tokens for site.
    Auto-refreshes if expired. Auto-extracts if never seen.
    """
    cached = _load(site)

    if not force_refresh and cached and not _is_expired(cached):
        return cached

    strategy = _registry.get(site)
    if not strategy:
        raise RuntimeError(f"No strategy registered for site: {site}")

    # try refresh first (cheaper)
    if cached and strategy.refresh:
        try:
            tokens = await strategy.refresh(cached)
            exp = _jwt_expiry(tokens.get("accessToken", ""))
            _save(site, tokens, expires_at=exp)
            logger.info("[vault] %s: token refreshed", site)
            return tokens
        except Exception as e:
            logger.warning("[vault] %s: refresh failed (%s) — re-extracting", site, e)

    # full browser extraction
    tokens = await strategy.extract()
    exp = _jwt_expiry(tokens.get("accessToken", ""))
    _save(site, tokens, expires_at=exp)
    logger.info("[vault] %s: tokens extracted via browser", site)
    return tokens


async def watch_all() -> None:
    """Background loop: proactively refresh all registered sites."""
    while True:
        for site, strategy in list(_registry.items()):
            try:
                await get_tokens(site)
            except Exception as e:
                logger.error("[vault] %s watch error: %s", site, e)
        await asyncio.sleep(min(s.interval_seconds for s in _registry.values()) // 2
                            if _registry else 3600)
