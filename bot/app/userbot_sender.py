"""
Pyrogram UserBot broadcast sender.

Required env vars:
  BOT_TOKEN         – Telegram Bot token (used to download the loaded file via Bot API)
  API_ID            – Telegram App API ID  (https://my.telegram.org/apps)
  API_HASH          – Telegram App API Hash
  PYROGRAM_SESSION  – Pyrogram StringSession string (generate with: python scripts/gen_session.py)

Optional env vars:
  BROADCAST_CHUNK_SIZE  – users per chunk          (default: 50)
  BROADCAST_SLEEP_SEC   – seconds between chunks   (default: 15)
  VIP_URL               – URL for VIP CASINO button (default: https://1wwtgq.com/?p=mskf)

Broadcast flow:
  1. Download the loaded file bytes from Telegram via Bot API (getFile + download URL)
  2. Start Pyrogram client using PYROGRAM_SESSION
  3. Upload the file once to UserBot's Saved Messages ("me") → get message_id
  4. For each chunk of CHUNK_SIZE unsent users (from PostgreSQL is_sent=FALSE):
       - copy_message from "me" to each user (adds VIP CASINO button)
       - mark chunk as is_sent=TRUE in PostgreSQL
       - notify admin via callback
       - sleep SLEEP_SEC before next chunk
  5. Delete uploaded file from Saved Messages (cleanup)
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
from typing import Awaitable, Callable

import httpx

logger = logging.getLogger("userbot_sender")

CHUNK_SIZE = int(os.getenv("BROADCAST_CHUNK_SIZE", "50"))
SLEEP_SEC  = float(os.getenv("BROADCAST_SLEEP_SEC", "15"))
VIP_URL    = os.getenv("VIP_URL", "https://1wwtgq.com/?p=mskf")


async def _download_via_bot_api(bot_token: str, file_id: str) -> tuple[bytes, str]:
    """Download a file from Telegram Bot API. Returns (file_bytes, remote_file_path)."""
    async with httpx.AsyncClient(timeout=120) as hc:
        r = await hc.get(
            f"https://api.telegram.org/bot{bot_token}/getFile",
            params={"file_id": file_id},
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"getFile failed: {data}")
        remote_path: str = data["result"]["file_path"]

        dl = await hc.get(
            f"https://api.telegram.org/file/bot{bot_token}/{remote_path}",
        )
        dl.raise_for_status()
        return dl.content, remote_path


async def broadcast_via_userbot(
    *,
    bot_token: str,
    file_id: str,
    file_type: str,
    caption: str,
    notify_callback: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    """
    Broadcast a loaded media message to all is_sent=FALSE users via Pyrogram UserBot.

    Args:
        bot_token:       Telegram Bot token (for file download)
        file_id:         Bot API file_id of the loaded media
        file_type:       'photo', 'video', or 'document'
        caption:         Caption text to attach
        notify_callback: async callable(str) — sends status updates to admin

    Returns:
        {"total": int, "sent": int, "failed": int, "skipped": int}
    """
    try:
        from pyrogram import Client
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        from pyrogram.errors import (
            FloodWait,
            UserIsBlocked,
            InputUserDeactivated,
            PeerIdInvalid,
            RPCError,
        )
    except ImportError:
        raise ImportError(
            "Pyrogram이 설치되지 않았습니다. 실행: pip install pyrogram tgcrypto"
        )

    from app.pg_broadcast import get_unsent_user_ids, mark_sent, count_unsent

    api_id   = int(os.getenv("API_ID", "0") or "0")
    api_hash = (os.getenv("API_HASH") or "").strip()
    session  = (os.getenv("PYROGRAM_SESSION") or "").strip()

    if not api_id or not api_hash or not session:
        raise ValueError(
            "API_ID, API_HASH, PYROGRAM_SESSION 환경변수가 모두 설정되어야 합니다."
        )

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("VIP CASINO", url=VIP_URL)]]
    )

    # ── Step 1: Download file via Bot API ────────────────────────────────────
    if notify_callback:
        await notify_callback("⬇️ 파일 다운로드 중 (Bot API)...")
    logger.info("파일 다운로드 시작 (type=%s)", file_type)
    file_bytes, remote_path = await _download_via_bot_api(bot_token, file_id)
    logger.info("다운로드 완료 (%d bytes)", len(file_bytes))

    total_unsent = count_unsent()
    sent = failed = skipped = 0

    async with Client(
        name="userbot_broadcast",
        api_id=api_id,
        api_hash=api_hash,
        session_string=session,
    ) as client:

        # ── Step 2: Upload once to Saved Messages ─────────────────────────────
        if notify_callback:
            await notify_callback("📤 Saved Messages에 미디어 업로드 중...")

        bio = io.BytesIO(file_bytes)
        if file_type == "photo":
            bio.name = "photo.jpg"
            saved_msg = await client.send_photo("me", bio, caption=caption)
        elif file_type == "video":
            bio.name = "video.mp4"
            saved_msg = await client.send_video("me", bio, caption=caption)
        else:
            ext = remote_path.rsplit(".", 1)[-1] if "." in remote_path else "bin"
            bio.name = f"file.{ext}"
            saved_msg = await client.send_document("me", bio, caption=caption)

        saved_msg_id = saved_msg.id
        logger.info("Saved Messages 업로드 완료 (msg_id=%d)", saved_msg_id)

        if notify_callback:
            await notify_callback(
                f"🚀 UserBot 발송 시작!\n"
                f"• 미발송 대상: {total_unsent}명\n"
                f"• 청크 크기: {CHUNK_SIZE}명 / 청크 간격: {SLEEP_SEC:.0f}초"
            )

        # ── Step 3: Send in chunks ────────────────────────────────────────────
        while True:
            user_ids = get_unsent_user_ids(limit=CHUNK_SIZE)
            if not user_ids:
                break

            chunk_done: list[int] = []

            for uid in user_ids:
                delivered = False

                for attempt in range(2):
                    try:
                        await client.copy_message(
                            chat_id=uid,
                            from_chat_id="me",
                            message_id=saved_msg_id,
                            reply_markup=keyboard,
                        )
                        sent += 1
                        delivered = True
                        break

                    except FloodWait as e:
                        wait = e.value + 5
                        logger.warning("FloodWait %ds (uid=%s, attempt=%d)", wait, uid, attempt)
                        if notify_callback:
                            await notify_callback(f"⚠️ FloodWait {wait}초 — 일시 대기 중...")
                        await asyncio.sleep(wait)
                        # Loop continues → retry once

                    except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
                        # User blocked/deleted/invalid — skip silently
                        skipped += 1
                        delivered = True
                        break

                    except RPCError as e:
                        logger.warning("RPCError uid=%s: %s", uid, e)
                        failed += 1
                        delivered = True
                        break

                    except Exception as e:
                        logger.warning("Unexpected error uid=%s: %s", uid, e)
                        failed += 1
                        delivered = True
                        break

                if delivered:
                    chunk_done.append(uid)

            # ── Step 4: Mark chunk as sent in PostgreSQL ──────────────────────
            if chunk_done:
                mark_sent(chunk_done)

            remaining = count_unsent()
            progress = (
                f"📤 청크 완료\n"
                f"• 성공: {sent}명 / 차단·탈퇴: {skipped}명 / 실패: {failed}명\n"
                f"• 남은 미발송: {remaining}명"
                + (f"\n⏳ 다음 청크까지 {SLEEP_SEC:.0f}초 대기..." if remaining > 0 else "")
            )
            logger.info(progress.replace("\n", " | "))
            if notify_callback:
                await notify_callback(progress)

            if remaining == 0:
                break
            await asyncio.sleep(SLEEP_SEC)

        # ── Cleanup: Delete from Saved Messages ───────────────────────────────
        try:
            await client.delete_messages("me", saved_msg_id)
        except Exception:
            pass

    return {"total": total_unsent, "sent": sent, "failed": failed, "skipped": skipped}
