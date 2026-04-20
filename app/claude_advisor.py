"""Claude Advisor: Sonnet Executor + Opus Advisor 패턴 구현.

비용 최적화: Sonnet이 기본, Opus는 전략 판단만, 실패 시 Gemini 폴백.
"""
from __future__ import annotations

import asyncio

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("claude_advisor")

SONNET_MODEL = "claude-sonnet-4-5-20250514"
OPUS_MODEL = "claude-opus-4-0-20250514"

CAPTION_PERSONALIZE_PROMPT = """You are a casino marketing expert.
Detect the likely language/region from the Telegram username "@{username}" \
(Indonesian names → Bahasa Indonesia, Korean patterns → Korean, otherwise English).
Rewrite the following promotional caption in that detected language.
Rules: Keep ALL URLs as-is, keep emojis, preserve structure, only translate text.
Respond with ONLY the rewritten caption.

Caption:
{caption}"""

CONTENT_REWRITE_PROMPT = """You are a casino/gambling content editor for Telegram.
Rewrite to be: ENGAGING (emojis, exciting), UNIQUE (no plagiarism), SHORT (<800 chars).
End with {{cta}} placeholder. Same language as input, Korean if ambiguous.
No source mentions, no external links, add 2-3 hashtags.

[Media type: {media_type}]
Original:
{text}"""

STRATEGY_EVAL_PROMPT = """You are a senior Telegram casino affiliate growth strategist.
Evaluate: 1) Ban risk 2) Conversion estimate 3) Top 3 improvements 4) Go/No-Go.

Proposal:
{proposal}"""


def _get_api_key() -> str:
    """Return ANTHROPIC_API_KEY or empty string."""
    return settings.anthropic_api_key


async def _call_model(
    model: str,
    prompt: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> str | None:
    """Claude 모델 호출 공통 함수. 실패 시 None 반환."""
    api_key = _get_api_key()
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY 미설정 — Claude 호출 불가")
        return None
    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        text_parts = [
            block.text for block in message.content if hasattr(block, "text")
        ]
        result = "\n".join(text_parts).strip()
        logger.info(
            "claude_call_ok",
            model=model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )
        return result or None
    except Exception:
        logger.exception("claude_call_failed", model=model)
        return None


async def _call_sonnet(prompt: str, **kwargs: float | int) -> str | None:
    """Sonnet Executor 호출."""
    return await _call_model(SONNET_MODEL, prompt, **kwargs)


async def _call_opus(prompt: str, **kwargs: float | int) -> str | None:
    """Opus Advisor 호출 (고난도 판단 전용)."""
    return await _call_model(OPUS_MODEL, prompt, **kwargs)


# ── 공개 API ─────────────────────────────────────────────────────────────────


async def generate_caption(caption: str, username: str) -> str:
    """DM 캡션 개인화: Sonnet → Gemini 폴백. 실패 시 원본 반환."""
    if not caption or not username:
        return caption

    if _get_api_key():
        prompt = CAPTION_PERSONALIZE_PROMPT.format(username=username, caption=caption)
        result = await _call_sonnet(prompt, max_tokens=800, temperature=0.7)
        if result:
            logger.info("caption_personalized", provider="claude_sonnet", username=username)
            return result

    return await _fallback_gemini_caption(caption, username)


async def rewrite_content(
    original_text: str, media_type: str = "text", cta_text: str = "",
) -> str | None:
    """채널 콘텐츠 리라이팅 (Sonnet). 실패 시 None."""
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
    """캠페인 전략 평가: Opus → Sonnet 폴백."""
    if not proposal.strip() or not _get_api_key():
        return None

    prompt = STRATEGY_EVAL_PROMPT.format(proposal=proposal)
    result = await _call_opus(prompt, max_tokens=1024, temperature=0.3)
    if result:
        logger.info("strategy_evaluated", provider="claude_opus")
        return result

    result = await _call_sonnet(prompt, max_tokens=1024, temperature=0.3)
    if result:
        logger.info("strategy_evaluated", provider="claude_sonnet_fallback")
    return result


async def generate_original_content(
    prompt: str, *, max_tokens: int = 400,
    temperature: float = 0.9, cta_text: str = "",
) -> str | None:
    """Sonnet으로 오리지널 콘텐츠 생성."""
    if not _get_api_key():
        return None

    result = await _call_sonnet(prompt, max_tokens=max_tokens, temperature=temperature)
    if result:
        if cta_text:
            result = result.replace("{cta}", cta_text)
        else:
            result = result.replace("{cta}", "👉 지금 바로 시작하기")
        logger.info("original_content_generated", provider="claude_sonnet", length=len(result))
        return result.strip()
    return None


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
