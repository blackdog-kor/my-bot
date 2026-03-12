"""
공유 DB(posts.db) 접근. competitor_users 등 읽기 전용 이터레이터.
Railway 환경변수 POSTS_DB_PATH 로 경로 지정 (미설정 시 bot/data/posts.db).
"""
import os
import sqlite3
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _ROOT / "data" / "posts.db"
DB_PATH = os.getenv("POSTS_DB_PATH", str(_DEFAULT_DB))


def _connect():
    return sqlite3.connect(DB_PATH)


def iter_competitor_telegram_user_ids(chunk_size: int = 500):
    """
    competitor_users 테이블에서 telegram_user_id를 청크 단위로 yield.
    메모리 최적화: fetchmany(chunk_size)만 사용.
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT telegram_user_id FROM competitor_users ORDER BY id"
        )
        while True:
            rows = cur.fetchmany(chunk_size)
            if not rows:
                break
            yield [row[0] for row in rows]
    finally:
        conn.close()
