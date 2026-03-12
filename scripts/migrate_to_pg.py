#!/usr/bin/env python3
"""
Migrate local SQLite data into PostgreSQL broadcast_targets table.

Reads from:
  - automation/data/posts.db   → competitor_users table (telegram_user_id, username)
  - bot/data/users.db          → users table (user_id as telegram_user_id, username)

Inserts into PostgreSQL broadcast_targets (ON CONFLICT DO NOTHING, so safe to re-run).

Usage:
  # Set DATABASE_URL first:
  set DATABASE_URL=postgresql://user:pass@host:5432/dbname   (Windows)
  export DATABASE_URL=postgresql://user:pass@host:5432/dbname (Mac/Linux)

  pip install psycopg2-binary
  python scripts/migrate_to_pg.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POSTS_DB = REPO_ROOT / "automation" / "data" / "posts.db"
USERS_DB  = REPO_ROOT / "bot" / "data" / "users.db"


def _pg_connect():
    try:
        import psycopg2
    except ImportError:
        print("psycopg2-binary is required. Run: pip install psycopg2-binary")
        sys.exit(1)
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        print("DATABASE_URL environment variable is not set.")
        sys.exit(1)
    return psycopg2.connect(url)


def ensure_table(conn) -> None:
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
    print("✅ broadcast_targets table ready")


def migrate_competitor_users(conn) -> int:
    if not POSTS_DB.is_file():
        print(f"⚠️  posts.db not found: {POSTS_DB} — skipping competitor_users")
        return 0
    src = sqlite3.connect(str(POSTS_DB))
    src.text_factory = lambda b: b.decode("utf-8", errors="ignore")
    try:
        cur = src.execute(
            "SELECT DISTINCT telegram_user_id, username FROM competitor_users WHERE telegram_user_id IS NOT NULL"
        )
        rows = cur.fetchall()
    except Exception as e:
        print(f"⚠️  competitor_users read failed: {e}")
        src.close()
        return 0
    src.close()

    if not rows:
        print("competitor_users: 0 rows found")
        return 0

    inserted = 0
    total_rows = len(rows)
    print(f"competitor_users: 총 {total_rows}명 처리 시작...", flush=True)
    with conn:
        with conn.cursor() as cur:
            for i, (uid, username) in enumerate(rows, start=1):
                try:
                    cur.execute("""
                        INSERT INTO broadcast_targets (telegram_user_id, username, source)
                        VALUES (%s, %s, 'scraper')
                        ON CONFLICT (telegram_user_id) DO NOTHING
                    """, (int(uid), username or ""))
                    inserted += cur.rowcount
                except Exception:
                    pass
                if i % 500 == 0:
                    print(f"✅ [진행 상황] {i}명 마이그레이션 완료... (전체 {total_rows}명 중)", flush=True)
    print(f"competitor_users → broadcast_targets: {total_rows}명 읽음, {inserted}명 신규 삽입 (나머지는 이미 존재)", flush=True)
    return inserted


def migrate_bot_users(conn) -> int:
    if not USERS_DB.is_file():
        print(f"⚠️  users.db not found: {USERS_DB} — skipping bot users")
        return 0
    src = sqlite3.connect(str(USERS_DB))
    src.text_factory = lambda b: b.decode("utf-8", errors="ignore")
    try:
        cur = src.execute("SELECT user_id, username FROM users WHERE user_id IS NOT NULL")
        rows = cur.fetchall()
    except Exception as e:
        print(f"⚠️  users read failed: {e}")
        src.close()
        return 0
    src.close()

    if not rows:
        print("bot users: 0 rows found")
        return 0

    inserted = 0
    total_rows = len(rows)
    print(f"bot users: 총 {total_rows}명 처리 시작...", flush=True)
    with conn:
        with conn.cursor() as cur:
            for i, (uid, username) in enumerate(rows, start=1):
                try:
                    cur.execute("""
                        INSERT INTO broadcast_targets (telegram_user_id, username, source)
                        VALUES (%s, %s, 'bot')
                        ON CONFLICT (telegram_user_id) DO NOTHING
                    """, (int(uid), username or ""))
                    inserted += cur.rowcount
                except Exception:
                    pass
                if i % 500 == 0:
                    print(f"✅ [진행 상황] {i}명 마이그레이션 완료... (전체 {total_rows}명 중)", flush=True)
    print(f"bot users → broadcast_targets: {total_rows}명 읽음, {inserted}명 신규 삽입 (나머지는 이미 존재)", flush=True)
    return inserted


def main() -> None:
    print("=== migrate_to_pg.py ===")
    print(f"posts.db : {POSTS_DB}")
    print(f"users.db : {USERS_DB}")

    conn = _pg_connect()
    ensure_table(conn)

    total = 0
    total += migrate_competitor_users(conn)
    total += migrate_bot_users(conn)

    # Print final counts
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM broadcast_targets")
        pg_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM broadcast_targets WHERE is_sent = FALSE")
        pg_unsent = cur.fetchone()[0]
    conn.close()

    print(f"\n🎉 Migration complete. New rows this run: {total}")
    print(f"   PostgreSQL broadcast_targets total : {pg_total}")
    print(f"   Unsent (is_sent=FALSE)             : {pg_unsent}")


if __name__ == "__main__":
    main()
