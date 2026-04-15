#!/usr/bin/env python
"""
매일 09:00 KST (00:00 UTC) 구독자 전체 자동 푸시 스크립트.
app/scheduler.py 에서 subprocess로 실행됨.
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
logger = logging.getLogger("subscribe_push")

SUBSCRIBE_BOT_TOKEN = (os.getenv("SUBSCRIBE_BOT_TOKEN") or "").strip()
AFFILIATE_URL       = (os.getenv("AFFILIATE_URL") or "").strip()
ADMIN_ID_RAW        = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID            = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None


async def _send_media(bot, chat_id: int, file_id: str, file_type: str, caption: str) -> None:
    cap = caption or None
    if file_type == "photo":
        await bot.send_photo(chat_id, file_id, caption=cap)
    elif file_type == "video":
        try:
            await bot.send_video(chat_id, file_id, caption=cap)
        except Exception:
            await bot.send_document(chat_id, file_id, caption=cap)
    else:
        await bot.send_document(chat_id, file_id, caption=cap)


async def main() -> None:
    from telegram import Bot
    from bot.handlers.callbacks import get_loaded_message_full
    from app.pg_broadcast import get_subscribe_users, get_campaign_config
    from app.userbot_sender import personalize_caption

    if not SUBSCRIBE_BOT_TOKEN:
        logger.error("SUBSCRIBE_BOT_TOKEN이 설정되지 않았습니다.")
        sys.exit(1)

    bot = Bot(token=SUBSCRIBE_BOT_TOKEN)

    # 장전된 미디어 확인
    loaded = get_loaded_message_full()
    if not loaded:
        msg = "⏰ [09:00 KST 자동 푸시] ❌ 장전된 미디어가 없습니다."
        logger.warning(msg)
        if ADMIN_ID:
            await bot.send_message(ADMIN_ID, msg)
        return

    _, _, file_id, file_type, loaded_caption = loaded
    if not file_id:
        msg = "⏰ [09:00 KST 자동 푸시] ❌ 파일 ID 없음. 재장전 필요."
        logger.warning(msg)
        if ADMIN_ID:
            await bot.send_message(ADMIN_ID, msg)
        return

    # campaign_config 로드 (DB 우선, 없으면 환경변수 폴백)
    try:
        cfg = get_campaign_config()
    except Exception:
        cfg = {}

    effective_affiliate_url = (cfg.get("affiliate_url") or "").strip() or AFFILIATE_URL
    _db_caption_tmpl        = (cfg.get("caption_template") or "").strip()
    _db_promo_code          = (cfg.get("promo_code") or "").strip()

    base_caption = _db_caption_tmpl or loaded_caption
    if _db_promo_code and "{promo_code}" in base_caption:
        base_caption = base_caption.replace("{promo_code}", _db_promo_code)

    # 구독자 목록 (id + username)
    users = get_subscribe_users()
    logger.info("자동 푸시: 총 %d명에게 발송 시작", len(users))

    if not users:
        msg = "⏰ [09:00 KST 자동 푸시] 구독자가 없습니다."
        logger.info(msg)
        if ADMIN_ID:
            await bot.send_message(ADMIN_ID, msg)
        return

    sent = skipped = failed = 0
    for uid, username in users:
        try:
            user_caption = await personalize_caption(base_caption, username)
            await _send_media(bot, uid, file_id, file_type, user_caption)
            sent += 1
        except Exception as e:
            err = str(e).lower()
            if any(k in err for k in ("blocked", "deactivated", "not found", "forbidden", "user is deactivated")):
                skipped += 1
            else:
                failed += 1
                logger.warning("send failed to %d: %s", uid, e)
        await asyncio.sleep(0.05)  # ~20 msg/sec (Bot API 제한 준수)

    result = (
        f"⏰ [09:00 KST 자동 푸시] 완료!\n"
        f"• 성공: {sent}명\n"
        f"• 차단/탈퇴: {skipped}명\n"
        f"• 실패: {failed}명"
    )
    logger.info(result)
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, result)


if __name__ == "__main__":
    asyncio.run(main())
