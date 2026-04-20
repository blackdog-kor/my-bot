"""
Sports Content Generator: AI 기반 스포츠 경기 분석 게시물 생성.

스포츠 데이터(일정, 결과, 순위)를 기반으로 AI가 분석 게시물을 작성:
1. 경기 프리뷰 (다가오는 경기 분석)
2. 경기 리뷰 (최근 결과 요약)
3. 순위 업데이트 (리그 순위 변동)
4. 베팅 인사이트 (경기 데이터 기반 트렌드)

AI 우선순위: Claude Sonnet → OpenAI GPT-4o-mini → Gemini Flash
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.logging_config import get_logger
from app.sports_scraper import (
    LEAGUE_EMOJI,
    LEAGUE_NAMES,
    Match,
    SportsData,
    TeamStanding,
)

logger = get_logger("sports_content_generator")

# ── System Prompts ───────────────────────────────────────────────────────────

PREVIEW_SYSTEM_PROMPT = """You are a professional sports analyst writing for a Korean Telegram betting/casino channel.
Generate an engaging MATCH PREVIEW post based on the provided match data.

Requirements:
- Write in Korean (한국어)
- Use sports emojis (⚽🔥🏟️📊) strategically
- Include key matchup factors: form, head-to-head narrative, tactical angles
- Mention betting-relevant insights (recent scoring trends, home/away records)
- End with a {cta} placeholder for affiliate link
- Keep under 800 characters for Telegram
- Add 2-3 relevant hashtags
- Do NOT fabricate specific statistics — only use data provided
- Be exciting and analytical, not generic

Format:
⚽ [Match Title]
📅 [Date/Time KST]
🏟️ [Venue]

[Analysis body with insights]

{cta}

#hashtag1 #hashtag2
"""

REVIEW_SYSTEM_PROMPT = """You are a professional sports analyst writing post-match reviews for a Korean Telegram channel.
Generate an engaging MATCH REVIEW post based on the provided result data.

Requirements:
- Write in Korean (한국어)
- Lead with the scoreline prominently
- Highlight key moments/turning points
- Include betting-angle analysis (was it expected? upsets?)
- End with a {cta} placeholder
- Keep under 800 characters
- Add 2-3 hashtags
- Be analytical and exciting, include reactions to surprising results

Format:
⚽ [Result: Team A X - Y Team B]
🏆 [League/Round]

[Analysis body]

{cta}

#hashtag1 #hashtag2
"""

STANDINGS_SYSTEM_PROMPT = """You are a sports data analyst writing league standings updates for a Korean Telegram channel.
Generate an engaging STANDINGS UPDATE post.

Requirements:
- Write in Korean (한국어)
- Show top 5 teams with ranks, points, and form
- Highlight promotion/relegation battles
- Include betting-relevant insights (who's trending up/down)
- End with {cta} placeholder
- Keep under 900 characters
- Add 2-3 hashtags
- Use table-like formatting with emojis

Format:
🏆 [League Name] 순위 업데이트

[Rankings with emojis]

[Analysis of key trends]

{cta}

#hashtag1 #hashtag2
"""


# ── Match Data Formatters ────────────────────────────────────────────────────

def _format_match_for_ai(match: Match) -> str:
    """Format a Match object as structured text for AI input."""
    date_str = ""
    if match.match_date:
        date_str = match.match_date.strftime("%Y-%m-%d %H:%M KST")

    score = ""
    if match.home_score is not None and match.away_score is not None:
        score = f"Score: {match.home_score} - {match.away_score}"

    return (
        f"League: {match.league_name}\n"
        f"Home: {match.home_team}\n"
        f"Away: {match.away_team}\n"
        f"Date: {date_str}\n"
        f"Status: {match.status}\n"
        f"Venue: {match.venue}\n"
        f"Round: {match.round_name}\n"
        f"{score}"
    ).strip()


def _format_standings_for_ai(
    standings: list[TeamStanding],
    league_name: str,
    top_n: int = 10,
) -> str:
    """Format standings as structured text for AI input."""
    lines = [f"League: {league_name}\n"]
    for s in standings[:top_n]:
        lines.append(
            f"{s.rank}. {s.team_name} | "
            f"P:{s.played} W:{s.wins} D:{s.draws} L:{s.losses} | "
            f"GF:{s.goals_for} GA:{s.goals_against} | "
            f"Pts:{s.points} | Form:{s.form}"
        )
    return "\n".join(lines)


# ── AI Content Generation ────────────────────────────────────────────────────

async def _generate_with_claude(
    system_prompt: str,
    user_prompt: str,
    cta_text: str,
) -> str | None:
    """Generate content using Claude Sonnet."""
    try:
        import anthropic

        api_key = settings.anthropic_api_key
        if not api_key:
            return None

        client = anthropic.AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            temperature=0.8,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        result = response.content[0].text if response.content else ""
        result = _apply_cta(result, cta_text)
        logger.info("Claude 스포츠 콘텐츠 생성 완료 (%d chars)", len(result))
        return result.strip()

    except Exception as e:
        logger.warning("Claude 생성 실패: %s", e)
        return None


async def _generate_with_openai(
    system_prompt: str,
    user_prompt: str,
    cta_text: str,
) -> str | None:
    """Generate content using OpenAI GPT-4o-mini."""
    try:
        from openai import AsyncOpenAI

        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            return None

        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=500,
            temperature=0.8,
        )

        result = response.choices[0].message.content or ""
        result = _apply_cta(result, cta_text)
        logger.info("OpenAI 스포츠 콘텐츠 생성 완료 (%d chars)", len(result))
        return result.strip()

    except Exception as e:
        logger.warning("OpenAI 생성 실패: %s", e)
        return None


async def _generate_with_gemini(
    system_prompt: str,
    user_prompt: str,
    cta_text: str,
) -> str | None:
    """Generate content using Gemini Flash."""
    try:
        import google.generativeai as genai

        api_key = settings.gemini_api_key
        if not api_key:
            return None

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        combined = f"{system_prompt}\n\n{user_prompt}"
        response = model.generate_content(combined)
        result = response.text or ""
        result = _apply_cta(result, cta_text)
        logger.info("Gemini 스포츠 콘텐츠 생성 완료 (%d chars)", len(result))
        return result.strip()

    except Exception as e:
        logger.warning("Gemini 생성 실패: %s", e)
        return None


async def _generate_content(
    system_prompt: str,
    user_prompt: str,
    cta_text: str = "",
) -> str | None:
    """3-tier AI fallback: Claude → OpenAI → Gemini."""
    result = await _generate_with_claude(system_prompt, user_prompt, cta_text)
    if result:
        return result

    result = await _generate_with_openai(system_prompt, user_prompt, cta_text)
    if result:
        return result

    result = await _generate_with_gemini(system_prompt, user_prompt, cta_text)
    if result:
        return result

    logger.error("모든 AI 생성 실패 — API 키 확인 필요")
    return None


def _apply_cta(text: str, cta_text: str) -> str:
    """Replace {cta} placeholder with actual CTA text."""
    if not cta_text:
        cta_text = "👉 스포츠 베팅 시작하기"
    return text.replace("{cta}", cta_text)


# ── Public Content Generation Functions ──────────────────────────────────────

async def generate_match_preview(
    match: Match,
    cta_text: str = "",
) -> str | None:
    """Generate an AI match preview post.

    Args:
        match: Upcoming match data.
        cta_text: CTA text for affiliate link.

    Returns:
        Generated post text or None.
    """
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")
    user_prompt = (
        f"Generate a match preview for this upcoming match:\n\n"
        f"{_format_match_for_ai(match)}\n\n"
        f"League emoji: {emoji}"
    )

    return await _generate_content(PREVIEW_SYSTEM_PROMPT, user_prompt, cta_text)


async def generate_match_review(
    match: Match,
    cta_text: str = "",
) -> str | None:
    """Generate an AI post-match review post.

    Args:
        match: Completed match data with scores.
        cta_text: CTA text for affiliate link.

    Returns:
        Generated post text or None.
    """
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")
    user_prompt = (
        f"Generate a post-match review for this result:\n\n"
        f"{_format_match_for_ai(match)}\n\n"
        f"League emoji: {emoji}"
    )

    return await _generate_content(REVIEW_SYSTEM_PROMPT, user_prompt, cta_text)


async def generate_standings_post(
    standings: list[TeamStanding],
    league_id: int,
    cta_text: str = "",
) -> str | None:
    """Generate an AI league standings update post.

    Args:
        standings: Current league standings.
        league_id: League ID for emoji/name.
        cta_text: CTA text.

    Returns:
        Generated post text or None.
    """
    league_name = LEAGUE_NAMES.get(league_id, f"League {league_id}")
    user_prompt = (
        f"Generate a league standings update:\n\n"
        f"{_format_standings_for_ai(standings, league_name)}"
    )

    return await _generate_content(
        STANDINGS_SYSTEM_PROMPT, user_prompt, cta_text,
    )


async def generate_daily_sports_content(
    sports_data: list[SportsData],
    max_posts: int = 4,
    cta_text: str = "",
) -> list[dict[str, Any]]:
    """Generate a batch of sports content posts from collected data.

    Prioritizes:
    1. Match previews (upcoming big matches)
    2. Match reviews (recent exciting results)
    3. Standings updates (weekly)

    Args:
        sports_data: Collected sports data per league.
        max_posts: Maximum posts to generate.
        cta_text: CTA text.

    Returns:
        List of content dicts ready for DB/posting.
    """
    posts: list[dict[str, Any]] = []

    # 1) Match previews (upcoming within 48h)
    for sd in sports_data:
        if len(posts) >= max_posts:
            break
        for match in sd.upcoming[:3]:
            if len(posts) >= max_posts:
                break
            text = await generate_match_preview(match, cta_text)
            if text:
                posts.append({
                    "text": text,
                    "content_type": "sports_preview",
                    "media_type": "text",
                    "source": f"api:sports:{sd.league_name}",
                    "match_id": match.match_id,
                    "league_id": sd.league_id,
                })

    # 2) Match reviews (recent results)
    for sd in sports_data:
        if len(posts) >= max_posts:
            break
        for match in sd.recent_results[:2]:
            if len(posts) >= max_posts:
                break
            text = await generate_match_review(match, cta_text)
            if text:
                posts.append({
                    "text": text,
                    "content_type": "sports_review",
                    "media_type": "text",
                    "source": f"api:sports:{sd.league_name}",
                    "match_id": match.match_id,
                    "league_id": sd.league_id,
                })

    # 3) Standings update (one per run, rotating leagues)
    if len(posts) < max_posts and sports_data:
        # Pick first league with standings
        for sd in sports_data:
            if sd.standings:
                text = await generate_standings_post(
                    sd.standings, sd.league_id, cta_text,
                )
                if text:
                    posts.append({
                        "text": text,
                        "content_type": "sports_standings",
                        "media_type": "text",
                        "source": f"api:sports:{sd.league_name}",
                        "match_id": 0,
                        "league_id": sd.league_id,
                    })
                break

    logger.info("스포츠 콘텐츠 %d건 생성 완료", len(posts))
    return posts


# ── Fallback: Template-based generation (no AI) ─────────────────────────────

def generate_match_preview_template(match: Match) -> str:
    """Generate a simple template-based match preview (no AI required)."""
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")
    date_str = ""
    if match.match_date:
        date_str = match.match_date.strftime("%m/%d %H:%M KST")

    return (
        f"{emoji} {match.league_name}\n"
        f"📅 {date_str}\n\n"
        f"🏠 {match.home_team}\n"
        f"🆚\n"
        f"✈️ {match.away_team}\n\n"
        f"🏟️ {match.venue}\n"
        f"📍 {match.round_name}\n\n"
        f"👉 스포츠 베팅 시작하기\n\n"
        f"#스포츠 #{match.league_name.replace(' ', '')}"
    )


def generate_match_review_template(match: Match) -> str:
    """Generate a simple template-based match review (no AI required)."""
    emoji = LEAGUE_EMOJI.get(match.league_id, "⚽")
    score = f"{match.home_score} - {match.away_score}"

    return (
        f"{emoji} {match.league_name} 결과\n\n"
        f"⚽ {match.home_team} {score} {match.away_team}\n\n"
        f"📍 {match.round_name}\n\n"
        f"👉 스포츠 베팅 시작하기\n\n"
        f"#스포츠결과 #{match.league_name.replace(' ', '')}"
    )
