"""
Sports Content Generator: premium pick-based posts with odds, match cards, accuracy.

Pipeline per preview post:
1. Fetch real odds (The Odds API) — optional, graceful fallback
2. Generate AI analysis with odds injected into prompt (via sports_ai_client)
3. Build Pillow match card image (match_card_generator)
4. Record pick to pick_history DB (pick_tracker)
5. Return {text, card_bytes, image_url, content_type, match_id}
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.logging_config import get_logger
from app.sports_ai_client import generate_text
from app.sports_image_fetcher import fetch_sport_image
from app.sports_prompts import (
    PREVIEW_SYSTEM_PROMPT,
    REVIEW_SYSTEM_PROMPT,
    STANDINGS_SYSTEM_PROMPT,
    build_odds_section,
)
from app.sports_context_builder import build_real_match_context
from app.sports_scraper import LEAGUE_EMOJI, LEAGUE_NAMES, Match, SportsData, TeamStanding

logger = get_logger("sports_content_generator")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _cta_html(url: str) -> str:
    return f"👉 <a href='{url}'>스포츠 베팅 시작하기</a>" if url else ""


def _fmt_match(match: Match, odds_section: str = "") -> str:
    date_str = match.match_date.strftime("%Y-%m-%d %H:%M KST") if match.match_date else "TBD"
    score = f"Score: {match.home_score} - {match.away_score}" if match.home_score is not None else ""
    base = (
        f"League: {match.league_name}\nHome: {match.home_team}\nAway: {match.away_team}\n"
        f"Date: {date_str}\nVenue: {match.venue or 'TBD'}\nRound: {match.round_name or 'TBD'}\n"
        f"Status: {match.status}\n{score}"
    ).strip()
    return f"{base}\n\n{odds_section}" if odds_section else base


def _fmt_standings(standings: list[TeamStanding], league_name: str) -> str:
    lines = [f"League: {league_name}", f"Date: {datetime.now().strftime('%Y-%m-%d')}"]
    for s in standings[:8]:
        lines.append(
            f"{s.rank}. {s.team_name} | P:{s.played} W:{s.wins} D:{s.draws} L:{s.losses} | "
            f"GF:{s.goals_for} GA:{s.goals_against} | Pts:{s.points} | Form:{s.form}"
        )
    return "\n".join(lines)


def _extract_pick(text: str) -> tuple[str, int, int]:
    """Heuristically extract pick/stars/confidence from AI-generated text.

    Returns pick as English ("home"/"draw"/"away") to match pick_tracker DB constants.
    """
    if "원정승" in text:
        pick = "away"
    elif "무승부" in text:
        pick = "draw"
    else:
        if "홈승" not in text:
            logger.debug("No explicit pick found in AI text — defaulting to home")
        pick = "home"
    stars, confidence = 3, 72
    for s in range(5, 0, -1):
        if "⭐" * s in text:
            stars = s
            confidence = {5: 92, 4: 83, 3: 72, 2: 60, 1: 52}.get(s, 72)
            break
    return pick, stars, confidence


async def _build_card(match: Match, pick: str, stars: int, confidence: int, odds=None, accuracy_line: str = "") -> bytes | None:
    try:
        from app.match_card_generator import generate_match_card
        date_str = match.match_date.strftime("%m/%d %H:%M KST") if match.match_date else ""
        return generate_match_card(
            home_team=match.home_team, away_team=match.away_team,
            league_name=match.league_name, league_id=match.league_id,
            match_date_str=date_str, pick=pick, stars=stars,
            confidence_pct=confidence, odds=odds, monthly_accuracy=accuracy_line,
        )
    except Exception as e:
        logger.warning("Card generation failed: %s", e)
        return None


# ── Public API ───────────────────────────────────────────────────────────────

async def generate_match_preview(
    match: Match, cta_url: str = "", odds=None, accuracy_line: str = "",
    sd: SportsData | None = None,
) -> dict[str, Any]:
    """Generate premium match preview: AI text + match card + pick record."""
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")
    odds_section = build_odds_section(odds)

    real_context = ""
    if sd:
        real_context = build_real_match_context(
            match,
            all_results=sd.recent_results,
            standings=sd.standings,
            scorers=getattr(sd, "scorers", None),
        )
    else:
        logger.warning("No SportsData passed for %s vs %s — real data context omitted", match.home_team, match.away_team)

    user_prompt = (
        f"Generate a match preview for:\n\n{_fmt_match(match, odds_section)}\n\n"
        f"League emoji: {emoji}\nMonthly accuracy: {accuracy_line or 'N/A'}\n\n"
        f"{real_context}"
    )
    text = await generate_text(PREVIEW_SYSTEM_PROMPT, user_prompt, _cta_html(cta_url))
    pick, stars, confidence = _extract_pick(text or "")

    card_bytes = await _build_card(match, pick, stars, confidence, odds, accuracy_line)
    image_url = None
    if not card_bytes:
        image_url = await fetch_sport_image(
            league_id=match.league_id, home_team=match.home_team,
            away_team=match.away_team, league_name=match.league_name,
        )

    try:
        from app.pick_tracker import record_pick
        record_pick(
            match_id=match.match_id or 0, home_team=match.home_team,
            away_team=match.away_team, league_id=match.league_id,
            pick=pick, stars=stars, match_date=match.match_date,
        )
    except Exception:
        pass

    return {"text": text or "", "card_bytes": card_bytes, "image_url": image_url,
            "content_type": "sports_preview", "match_id": match.match_id or 0}


async def generate_match_review(
    match: Match, cta_url: str = "", odds=None, accuracy_line: str = "",
) -> dict[str, Any]:
    """Generate post-match review and update pick accuracy."""
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")
    user_prompt = f"Generate a post-match review:\n\n{_fmt_match(match)}\n\nLeague emoji: {emoji}"

    if match.home_score is not None and match.away_score is not None:
        try:
            from app.pick_tracker import record_result
            record_result(match.match_id or 0, match.home_score, match.away_score)
        except Exception:
            pass

    text = await generate_text(REVIEW_SYSTEM_PROMPT, user_prompt, _cta_html(cta_url))
    image_url = await fetch_sport_image(
        league_id=match.league_id, home_team=match.home_team,
        away_team=match.away_team, league_name=match.league_name,
    )
    return {"text": text or "", "card_bytes": None, "image_url": image_url,
            "content_type": "sports_review", "match_id": match.match_id or 0}


async def generate_standings_post(
    standings: list[TeamStanding], league_id: int, cta_url: str = "",
) -> dict[str, Any] | None:
    league_name = LEAGUE_NAMES.get(league_id, f"League {league_id}")
    text = await generate_text(STANDINGS_SYSTEM_PROMPT, _fmt_standings(standings, league_name), _cta_html(cta_url))
    if not text:
        return None
    image_url = await fetch_sport_image(league_id=league_id, league_name=league_name)
    return {"text": text, "card_bytes": None, "image_url": image_url, "content_type": "sports_standings", "match_id": 0}


async def generate_daily_sports_content(
    sports_data: list[SportsData],
    max_posts: int = 4,
    cta_url: str = "",
    odds_by_league: dict[int, list] | None = None,
    accuracy_line: str = "",
) -> list[dict[str, Any]]:
    """Generate full batch: previews → reviews → standings."""
    from app.odds_fetcher import match_odds_to_game

    posts: list[dict[str, Any]] = []
    odds_by_league = odds_by_league or {}

    for sd in sports_data:
        if len(posts) >= max_posts:
            break
        league_odds = odds_by_league.get(sd.league_id, [])
        for match in sd.upcoming[:2]:
            if len(posts) >= max_posts:
                break
            odds = match_odds_to_game(match.home_team, match.away_team, league_odds)
            post = await generate_match_preview(match, cta_url, odds, accuracy_line, sd=sd)
            post.update({"media_type": "photo", "source": f"api:sports:{sd.league_name}", "league_id": sd.league_id})
            posts.append(post)

    for sd in sports_data:
        if len(posts) >= max_posts:
            break
        for match in sd.recent_results[:1]:
            if len(posts) >= max_posts:
                break
            post = await generate_match_review(match, cta_url)
            post.update({"media_type": "photo", "source": f"api:sports:{sd.league_name}", "league_id": sd.league_id})
            posts.append(post)

    if len(posts) < max_posts:
        for sd in sports_data:
            if sd.standings:
                post = await generate_standings_post(sd.standings, sd.league_id, cta_url)
                if post:
                    post.update({"media_type": "photo", "source": f"api:sports:{sd.league_name}", "league_id": sd.league_id})
                    posts.append(post)
                break

    logger.info("Generated %d sports posts", len(posts))
    return posts
