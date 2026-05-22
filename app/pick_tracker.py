"""
Pick Tracker: record sports picks and measure accuracy over time.

DB table: pick_history
- Records every pick recommendation made by the AI
- When a match result is posted, auto-calculates hit/miss
- Exposes monthly accuracy % and current win streak for display in posts
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.logging_config import get_logger

logger = get_logger("pick_tracker")

# Pick result constants
PICK_HOME = "home"
PICK_DRAW = "draw"
PICK_AWAY = "away"


def ensure_pick_history_table() -> None:
    """Create pick_history table if not exists (idempotent)."""
    from app.pg_broadcast import _get_conn
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pick_history (
                    id              SERIAL PRIMARY KEY,
                    match_id        INTEGER,
                    home_team       TEXT NOT NULL,
                    away_team       TEXT NOT NULL,
                    league_id       INTEGER,
                    pick            TEXT NOT NULL,
                    stars           INTEGER DEFAULT 3,
                    actual_result   TEXT,
                    is_correct      BOOLEAN,
                    match_date      TIMESTAMPTZ,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pick_history_match_id ON pick_history (match_id)")
            # Unique constraint so ON CONFLICT DO NOTHING actually deduplicates by match_id
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pick_history_unique_match ON pick_history (match_id)")
            conn.commit()
            cur.close()
            logger.info("pick_history table ready")
    except Exception as e:
        logger.warning("ensure_pick_history_table failed: %s", e)


def record_pick(
    match_id: int,
    home_team: str,
    away_team: str,
    league_id: int,
    pick: str,
    stars: int = 3,
    match_date: datetime | None = None,
) -> int | None:
    """Record a new pick recommendation. Returns inserted row id."""
    from app.pg_broadcast import _get_conn
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO pick_history
                    (match_id, home_team, away_team, league_id, pick, stars, match_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
            """, (match_id, home_team, away_team, league_id, pick, stars, match_date))
            row = cur.fetchone()
            conn.commit()
            cur.close()
            return row[0] if row else None
    except Exception as e:
        logger.warning("record_pick failed: %s", e)
        return None


def record_result(match_id: int, home_score: int, away_score: int) -> None:
    """Update pick_history with actual match result and calculate correctness."""
    from app.pg_broadcast import _get_conn
    if home_score > away_score:
        actual = PICK_HOME
    elif home_score < away_score:
        actual = PICK_AWAY
    else:
        actual = PICK_DRAW

    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE pick_history
                SET actual_result = %s,
                    is_correct = (pick = %s)
                WHERE match_id = %s AND actual_result IS NULL
            """, (actual, actual, match_id))
            conn.commit()
            cur.close()
            logger.info("Pick result recorded: match_id=%d → %s", match_id, actual)
    except Exception as e:
        logger.warning("record_result failed: %s", e)


def get_monthly_accuracy() -> dict[str, Any]:
    """Return this month's pick accuracy stats."""
    from app.pg_broadcast import _get_conn
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE is_correct IS NOT NULL) AS total,
                    COUNT(*) FILTER (WHERE is_correct = TRUE)      AS correct
                FROM pick_history
                WHERE created_at >= DATE_TRUNC('month', NOW())
                  AND is_correct IS NOT NULL
            """)
            row = cur.fetchone()
            cur.close()
            total, correct = (row[0] or 0), (row[1] or 0)
            pct = round(correct / total * 100) if total else 0
            return {"total": total, "correct": correct, "pct": pct}
    except Exception as e:
        logger.warning("get_monthly_accuracy failed: %s", e)
        return {"total": 0, "correct": 0, "pct": 0}


def get_current_streak() -> int:
    """Return current consecutive win (+) or loss (-) streak."""
    from app.pg_broadcast import _get_conn
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT is_correct FROM pick_history
                WHERE is_correct IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 20
            """)
            rows = [r[0] for r in cur.fetchall()]
            cur.close()

        if not rows:
            return 0
        streak, first = 0, rows[0]
        for r in rows:
            if r == first:
                streak += 1
            else:
                break
        return streak if first else -streak
    except Exception as e:
        logger.warning("get_current_streak failed: %s", e)
        return 0


def format_accuracy_line() -> str:
    """Format a one-line accuracy summary for post footers."""
    acc = get_monthly_accuracy()
    streak = get_current_streak()

    if acc["total"] == 0:
        return ""

    streak_str = ""
    if streak >= 3:
        streak_str = f" | 🔥 {streak}연속 적중"
    elif streak <= -3:
        streak_str = f" | 😓 {abs(streak)}연속 미적중"

    return f"📊 이번 달 적중률 {acc['pct']}% ({acc['correct']}/{acc['total']}){streak_str}"
