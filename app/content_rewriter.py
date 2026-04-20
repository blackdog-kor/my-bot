"""
Content Rewriter: AI를 활용한 콘텐츠 리라이팅 & 현지화.

스크래핑된 콘텐츠를 AI로 재작성하여:
1. 저작권 문제 회피
2. 채널 톤&매너 일관성 유지
3. 어필리에이트 CTA 자연스럽게 삽입
4. 이모지/포맷팅 최적화

지원 AI: OpenAI GPT-4o-mini (비용 효율) / Gemini (대안)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("content_rewriter")

# ── System Prompts ───────────────────────────────────────────────────────────

REWRITE_SYSTEM_PROMPT = """You are a professional casino/gambling content editor for a Telegram channel.
Your job is to rewrite the given content to make it:

1. ENGAGING: Use exciting language, emojis, and formatting that casino players love
2. UNIQUE: Completely rephrase so it's not a copy (avoid plagiarism)
3. CHANNEL-BRANDED: Keep a consistent fun, exciting tone
4. CTA-READY: End with a subtle call-to-action placeholder {cta}
5. SHORT: Keep under 800 characters for Telegram readability
6. MULTILINGUAL: Write in the SAME language as the input, or Korean if ambiguous

Content types to optimize for:
- 🎰 Big Win announcements → maximize excitement, use numbers prominently
- 🃏 Game tips → clear, actionable advice
- 🎁 Bonus/Promo news → urgency + exclusivity
- 📊 Casino news → informative but engaging

Rules:
- Never mention the source channel
- Never include external links (only {cta} placeholder)
- Use line breaks and emojis for readability
- Add relevant hashtags at the end (2-3 max)
"""

CAPTION_GENERATION_PROMPT = """You are a Telegram channel content creator for casino/gambling.
Generate an ORIGINAL engaging post based on this topic/theme:

Topic: {topic}

Requirements:
- Exciting, attention-grabbing opening line
- Use emojis strategically (not excessive)
- Include a {cta} placeholder for affiliate link
- Under 600 characters
- Write in Korean
- Add 2-3 relevant hashtags
"""


async def rewrite_content(
    original_text: str,
    media_type: str = "text",
    cta_text: str = "",
) -> str | None:
    """AI를 사용하여 콘텐츠를 리라이팅.

    Args:
        original_text: 원본 콘텐츠 텍스트
        media_type: 미디어 유형 (photo/video/text)
        cta_text: CTA 버튼 텍스트 (빈 문자열이면 기본값 사용)

    Returns:
        리라이팅된 텍스트 또는 None (실패 시)
    """
    if not original_text.strip():
        return None

    # AI 선택: Claude 우선, OpenAI 폴백, Gemini 최종 폴백
    anthropic_key = settings.anthropic_api_key
    openai_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
    gemini_key = settings.gemini_api_key

    if anthropic_key:
        result = await _rewrite_with_claude(original_text, media_type, cta_text)
        if result:
            return result
        logger.info("Claude 리라이팅 실패 — OpenAI 폴백 시도")

    if openai_key:
        return await _rewrite_with_openai(original_text, media_type, cta_text, openai_key)
    elif gemini_key:
        return await _rewrite_with_gemini(original_text, media_type, cta_text, gemini_key)
    else:
        logger.warning("AI API 키 없음 — 리라이팅 불가, 원본 반환")
        return _basic_rewrite(original_text, cta_text)


async def generate_original_content(topic: str, cta_text: str = "") -> str | None:
    """주제 기반 오리지널 콘텐츠 생성.

    Args:
        topic: 콘텐츠 주제 (예: "슬롯 잭팟", "주간 보너스")
        cta_text: CTA 텍스트

    Returns:
        생성된 콘텐츠 또는 None
    """
    openai_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
    gemini_key = settings.gemini_api_key
    anthropic_key = settings.anthropic_api_key

    prompt = CAPTION_GENERATION_PROMPT.format(topic=topic)

    # Claude 우선 → OpenAI 폴백 → Gemini 최종 폴백
    if anthropic_key:
        result = await _generate_with_claude(prompt, cta_text)
        if result:
            return result

    if openai_key:
        return await _generate_with_openai(prompt, cta_text, openai_key)
    elif gemini_key:
        return await _generate_with_gemini(prompt, cta_text, gemini_key)
    else:
        logger.warning("AI API 키 없음 — 콘텐츠 생성 불가")
        return None


async def _rewrite_with_claude(
    text: str, media_type: str, cta_text: str,
) -> str | None:
    """Claude Sonnet으로 리라이팅 (claude_advisor 모듈 위임)."""
    try:
        from app.claude_advisor import rewrite_content as claude_rewrite

        result = await claude_rewrite(text, media_type, cta_text)
        if result:
            logger.info("Claude 리라이팅 완료 (%d chars)", len(result))
        return result
    except Exception as e:
        logger.exception("Claude 리라이팅 실패: %s", e)
        return None


async def _rewrite_with_openai(
    text: str, media_type: str, cta_text: str, api_key: str
) -> str | None:
    """OpenAI GPT-4o-mini로 리라이팅."""
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        user_msg = f"[Media type: {media_type}]\n\nOriginal content:\n{text}"

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=500,
            temperature=0.8,
        )

        result = response.choices[0].message.content or ""
        result = _apply_cta(result, cta_text)
        logger.info("OpenAI 리라이팅 완료 (%d chars)", len(result))
        return result.strip()

    except Exception as e:
        logger.exception("OpenAI 리라이팅 실패: %s", e)
        return None


async def _rewrite_with_gemini(
    text: str, media_type: str, cta_text: str, api_key: str
) -> str | None:
    """Google Gemini로 리라이팅."""
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = (
            f"{REWRITE_SYSTEM_PROMPT}\n\n"
            f"[Media type: {media_type}]\n\n"
            f"Original content:\n{text}"
        )

        response = model.generate_content(prompt)
        result = response.text or ""
        result = _apply_cta(result, cta_text)
        logger.info("Gemini 리라이팅 완료 (%d chars)", len(result))
        return result.strip()

    except Exception as e:
        logger.exception("Gemini 리라이팅 실패: %s", e)
        return None


async def _generate_with_claude(prompt: str, cta_text: str) -> str | None:
    """Claude Sonnet으로 오리지널 콘텐츠 생성."""
    try:
        from app.claude_advisor import _call_sonnet

        result = await _call_sonnet(prompt, max_tokens=400, temperature=0.9)
        if result:
            result = _apply_cta(result, cta_text)
            logger.info("Claude 콘텐츠 생성 완료 (%d chars)", len(result))
            return result.strip()
        return None
    except Exception as e:
        logger.exception("Claude 생성 실패: %s", e)
        return None


async def _generate_with_openai(prompt: str, cta_text: str, api_key: str) -> str | None:
    """OpenAI로 오리지널 콘텐츠 생성."""
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a creative casino content writer for Telegram."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
            temperature=0.9,
        )

        result = response.choices[0].message.content or ""
        result = _apply_cta(result, cta_text)
        return result.strip()

    except Exception as e:
        logger.exception("OpenAI 생성 실패: %s", e)
        return None


async def _generate_with_gemini(prompt: str, cta_text: str, api_key: str) -> str | None:
    """Gemini로 오리지널 콘텐츠 생성."""
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        response = model.generate_content(prompt)
        result = response.text or ""
        result = _apply_cta(result, cta_text)
        return result.strip()

    except Exception as e:
        logger.exception("Gemini 생성 실패: %s", e)
        return None


def _apply_cta(text: str, cta_text: str) -> str:
    """CTA 플레이스홀더를 실제 텍스트로 치환."""
    if not cta_text:
        cta_text = "👉 지금 바로 시작하기"
    return text.replace("{cta}", cta_text)


def _basic_rewrite(text: str, cta_text: str) -> str:
    """AI 없이 기본 포맷팅만 적용 (폴백)."""
    if not cta_text:
        cta_text = "👉 지금 바로 시작하기"

    # 기본 이모지 추가 + CTA 삽입
    lines = text.strip().split("\n")
    if lines and not any(e in lines[0] for e in "🎰🎲🃏💰🔥"):
        lines[0] = "🎰 " + lines[0]

    result = "\n".join(lines)
    if "{cta}" in result:
        result = result.replace("{cta}", cta_text)
    else:
        result += f"\n\n{cta_text}"

    return result.strip()
