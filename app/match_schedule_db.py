"""
Match Schedule DB: persist upcoming matches and track preview/review posting status.

Table: match_schedule
Status flow: pending_preview → previewed → reviewed | skipped
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.logging_config import get_logger

logger = get_logger("match_schedule_db")


def ensure_match_schedule_table() -> None:
    """Create match_schedule table (idempotent)."""
    from app.pg_broadcast import _get_conn
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS match_schedule (
                    id                  SERIAL PRIMARY KEY,
                    match_id            INTEGER UNIQUE NOT NULL,
                    league_id           INTEGER NOT NULL,
                    home_team           TEXT NOT NULL,
                    away_team           TEXT NOT NULL,
                    league_name         TEXT,
                    kickoff_utc         TIMESTAMPTZ NOT NULL,
                    venue               TEXT,
                    round_name          TEXT,
                    status              TEXT NOT NULL DEFAULT 'pending_preview',
                    odds_json           TEXT,
                    preview_posted_at   TIMESTAMPTZ,
                    review_posted_at    TIMESTAMPTZ,
                    created_at          TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ms_status   ON match_schedule (status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ms_kickoff  ON match_schedule (kickoff_utc)")
            conn.commit()
            cur.close()
            logger.info("match_schedule table ready")
    except Exception as e:
        logger.warning("ensure_match_schedule_table failed: %s", e)


def upsert_match(
    match_id: int,
    league_id: int,
    home_team: str,
    away_team: str,
    kickoff_utc: datetime,
    league_name: str = "",
    venue: str = "",
    round_name: str = "",
    odds_dict: dict | None = None,
) -> bool:
    """Insert match or update odds if already exists. Returns True on success."""
    from app.pg_broadcast import _get_conn
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO match_schedule
                    (match_id, league_id, home_team, away_team, kickoff_utc,
                     league_name, venue, round_name, odds_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (match_id) DO UPDATE
                    SET odds_json = EXCLUDED.odds_json,
                        kickoff_utc = EXCLUDED.kickoff_utc
                    WHERE match_schedule.status = 'pending_preview'
            """, (
                match_id, league_id, home_team, away_team, kickoff_utc,
                league_name, venue, round_name,
                json.dumps(odds_dict) if odds_dict else None,
            ))
            conn.commit()
            cur.close()
            return True
    except Exception as e:
        logger.warning("upsert_match failed: %s", e)
        return False


def get_matches_needing_preview(hours_before: int = 3) -> list[dict[str, Any]]:
    """Return matches whose kickoff is within [1h, hours_before+1h] from now."""
    from app.pg_broadcast import _get_conn
    now = datetime.now(timezone.utc)
    window_start = now + timedelta(hours=1)
    window_end = now + timedelta(hours=hours_before + 1)
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT match_id, league_id, home_team, away_team, kickoff_utc,
                       league_name, venue, round_name, odds_json
                FROM match_schedule
                WHERE status = 'pending_preview'
                  AND kickoff_utc BETWEEN %s AND %s
                ORDER BY kickoff_utc ASC
            """, (window_start, window_end))
            rows = cur.fetchall()
            cur.close()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning("get_matches_needing_preview failed: %s", e)
        return []


def get_matches_needing_review(mins_after: int = 110) -> list[dict[str, Any]]:
    """Return matches that finished and haven't been reviewed yet."""
    from app.pg_broadcast import _get_conn
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=mins_after)
    # Only pick matches up to 6 hours ago (avoid stale reviews)
    oldest = now - timedelta(hours=6)
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT match_id, league_id, home_team, away_team, kickoff_utc,
                       league_name, venue, round_name, odds_json
                FROM match_schedule
                WHERE status = 'previewed'
                  AND kickoff_utc < %s
                  AND kickoff_utc > %s
                ORDER BY kickoff_utc ASC
            """, (cutoff, oldest))
            rows = cur.fetchall()
            cur.close()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning("get_matches_needing_review failed: %s", e)
        return []


def mark_previewed(match_id: int) -> None:
    _update_status(match_id, "previewed", "preview_posted_at")


def mark_reviewed(match_id: int) -> None:
    _update_status(match_id, "reviewed", "review_posted_at")


def mark_skipped(match_id: int) -> None:
    _update_status(match_id, "skipped")


def _update_status(match_id: int, status: str, ts_col: str | None = None) -> None:
    from app.pg_broadcast import _get_conn
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            if ts_col:
                cur.execute(
                    f"UPDATE match_schedule SET status=%s, {ts_col}=NOW() WHERE match_id=%s",
                    (status, match_id),
                )
            else:
                cur.execute("UPDATE match_schedule SET status=%s WHERE match_id=%s", (status, match_id))
            conn.commit()
            cur.close()
    except Exception as e:
        logger.warning("_update_status failed: %s", e)


def _row_to_dict(row: tuple) -> dict[str, Any]:
    odds_dict = None
    if row[8]:
        try:
            odds_dict = json.loads(row[8])
        except Exception:
            pass
    return {
        "match_id": row[0], "league_id": row[1],
        "home_team": row[2], "away_team": row[3],
        "kickoff_utc": row[4], "league_name": row[5] or "",
        "venue": row[6] or "", "round_name": row[7] or "",
        "odds_dict": odds_dict,
    }
