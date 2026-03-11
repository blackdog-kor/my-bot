import os
import json
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "posts.db")

REQUIRED_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "source": "TEXT NOT NULL DEFAULT 'manual'",
    "language": "TEXT NOT NULL DEFAULT '한국어'",
    "title": "TEXT NOT NULL DEFAULT ''",
    "body": "TEXT NOT NULL DEFAULT ''",
    "cta_link": "TEXT NOT NULL DEFAULT ''",
    "status": "TEXT NOT NULL DEFAULT 'draft'",
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "media_type": "TEXT NOT NULL DEFAULT 'text'",
    "media_path": "TEXT NOT NULL DEFAULT ''",
    "thumbnail_path": "TEXT NOT NULL DEFAULT ''",
    "platform_meta_json": "TEXT NOT NULL DEFAULT '{}'",
}

VIDEO_JOB_COLUMNS = {
    "job_id": "TEXT PRIMARY KEY",
    "post_id": "INTEGER NOT NULL",
    "engine": "TEXT NOT NULL DEFAULT 'external'",
    "status": "TEXT NOT NULL DEFAULT 'queued'",
    "payload_json": "TEXT NOT NULL DEFAULT '{}'",
    "result_video_path": "TEXT NOT NULL DEFAULT ''",
    "result_thumb_path": "TEXT NOT NULL DEFAULT ''",
    "error_message": "TEXT NOT NULL DEFAULT ''",
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "completed_at": "TEXT NOT NULL DEFAULT ''",
}

CAMPAIGN_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "name": "TEXT NOT NULL DEFAULT ''",
    "keyword": "TEXT NOT NULL DEFAULT ''",
    "engine": "TEXT NOT NULL DEFAULT 'runway'",
    "post_count": "INTEGER NOT NULL DEFAULT 1",
    "status": "TEXT NOT NULL DEFAULT 'draft'",
    "language": "TEXT NOT NULL DEFAULT '한국어'",
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "meta_json": "TEXT NOT NULL DEFAULT '{}'",
}

CAMPAIGN_POST_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "campaign_id": "INTEGER NOT NULL",
    "post_id": "INTEGER NOT NULL",
    "job_id": "TEXT NOT NULL DEFAULT ''",
    "created_at": "TEXT NOT NULL DEFAULT ''",
}

USER_COLUMNS = {
    "user_id": "INTEGER PRIMARY KEY",
    "username": "TEXT NOT NULL DEFAULT ''",
    "join_time": "TEXT NOT NULL DEFAULT ''",
    "source": "TEXT NOT NULL DEFAULT 'direct'",
    "campaign": "TEXT NOT NULL DEFAULT ''",
    "promo_code": "TEXT NOT NULL DEFAULT ''",
    "game_category": "TEXT NOT NULL DEFAULT 'unknown'",
    "last_seen": "TEXT NOT NULL DEFAULT ''",
    "offer_name": "TEXT NOT NULL DEFAULT ''",
}

ENTRY_EVENT_COLUMNS = {
    "event_id": "TEXT PRIMARY KEY",
    "telegram_user_id": "INTEGER NOT NULL",
    "received_at": "TEXT NOT NULL DEFAULT ''",
}

PROMO_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "source": "TEXT NOT NULL DEFAULT ''",
    "title": "TEXT NOT NULL DEFAULT ''",
    "bonus_percent": "INTEGER NOT NULL DEFAULT 0",
    "raw_snippet": "TEXT NOT NULL DEFAULT ''",
    "scraped_at": "TEXT NOT NULL DEFAULT ''",
}

SITE_DATA_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "url": "TEXT NOT NULL DEFAULT ''",
    "source": "TEXT NOT NULL DEFAULT ''",
    "markdown": "TEXT NOT NULL DEFAULT ''",
    "meta_json": "TEXT NOT NULL DEFAULT '{}'",
    "scraped_at": "TEXT NOT NULL DEFAULT ''",
}

COMPETITOR_USER_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "source": "TEXT NOT NULL DEFAULT ''",
    "group_url": "TEXT NOT NULL DEFAULT ''",
    "telegram_user_id": "INTEGER NOT NULL",
    "username": "TEXT NOT NULL DEFAULT ''",
    "last_seen": "TEXT NOT NULL DEFAULT ''",
    "scraped_at": "TEXT NOT NULL DEFAULT ''",
}


def _connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def ensure_db() -> None:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        )
        """
    )

    cur.execute("PRAGMA table_info(posts)")
    existing = {row[1] for row in cur.fetchall()}

    for column_name, column_type in REQUIRED_COLUMNS.items():
        if column_name not in existing:
            cur.execute(f"ALTER TABLE posts ADD COLUMN {column_name} {column_type}")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS video_jobs (
            job_id TEXT PRIMARY KEY
        )
        """
    )

    cur.execute("PRAGMA table_info(video_jobs)")
    existing_video_jobs = {row[1] for row in cur.fetchall()}

    for column_name, column_type in VIDEO_JOB_COLUMNS.items():
        if column_name not in existing_video_jobs:
            cur.execute(f"ALTER TABLE video_jobs ADD COLUMN {column_name} {column_type}")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        )
        """
    )

    cur.execute("PRAGMA table_info(campaigns)")
    existing_campaigns = {row[1] for row in cur.fetchall()}

    for column_name, column_type in CAMPAIGN_COLUMNS.items():
        if column_name not in existing_campaigns:
            cur.execute(f"ALTER TABLE campaigns ADD COLUMN {column_name} {column_type}")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS campaign_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        )
        """
    )

    cur.execute("PRAGMA table_info(campaign_posts)")
    existing_campaign_posts = {row[1] for row in cur.fetchall()}

    for column_name, column_type in CAMPAIGN_POST_COLUMNS.items():
        if column_name not in existing_campaign_posts:
            cur.execute(f"ALTER TABLE campaign_posts ADD COLUMN {column_name} {column_type}")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )
        """
    )

    cur.execute("PRAGMA table_info(users)")
    existing_users = {row[1] for row in cur.fetchall()}

    for column_name, column_type in USER_COLUMNS.items():
        if column_name not in existing_users:
            cur.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS entry_events (
            event_id TEXT PRIMARY KEY
        )
        """
    )

    cur.execute("PRAGMA table_info(entry_events)")
    existing_entry_events = {row[1] for row in cur.fetchall()}

    for column_name, column_type in ENTRY_EVENT_COLUMNS.items():
        if column_name not in existing_entry_events:
            cur.execute(f"ALTER TABLE entry_events ADD COLUMN {column_name} {column_type}")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS promotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        )
        """
    )

    cur.execute("PRAGMA table_info(promotions)")
    existing_promos = {row[1] for row in cur.fetchall()}

    for column_name, column_type in PROMO_COLUMNS.items():
        if column_name not in existing_promos:
            cur.execute(f"ALTER TABLE promotions ADD COLUMN {column_name} {column_type}")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS site_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        )
        """
    )

    cur.execute("PRAGMA table_info(site_data)")
    existing_site_data = {row[1] for row in cur.fetchall()}

    for column_name, column_type in SITE_DATA_COLUMNS.items():
        if column_name not in existing_site_data:
            cur.execute(f"ALTER TABLE site_data ADD COLUMN {column_name} {column_type}")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS competitor_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        )
        """
    )

    cur.execute("PRAGMA table_info(competitor_users)")
    existing_competitor_users = {row[1] for row in cur.fetchall()}

    for column_name, column_type in COMPETITOR_USER_COLUMNS.items():
        if column_name not in existing_competitor_users:
            cur.execute(f"ALTER TABLE competitor_users ADD COLUMN {column_name} {column_type}")

    conn.commit()
    conn.close()


def create_post(
    source: str,
    language: str,
    title: str,
    body: str,
    cta_link: str,
    media_type: str = "text",
    media_path: str = "",
    thumbnail_path: str = "",
    platform_meta_json: str = "{}",
) -> int:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO posts (
            source, language, title, body, cta_link, status, created_at,
            media_type, media_path, thumbnail_path, platform_meta_json
        )
        VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?)
        """,
        (
            source,
            language,
            title,
            body,
            cta_link,
            datetime.utcnow().isoformat(),
            media_type,
            media_path,
            thumbnail_path,
            platform_meta_json,
        ),
    )

    post_id = cur.lastrowid
    conn.commit()
    conn.close()
    return post_id


def list_posts() -> list[tuple]:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, source, language, title, status, created_at, media_type
        FROM posts
        ORDER BY id DESC
        """
    )

    rows = cur.fetchall()
    conn.close()
    return rows


def get_post(post_id: int) -> tuple | None:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id, source, language, title, body, cta_link, status, created_at,
            media_type, media_path, thumbnail_path, platform_meta_json
        FROM posts
        WHERE id = ?
        """,
        (post_id,),
    )

    row = cur.fetchone()
    conn.close()
    return row


def update_post_status(post_id: int, status: str) -> None:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE posts
        SET status = ?
        WHERE id = ?
        """,
        (status, post_id),
    )

    conn.commit()
    conn.close()


def delete_post(post_id: int) -> bool:
    conn = _connect()
    cur = conn.cursor()

    cur.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    deleted = cur.rowcount > 0

    conn.commit()
    conn.close()
    return deleted


def attach_media(post_id: int, media_type: str, media_path: str) -> bool:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE posts
        SET media_type = ?, media_path = ?
        WHERE id = ?
        """,
        (media_type, media_path, post_id),
    )

    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def attach_thumbnail(post_id: int, thumbnail_path: str) -> bool:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE posts
        SET thumbnail_path = ?
        WHERE id = ?
        """,
        (thumbnail_path, post_id),
    )

    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def update_platform_meta(post_id: int, platform_meta: dict) -> bool:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE posts
        SET platform_meta_json = ?
        WHERE id = ?
        """,
        (json.dumps(platform_meta, ensure_ascii=False), post_id),
    )

    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def create_video_job(post_id: int, engine: str, payload: dict) -> str:
    job_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO video_jobs (
            job_id, post_id, engine, status, payload_json,
            result_video_path, result_thumb_path, error_message,
            created_at, completed_at
        )
        VALUES (?, ?, ?, 'queued', ?, '', '', '', ?, '')
        """,
        (
            job_id,
            post_id,
            engine,
            json.dumps(payload, ensure_ascii=False),
            datetime.utcnow().isoformat(),
        ),
    )

    conn.commit()
    conn.close()
    return job_id


def get_video_job(job_id: str) -> tuple | None:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            job_id, post_id, engine, status, payload_json,
            result_video_path, result_thumb_path, error_message,
            created_at, completed_at
        FROM video_jobs
        WHERE job_id = ?
        """,
        (job_id,),
    )

    row = cur.fetchone()
    conn.close()
    return row


def list_video_jobs() -> list[tuple]:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT job_id, post_id, engine, status, created_at, completed_at
        FROM video_jobs
        ORDER BY created_at DESC
        """
    )

    rows = cur.fetchall()
    conn.close()
    return rows


def update_video_job_status(
    job_id: str,
    status: str,
    result_video_path: str = "",
    result_thumb_path: str = "",
    error_message: str = "",
) -> bool:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE video_jobs
        SET status = ?,
            result_video_path = ?,
            result_thumb_path = ?,
            error_message = ?,
            completed_at = ?
        WHERE job_id = ?
        """,
        (
            status,
            result_video_path,
            result_thumb_path,
            error_message,
            datetime.utcnow().isoformat() if status in {"completed", "failed"} else "",
            job_id,
        ),
    )

    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def create_campaign(
    name: str,
    keyword: str,
    engine: str,
    post_count: int,
    language: str,
    meta: dict | None = None,
) -> int:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO campaigns (
            name, keyword, engine, post_count, status, language, created_at, meta_json
        )
        VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)
        """,
        (
            name,
            keyword,
            engine,
            post_count,
            language,
            datetime.utcnow().isoformat(),
            json.dumps(meta or {}, ensure_ascii=False),
        ),
    )

    campaign_id = cur.lastrowid
    conn.commit()
    conn.close()
    return campaign_id


def list_campaigns() -> list[tuple]:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, name, keyword, engine, post_count, status, language, created_at
        FROM campaigns
        ORDER BY id DESC
        """
    )

    rows = cur.fetchall()
    conn.close()
    return rows


def get_campaign(campaign_id: int) -> tuple | None:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id, name, keyword, engine, post_count, status, language, created_at, meta_json
        FROM campaigns
        WHERE id = ?
        """,
        (campaign_id,),
    )

    row = cur.fetchone()
    conn.close()
    return row


def update_campaign_status(campaign_id: int, status: str) -> bool:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE campaigns
        SET status = ?
        WHERE id = ?
        """,
        (status, campaign_id),
    )

    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def delete_campaign(campaign_id: int) -> bool:
    conn = _connect()
    cur = conn.cursor()

    cur.execute("DELETE FROM campaign_posts WHERE campaign_id = ?", (campaign_id,))
    cur.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
    deleted = cur.rowcount > 0

    conn.commit()
    conn.close()
    return deleted


def link_campaign_post(campaign_id: int, post_id: int, job_id: str = "") -> int:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO campaign_posts (campaign_id, post_id, job_id, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            campaign_id,
            post_id,
            job_id,
            datetime.utcnow().isoformat(),
        ),
    )

    link_id = cur.lastrowid
    conn.commit()
    conn.close()
    return link_id


def list_campaign_posts(campaign_id: int) -> list[tuple]:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, campaign_id, post_id, job_id, created_at
        FROM campaign_posts
        WHERE campaign_id = ?
        ORDER BY id ASC
        """,
        (campaign_id,),
    )

    rows = cur.fetchall()
    conn.close()
    return rows


def save_user(user_id: int, username: str, source: str = "direct") -> bool:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT OR IGNORE INTO users (user_id, username, join_time, source)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, username, datetime.utcnow().isoformat(), source),
    )

    inserted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return inserted


def get_user(user_id: int) -> tuple | None:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT user_id, username, join_time, source,
               campaign, promo_code, game_category, last_seen, offer_name
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    )

    row = cur.fetchone()
    conn.close()
    return row


def list_users() -> list[tuple]:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT user_id, username, join_time, source
        FROM users
        ORDER BY join_time DESC
        """
    )

    rows = cur.fetchall()
    conn.close()
    return rows


def count_users() -> int:
    conn = _connect()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    conn.close()
    return count


def upsert_user_entry(
    telegram_user_id: int,
    username: str,
    source: str,
    campaign: str,
    promo_code: str,
    game_category: str,
    offer_name: str,
) -> tuple[bool, bool]:
    """Insert or update a user from an entry-bot event.

    Returns (created, updated):
        created=True  – a new user record was inserted.
        updated=True  – an existing user record had its attribution refreshed.
        Both False    – only on idempotent replay (should not be reached here).
    """
    conn = _connect()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()

    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (telegram_user_id,))
    existing = cur.fetchone()

    if existing is None:
        cur.execute(
            """
            INSERT INTO users (
                user_id, username, join_time, source,
                campaign, promo_code, game_category, last_seen, offer_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_user_id,
                username,
                now,
                source,
                campaign,
                promo_code,
                game_category,
                now,
                offer_name,
            ),
        )
        conn.commit()
        conn.close()
        return True, False

    cur.execute(
        """
        UPDATE users
        SET username = ?,
            source = ?,
            campaign = ?,
            promo_code = ?,
            game_category = ?,
            last_seen = ?,
            offer_name = ?
        WHERE user_id = ?
        """,
        (
            username,
            source,
            campaign,
            promo_code,
            game_category,
            now,
            offer_name,
            telegram_user_id,
        ),
    )
    conn.commit()
    conn.close()
    return False, True


def has_entry_event(event_id: str) -> bool:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM entry_events WHERE event_id = ?", (event_id,))
    found = cur.fetchone() is not None
    conn.close()
    return found


def save_entry_event(event_id: str, telegram_user_id: int) -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO entry_events (event_id, telegram_user_id, received_at)
        VALUES (?, ?, ?)
        """,
        (event_id, telegram_user_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def save_site_snapshot(
    url: str,
    markdown: str,
    source: str = "",
    meta: dict | None = None,
) -> int:
    """
    Persist a raw site snapshot (Markdown) for later analysis.
    """
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO site_data (
            url, source, markdown, meta_json, scraped_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            url,
            source,
            markdown,
            json.dumps(meta or {}, ensure_ascii=False),
            datetime.utcnow().isoformat(),
        ),
    )

    site_id = cur.lastrowid
    conn.commit()
    conn.close()
    return site_id


def save_competitor_user(
    source: str,
    group_url: str,
    telegram_user_id: int,
    username: str,
    last_seen: str = "",
) -> int:
    """
    Save a single competitor user snapshot. We don't enforce uniqueness here,
    so repeated runs will simply append more rows (time-series style).
    """
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO competitor_users (
            source, group_url, telegram_user_id, username, last_seen, scraped_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            source,
            group_url,
            telegram_user_id,
            username or "",
            last_seen or "",
            datetime.utcnow().isoformat(),
        ),
    )

    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def count_competitor_users() -> int:
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM competitor_users")
    count = cur.fetchone()[0]
    conn.close()
    return int(count)


def save_promotion(
    source: str,
    title: str,
    bonus_percent: int = 0,
    raw_snippet: str = "",
) -> int:
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO promotions (
            source, title, bonus_percent, raw_snippet, scraped_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            source,
            title,
            int(bonus_percent or 0),
            raw_snippet,
            datetime.utcnow().isoformat(),
        ),
    )

    promo_id = cur.lastrowid
    conn.commit()
    conn.close()
    return promo_id
