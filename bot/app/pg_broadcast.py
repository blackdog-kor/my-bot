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
import time
from datetime import datetime, timezone
from typing import Generator

import httpx

logger = logging.getLogger(__name__)

_DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None


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
                        sent_at          TIMESTAMPTZ,
                        clicked_at       TIMESTAMPTZ,
                        click_count      INTEGER      NOT NULL DEFAULT 0,
                        unique_ref       TEXT
                    )
                """)
                # 기존 테이블에 컬럼이 없다면 추가 (에러는 조용히 무시)
                for alter_sql in (
                    "ALTER TABLE broadcast_targets ADD COLUMN clicked_at TIMESTAMPTZ",
                    "ALTER TABLE broadcast_targets ADD COLUMN click_count INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE broadcast_targets ADD COLUMN unique_ref TEXT",
                ):
                    try:
                        cur.execute(alter_sql)
                    except Exception:
                        pass
        conn.close()
        logger.info("broadcast_targets table ready (with click tracking columns)")
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


def get_unsent_users(limit: int = 0) -> list[tuple[int, str]]:
    """Return (telegram_user_id, username) pairs where is_sent=FALSE AND username != ''.

    Filters out username-less users because MTProto UserBot cannot send DMs to
    numeric-only peers it has never interacted with (PeerIdInvalid).
    Only users with a @username are reliably reachable via UserBot select-first DM.
    """
    if not (os.getenv("DATABASE_URL") or "").strip():
        return []
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            sql = """
                SELECT telegram_user_id, username
                FROM broadcast_targets
                WHERE is_sent = FALSE AND username IS NOT NULL AND username != ''
                ORDER BY added_at
            """
            if limit > 0:
                cur.execute(sql + " LIMIT %s", (limit,))
            else:
                cur.execute(sql)
            rows = cur.fetchall()
        conn.close()
        return [(int(row[0]), row[1]) for row in rows]
    except Exception as e:
        logger.warning("get_unsent_users failed: %s", e)
        return []


def count_unsent_with_username() -> int:
    """Return count of unsent users that have a non-empty username (actually sendable)."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        return 0
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM broadcast_targets WHERE is_sent = FALSE AND username IS NOT NULL AND username != ''"
            )
            row = cur.fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.warning("count_unsent_with_username failed: %s", e)
        return 0


def purge_no_username(dry_run: bool = False) -> int:
    """Mark username-less broadcast_targets rows as sent=TRUE so they no longer clog the queue.

    These users are unreachable via UserBot anyway (PeerIdInvalid).
    Returns the number of affected rows.
    """
    if not (os.getenv("DATABASE_URL") or "").strip():
        return 0
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                if dry_run:
                    cur.execute(
                        "SELECT COUNT(*) FROM broadcast_targets WHERE is_sent = FALSE AND (username IS NULL OR username = '')"
                    )
                    row = cur.fetchone()
                    count = int(row[0]) if row else 0
                else:
                    cur.execute(
                        "UPDATE broadcast_targets SET is_sent = TRUE WHERE is_sent = FALSE AND (username IS NULL OR username = '')"
                    )
                    count = cur.rowcount
        conn.close()
        return count
    except Exception as e:
        logger.warning("purge_no_username failed: %s", e)
        return 0


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


def generate_unique_ref(telegram_user_id: int) -> str:
    """Generate and persist a per-user unique tracking ref."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        return ""
    ref = f"{telegram_user_id}_{int(time.time() * 1000)}"
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE broadcast_targets
                    SET unique_ref = %s
                    WHERE telegram_user_id = %s
                    """,
                    (ref, telegram_user_id),
                )
        conn.close()
    except Exception as e:
        logger.warning("generate_unique_ref(%s) failed: %s", telegram_user_id, e)
    return ref


def _notify_click(telegram_user_id: int, username: str, click_count: int, clicked_at: datetime) -> None:
    """Send a Telegram DM to admin about a click event. Best effort only."""
    if not BOT_TOKEN or not ADMIN_ID:
        return
    text = (
        "🎯 클릭 발생!\n"
        f"유저ID: {telegram_user_id}\n"
        f"username: @{username or '-'}\n"
        f"클릭횟수: {click_count}회\n"
        f"시각: {clicked_at.isoformat()}"
    )
    try:
        with httpx.Client(timeout=10) as hc:
            hc.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": ADMIN_ID,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
    except Exception as e:
        logger.warning("click notify failed: %s", e)


def mark_clicked(ref: str) -> None:
    """Increment click_count and set clicked_at for the given unique_ref."""
    if not ref or not (os.getenv("DATABASE_URL") or "").strip():
        return
    try:
        now = datetime.now(timezone.utc)
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE broadcast_targets
                    SET
                        click_count = COALESCE(click_count, 0) + 1,
                        clicked_at = %s
                    WHERE unique_ref = %s
                    RETURNING telegram_user_id, username, click_count, clicked_at
                    """,
                    (now, ref),
                )
                row = cur.fetchone()
        conn.close()
        if row:
            telegram_user_id, username, click_count, clicked_at = row
            _notify_click(int(telegram_user_id), username or "", int(click_count), clicked_at or now)
    except Exception as e:
        logger.warning("mark_clicked(%s) failed: %s", ref, e)


def get_campaign_stats() -> dict:
    """Return aggregate campaign statistics."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        return {
            "total_targets": 0,
            "total_sent": 0,
            "total_clicked": 0,
            "click_rate": 0.0,
            "pending": 0,
        }
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM broadcast_targets")
            total_targets = int(cur.fetchone()[0] or 0)

            cur.execute("SELECT COUNT(*) FROM broadcast_targets WHERE is_sent = TRUE")
            total_sent = int(cur.fetchone()[0] or 0)

            cur.execute(
                "SELECT COUNT(*) FROM broadcast_targets WHERE click_count IS NOT NULL AND click_count > 0"
            )
            total_clicked = int(cur.fetchone()[0] or 0)

            cur.execute("SELECT COUNT(*) FROM broadcast_targets WHERE is_sent = FALSE")
            pending = int(cur.fetchone()[0] or 0)
        conn.close()
    except Exception as e:
        logger.warning("get_campaign_stats failed: %s", e)
        return {
            "total_targets": 0,
            "total_sent": 0,
            "total_clicked": 0,
            "click_rate": 0.0,
            "pending": 0,
        }

    click_rate = (total_clicked / total_sent * 100.0) if total_sent > 0 else 0.0
    return {
        "total_targets": total_targets,
        "total_sent": total_sent,
        "total_clicked": total_clicked,
        "click_rate": round(click_rate, 2),
        "pending": pending,
    }

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
