"""
PostgreSQL broadcast_targets table interface (통합 서비스 공용).

Table: broadcast_targets
  telegram_user_id  BIGINT PRIMARY KEY
  username          TEXT DEFAULT ''
  source            TEXT DEFAULT 'scraper'
  added_at          TIMESTAMPTZ DEFAULT NOW()
  is_sent           BOOLEAN DEFAULT FALSE
  sent_at           TIMESTAMPTZ
  clicked_at        TIMESTAMPTZ
  click_count       INTEGER DEFAULT 0
  unique_ref        TEXT
  retry_sent        BOOLEAN DEFAULT FALSE
  retry_sent_at     TIMESTAMPTZ

Requires env var: DATABASE_URL (PostgreSQL DSN)
"""
from __future__ import annotations

import os
import sys
sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    """Create broadcast_targets table if it doesn't exist. Add columns if missing."""
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
                        unique_ref       TEXT,
                        retry_sent       BOOLEAN      NOT NULL DEFAULT FALSE,
                        retry_sent_at    TIMESTAMPTZ
                    )
                """)
                for alter_sql in (
                    "ALTER TABLE broadcast_targets ADD COLUMN clicked_at TIMESTAMPTZ",
                    "ALTER TABLE broadcast_targets ADD COLUMN click_count INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE broadcast_targets ADD COLUMN unique_ref TEXT",
                    "ALTER TABLE broadcast_targets ADD COLUMN retry_sent BOOLEAN NOT NULL DEFAULT FALSE",
                    "ALTER TABLE broadcast_targets ADD COLUMN retry_sent_at TIMESTAMPTZ",
                ):
                    try:
                        cur.execute(alter_sql)
                    except Exception:
                        pass
        conn.close()
        logger.info("broadcast_targets table ready")
    except Exception as e:
        logger.warning("ensure_pg_table failed: %s", e)


def ensure_loaded_message_table() -> None:
    """Create loaded_message table (for media metadata) if it doesn't exist."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        logger.warning("DATABASE_URL not set — skipping loaded_message table setup")
        return
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS loaded_message (
                        id         INTEGER PRIMARY KEY DEFAULT 1,
                        file_id    TEXT,
                        file_type  TEXT,
                        caption    TEXT,
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
        conn.close()
        logger.info("loaded_message table ready")
    except Exception as e:
        logger.warning("ensure_loaded_message_table failed: %s", e)


def upsert_user(telegram_user_id: int, username: str = "", source: str = "bot") -> None:
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


def save_broadcast_batch(entries: list[tuple[int, str, str]]) -> int:
    """Batch upsert (telegram_user_id, username, source). ON CONFLICT DO UPDATE for empty username. Returns affected count."""
    if not entries or not (os.getenv("DATABASE_URL") or "").strip():
        return 0
    n = 0
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                for uid, username, source in entries:
                    cur.execute("""
                        INSERT INTO broadcast_targets (telegram_user_id, username, source)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (telegram_user_id) DO UPDATE
                        SET username = EXCLUDED.username, source = EXCLUDED.source
                        WHERE broadcast_targets.username IS NULL OR broadcast_targets.username = ''
                           OR broadcast_targets.username <> EXCLUDED.username
                    """, (uid, username or "", source or "scraper"))
                    n += cur.rowcount
        conn.close()
    except Exception as e:
        logger.warning("save_broadcast_batch failed: %s", e)
    return n


def get_unsent_user_ids(limit: int = 0) -> list[int]:
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
    if not telegram_user_ids or not (os.getenv("DATABASE_URL") or "").strip():
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


def generate_unique_ref(telegram_user_id: int) -> str:
    if not (os.getenv("DATABASE_URL") or "").strip():
        return ""
    ref = f"{telegram_user_id}_{int(time.time() * 1000)}"
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE broadcast_targets SET unique_ref = %s WHERE telegram_user_id = %s",
                    (ref, telegram_user_id),
                )
        conn.close()
    except Exception as e:
        logger.warning("generate_unique_ref(%s) failed: %s", telegram_user_id, e)
    return ref


def _notify_click(telegram_user_id: int, username: str, click_count: int, clicked_at: datetime) -> None:
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
                json={"chat_id": ADMIN_ID, "text": text, "disable_web_page_preview": True},
            )
    except Exception as e:
        logger.warning("click notify failed: %s", e)


def mark_clicked(ref: str) -> None:
    if not ref or not (os.getenv("DATABASE_URL") or "").strip():
        return
    try:
        now = datetime.now(timezone.utc)
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE broadcast_targets
                    SET click_count = COALESCE(click_count, 0) + 1, clicked_at = %s
                    WHERE unique_ref = %s
                    RETURNING telegram_user_id, username, click_count, clicked_at
                """, (now, ref))
                row = cur.fetchone()
        conn.close()
        if row:
            telegram_user_id, username, click_count, clicked_at = row
            _notify_click(int(telegram_user_id), username or "", int(click_count), clicked_at or now)
    except Exception as e:
        logger.warning("mark_clicked(%s) failed: %s", ref, e)


def get_campaign_stats() -> dict:
    if not (os.getenv("DATABASE_URL") or "").strip():
        return {"total_targets": 0, "total_sent": 0, "total_clicked": 0, "click_rate": 0.0, "pending": 0}
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM broadcast_targets")
            total_targets = int(cur.fetchone()[0] or 0)
            cur.execute("SELECT COUNT(*) FROM broadcast_targets WHERE is_sent = TRUE")
            total_sent = int(cur.fetchone()[0] or 0)
            cur.execute("SELECT COUNT(*) FROM broadcast_targets WHERE click_count IS NOT NULL AND click_count > 0")
            total_clicked = int(cur.fetchone()[0] or 0)
            cur.execute("SELECT COUNT(*) FROM broadcast_targets WHERE is_sent = FALSE")
            pending = int(cur.fetchone()[0] or 0)
        conn.close()
    except Exception as e:
        logger.warning("get_campaign_stats failed: %s", e)
        return {"total_targets": 0, "total_sent": 0, "total_clicked": 0, "click_rate": 0.0, "pending": 0}
    click_rate = (total_clicked / total_sent * 100.0) if total_sent > 0 else 0.0
    return {
        "total_targets": total_targets,
        "total_sent": total_sent,
        "total_clicked": total_clicked,
        "click_rate": round(click_rate, 2),
        "pending": pending,
    }


def get_count_added_on_date(target_date) -> int:
    """added_at 날짜가 target_date인 행 수 (일일 리포트용). target_date: date 객체."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        return 0
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM broadcast_targets WHERE (added_at AT TIME ZONE 'UTC')::date = %s",
                (target_date,),
            )
            row = cur.fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.warning("get_count_added_on_date failed: %s", e)
        return 0


def get_count_clicked_on_date(target_date) -> int:
    """clicked_at 날짜가 target_date인 행 수 (일일 리포트용). target_date: date 객체."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        return 0
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM broadcast_targets WHERE clicked_at IS NOT NULL AND (clicked_at AT TIME ZONE 'UTC')::date = %s",
                (target_date,),
            )
            row = cur.fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.warning("get_count_clicked_on_date failed: %s", e)
        return 0


def get_retry_sent_count() -> int:
    """retry_sent = TRUE 인 행 수."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        return 0
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM broadcast_targets WHERE retry_sent = TRUE")
            row = cur.fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.warning("get_retry_sent_count failed: %s", e)
        return 0


def save_loaded_message(file_id: str, file_type: str, caption: str) -> None:
    """Upsert loaded_message row (always id=1)."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        return
    try:
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO loaded_message (id, file_id, file_type, caption, updated_at)
                    VALUES (1, %s, %s, %s, NOW())
                    ON CONFLICT (id) DO UPDATE
                    SET file_id = EXCLUDED.file_id,
                        file_type = EXCLUDED.file_type,
                        caption = EXCLUDED.caption,
                        updated_at = NOW()
                    """,
                    (file_id or "", file_type or "photo", caption or ""),
                )
        conn.close()
    except Exception as e:
        logger.warning("save_loaded_message failed: %s", e)


def get_loaded_message() -> tuple[str, str, str] | None:
    """Return (file_id, file_type, caption) from PostgreSQL loaded_message, or None."""
    if not (os.getenv("DATABASE_URL") or "").strip():
        return None
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT file_id, file_type, caption FROM loaded_message WHERE id = 1"
            )
            row = cur.fetchone()
        conn.close()
        if not row:
            return None
        file_id = row[0] or ""
        file_type = row[1] or "photo"
        caption = row[2] or ""
        if not file_id:
            return None
        return file_id, file_type, caption
    except Exception as e:
        logger.warning("get_loaded_message failed: %s", e)
        return None


def get_retry_targets(cutoff: datetime | None = None) -> list[tuple[int, str]]:
    if not (os.getenv("DATABASE_URL") or "").strip():
        return []
    if cutoff is None:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT telegram_user_id, username
                FROM broadcast_targets
                WHERE is_sent = TRUE AND COALESCE(click_count, 0) = 0 AND retry_sent = FALSE
                  AND sent_at IS NOT NULL AND sent_at <= %s
                  AND username IS NOT NULL AND username <> ''
                ORDER BY sent_at
            """, (cutoff,))
            rows = cur.fetchall()
        conn.close()
        return [(int(r[0]), r[1]) for r in rows]
    except Exception as e:
        logger.warning("get_retry_targets failed: %s", e)
        return []


def mark_retry_sent(telegram_user_ids: list[int]) -> None:
    if not telegram_user_ids or not (os.getenv("DATABASE_URL") or "").strip():
        return
    try:
        now = datetime.now(timezone.utc)
        conn = _get_conn()
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE broadcast_targets SET retry_sent = TRUE, retry_sent_at = %s
                    WHERE telegram_user_id = ANY(%s)
                """, (now, telegram_user_ids))
        conn.close()
    except Exception as e:
        logger.warning("mark_retry_sent failed: %s", e)
