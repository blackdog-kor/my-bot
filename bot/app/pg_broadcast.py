"""
PostgreSQL broadcast_targets table interface (shared with automation).

Table: broadcast_targets
  telegram_user_id  BIGINT PRIMARY KEY
  username          TEXT DEFAULT ''
  source            TEXT DEFAULT 'scraper'
  added_at          TIMESTAMPTZ DEFAULT NOW()
  is_sent           BOOLEAN DEFAULT FALSE
  sent_at           TIMESTAMPTZ

Requires env var: DATABASE_URL (PostgreSQL DSN)
Falls back gracefully if DATABASE_URL is not set (returns empty / no-op).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Generator

logger = logging.getLogger(__name__)

_DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()


def _get_conn():
    """Open a new psycopg2 connection. Caller must close it."""
    import psycopg2
    url = _DATABASE_URL or os.getenv("DATABASE_URL") or ""
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
        logger.info("broadcast_targets table ready")
    except Exception as e:
        logger.warning("ensure_pg_table failed: %s", e)


def upsert_user(telegram_user_id: int, username: str = "", source: str = "bot") -> None:
    """Insert user into broadcast_targets. Ignores if already exists."""
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
        logger.warning("upsert_user(%s) failed: %s", telegram_user_id, e)


def get_unsent_user_ids(limit: int = 0) -> list[int]:
    """Return telegram_user_ids where is_sent=FALSE, ordered by added_at."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        return []
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            if limit > 0:
                cur.execute(
                    "SELECT telegram_user_id FROM broadcast_targets WHERE is_sent = FALSE ORDER BY added_at LIMIT %s",
                    (limit,)
                )
            else:
                cur.execute(
                    "SELECT telegram_user_id FROM broadcast_targets WHERE is_sent = FALSE ORDER BY added_at"
                )
            rows = cur.fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        logger.warning("get_unsent_user_ids failed: %s", e)
        return []


def get_all_pg_user_ids() -> list[int]:
    """Return ALL telegram_user_ids from broadcast_targets (sent or not)."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        return []
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT telegram_user_id FROM broadcast_targets ORDER BY added_at")
            rows = cur.fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        logger.warning("get_all_pg_user_ids failed: %s", e)
        return []


def mark_sent(telegram_user_ids: list[int]) -> None:
    """Mark the given user IDs as is_sent=TRUE."""
    if not telegram_user_ids:
        return
    if not (os.getenv("DATABASE_URL") or "").strip():
        return
    try:
        now = datetime.now(timezone.utc)
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE broadcast_targets
                    SET is_sent = TRUE, sent_at = %s
                    WHERE telegram_user_id = ANY(%s)
                """, (now, telegram_user_ids))
        conn.close()
    except Exception as e:
        logger.warning("mark_sent failed: %s", e)


def reset_all_sent_flags() -> int:
    """Reset is_sent=FALSE for all rows (for re-broadcast). Returns affected rows."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        return 0
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE broadcast_targets SET is_sent = FALSE, sent_at = NULL")
                count = cur.rowcount
        conn.close()
        return count
    except Exception as e:
        logger.warning("reset_all_sent_flags failed: %s", e)
        return 0


def count_unsent() -> int:
    """Return count of unsent users."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        return 0
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM broadcast_targets WHERE is_sent = FALSE")
            row = cur.fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.warning("count_unsent failed: %s", e)
        return 0


def count_total() -> int:
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
        logger.warning("count_total failed: %s", e)
        return 0
