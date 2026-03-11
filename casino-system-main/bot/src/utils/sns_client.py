import os
from datetime import datetime, timezone

import httpx

from utils.logger import setup_logger, log_event

logger = setup_logger("sns_client")


async def send_user_entry_event(telegram_user_id: int, username: str | None) -> None:
    url = os.getenv("SNS_AUTOMATION_URL", "")
    secret = os.getenv("SNS_AUTOMATION_SECRET", "")

    if not url:
        log_event(logger, "sns_event_skipped", reason="SNS_AUTOMATION_URL not set")
        return

    payload = {
        "event_name": "user_entry",
        "telegram_user_id": telegram_user_id,
        "username": username,
        "event_time": datetime.now(timezone.utc).isoformat(),
    }

    headers = {
        "Content-Type": "application/json",
        "X-Secret": secret,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=5.0)
        log_event(
            logger,
            "sns_user_entry_sent",
            telegram_user_id=telegram_user_id,
            status_code=response.status_code,
        )
    except Exception as exc:
        log_event(
            logger,
            "sns_user_entry_failed",
            telegram_user_id=telegram_user_id,
            error=str(exc),
        )
