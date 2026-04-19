import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2
from psycopg2 import pool as pg_pool

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.logging_config import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ── Connection Pool ──────────────────────────────────────────────────────────
_pool: pg_pool.ThreadedConnectionPool | None = None


def _init_pool() -> None:
    """ThreadedConnectionPool 초기화. 앱 시작 시 1회 호출."""
    global _pool
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set — DB pool not initialized")
        return
    try:
        from app.config import settings
        _pool = pg_pool.ThreadedConnectionPool(
            minconn=settings.db_pool_min_conn,
            maxconn=settings.db_pool_max_conn,
            dsn=DATABASE_URL,
        )
        logger.info(
            "DB connection pool initialized (min=%d, max=%d)",
            settings.db_pool_min_conn,
            settings.db_pool_max_conn,
        )
    except Exception as e:
        logger.exception("Failed to initialize DB pool: %s", e)
        _pool = None


@contextmanager
def _get_conn():
    """Connection context manager — pool 사용, pool 미초기화 시 직접 연결 fallback."""
    if _pool and not _pool.closed:
        conn = _pool.getconn()
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            _pool.putconn(conn)
    else:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# Pool 초기화 즉시 실행
_init_pool()


# ─────────────────────────────────────────────
# broadcast_targets 테이블
# ─────────────────────────────────────────────

def ensure_pg_table():
    try:
        with _get_conn() as conn:
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
            logger.info("ensure_pg_table: OK")
    except Exception as e:
        logger.warning("ensure_pg_table failed: %s", e)


def save_broadcast_batch(users: list[tuple[int, str, str]]):
    """users: [(telegram_user_id, username, source), ...]"""
    if not users:
        return
    try:
        with _get_conn() as conn:
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
    except Exception as e:
        logger.warning("save_broadcast_batch failed: %s", e)


def get_unsent_users(limit: int = 500) -> list[tuple[int, str]]:
    """(telegram_user_id, username) 목록 반환"""
    try:
        with _get_conn() as conn:
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
            return rows
    except Exception as e:
        logger.warning("get_unsent_users failed: %s", e)
        return []


def count_unsent_with_username() -> int:
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM broadcast_targets
                WHERE is_sent = FALSE
                  AND username IS NOT NULL
                  AND username <> ''
            """)
            count = cur.fetchone()[0]
            cur.close()
            return count
    except Exception as e:
        logger.warning("count_unsent_with_username failed: %s", e)
        return 0


def count_total() -> int:
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM broadcast_targets")
            count = cur.fetchone()[0]
            cur.close()
            return count
    except Exception as e:
        logger.warning("count_total failed: %s", e)
        return 0


def mark_sent(user_ids: list[int]):
    if not user_ids:
        return
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE broadcast_targets
                SET is_sent = TRUE, sent_at = NOW()
                WHERE telegram_user_id = ANY(%s)
            """, (user_ids,))
            conn.commit()
            cur.close()
    except Exception as e:
        logger.warning("mark_sent failed: %s", e)


def generate_unique_ref(user_id: int) -> str:
    ts = int(datetime.now(timezone.utc).timestamp())
    return f"{user_id}_{ts}"


def mark_clicked(ref: str):
    try:
        with _get_conn() as conn:
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
        with _get_conn() as conn:
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
        with _get_conn() as conn:
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
            return rows
    except Exception as e:
        logger.warning("get_retry_targets failed: %s", e)
        return []


def mark_retry_sent(user_ids: list[int]):
    if not user_ids:
        return
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE broadcast_targets
                SET retry_sent = TRUE, retry_sent_at = NOW()
                WHERE telegram_user_id = ANY(%s)
            """, (user_ids,))
            conn.commit()
            cur.close()
    except Exception as e:
        logger.warning("mark_retry_sent failed: %s", e)


def purge_no_username() -> int:
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                DELETE FROM broadcast_targets
                WHERE username IS NULL OR username = ''
            """)
            count = cur.rowcount
            conn.commit()
            cur.close()
            return count
    except Exception as e:
        logger.warning("purge_no_username failed: %s", e)
        return 0


def get_count_added_on_date(target_date) -> int:
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM broadcast_targets
                WHERE DATE(added_at AT TIME ZONE 'UTC') = %s
            """, (target_date,))
            count = cur.fetchone()[0]
            cur.close()
            return count
    except Exception as e:
        logger.warning("get_count_added_on_date failed: %s", e)
        return 0


# ─────────────────────────────────────────────
# discovered_groups 테이블
# ─────────────────────────────────────────────

def ensure_discovered_groups_table():
    try:
        with _get_conn() as conn:
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
            logger.info("ensure_discovered_groups_table: OK")
    except Exception as e:
        logger.warning("ensure_discovered_groups_table failed: %s", e)


def save_discovered_group(
    group_id: int, username: str, title: str, member_count: int
) -> bool:
    """신규 그룹 저장. 이미 존재하면 False 반환."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO discovered_groups (group_id, username, title, member_count)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (group_id) DO NOTHING
            """, (group_id, username, title, member_count))
            inserted = cur.rowcount > 0
            conn.commit()
            cur.close()
            return inserted
    except Exception as e:
        logger.warning("save_discovered_group failed: %s", e)
        return False


def get_unscraped_groups(limit: int = 50) -> list[tuple[int, str, str]]:
    """scraped=FALSE, scrape_failed=FALSE 그룹 반환 (group_id, username, title)"""
    try:
        with _get_conn() as conn:
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
            return rows
    except Exception as e:
        logger.warning("get_unscraped_groups failed: %s", e)
        return []


def mark_group_scraped(group_id: int):
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE discovered_groups SET scraped=TRUE WHERE group_id=%s",
                (group_id,),
            )
            conn.commit()
            cur.close()
    except Exception as e:
        logger.warning("mark_group_scraped failed: %s", e)


def mark_group_scrape_failed(group_id: int):
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE discovered_groups SET scrape_failed=TRUE WHERE group_id=%s",
                (group_id,),
            )
            conn.commit()
            cur.close()
    except Exception as e:
        logger.warning("mark_group_scrape_failed failed: %s", e)


def truncate_discovered_groups() -> int:
    """discovered_groups 테이블 전체 삭제. 삭제된 행 수 반환."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM discovered_groups")
            deleted = cur.rowcount or 0
            conn.commit()
            cur.close()
            logger.info("truncate_discovered_groups: %d rows deleted", deleted)
            return deleted
    except Exception as e:
        logger.warning("truncate_discovered_groups failed: %s", e)
        return 0


def count_discovered_groups() -> dict:
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE scraped = FALSE AND scrape_failed = FALSE) AS pending
                FROM discovered_groups
            """)
            row = cur.fetchone()
            cur.close()
            return {"total": row[0] or 0, "pending": row[1] or 0}
    except Exception as e:
        logger.warning("count_discovered_groups failed: %s", e)
        return {"total": 0, "pending": 0}


def get_count_clicked_on_date(target_date) -> int:
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM broadcast_targets
                WHERE DATE(clicked_at AT TIME ZONE 'UTC') = %s
            """, (target_date,))
            count = cur.fetchone()[0]
            cur.close()
            return count
    except Exception as e:
        logger.warning("get_count_clicked_on_date failed: %s", e)
        return 0


def get_retry_sent_count() -> int:
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM broadcast_targets WHERE retry_sent = TRUE")
            count = cur.fetchone()[0]
            cur.close()
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
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT telegram_user_id FROM broadcast_targets
                WHERE source = 'subscribe_bot'
                ORDER BY added_at
            """)
            rows = cur.fetchall()
            cur.close()
            return [r[0] for r in rows]
    except Exception as e:
        logger.warning("get_subscribe_user_ids failed: %s", e)
        return []


def get_subscribe_users() -> list[tuple[int, str]]:
    """subscribe_bot source 구독자의 (telegram_user_id, username) 목록 반환."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT telegram_user_id, COALESCE(username, '') FROM broadcast_targets
                WHERE source = 'subscribe_bot'
                ORDER BY added_at
            """)
            rows = cur.fetchall()
            cur.close()
            return rows
    except Exception as e:
        logger.warning("get_subscribe_users failed: %s", e)
        return []


def count_subscribe_users() -> int:
    """subscribe_bot source 구독자 수 반환."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM broadcast_targets WHERE source = 'subscribe_bot'"
            )
            count = cur.fetchone()[0]
            cur.close()
            return count
    except Exception as e:
        logger.warning("count_subscribe_users failed: %s", e)
        return 0


# ─────────────────────────────────────────────
# campaign_posts 테이블
# ─────────────────────────────────────────────

def ensure_campaign_posts_table():
    """campaign_posts 테이블 생성."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS campaign_posts (
                    id                SERIAL PRIMARY KEY,
                    file_id           TEXT NOT NULL,
                    file_type         TEXT NOT NULL DEFAULT 'photo',
                    caption           TEXT NOT NULL DEFAULT '',
                    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
                    send_order        INTEGER NOT NULL DEFAULT 0,
                    last_sent_at      TIMESTAMPTZ,
                    created_at        TIMESTAMPTZ DEFAULT NOW(),
                    caption_entities  TEXT
                )
            """)
            conn.commit()
            try:
                cur.execute("ALTER TABLE campaign_posts ADD COLUMN caption_entities TEXT")
                conn.commit()
            except Exception:
                conn.rollback()
            cur.close()
            logger.info("ensure_campaign_posts_table: OK")
    except Exception as e:
        logger.warning("ensure_campaign_posts_table failed: %s", e)


def get_next_post() -> dict | None:
    """순환 발송용: 활성 게시물 중 last_sent_at이 가장 오래된 것 반환 + last_sent_at 갱신."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, file_id, file_type, caption, is_active, send_order,
                       last_sent_at, caption_entities
                FROM campaign_posts
                WHERE is_active = TRUE
                ORDER BY COALESCE(last_sent_at, '1970-01-01'::timestamptz) ASC, send_order ASC
                LIMIT 1
            """)
            row = cur.fetchone()
            if not row:
                cur.close()
                return None
            post_id = row[0]
            cur.execute(
                "UPDATE campaign_posts SET last_sent_at = NOW() WHERE id = %s",
                (post_id,),
            )
            conn.commit()
            cur.close()
            return {
                "id": row[0], "file_id": row[1], "file_type": row[2],
                "caption": row[3], "is_active": row[4],
                "send_order": row[5], "last_sent_at": row[6],
                "caption_entities": row[7],
            }
    except Exception as e:
        logger.warning("get_next_post failed: %s", e)
        return None


def get_current_post() -> dict | None:
    """/start 환영 메시지 등 비소모성 조회용 (last_sent_at 변경 없음)."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, file_id, file_type, caption, is_active, send_order,
                       last_sent_at, caption_entities
                FROM campaign_posts
                WHERE is_active = TRUE
                ORDER BY COALESCE(last_sent_at, '1970-01-01'::timestamptz) ASC, send_order ASC
                LIMIT 1
            """)
            row = cur.fetchone()
            cur.close()
            if not row:
                return None
            return {
                "id": row[0], "file_id": row[1], "file_type": row[2],
                "caption": row[3], "is_active": row[4],
                "send_order": row[5], "last_sent_at": row[6],
                "caption_entities": row[7],
            }
    except Exception as e:
        logger.warning("get_current_post failed: %s", e)
        return None


def add_post(
    file_id: str,
    file_type: str,
    caption: str,
    send_order: int = 0,
    caption_entities: str | None = None,
) -> int | None:
    """게시물 추가. 삽입된 id 반환. 실패 시 None."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO campaign_posts (file_id, file_type, caption, send_order, caption_entities)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (file_id, file_type, caption, send_order, caption_entities))
            row = cur.fetchone()
            conn.commit()
            cur.close()
            return row[0] if row else None
    except Exception as e:
        logger.warning("add_post failed: %s", e)
        return None


def delete_post(post_id: int) -> bool:
    """게시물 삭제. 성공 True."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM campaign_posts WHERE id = %s", (post_id,))
            deleted = cur.rowcount > 0
            conn.commit()
            cur.close()
            return deleted
    except Exception as e:
        logger.warning("delete_post failed: %s", e)
        return False


def list_posts() -> list[dict]:
    """전체 게시물 목록 반환 (send_order, created_at 순)."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, file_id, file_type, caption, is_active, send_order, last_sent_at, created_at
                FROM campaign_posts
                ORDER BY send_order ASC, created_at ASC
            """)
            rows = cur.fetchall()
            cur.close()
            return [
                {
                    "id": r[0], "file_id": r[1], "file_type": r[2],
                    "caption": r[3], "is_active": r[4], "send_order": r[5],
                    "last_sent_at": r[6], "created_at": r[7],
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("list_posts failed: %s", e)
        return []


# ─────────────────────────────────────────────
# campaign_config 테이블
# ─────────────────────────────────────────────

_SUBSCRIBE_BOT_LINK_DEFAULT = "t.me/blackdog_eve_casino_bot"


def ensure_campaign_config_table():
    """campaign_config 테이블 생성 + 기본 행(id=1) 보장."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS campaign_config (
                    id                 INTEGER PRIMARY KEY DEFAULT 1,
                    affiliate_url      TEXT NOT NULL DEFAULT '',
                    promo_code         TEXT NOT NULL DEFAULT '',
                    caption_template   TEXT NOT NULL DEFAULT '',
                    subscribe_bot_link TEXT NOT NULL DEFAULT 't.me/blackdog_eve_casino_bot',
                    button_text        TEXT NOT NULL DEFAULT '🎰 VIP 카지노 입장',
                    updated_at         TIMESTAMPTZ DEFAULT NOW(),
                    CHECK (id = 1)
                )
            """)
            cur.execute("""
                INSERT INTO campaign_config (id) VALUES (1)
                ON CONFLICT (id) DO NOTHING
            """)
            conn.commit()
            # 기존 테이블에 누락된 컬럼 추가
            for col_def in [
                ("subscribe_bot_link", "TEXT NOT NULL DEFAULT 't.me/blackdog_eve_casino_bot'"),
                ("button_text",        "TEXT NOT NULL DEFAULT '🎰 VIP 카지노 입장'"),
            ]:
                try:
                    cur.execute(
                        f"ALTER TABLE campaign_config ADD COLUMN {col_def[0]} {col_def[1]}"
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
            cur.close()
            logger.info("ensure_campaign_config_table: OK")
    except Exception as e:
        logger.warning("ensure_campaign_config_table failed: %s", e)


def get_campaign_config() -> dict:
    """campaign_config 설정을 dict로 반환.
    실패 시 빈 값 dict 반환 (호출부에서 환경변수 폴백 사용).
    """
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT affiliate_url, promo_code, caption_template, subscribe_bot_link,
                       button_text, updated_at
                FROM campaign_config WHERE id = 1
            """)
            row = cur.fetchone()
            cur.close()
            if row:
                return {
                    "affiliate_url":      row[0] or "",
                    "promo_code":         row[1] or "",
                    "caption_template":   row[2] or "",
                    "subscribe_bot_link": row[3] or _SUBSCRIBE_BOT_LINK_DEFAULT,
                    "button_text":        row[4] or "🎰 VIP 카지노 입장",
                    "updated_at":         row[5],
                }
    except Exception as e:
        logger.warning("get_campaign_config failed: %s", e)
    return {
        "affiliate_url": "", "promo_code": "", "caption_template": "",
        "subscribe_bot_link": _SUBSCRIBE_BOT_LINK_DEFAULT,
        "button_text": "🎰 VIP 카지노 입장", "updated_at": None,
    }


def update_campaign_config(field: str, value: str) -> bool:
    """campaign_config의 단일 필드를 업데이트한다.

    허용 필드: affiliate_url, promo_code, caption_template, subscribe_bot_link
    SQL injection 방지: 허용 목록 검증 후 f-string 사용 (값은 파라미터 바인딩).
    """
    _ALLOWED = {"affiliate_url", "button_text"}
    if field not in _ALLOWED:
        logger.warning("update_campaign_config: 허용되지 않은 필드 %r", field)
        return False
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE campaign_config SET {field} = %s, updated_at = NOW() WHERE id = 1",
                (value,),
            )
            conn.commit()
            cur.close()
            logger.info("update_campaign_config: %s 업데이트 완료", field)
            return True
    except Exception as e:
        logger.warning("update_campaign_config failed (%s): %s", field, e)
        return False
