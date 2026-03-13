#!/usr/bin/env python3
"""
CHANNEL_ID 채널에 프리미엄 게시물 1건 발송.
app/scheduler.py 에서 1시간 간격으로 호출.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "bot" / ".env")

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "").strip()

if not BOT_TOKEN or not CHANNEL_ID:
    sys.exit(0)

async def main() -> None:
    from telegram import Bot
    from app.services.premium_formatter import post_premium_to_channel
    bot = Bot(token=BOT_TOKEN)
    await post_premium_to_channel(bot)

if __name__ == "__main__":
    asyncio.run(main())
