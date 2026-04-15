import logging
import os
import sys
from datetime import datetime, timezone

import psycopg2

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


# ─────────────────────────────────────────────
# broadcast_targets 테이블
# ─────────────────────────────────────────────

def ensure_pg_table():
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_targets (
                telegram_user_id BIGINT PRIMARY KEY,
                username         TEXT,
                source           TEXT,
                added_at         TIMESTAMPTZ DEFAULT NOW(),
                is_sent          BOOLEAN     DEFAULT FALSE,
                sent_at          TIMESTAMPTZ,
                clicked_at       TIMESTAMPTZ,
                click_count      INTEGER     DEFAULT 0,
                unique_ref       TEXT,
                retry_sent       BOOLEAN     DEFAULT FALSE,
                retry_sent_at    TIMESTAMPTZ
            )
        """)
        conn.commit()

        # 기존 테이블에 컬럼이 없을 수 있으므로 ALTER로 추가
        extra_columns = [
            ("clicked_at",    "TIMESTAMPTZ"),
            ("click_count",   "INTEGER DEFAULT 0"),
            ("unique_ref",    "TEXT"),
            ("retry_sent",    "BOOLEAN DEFAULT FALSE"),
            ("retry_sent_at", "TIMESTAMPTZ"),
        ]
        for col_name, col_type in extra_columns:
            try:
                cur.execute(
                    f"ALTER TABLE broadcast_targets ADD COLUMN {col_name} {col_type}"
                )
                conn.commit()
            except Exception:
                conn.rollback()

        cur.close()
        conn.close()
        logger.info("ensure_pg_table: OK")
    except Exception as e:
        logger.warning("ensure_pg_table failed: %s", e)


def save_broadcast_batch(users: list[tuple[int, str, str]]):
    """users: [(telegram_user_id, username, source), ...]"""
    if not users:
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.executemany("""
            INSERT INTO broadcast_targets (telegram_user_id, username, source)
            VALUES (%s, %s, %s)
            ON CONFLICT (telegram_user_id) DO UPDATE
                SET username = EXCLUDED.username,
                    source   = EXCLUDED.source
        """, users)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("save_broadcast_batch failed: %s", e)


def get_unsent_users(limit: int = 500) -> list[tuple[int, str]]:
    """(telegram_user_id, username) 목록 반환"""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT telegram_user_id, username
            FROM broadcast_targets
            WHERE is_sent = FALSE
              AND username IS NOT NULL
              AND username <> ''
            ORDER BY added_at
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        logger.warning("get_unsent_users failed: %s", e)
        return []


def count_unsent_with_username() -> int:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM broadcast_targets
            WHERE is_sent = FALSE
              AND username IS NOT NULL
              AND username <> ''
        """)
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception as e:
        logger.warning("count_unsent_with_username failed: %s", e)
        return 0


def count_total() -> int:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM broadcast_targets")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception as e:
        logger.warning("count_total failed: %s", e)
        return 0


def mark_sent(user_ids: list[int]):
    if not user_ids:
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE broadcast_targets
            SET is_sent = TRUE, sent_at = NOW()
            WHERE telegram_user_id = ANY(%s)
        """, (user_ids,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("mark_sent failed: %s", e)


def generate_unique_ref(user_id: int) -> str:
    ts = int(datetime.now(timezone.utc).timestamp())
    return f"{user_id}_{ts}"


def mark_clicked(ref: str):
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE broadcast_targets
            SET click_count = COALESCE(click_count, 0) + 1,
                clicked_at  = NOW()
            WHERE unique_ref = %s
        """, (ref,))
        conn.commit()

        # 관리자 알림
        cur.execute("""
            SELECT telegram_user_id, username, click_count
            FROM broadcast_targets
            WHERE unique_ref = %s
        """, (ref,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row:
            _notify_click(row[0], row[1], row[2])
    except Exception as e:
        logger.warning("mark_clicked failed: %s", e)


def _notify_click(user_id: int, username: str, click_count: int):
    import httpx
    bot_token = os.getenv("BOT_TOKEN", "")
    admin_id  = os.getenv("ADMIN_ID", "")
    if not bot_token or not admin_id:
        return
    text = (
        f"🎯 클릭 발생!\n"
        f"유저ID: {user_id}\n"
        f"username: @{username}\n"
        f"클릭횟수: {click_count}회"
    )
    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": admin_id, "text": text},
            timeout=10,
        )
    except Exception as e:
        logger.warning("_notify_click failed: %s", e)


def get_campaign_stats() -> dict:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*)                                          AS total_targets,
                COUNT(*) FILTER (WHERE is_sent = TRUE)           AS total_sent,
                COUNT(*) FILTER (WHERE click_count > 0)          AS total_clicked,
                COUNT(*) FILTER (WHERE is_sent = FALSE
                                   AND username IS NOT NULL
                                   AND username <> '')            AS pending
            FROM broadcast_targets
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        total_targets = row[0] or 0
        total_sent    = row[1] or 0
        total_clicked = row[2] or 0
        pending       = row[3] or 0
        click_rate    = round(total_clicked / total_sent * 100, 2) if total_sent > 0 else 0.0
        return {
            "total_targets": total_targets,
            "total_sent":    total_sent,
            "total_clicked": total_clicked,
            "click_rate":    click_rate,
            "pending":       pending,
        }
    except Exception as e:
        logger.warning("get_campaign_stats failed: %s", e)
        return {"total_targets": 0, "total_sent": 0, "total_clicked": 0,
                "click_rate": 0.0, "pending": 0}


def get_retry_targets(cutoff: datetime | None = None) -> list[tuple[int, str]]:
    if cutoff is None:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT telegram_user_id, username
            FROM broadcast_targets
            WHERE is_sent      = TRUE
              AND COALESCE(click_count, 0) = 0
              AND retry_sent   = FALSE
              AND sent_at     <= %s
              AND username IS NOT NULL
              AND username <> ''
            ORDER BY sent_at
        """, (cutoff,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        logger.warning("get_retry_targets failed: %s", e)
        return []


def mark_retry_sent(user_ids: list[int]):
    if not user_ids:
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE broadcast_targets
            SET retry_sent = TRUE, retry_sent_at = NOW()
            WHERE telegram_user_id = ANY(%s)
        """, (user_ids,))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("mark_retry_sent failed: %s", e)


def purge_no_username() -> int:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM broadcast_targets
            WHERE username IS NULL OR username = ''
        """)
        count = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return count
    except Exception as e:
        logger.warning("purge_no_username failed: %s", e)
        return 0


def get_count_added_on_date(target_date) -> int:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM broadcast_targets
            WHERE DATE(added_at AT TIME ZONE 'UTC') = %s
        """, (target_date,))
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception as e:
        logger.warning("get_count_added_on_date failed: %s", e)
        return 0


# ─────────────────────────────────────────────
# discovered_groups 테이블
# ─────────────────────────────────────────────

def ensure_discovered_groups_table():
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS discovered_groups (
                group_id      BIGINT PRIMARY KEY,
                username      TEXT,
                title         TEXT,
                member_count  INTEGER,
                discovered_at TIMESTAMPTZ DEFAULT NOW(),
                scraped       BOOLEAN DEFAULT FALSE,
                scrape_failed BOOLEAN DEFAULT FALSE
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        logger.info("ensure_discovered_groups_table: OK")
    except Exception as e:
        logger.warning("ensure_discovered_groups_table failed: %s", e)


def save_discovered_group(
    group_id: int, username: str, title: str, member_count: int
) -> bool:
    """신규 그룹 저장. 이미 존재하면 False 반환."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO discovered_groups (group_id, username, title, member_count)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (group_id) DO NOTHING
        """, (group_id, username, title, member_count))
        inserted = cur.rowcount > 0
        conn.commit()
        cur.close()
        conn.close()
        return inserted
    except Exception as e:
        logger.warning("save_discovered_group failed: %s", e)
        return False


def get_unscraped_groups(limit: int = 50) -> list[tuple[int, str, str]]:
    """scraped=FALSE, scrape_failed=FALSE 그룹 반환 (group_id, username, title)"""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT group_id, username, title
            FROM discovered_groups
            WHERE scraped = FALSE
              AND scrape_failed = FALSE
              AND username IS NOT NULL
              AND username <> ''
            ORDER BY discovered_at
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        logger.warning("get_unscraped_groups failed: %s", e)
        return []


def mark_group_scraped(group_id: int):
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE discovered_groups SET scraped=TRUE WHERE group_id=%s",
            (group_id,),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("mark_group_scraped failed: %s", e)


def mark_group_scrape_failed(group_id: int):
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE discovered_groups SET scrape_failed=TRUE WHERE group_id=%s",
            (group_id,),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("mark_group_scrape_failed failed: %s", e)


def truncate_discovered_groups() -> int:
    """discovered_groups 테이블 전체 삭제. 삭제된 행 수 반환."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM discovered_groups")
        deleted = cur.rowcount or 0
        conn.commit()
        cur.close()
        conn.close()
        logger.info("truncate_discovered_groups: %d rows deleted", deleted)
        return deleted
    except Exception as e:
        logger.warning("truncate_discovered_groups failed: %s", e)
        return 0


def count_discovered_groups() -> dict:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE scraped = FALSE AND scrape_failed = FALSE) AS pending
            FROM discovered_groups
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        return {"total": row[0] or 0, "pending": row[1] or 0}
    except Exception as e:
        logger.warning("count_discovered_groups failed: %s", e)
        return {"total": 0, "pending": 0}


def get_count_clicked_on_date(target_date) -> int:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM broadcast_targets
            WHERE DATE(clicked_at AT TIME ZONE 'UTC') = %s
        """, (target_date,))
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception as e:
        logger.warning("get_count_clicked_on_date failed: %s", e)
        return 0


def get_retry_sent_count() -> int:
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM broadcast_targets WHERE retry_sent = TRUE")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception as e:
        logger.warning("get_retry_sent_count failed: %s", e)
        return 0


# ─────────────────────────────────────────────
# Subscribe Bot 전용 헬퍼
# ─────────────────────────────────────────────

def get_subscribe_user_ids() -> list[int]:
    """subscribe_bot source 구독자의 telegram_user_id 목록 반환."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT telegram_user_id FROM broadcast_targets
            WHERE source = 'subscribe_bot'
            ORDER BY added_at
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [r[0] for r in rows]
    except Exception as e:
        logger.warning("get_subscribe_user_ids failed: %s", e)
        return []


def get_subscribe_users() -> list[tuple[int, str]]:
    """subscribe_bot source 구독자의 (telegram_user_id, username) 목록 반환."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT telegram_user_id, COALESCE(username, '') FROM broadcast_targets
            WHERE source = 'subscribe_bot'
            ORDER BY added_at
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        logger.warning("get_subscribe_users failed: %s", e)
        return []


def count_subscribe_users() -> int:
    """subscribe_bot source 구독자 수 반환."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM broadcast_targets WHERE source = 'subscribe_bot'"
        )
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception as e:
        logger.warning("count_subscribe_users failed: %s", e)
        return 0


# ─────────────────────────────────────────────
# loaded_message 테이블 (UserBot Saved Messages ID 보관)
# ─────────────────────────────────────────────

def ensure_loaded_message_table():
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS loaded_message (
                id                 INTEGER PRIMARY KEY DEFAULT 1,
                userbot_message_id INTEGER,
                file_id            TEXT    NOT NULL DEFAULT '',
                file_type          TEXT    NOT NULL DEFAULT 'photo',
                caption            TEXT    NOT NULL DEFAULT '',
                chat_id            BIGINT  NOT NULL DEFAULT 0,
                message_id         BIGINT  NOT NULL DEFAULT 0,
                updated_at         TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        conn.commit()

        # 기존 테이블 마이그레이션 (누락 컬럼 추가)
        columns_to_add = [
            ("userbot_message_id", "INTEGER"),
            ("file_id",            "TEXT NOT NULL DEFAULT ''"),
            ("file_type",          "TEXT NOT NULL DEFAULT 'photo'"),
            ("caption",            "TEXT NOT NULL DEFAULT ''"),
            ("chat_id",            "BIGINT NOT NULL DEFAULT 0"),
            ("message_id",         "BIGINT NOT NULL DEFAULT 0"),
            ("updated_at",         "TIMESTAMPTZ DEFAULT NOW()"),
        ]
        for col_name, col_type in columns_to_add:
            try:
                cur.execute(
                    f"ALTER TABLE loaded_message ADD COLUMN {col_name} {col_type}"
                )
                conn.commit()
            except Exception:
                conn.rollback()

        cur.close()
        conn.close()
        logger.info("ensure_loaded_message_table: OK")
    except Exception as e:
        logger.warning("ensure_loaded_message_table failed: %s", e)


def get_loaded_message_full_pg() -> tuple[int, int, str, str, str] | None:
    """(chat_id, message_id, file_id, file_type, caption) 반환. 없거나 file_id 없으면 None."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT chat_id, message_id, file_id, file_type, caption
            FROM loaded_message WHERE id = 1
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None or not (row[2] or "").strip():
            return None
        return (int(row[0]), int(row[1]), row[2] or "", row[3] or "photo", row[4] or "")
    except Exception as e:
        logger.warning("get_loaded_message_full_pg failed: %s", e)
        return None


def set_loaded_message_pg(
    chat_id: int,
    message_id: int,
    *,
    file_id: str = "",
    file_type: str = "photo",
    caption: str = "",
) -> bool:
    """PG loaded_message 저장. 성공 True, 실패 False."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO loaded_message (id, chat_id, message_id, file_id, file_type, caption, updated_at)
            VALUES (1, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE
                SET chat_id    = EXCLUDED.chat_id,
                    message_id = EXCLUDED.message_id,
                    file_id    = EXCLUDED.file_id,
                    file_type  = EXCLUDED.file_type,
                    caption    = EXCLUDED.caption,
                    updated_at = NOW()
        """, (chat_id, message_id, file_id, file_type, caption))
        conn.commit()
        cur.close()
        conn.close()
        logger.info("set_loaded_message_pg: OK (file_id=%s, type=%s)", file_id[:20], file_type)
        return True
    except Exception as e:
        logger.warning("set_loaded_message_pg failed: %s", e)
        return False


def save_loaded_message(userbot_message_id: int, file_type: str, caption: str):
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO loaded_message (id, userbot_message_id, file_type, caption, updated_at)
            VALUES (1, %s, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE
                SET userbot_message_id = EXCLUDED.userbot_message_id,
                    file_type          = EXCLUDED.file_type,
                    caption            = EXCLUDED.caption,
                    updated_at         = NOW()
        """, (userbot_message_id, file_type, caption))
        conn.commit()
        cur.close()
        conn.close()
        logger.info("save_loaded_message: OK (msg_id=%s)", userbot_message_id)
    except Exception as e:
        logger.warning("save_loaded_message failed: %s", e)


def get_loaded_message():
    """Returns (userbot_message_id, file_type, caption) or None"""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT userbot_message_id, file_type, caption
            FROM loaded_message
            WHERE id = 1
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None or row[0] is None:
            return None
        return (int(row[0]), row[1] or "photo", row[2] or "")
    except Exception as e:
        logger.warning("get_loaded_message failed: %s", e)
        return None


# ─────────────────────────────────────────────
# campaign_config 테이블
# ─────────────────────────────────────────────

_SUBSCRIBE_BOT_LINK_DEFAULT = "t.me/blackdog_eve_casino_bot"


def ensure_campaign_config_table():
    """campaign_config 테이블 생성 + 기본 행(id=1) 보장."""
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS campaign_config (
                id                 INTEGER PRIMARY KEY DEFAULT 1,
                affiliate_url      TEXT NOT NULL DEFAULT '',
                promo_code         TEXT NOT NULL DEFAULT '',
                caption_template   TEXT NOT NULL DEFAULT '',
                subscribe_bot_link TEXT NOT NULL DEFAULT 't.me/blackdog_eve_casino_bot',
                updated_at         TIMESTAMPTZ DEFAULT NOW(),
                CHECK (id = 1)
            )
        """)
        cur.execute("""
            INSERT INTO campaign_config (id) VALUES (1)
            ON CONFLICT (id) DO NOTHING
        """)
        conn.commit()
        # 기존 테이블에 subscribe_bot_link 컬럼 없으면 추가
        try:
            cur.execute(
                "ALTER TABLE campaign_config ADD COLUMN subscribe_bot_link "
                "TEXT NOT NULL DEFAULT 't.me/blackdog_eve_casino_bot'"
            )
            conn.commit()
        except Exception:
            conn.rollback()
        cur.close()
        conn.close()
        logger.info("ensure_campaign_config_table: OK")
    except Exception as e:
        logger.warning("ensure_campaign_config_table failed: %s", e)


def get_campaign_config() -> dict:
    """campaign_config 설정을 dict로 반환.
    실패 시 빈 값 dict 반환 (호출부에서 환경변수 폴백 사용).
    """
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT affiliate_url, promo_code, caption_template, subscribe_bot_link, updated_at
            FROM campaign_config WHERE id = 1
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {
                "affiliate_url":      row[0] or "",
                "promo_code":         row[1] or "",
                "caption_template":   row[2] or "",
                "subscribe_bot_link": row[3] or _SUBSCRIBE_BOT_LINK_DEFAULT,
                "updated_at":         row[4],
            }
    except Exception as e:
        logger.warning("get_campaign_config failed: %s", e)
    return {
        "affiliate_url": "", "promo_code": "", "caption_template": "",
        "subscribe_bot_link": _SUBSCRIBE_BOT_LINK_DEFAULT, "updated_at": None,
    }


def update_campaign_config(field: str, value: str) -> bool:
    """campaign_config의 단일 필드를 업데이트한다.

    허용 필드: affiliate_url, promo_code, caption_template, subscribe_bot_link
    SQL injection 방지: 허용 목록 검증 후 f-string 사용 (값은 파라미터 바인딩).
    """
    _ALLOWED = {"affiliate_url", "promo_code", "caption_template", "subscribe_bot_link"}
    if field not in _ALLOWED:
        logger.warning("update_campaign_config: 허용되지 않은 필드 %r", field)
        return False
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            f"UPDATE campaign_config SET {field} = %s, updated_at = NOW() WHERE id = 1",
            (value,),
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info("update_campaign_config: %s 업데이트 완료", field)
        return True
    except Exception as e:
        logger.warning("update_campaign_config failed (%s): %s", field, e)
        return False
