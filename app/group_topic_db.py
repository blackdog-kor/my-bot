"""
Group Topic DB: 포럼 토픽 DB CRUD 레이어.

- forum_topics 테이블 관리
- 토픽 저장/조회/목록
"""
from __future__ import annotations

from typing import Any

from app.logging_config import get_logger
from app.pg_broadcast import _get_conn

logger = get_logger("group_topic_db")


def ensure_forum_topics_table() -> None:
    """forum_topics 테이블 생성."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS forum_topics (
                    id              SERIAL PRIMARY KEY,
                    thread_id       INTEGER NOT NULL UNIQUE,
                    name            TEXT NOT NULL,
                    content_type    TEXT NOT NULL,
                    icon_color      INTEGER DEFAULT 0,
                    description     TEXT DEFAULT '',
                    is_active       BOOLEAN DEFAULT TRUE,
                    auto_post       BOOLEAN DEFAULT TRUE,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            conn.commit()
            cur.close()
            logger.info("ensure_forum_topics_table: OK")
    except Exception as e:
        logger.warning("ensure_forum_topics_table failed: %s", e)


def save_topic(
    thread_id: int,
    name: str,
    content_type: str,
    icon_color: int = 0,
    description: str = "",
) -> int | None:
    """토픽 정보를 DB에 저장. 삽입된 id 반환."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO forum_topics (thread_id, name, content_type, icon_color, description)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (thread_id) DO NOTHING
                RETURNING id
            """, (thread_id, name, content_type, icon_color, description))
            row = cur.fetchone()
            conn.commit()
            cur.close()
            return row[0] if row else None
    except Exception as e:
        logger.warning("save_topic failed: %s", e)
        return None


def get_topic_by_content_type(content_type: str) -> dict | None:
    """content_type으로 토픽 조회."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, thread_id, name, content_type, icon_color, description, is_active
                FROM forum_topics
                WHERE content_type = %s AND is_active = TRUE
                LIMIT 1
            """, (content_type,))
            row = cur.fetchone()
            cur.close()
            if row:
                return {
                    "id": row[0], "thread_id": row[1], "name": row[2],
                    "content_type": row[3], "icon_color": row[4],
                    "description": row[5], "is_active": row[6],
                }
    except Exception as e:
        logger.warning("get_topic_by_content_type failed: %s", e)
    return None


def list_topics() -> list[dict]:
    """전체 토픽 목록 조회."""
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, thread_id, name, content_type, icon_color,
                       description, is_active, auto_post
                FROM forum_topics
                ORDER BY id ASC
            """)
            rows = cur.fetchall()
            cur.close()
            return [
                {
                    "id": r[0], "thread_id": r[1], "name": r[2],
                    "content_type": r[3], "icon_color": r[4],
                    "description": r[5], "is_active": r[6], "auto_post": r[7],
                }
                for r in rows
            ]
    except Exception as e:
        logger.warning("list_topics failed: %s", e)
        return []
