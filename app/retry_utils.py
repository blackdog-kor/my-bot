"""Retry utilities using tenacity for Telegram API calls.

Usage:
    from app.retry_utils import retry_on_floodwait

    @retry_on_floodwait
    async def send_message(client, chat_id, text):
        return await client.send_message(chat_id, text)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Jitter range for FloodWait backoff (percentage of base wait)
_JITTER_MIN_PERCENT = 0.1
_JITTER_MAX_PERCENT = 0.3


def _is_floodwait(exc: BaseException) -> bool:
    """Check if exception is a Pyrogram FloodWait error."""
    return type(exc).__name__ == "FloodWait"


def _wait_floodwait(retry_state: RetryCallState) -> float:
    """Extract wait time from FloodWait exception, with jitter."""
    import random

    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if exc and hasattr(exc, "value"):
        base_wait = float(exc.value)  # type: ignore[union-attr]
    else:
        base_wait = 60.0
    # Add jitter to avoid thundering herd
    jitter = base_wait * random.uniform(_JITTER_MIN_PERCENT, _JITTER_MAX_PERCENT)
    total_wait = base_wait + jitter
    logger.warning(
        "FloodWait: waiting %.1f seconds (base=%d, jitter=%.1f)",
        total_wait,
        base_wait,
        jitter,
    )
    return total_wait


def _log_retry(retry_state: RetryCallState) -> None:
    """Log retry attempts."""
    if retry_state.outcome and retry_state.outcome.failed:
        exc = retry_state.outcome.exception()
        logger.warning(
            "Retry attempt %d failed: %s: %s",
            retry_state.attempt_number,
            type(exc).__name__ if exc else "Unknown",
            str(exc)[:200] if exc else "",
        )


# Pre-built decorator for FloodWait retry
retry_on_floodwait: Callable[..., Any] = retry(
    retry=retry_if_exception(_is_floodwait),
    wait=_wait_floodwait,
    stop=stop_after_attempt(3),
    before_sleep=_log_retry,
    reraise=True,
)
