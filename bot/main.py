"""
[DEPRECATED] Admin Bot 진입점.

이 모듈은 더 이상 사용되지 않습니다.
모든 관리 기능은 구독봇(subscribe_bot.py)으로 통합되었습니다.
BOT_TOKEN은 스케줄러 관리자 DM 알림 전용으로만 유지됩니다.

사용하지 마세요 — bot/subscribe_bot.py를 대신 사용하세요.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, "/app")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Deprecated — 구독봇으로 통합됨."""
    logger.warning(
        "[DEPRECATED] bot/main.py (Admin Bot)은 더 이상 사용되지 않습니다. "
        "모든 관리 기능은 bot/subscribe_bot.py로 통합되었습니다."
    )


if __name__ == "__main__":
    main()
