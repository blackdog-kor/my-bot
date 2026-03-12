"""
PostgreSQL broadcast_targets table interface for automation scraper.
Shares the same table as bot/app/pg_broadcast.py.

Requires env var: DATABASE_URL (PostgreSQL DSN)
Falls back gracefully if DATABASE_URL is not set.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _get_conn():
    import psycopg2
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(url)


def ensure_pg_table() -> None:
    """Create broadcast_targets table if it doesn't exist."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        logger.warning("DATABASE_URL not set — skipping PostgreSQL table setup")
        return
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS broadcast_targets (
                        telegram_user_id BIGINT PRIMARY KEY,
                        username         TEXT        NOT NULL DEFAULT '',
                        source           TEXT        NOT NULL DEFAULT 'scraper',
                        added_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        is_sent          BOOLEAN     NOT NULL DEFAULT FALSE,
                        sent_at          TIMESTAMPTZ
                    )
                """)
        conn.close()
        logger.info("broadcast_targets table ready (automation)")
    except Exception as e:
        logger.warning("ensure_pg_table failed: %s", e)


def upsert_broadcast_target(
    telegram_user_id: int,
    username: str = "",
    source: str = "scraper",
) -> None:
    """
    Insert scraped user into broadcast_targets with is_sent=FALSE.
    Ignores duplicate (ON CONFLICT DO NOTHING) so repeated scrapes are safe.
    """
    if not (os.getenv("DATABASE_URL") or "").strip():
        return
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO broadcast_targets (telegram_user_id, username, source)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (telegram_user_id) DO NOTHING
                """, (telegram_user_id, username or "", source))
        conn.close()
    except Exception as e:
        logger.warning("upsert_broadcast_target(%s) failed: %s", telegram_user_id, e)


def count_broadcast_targets() -> int:
    """Return total rows in broadcast_targets."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        return 0
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM broadcast_targets")
            row = cur.fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.warning("count_broadcast_targets failed: %s", e)
        return 0
