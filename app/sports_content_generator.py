"""
Sports Content Generator: AI-powered pick-based sports posts with images.

3-tier AI fallback: Claude Sonnet → OpenAI GPT-4o-mini → Gemini Flash
Each post includes: specific pick, star confidence, 3 analysis bullets, image.
Prompts are defined in app/sports_prompts.py.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from app.config import settings
from app.logging_config import get_logger
from app.sports_image_fetcher import fetch_sport_image
from app.sports_prompts import (
    PREVIEW_SYSTEM_PROMPT,
    REVIEW_SYSTEM_PROMPT,
    STANDINGS_SYSTEM_PROMPT,
    apply_cta,
)
from app.sports_scraper import (
    LEAGUE_EMOJI,
    LEAGUE_NAMES,
    Match,
    SportsData,
    TeamStanding,
)

logger = get_logger("sports_content_generator")


# ── Data Formatters ──────────────────────────────────────────────────────────

def _fmt_match(match: Match) -> str:
    date_str = match.match_date.strftime("%Y-%m-%d %H:%M KST") if match.match_date else "TBD"
    score = (
        f"Current Score: {match.home_score} - {match.away_score}"
        if match.home_score is not None else ""
    )
    return (
        f"League: {match.league_name}\n"
        f"Home Team: {match.home_team}\n"
        f"Away Team: {match.away_team}\n"
        f"Date/Time: {date_str}\n"
        f"Venue: {match.venue or 'TBD'}\n"
        f"Round: {match.round_name or 'TBD'}\n"
        f"Status: {match.status}\n"
        f"{score}"
    ).strip()


def _fmt_standings(standings: list[TeamStanding], league_name: str) -> str:
    lines = [f"League: {league_name}", f"Date: {datetime.now().strftime('%Y-%m-%d')}"]
    for s in standings[:8]:
        lines.append(
            f"{s.rank}. {s.team_name} | "
            f"P:{s.played} W:{s.wins} D:{s.draws} L:{s.losses} | "
            f"GF:{s.goals_for} GA:{s.goals_against} GD:{s.goals_for - s.goals_against} | "
            f"Pts:{s.points} | Form:{s.form}"
        )
    return "\n".join(lines)


# ── AI Generation (3-tier fallback) ─────────────────────────────────────────

async def _call_claude(system: str, user: str) -> str | None:
    try:
        import anthropic
        if not settings.anthropic_api_key:
            return None
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=700,
            temperature=0.85,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = resp.content[0].text if resp.content else ""
        logger.info("Claude generated %d chars", len(text))
        return text.strip() or None
    except Exception as e:
        logger.warning("Claude failed: %s", e)
        return None


async def _call_openai(system: str, user: str) -> str | None:
    try:
        from openai import AsyncOpenAI
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            return None
        client = AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=600,
            temperature=0.85,
        )
        text = resp.choices[0].message.content or ""
        logger.info("OpenAI generated %d chars", len(text))
        return text.strip() or None
    except Exception as e:
        logger.warning("OpenAI failed: %s", e)
        return None


async def _call_gemini(system: str, user: str) -> str | None:
    try:
        import google.generativeai as genai
        if not settings.gemini_api_key:
            return None
        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content(f"{system}\n\n{user}")
        text = resp.text or ""
        logger.info("Gemini generated %d chars", len(text))
        return text.strip() or None
    except Exception as e:
        logger.warning("Gemini failed: %s", e)
        return None


async def _generate(system: str, user: str, cta_html: str = "") -> str | None:
    """3-tier AI generation with CTA injection."""
    for fn in (_call_claude, _call_openai, _call_gemini):
        result = await fn(system, user)
        if result:
            return apply_cta(result, cta_html)
    logger.error("All AI providers failed — check API keys")
    return None


# ── Template Fallbacks (no AI) ───────────────────────────────────────────────

def _template_preview(match: Match) -> str:
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")
    date_str = match.match_date.strftime("%m/%d %H:%M KST") if match.match_date else "TBD"
    return (
        f"<b>{emoji} {match.home_team} vs {match.away_team}</b>\n"
        f"<b>🏆 {match.league_name}</b>  |  📅 {date_str}\n\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>경기 정보</b>\n"
        f"• 🏟️ {match.venue or '장소 미정'}\n"
        f"• 📍 {match.round_name or 'TBD'}\n\n"
        f"🎯 <b>분석 예정</b>\n\n"
        f"#{match.home_team.replace(' ', '')} #{match.away_team.replace(' ', '')} #스포츠픽"
    )


def _template_review(match: Match) -> str:
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")
    score = f"{match.home_score} - {match.away_score}"
    return (
        f"<b>{emoji} {match.home_team} {score} {match.away_team}</b>\n"
        f"<b>🏆 {match.league_name}  {match.round_name or ''}</b>\n\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"📋 경기 결과가 업데이트되었습니다.\n\n"
        f"#{match.home_team.replace(' ', '')} #{match.away_team.replace(' ', '')} #경기결과"
    )


# ── Public API ───────────────────────────────────────────────────────────────

def _cta_html(url: str) -> str:
    return f"👉 <a href='{url}'>스포츠 베팅 시작하기</a>" if url else ""


async def generate_match_preview(match: Match, cta_url: str = "") -> dict[str, Any]:
    """Generate a pick-based match preview post with image."""
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")
    user_prompt = f"Generate a match preview:\n\n{_fmt_match(match)}\n\nLeague emoji: {emoji}"
    cta = _cta_html(cta_url)

    text = await _generate(PREVIEW_SYSTEM_PROMPT, user_prompt, cta)
    if not text:
        text = _template_preview(match)

    image_url = await fetch_sport_image(
        league_id=match.league_id,
        home_team=match.home_team,
        away_team=match.away_team,
        league_name=match.league_name,
    )
    return {"text": text, "image_url": image_url, "content_type": "sports_preview"}


async def generate_match_review(match: Match, cta_url: str = "") -> dict[str, Any]:
    """Generate a post-match review post with image."""
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")
    user_prompt = f"Generate a post-match review:\n\n{_fmt_match(match)}\n\nLeague emoji: {emoji}"
    cta = _cta_html(cta_url)

    text = await _generate(REVIEW_SYSTEM_PROMPT, user_prompt, cta)
    if not text:
        text = _template_review(match)

    image_url = await fetch_sport_image(
        league_id=match.league_id,
        home_team=match.home_team,
        away_team=match.away_team,
        league_name=match.league_name,
    )
    return {"text": text, "image_url": image_url, "content_type": "sports_review"}


async def generate_standings_post(
    standings: list[TeamStanding],
    league_id: int,
    cta_url: str = "",
) -> dict[str, Any] | None:
    """Generate a league standings update post with image."""
    league_name = LEAGUE_NAMES.get(league_id, f"League {league_id}")
    user_prompt = f"Generate standings update:\n\n{_fmt_standings(standings, league_name)}"
    cta = _cta_html(cta_url)

    text = await _generate(STANDINGS_SYSTEM_PROMPT, user_prompt, cta)
    if not text:
        return None

    image_url = await fetch_sport_image(league_id=league_id, league_name=league_name)
    return {"text": text, "image_url": image_url, "content_type": "sports_standings"}


async def generate_daily_sports_content(
    sports_data: list[SportsData],
    max_posts: int = 4,
    cta_url: str = "",
) -> list[dict[str, Any]]:
    """Generate a full batch of sports posts (previews → reviews → standings)."""
    posts: list[dict[str, Any]] = []

    for sd in sports_data:
        if len(posts) >= max_posts:
            break
        for match in sd.upcoming[:2]:
            if len(posts) >= max_posts:
                break
            post = await generate_match_preview(match, cta_url)
            post.update({
                "media_type": "photo",
                "source": f"api:sports:{sd.league_name}",
                "match_id": match.match_id,
                "league_id": sd.league_id,
            })
            posts.append(post)

    for sd in sports_data:
        if len(posts) >= max_posts:
            break
        for match in sd.recent_results[:1]:
            if len(posts) >= max_posts:
                break
            post = await generate_match_review(match, cta_url)
            post.update({
                "media_type": "photo",
                "source": f"api:sports:{sd.league_name}",
                "match_id": match.match_id,
                "league_id": sd.league_id,
            })
            posts.append(post)

    if len(posts) < max_posts:
        for sd in sports_data:
            if sd.standings:
                post = await generate_standings_post(sd.standings, sd.league_id, cta_url)
                if post:
                    post.update({
                        "media_type": "photo",
                        "source": f"api:sports:{sd.league_name}",
                        "match_id": 0,
                        "league_id": sd.league_id,
                    })
                    posts.append(post)
                break

    logger.info("Generated %d sports posts", len(posts))
    return posts
