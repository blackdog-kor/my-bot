"""Claude Advisor: Sonnet Executor + Opus Advisor 패턴 구현.

비용 최적화 전략:
  - 기본 작업(캡션 생성, 리라이팅)은 Sonnet이 처리
  - 전략적 판단이 필요할 때만 Opus Advisor로 에스컬레이션
  - 실패 시 Gemini Flash로 자동 폴백

Usage:
    from app.claude_advisor import generate_caption, rewrite_content
    caption = await generate_caption(template, {"username": "john"})
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("claude_advisor")

# ── 모델 상수 ────────────────────────────────────────────────────────────────
SONNET_MODEL = "claude-sonnet-4-5-20250514"
OPUS_MODEL = "claude-opus-4-0-20250514"
HAIKU_MODEL = "claude-haiku-4-5-20250514"

# ── 캡션 개인화 프롬프트 ──────────────────────────────────────────────────────
CAPTION_PERSONALIZE_PROMPT = """You are a casino marketing expert.
Detect the likely language/region from the Telegram username "@{username}" \
(common Indonesian names/words → Bahasa Indonesia, \
Korean name patterns or hangul characters → Korean, \
otherwise English).
Rewrite the following promotional caption in that detected language.
Rules:
- Keep ALL URLs exactly as-is (do not translate or modify URLs)
- Keep ALL emojis in place
- Preserve line breaks and overall structure
- Only translate the natural language text portions
Respond with ONLY the rewritten caption, nothing else.

Caption:
{caption}"""

# ── 콘텐츠 리라이팅 프롬프트 ──────────────────────────────────────────────────
CONTENT_REWRITE_PROMPT = """You are a professional casino/gambling content editor \
for a Telegram channel. Rewrite the given content to make it:

1. ENGAGING: Use exciting language, emojis, and formatting
2. UNIQUE: Completely rephrase (avoid plagiarism)
3. CHANNEL-BRANDED: Keep a consistent fun, exciting tone
4. CTA-READY: End with a subtle call-to-action placeholder {{cta}}
5. SHORT: Keep under 800 characters for Telegram readability
6. MULTILINGUAL: Write in the SAME language as the input, or Korean if ambiguous

Rules:
- Never mention the source channel
- Never include external links (only {{cta}} placeholder)
- Use line breaks and emojis for readability
- Add relevant hashtags at the end (2-3 max)

[Media type: {media_type}]

Original content:
{text}"""

# ── 전략 평가 프롬프트 ────────────────────────────────────────────────────────
STRATEGY_EVAL_PROMPT = """You are a senior growth marketing strategist specializing \
in Telegram casino affiliate campaigns.

Evaluate the following campaign proposal and provide:
1. Risk assessment (ban probability, compliance issues)
2. Expected conversion rate estimate
3. Recommended improvements (max 3)
4. Go/No-Go recommendation with reasoning

Proposal:
{proposal}"""


def _get_api_key() -> str:
    """Return ANTHROPIC_API_KEY or empty string."""
    return settings.anthropic_api_key


async def _call_sonnet(
    prompt: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> str | None:
    """Claude Sonnet 호출 (Executor 역할).

    Returns:
        응답 텍스트 또는 None (실패 시).
    """
    api_key = _get_api_key()
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY 미설정 — Claude 호출 불가")
        return None

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model=SONNET_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        # message.content is a list of ContentBlock objects
        text_parts = [
            block.text for block in message.content if hasattr(block, "text")
        ]
        result = "\n".join(text_parts).strip()
        logger.info(
            "sonnet_call_ok",
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )
        return result or None
    except Exception:
        logger.exception("sonnet_call_failed")
        return None


async def _call_opus(
    prompt: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.5,
) -> str | None:
    """Claude Opus 호출 (Advisor 역할 — 고난도 판단에만 사용).

    Returns:
        응답 텍스트 또는 None (실패 시).
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model=OPUS_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        text_parts = [
            block.text for block in message.content if hasattr(block, "text")
        ]
        result = "\n".join(text_parts).strip()
        logger.info(
            "opus_advisor_call_ok",
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )
        return result or None
    except Exception:
        logger.exception("opus_advisor_call_failed")
        return None


# ── 공개 API ─────────────────────────────────────────────────────────────────


async def generate_caption(caption: str, username: str) -> str:
    """DM 캡션 개인화: Sonnet으로 언어 감지 + 재작성.

    Claude 실패 시 Gemini Flash로 자동 폴백.
    API 키 미설정 시 원본 캡션 그대로 반환.

    Args:
        caption: 원본 캡션 텍스트
        username: 수신자 Telegram username

    Returns:
        개인화된 캡션 (실패 시 원본 그대로)
    """
    if not caption or not username:
        return caption

    # 1차: Claude Sonnet
    if _get_api_key():
        prompt = CAPTION_PERSONALIZE_PROMPT.format(
            username=username, caption=caption,
        )
        result = await _call_sonnet(prompt, max_tokens=800, temperature=0.7)
        if result:
            logger.info(
                "caption_personalized",
                provider="claude_sonnet",
                username=username,
            )
            return result

    # 2차: Gemini Flash 폴백
    return await _fallback_gemini_caption(caption, username)


async def rewrite_content(
    original_text: str,
    media_type: str = "text",
    cta_text: str = "",
) -> str | None:
    """채널 콘텐츠 리라이팅: Claude Sonnet 우선, 실패 시 None.

    Args:
        original_text: 원본 콘텐츠
        media_type: 미디어 유형 (photo/video/text)
        cta_text: CTA 텍스트

    Returns:
        리라이팅된 텍스트 또는 None (실패 시)
    """
    if not original_text.strip():
        return None

    if not _get_api_key():
        return None

    prompt = CONTENT_REWRITE_PROMPT.format(
        media_type=media_type, text=original_text,
    )
    result = await _call_sonnet(prompt, max_tokens=600, temperature=0.8)
    if result and cta_text:
        result = result.replace("{cta}", cta_text)
    elif result:
        result = result.replace("{cta}", "👉 지금 바로 시작하기")

    if result:
        logger.info("content_rewritten", provider="claude_sonnet", length=len(result))
    return result


async def evaluate_strategy(proposal: str) -> str | None:
    """캠페인 전략 평가: Opus Advisor로 고급 분석.

    Opus 실패 시 Sonnet으로 폴백.

    Args:
        proposal: 캠페인 전략 제안 텍스트

    Returns:
        전략 평가 결과 또는 None
    """
    if not proposal.strip() or not _get_api_key():
        return None

    prompt = STRATEGY_EVAL_PROMPT.format(proposal=proposal)

    # 1차: Opus (고급 분석)
    result = await _call_opus(prompt, max_tokens=1024, temperature=0.3)
    if result:
        logger.info("strategy_evaluated", provider="claude_opus")
        return result

    # 2차: Sonnet 폴백
    result = await _call_sonnet(prompt, max_tokens=1024, temperature=0.3)
    if result:
        logger.info("strategy_evaluated", provider="claude_sonnet_fallback")
    return result


# ── Gemini 폴백 ──────────────────────────────────────────────────────────────


async def _fallback_gemini_caption(caption: str, username: str) -> str:
    """Gemini Flash로 캡션 개인화 (Claude 실패 시 폴백)."""
    gemini_key = settings.gemini_api_key
    if not gemini_key:
        logger.debug("gemini_fallback_skip", reason="no_api_key")
        return caption

    try:
        import google.generativeai as genai

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = CAPTION_PERSONALIZE_PROMPT.format(
            username=username, caption=caption,
        )
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, model.generate_content, prompt)
        result = (response.text or "").strip()
        if result:
            logger.info(
                "caption_personalized",
                provider="gemini_fallback",
                username=username,
            )
            return result
        return caption
    except Exception:
        logger.exception("gemini_fallback_failed", username=username)
        return caption
