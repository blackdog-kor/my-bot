"""
UserBot DM 캠페인 자동 실행.
campaign_posts 테이블의 다음 게시물(순환)로 발송.
실행: python scripts/dm_campaign_runner.py (또는 스케줄러 06:00)
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)
load_dotenv(ROOT / "bot" / ".env", override=True)

from app.userbot_sender import broadcast_via_userbot
from app.pg_broadcast import get_campaign_stats, get_next_post

BOT_TOKEN    = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID     = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None


async def _notify(text: str) -> None:
    if not BOT_TOKEN or not ADMIN_ID:
        return
    text = (text or "")[:4000]
    try:
        async with httpx.AsyncClient(timeout=15) as hc:
            await hc.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_ID, "text": text, "disable_web_page_preview": True},
            )
    except Exception:
        pass


async def _send_preview(file_id: str, file_type: str, caption: str) -> None:
    if not BOT_TOKEN or not ADMIN_ID or not file_id:
        return
    if file_type == "video":
        endpoint, key = "sendVideo", "video"
    elif file_type == "document":
        endpoint, key = "sendDocument", "document"
    else:
        endpoint, key = "sendPhoto", "photo"
    try:
        async with httpx.AsyncClient(timeout=20) as hc:
            await hc.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/{endpoint}",
                json={"chat_id": ADMIN_ID, key: file_id, "caption": caption},
            )
    except Exception:
        pass


async def main() -> None:
    post = get_next_post()
    if not post or not post.get("file_id"):
        print("❌ 발송할 게시물이 없습니다.")
        await _notify(
            "❌ DM 캠페인 실행 실패\n"
            "campaign_posts에 활성 게시물이 없습니다.\n"
            "구독봇 /admin → ➕ 게시물 추가 후 다시 시도해주세요."
        )
        return

    file_id   = post["file_id"]
    file_type = post["file_type"]
    caption   = post["caption"] or ""
    post_id   = post["id"]

    if not BOT_TOKEN:
        print("❌ BOT_TOKEN이 설정되지 않았습니다.")
        return

    await _notify(
        f"🚀 DM 캠페인 자동 실행 시작 (게시물 #{post_id})\n"
        "아래 미리보기가 이번 캠페인에서 발송될 게시물입니다."
    )
    await _send_preview(file_id=file_id, file_type=file_type, caption=caption)

    try:
        result = await broadcast_via_userbot(
            bot_token=BOT_TOKEN,
            file_id=file_id,
            file_type=file_type,
            caption=caption,
            notify_callback=_notify,
        )
    except Exception as e:
        print("❌ UserBot 발송 실패:", e)
        await _notify(f"❌ DM 캠페인 실행 중 에러\n{type(e).__name__}: {e}")
        return

    summary = (
        f"🎉 DM 캠페인 자동 실행 완료 (게시물 #{post_id})\n"
        f"• 발송 대상: {result.get('total', 0)}명\n"
        f"• 성공: {result.get('sent', 0)}명\n"
        f"• 차단/탈퇴/미존재: {result.get('skipped', 0)}명\n"
        f"• 실패: {result.get('failed', 0)}명\n"
    )
    print(summary)
    await _notify(summary)

    try:
        stats = get_campaign_stats()
        report = (
            "📊 캠페인 완료 리포트\n"
            f"총 수집: {stats.get('total_targets', 0)}명\n"
            f"발송 완료: {stats.get('total_sent', 0)}명\n"
            f"링크 클릭: {stats.get('total_clicked', 0)}명\n"
            f"클릭률: {stats.get('click_rate', 0.0)}%\n"
            f"대기 중: {stats.get('pending', 0)}명"
        )
        await _notify(report)
    except Exception as e:
        print("캠페인 통계 조회 실패:", e)


if __name__ == "__main__":
    asyncio.run(main())
