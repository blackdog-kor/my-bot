"""
Sports Periodic Content: weekly roundup, monthly report, standings update.

Separated from sports_content_generator to keep file size under 200 lines.
These post types run on a scheduled basis (not per-match).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.logging_config import get_logger
from app.sports_ai_client import generate_text
from app.sports_image_fetcher import fetch_sport_image
from app.sports_prompts import (
    MONTHLY_REPORT_PROMPT,
    STANDINGS_SYSTEM_PROMPT,
    TOP_SCORER_PROMPT,
    WEEKLY_ROUNDUP_PROMPT,
)
from app.sports_scraper import LEAGUE_EMOJI, LEAGUE_NAMES, Match, SportsData, TeamStanding

logger = get_logger("sports_periodic_content")

_DEFAULT_LEAGUE_ID = 39  # EPL — fallback league for image fetch when no data


def _cta_html(url: str) -> str:
    return f"👉 <a href='{url}'>스포츠 베팅 시작하기</a>" if url else ""


def _fmt_standings_block(standings: list[TeamStanding], league_name: str) -> str:
    """Format standings for AI prompt input."""
    lines = [f"League: {league_name}", f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"]
    for s in standings[:8]:
        lines.append(
            f"{s.rank}. {s.team_name} | P:{s.played} W:{s.wins} D:{s.draws} L:{s.losses} | "
            f"GF:{s.goals_for} GA:{s.goals_against} | Pts:{s.points} | Form:{s.form}"
        )
    return "\n".join(lines)


def _fmt_upcoming_for_roundup(sports_data: list[SportsData], days: int = 7) -> str:
    """Build fixture list text for the weekly roundup prompt."""
    cutoff = datetime.now(timezone.utc) + timedelta(days=days)
    lines: list[str] = []
    now = datetime.now(timezone.utc)

    for sd in sports_data:
        league_matches = [
            m for m in sd.upcoming
            if m.match_date and now <= m.match_date <= cutoff
        ]
        if not league_matches:
            continue
        league_matches.sort(key=lambda m: m.match_date or now)
        lines.append(f"League: {sd.league_name}")
        for m in league_matches[:4]:
            date_str = m.match_date.strftime("%m/%d %H:%M KST") if m.match_date else "TBD"
            lines.append(f"  {m.home_team} vs {m.away_team} | {date_str} | {m.venue or 'TBD'}")
        lines.append("")

    if not lines:
        return "No upcoming fixtures in the next 7 days."
    return "\n".join(lines)


async def generate_standings_post(
    standings: list[TeamStanding],
    league_id: int,
    cta_url: str = "",
) -> dict[str, Any] | None:
    """Generate a league standings update post."""
    league_name = LEAGUE_NAMES.get(league_id, f"League {league_id}")
    try:
        prompt_data = _fmt_standings_block(standings, league_name)
        text = await generate_text(STANDINGS_SYSTEM_PROMPT, prompt_data, _cta_html(cta_url))
        if not text:
            return None
        image_url = await fetch_sport_image(league_id=league_id, league_name=league_name)
        return {
            "text": text,
            "card_bytes": None,
            "image_url": image_url,
            "content_type": "sports_standings",
            "match_id": 0,
        }
    except Exception as e:
        logger.warning("generate_standings_post failed (league=%d): %s", league_id, e)
        return None


async def generate_weekly_roundup(
    sports_data: list[SportsData],
    cta_url: str = "",
) -> dict[str, Any] | None:
    """Generate a weekly fixture preview covering all leagues."""
    fixture_text = _fmt_upcoming_for_roundup(sports_data, days=7)
    if "No upcoming fixtures" in fixture_text:
        logger.info("Weekly roundup: no fixtures in next 7 days — skipping")
        return None

    now = datetime.now(timezone.utc)
    week_end = now + timedelta(days=7)
    date_range = f"{now.strftime('%m/%d')}~{week_end.strftime('%m/%d')}"

    user_prompt = (
        f"Generate a weekly fixture roundup for: {date_range}\n\n"
        f"Upcoming matches:\n{fixture_text}"
    )
    try:
        text = await generate_text(WEEKLY_ROUNDUP_PROMPT, user_prompt, _cta_html(cta_url))
        if not text:
            return None
        first_league = sports_data[0].league_id if sports_data else _DEFAULT_LEAGUE_ID
        image_url = await fetch_sport_image(league_id=first_league)
        return {
            "text": text,
            "card_bytes": None,
            "image_url": image_url,
            "content_type": "sports_weekly_roundup",
            "match_id": 0,
        }
    except Exception as e:
        logger.warning("generate_weekly_roundup failed: %s", e)
        return None


async def generate_monthly_report(cta_url: str = "") -> dict[str, Any] | None:
    """Generate a monthly pick accuracy report from pick_history DB."""
    try:
        from app.pick_tracker import get_current_streak, get_monthly_accuracy
        acc = get_monthly_accuracy()
        streak = get_current_streak()
    except Exception as e:
        logger.warning("Monthly report: failed to fetch accuracy: %s", e)
        return None

    if acc["total"] < 3:
        logger.info("Monthly report: too few picks (%d) — skipping", acc["total"])
        return None

    month_name = datetime.now().strftime("%m")
    streak_line = ""
    if streak >= 3:
        streak_line = f"Current streak: {streak} consecutive wins"
    elif streak <= -3:
        streak_line = f"Current streak: {abs(streak)} consecutive losses"

    user_prompt = (
        f"Generate a monthly pick accuracy report:\n\n"
        f"Month: {month_name}월\n"
        f"Total picks: {acc['total']}\n"
        f"Correct: {acc['correct']}\n"
        f"Accuracy: {acc['pct']}%\n"
        f"{streak_line}"
    )
    text = await generate_text(MONTHLY_REPORT_PROMPT, user_prompt, _cta_html(cta_url))
    if not text:
        return None

    return {
        "text": text,
        "card_bytes": None,
        "image_url": None,
        "content_type": "sports_monthly_report",
        "match_id": 0,
    }


async def generate_top_scorer_post(
    scorers: list[dict],
    league_id: int,
    cta_url: str = "",
) -> dict[str, Any] | None:
    """Generate a top scorer race post from scorers data (already fetched by FD client)."""
    if not scorers:
        return None
    league_name = LEAGUE_NAMES.get(league_id, f"League {league_id}")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scorer_lines = "\n".join(
        f"{i+1}. {s['name']} ({s['team']}): {s['goals']}골"
        for i, s in enumerate(scorers[:5])
    )
    user_prompt = (
        f"League: {league_name}\nDate: {today}\n\nTop scorers:\n{scorer_lines}"
    )
    try:
        text = await generate_text(TOP_SCORER_PROMPT, user_prompt, _cta_html(cta_url))
        if not text:
            return None
        image_url = await fetch_sport_image(league_id=league_id, league_name=league_name)
        return {
            "text": text,
            "card_bytes": None,
            "image_url": image_url,
            "content_type": "sports_top_scorers",
            "match_id": 0,
        }
    except Exception as e:
        logger.warning("generate_top_scorer_post failed (league=%d): %s", league_id, e)
        return None
