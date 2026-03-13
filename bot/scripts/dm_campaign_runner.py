#!/usr/bin/env python3
"""
UserBot DM 캠페인 자동 실행 스크립트.

용도:
  - /admin → 장전된 메시지를 사람이 눌러 발사하는 것과 동일한 발송을
    별도 워커/크론에서 자동으로 실행하기 위한 엔트리 포인트입니다.

전제:
  1) 관리자 계정이 이미 봇에게 사진/영상(+캡션)을 보내서
     '장전된 메시지'가 설정되어 있음 (bot/data/users.db / loaded_message)
  2) Railway 환경변수 또는 bot/.env 에 아래 값들이 설정되어 있음:
       BOT_TOKEN       – Bot API 토큰 (파일 다운로드 + 관리자 알림용)
       ADMIN_ID        – 진행 상황/에러 알림을 보낼 chat_id
       API_ID          – 텔레그램 앱 API ID
       API_HASH        – 텔레그램 앱 API Hash
       SESSION_STRING  – Pyrogram UserBot 세션 문자열
       DATABASE_URL    – PostgreSQL DSN (broadcast_targets)

실행 예:
  python3.12 bot/scripts/dm_campaign_runner.py

Railway에서 완전 자동화를 원하면:
  - 별도 Worker 서비스로 이 스크립트를 주기적으로 실행하도록 설정하면 됩니다.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
import sqlite3
from dotenv import load_dotenv

# 루트/경로 세팅
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# app.userbot_sender 모듈 import 가능하도록 경로 추가
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.userbot_sender import broadcast_via_userbot  # type: ignore


BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None


def _get_loaded_message_full() -> tuple[int, int, str, str, str] | None:
    """
    bot/data/users.db 의 loaded_message 테이블에서
    (chat_id, message_id, file_id, file_type, caption)을 읽어온다.

    telegram 라이브러리에 의존하지 않도록 callbacks 모듈 대신
    여기서 직접 SQLite를 읽는다.
    """
    db_path = ROOT / "data" / "users.db"
    if not db_path.is_file():
        return None
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT chat_id, message_id, file_id, file_type, caption "
            "FROM loaded_message WHERE id = 1"
        )
        row = cur.fetchone()
    except Exception:
        row = None
    finally:
        conn.close()
    if not row:
        return None
    chat_id, message_id, file_id, file_type, caption = row
    return int(chat_id), int(message_id), file_id or "", file_type or "photo", caption or ""


async def _notify(text: str) -> None:
    """관리자에게 진행 상황/에러를 Bot API로 전송."""
    if not BOT_TOKEN or not ADMIN_ID:
        return
    text = (text or "")[:4000]
    try:
        async with httpx.AsyncClient(timeout=15) as hc:
            await hc.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": ADMIN_ID,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
    except Exception:
        # 알림 실패는 조용히 무시 (DM 발송 로직 자체는 계속 진행)
        pass


async def main() -> None:
    # 장전된 메시지 확인
    loaded = _get_loaded_message_full()
    if not loaded:
        print("❌ 장전된 메시지가 없습니다. 관리자 계정이 봇에게 사진/영상+캡션을 먼저 보내야 합니다.")
        await _notify(
            "❌ DM 캠페인 실행 실패\n"
            "장전된 메시지가 없습니다. 봇 채팅에서 /admin → 이미지를 다시 장전해 주세요."
        )
        return

    _, _, file_id, file_type, caption = loaded
    if not file_id:
        print("❌ loaded_message에 file_id가 비어 있습니다.")
        await _notify("❌ DM 캠페인 실행 실패\nloaded_message에 file_id가 비어 있습니다.")
        return

    if not BOT_TOKEN:
        print("❌ BOT_TOKEN이 설정되지 않았습니다.")
        return

    await _notify("🚀 DM 캠페인 자동 실행 시작\n장전된 메시지를 기준으로 발송을 시작합니다.")

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
        await _notify(f"❌ DM 캠페인 실행 중 에러 발생\n{type(e).__name__}: {e}")
        return

    summary = (
        "🎉 DM 캠페인 자동 실행 완료\n"
        f"• 발송 대상 (username 보유): {result.get('total', 0)}명\n"
        f"• 성공: {result.get('sent', 0)}명\n"
        f"• 차단/탈퇴/미존재: {result.get('skipped', 0)}명\n"
        f"• 실패: {result.get('failed', 0)}명\n"
    )
    print(summary)
    await _notify(summary)


if __name__ == "__main__":
    asyncio.run(main())

