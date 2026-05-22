#!/usr/bin/env python
"""
Match Schedule Runner: entry point for APScheduler 30-min interval job.

Executes one full cycle:
  1. Populate match_schedule from API-Football (next N days)
  2. Post previews for matches kicking off soon
  3. Post reviews for matches that just ended

Called by scheduler.py via _run_script("match_schedule_runner.py", ...).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("match_schedule_runner")


async def main() -> None:
    import httpx

    bot_token = os.getenv("SUBSCRIBE_BOT_TOKEN", "")
    admin_id  = os.getenv("ADMIN_ID", "")

    def notify(text: str) -> None:
        if not bot_token or not admin_id:
            return
        try:
            httpx.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": admin_id, "text": text[:4000]},
                timeout=10,
            )
        except Exception as e:
            logger.warning("Admin notify failed: %s", e)

    try:
        from app.match_scheduler import run_match_scheduler_cycle
        result = await run_match_scheduler_cycle()

        summary = (
            f"⚽ [매치 스케줄러]\n"
            f"• 경기 등록: {result['populated']}건\n"
            f"• 프리뷰 게시: {result['previewed']}건\n"
            f"• 리뷰 게시: {result['reviewed']}건"
        )
        logger.info(summary)

        # Only notify when something was actually posted (avoid noise)
        if result["previewed"] or result["reviewed"]:
            notify(summary)

    except Exception as e:
        msg = f"❌ [매치 스케줄러] 실패: {e}"
        logger.exception(msg)
        notify(msg)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
