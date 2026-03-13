"""
UserBot 재발송(retry) 캠페인 (통합 scripts/).
조건: is_sent=TRUE, click_count=0, retry_sent=FALSE, sent_at <= 3일 전, username 있음.
메시지: RETRY_CAPTION, 추적 링크 TRACKING_SERVER_URL/track/{ref}
실행: python scripts/retry_sender.py (또는 스케줄러 12:00)
"""
from __future__ import annotations

import asyncio
import io
import os
import random
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import (
    FloodWait,
    UserIsBlocked,
    InputUserDeactivated,
    PeerIdInvalid,
    UsernameNotOccupied,
    UsernameInvalid,
    RPCError,
)

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "bot" / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pg_broadcast import (
    get_retry_targets,
    mark_retry_sent,
    generate_unique_ref,
    get_campaign_stats,
    get_loaded_message,
)

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

API_ID = int(os.getenv("API_ID", "0") or "0")
API_HASH = (os.getenv("API_HASH") or "").strip()
SESSION_STRING = (os.getenv("SESSION_STRING") or "").strip()
AFFILIATE_URL = (os.getenv("AFFILIATE_URL") or "").strip()
TRACKING_SERVER_URL = (os.getenv("TRACKING_SERVER_URL") or "").rstrip("/")
VIP_URL = os.getenv("VIP_URL", "https://1wwtgq.com/?p=mskf")
RETRY_CAPTION = (os.getenv("RETRY_CAPTION") or "").strip()

USER_DELAY_MIN = float(os.getenv("USER_DELAY_MIN", "3"))
USER_DELAY_MAX = float(os.getenv("USER_DELAY_MAX", "7"))
LONG_BREAK_EVERY = int(os.getenv("LONG_BREAK_EVERY", "50"))
LONG_BREAK_MIN = float(os.getenv("LONG_BREAK_MIN", "300"))
LONG_BREAK_MAX = float(os.getenv("LONG_BREAK_MAX", "600"))


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


async def _download_via_bot_api(file_id: str) -> tuple[bytes, str]:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set")
    async with httpx.AsyncClient(timeout=120) as hc:
        r = await hc.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
            params={"file_id": file_id},
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"getFile failed: {data}")
        remote_path = data["result"]["file_path"]
        dl = await hc.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{remote_path}")
        dl.raise_for_status()
        return dl.content, remote_path


async def run_retry_campaign() -> None:
    if not API_ID or not API_HASH or not SESSION_STRING:
        print("❌ API_ID / API_HASH / SESSION_STRING 이 설정되지 않았습니다.")
        return
    if not RETRY_CAPTION:
        print("❌ RETRY_CAPTION 환경변수가 비어 있습니다.")
        return

    targets = get_retry_targets()
    if not targets:
        await _notify("🔁 재발송 대상이 없습니다.")
        return

    await _notify(
        "🔁 재발송 캠페인 시작\n"
        f"재발송 대상: {len(targets)}명\n"
        "조건: 3일 전 발송, 미클릭, retry_sent=FALSE"
    )

    loaded = get_loaded_message()
    if not loaded:
        await _notify("❌ 재발송 실패: loaded_message 레코드가 없습니다.")
        return
    file_id, file_type, _caption = loaded
    if not file_id:
        await _notify("❌ 재발송 실패: loaded_message.file_id 가 비어 있습니다.")
        return

    await _notify("⬇️ 재발송용 미디어 다운로드 중 (Bot API)...")
    file_bytes, remote_path = await _download_via_bot_api(file_id)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("VIP CASINO", url=VIP_URL)]])

    sent = failed = 0
    total = len(targets)

    async with Client(
        name="userbot_retry_campaign",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING,
    ) as client:
        bio = io.BytesIO(file_bytes)
        if file_type == "video":
            bio.name = "retry_video.mp4"
            saved_msg = await client.send_video("me", bio, caption=RETRY_CAPTION)
        elif file_type == "document":
            ext = remote_path.rsplit(".", 1)[-1] if "." in remote_path else "bin"
            bio.name = f"retry_file.{ext}"
            saved_msg = await client.send_document("me", bio, caption=RETRY_CAPTION)
        else:
            bio.name = "retry_photo.jpg"
            saved_msg = await client.send_photo("me", bio, caption=RETRY_CAPTION)
        saved_msg_id = saved_msg.id

        await _notify(
            f"🔁 재발송 DM 시작\n대상: {total}명 | "
            f"DM 간격 {USER_DELAY_MIN:.0f}~{USER_DELAY_MAX:.0f}초"
        )

        batch_done: list[int] = []
        for idx, (uid, raw_username) in enumerate(targets, start=1):
            username_clean = (raw_username or "").lstrip("@").strip()
            if not username_clean:
                continue
            target = f"@{username_clean}"
            user_caption = RETRY_CAPTION
            if AFFILIATE_URL and TRACKING_SERVER_URL:
                try:
                    ref = generate_unique_ref(uid)
                    if ref:
                        tracking_url = f"{TRACKING_SERVER_URL}/track/{ref}"
                        user_caption = RETRY_CAPTION.replace(AFFILIATE_URL, tracking_url)
                except Exception:
                    pass

            delivered = False
            for attempt in range(2):
                try:
                    await client.copy_message(
                        chat_id=target,
                        from_chat_id="me",
                        message_id=saved_msg_id,
                        caption=user_caption,
                        reply_markup=keyboard,
                    )
                    sent += 1
                    delivered = True
                    break
                except FloodWait as e:
                    await _notify(f"⚠️ FloodWait {e.value + 5}초 (retry, {target})")
                    await asyncio.sleep(e.value + 5)
                except (UserIsBlocked, InputUserDeactivated):
                    delivered = True
                    break
                except (PeerIdInvalid, UsernameNotOccupied, UsernameInvalid):
                    delivered = True
                    break
                except RPCError:
                    failed += 1
                    delivered = True
                    break
                except Exception:
                    failed += 1
                    delivered = True
                    break

            if delivered:
                batch_done.append(uid)
            await asyncio.sleep(
                random.uniform(USER_DELAY_MIN, USER_DELAY_MAX)
                if USER_DELAY_MAX > USER_DELAY_MIN
                else USER_DELAY_MIN
            )

            if idx % LONG_BREAK_EVERY == 0 or idx == total:
                if batch_done:
                    mark_retry_sent(batch_done)
                remaining = max(0, total - idx)
                await _notify(
                    f"🔁 재발송 진행: {idx}/{total}명 (성공 {sent} / 실패 {failed} / 남은 {remaining})"
                )
                if remaining > 0:
                    await asyncio.sleep(random.uniform(LONG_BREAK_MIN, LONG_BREAK_MAX))
                batch_done = []

        try:
            await client.delete_messages("me", saved_msg_id)
        except Exception:
            pass

    stats = get_campaign_stats()
    pending = stats.get("pending", 0)
    text = (
        "🔁 재발송 캠페인 완료\n"
        f"재발송 대상: {total}명\n"
        f"발송 성공: {sent}명\n"
        f"클릭 유도 대기 중: {pending}명"
    )
    print(text)
    await _notify(text)


if __name__ == "__main__":
    asyncio.run(run_retry_campaign())
