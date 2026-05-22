"""
Sports AI Client: 3-tier AI fallback for sports content generation.

Priority: Claude Sonnet → OpenAI GPT-4o-mini → Gemini Flash
"""
from __future__ import annotations

import os

from app.config import settings
from app.logging_config import get_logger
from app.sports_prompts import apply_cta

logger = get_logger("sports_ai_client")


async def _call_claude(system: str, user: str) -> str | None:
    try:
        import anthropic
        if not settings.anthropic_api_key:
            return None
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=800, temperature=0.85,
            system=system, messages=[{"role": "user", "content": user}],
        )
        text = resp.content[0].text if resp.content else ""
        logger.info("Claude: %d chars", len(text))
        return text.strip() or None
    except Exception as e:
        logger.warning("Claude failed: %s", e)
        return None


async def _call_openai(system: str, user: str) -> str | None:
    try:
        from openai import AsyncOpenAI
        key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
        if not key:
            return None
        client = AsyncOpenAI(api_key=key)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=700, temperature=0.85,
        )
        text = resp.choices[0].message.content or ""
        logger.info("OpenAI: %d chars", len(text))
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
        resp = genai.GenerativeModel("gemini-1.5-flash").generate_content(f"{system}\n\n{user}")
        text = resp.text or ""
        logger.info("Gemini: %d chars", len(text))
        return text.strip() or None
    except Exception as e:
        logger.warning("Gemini failed: %s", e)
        return None


async def generate_text(system: str, user: str, cta_html: str = "") -> str | None:
    """3-tier AI generation with CTA injection. Returns None if all fail."""
    for fn in (_call_claude, _call_openai, _call_gemini):
        result = await fn(system, user)
        if result:
            return apply_cta(result, cta_html)
    logger.error("All AI providers failed — check API keys")
    return None
