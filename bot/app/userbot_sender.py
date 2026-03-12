"""
Pyrogram UserBot broadcast sender.

Required env vars:
  BOT_TOKEN       – Telegram Bot token (for downloading the loaded file via Bot API)
  API_ID          – Telegram App API ID  (https://my.telegram.org/apps)
  API_HASH        – Telegram App API Hash
  SESSION_STRING  – Pyrogram StringSession (generate with: python scripts/generate_session.py)

Optional env vars (spam-ban defense tuning):
  USER_DELAY_MIN      – min seconds between each DM       (default: 3)
  USER_DELAY_MAX      – max seconds between each DM       (default: 7)
  LONG_BREAK_EVERY    – DMs per long cooldown              (default: 50)
  LONG_BREAK_MIN      – min seconds for the long cooldown  (default: 300  = 5 min)
  LONG_BREAK_MAX      – max seconds for the long cooldown  (default: 600  = 10 min)
  VIP_URL             – URL for VIP CASINO inline button   (default: https://1wwtgq.com/?p=mskf)

Broadcast flow:
  1. Download the loaded file bytes via Telegram Bot API (getFile + download URL)
  2. Start Pyrogram client with SESSION_STRING
  3. Upload the file once to UserBot's Saved Messages ("me") → get message_id
  4. Loop over all is_sent=FALSE users from PostgreSQL:
       ▸ copy_message from "me" to user  (+ VIP CASINO button)
       ▸ random delay  USER_DELAY_MIN ~ USER_DELAY_MAX  seconds  (per DM)
       ▸ every LONG_BREAK_EVERY DMs → random long cooldown LONG_BREAK_MIN ~ LONG_BREAK_MAX
       ▸ every LONG_BREAK_EVERY DMs → mark batch as is_sent=TRUE in PostgreSQL
       ▸ notify admin with progress
  5. Delete uploaded file from Saved Messages (cleanup)
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import random
from typing import Awaitable, Callable

import httpx

logger = logging.getLogger("userbot_sender")

# ── Spam-ban defense parameters ─────────────────────────────────────────────
USER_DELAY_MIN   = float(os.getenv("USER_DELAY_MIN",   "3"))
USER_DELAY_MAX   = float(os.getenv("USER_DELAY_MAX",   "7"))
LONG_BREAK_EVERY = int(  os.getenv("LONG_BREAK_EVERY", "50"))
LONG_BREAK_MIN   = float(os.getenv("LONG_BREAK_MIN",   "300"))   # 5 min
LONG_BREAK_MAX   = float(os.getenv("LONG_BREAK_MAX",   "600"))   # 10 min

VIP_URL = os.getenv("VIP_URL", "https://1wwtgq.com/?p=mskf")


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

    Anti-spam logic:
      • Random delay between every DM  (USER_DELAY_MIN ~ USER_DELAY_MAX seconds)
      • Long cooldown every LONG_BREAK_EVERY DMs  (LONG_BREAK_MIN ~ LONG_BREAK_MAX seconds)
      • FloodWait → obey Telegram's wait + 5s buffer, retry once
      • Blocked / deactivated / invalid users → skip silently (marked as sent)

    Returns: {"total": int, "sent": int, "failed": int, "skipped": int}
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

    api_id  = int(os.getenv("API_ID", "0") or "0")
    api_hash = (os.getenv("API_HASH") or "").strip()
    session  = (os.getenv("SESSION_STRING") or "").strip()

    if not api_id or not api_hash or not session:
        raise ValueError(
            "API_ID, API_HASH, SESSION_STRING 환경변수가 모두 설정되어야 합니다."
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
                f"• DM 간격: {USER_DELAY_MIN:.0f}~{USER_DELAY_MAX:.0f}초 랜덤\n"
                f"• {LONG_BREAK_EVERY}명마다 {LONG_BREAK_MIN/60:.0f}~{LONG_BREAK_MAX/60:.0f}분 휴식"
            )

        # ── Step 3: Send to all unsent users ─────────────────────────────────
        # Fetch all unsent IDs upfront to avoid repeated DB queries on small datasets;
        # for very large lists we process in LONG_BREAK_EVERY-sized batches.
        batch: list[int] = []
        batch_done: list[int] = []
        sent_in_current_break = 0   # resets after every long break

        def _fetch_next_batch() -> list[int]:
            return get_unsent_user_ids(limit=LONG_BREAK_EVERY)

        batch = _fetch_next_batch()

        while batch:
            for uid in batch:
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
                        logger.warning(
                            "⚠️ FloodWait %ds (uid=%s, attempt=%d)", wait, uid, attempt
                        )
                        if notify_callback:
                            await notify_callback(
                                f"⚠️ FloodWait {wait}초 — Telegram 지시에 따라 대기 중..."
                            )
                        await asyncio.sleep(wait)
                        # attempt loop continues → retry once

                    except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
                        skipped += 1
                        delivered = True   # no retry needed
                        break

                    except RPCError as e:
                        logger.warning("RPCError uid=%s: %s", uid, e)
                        failed += 1
                        delivered = True
                        break

                    except Exception as e:
                        logger.warning("Error uid=%s: %s", uid, e)
                        failed += 1
                        delivered = True
                        break

                if delivered:
                    batch_done.append(uid)
                    sent_in_current_break += 1

                # ── Per-DM random delay (spam-ban defense) ────────────────────
                delay = random.uniform(USER_DELAY_MIN, USER_DELAY_MAX)
                await asyncio.sleep(delay)

            # ── Commit this batch to PostgreSQL ───────────────────────────────
            if batch_done:
                mark_sent(batch_done)

            remaining = count_unsent()
            progress = (
                f"📤 배치 완료\n"
                f"• 성공: {sent}명 / 차단·탈퇴: {skipped}명 / 실패: {failed}명\n"
                f"• 남은 미발송: {remaining}명"
            )
            logger.info(progress.replace("\n", " | "))
            if notify_callback:
                await notify_callback(progress)

            if remaining == 0:
                break

            # ── Long cooldown every LONG_BREAK_EVERY DMs ─────────────────────
            cooldown = random.uniform(LONG_BREAK_MIN, LONG_BREAK_MAX)
            cooldown_min = cooldown / 60
            logger.info(
                "🛡️ 스팸 방어 휴식 시작: %.1f분 대기 (%d명 발송 완료)", cooldown_min, sent
            )
            if notify_callback:
                await notify_callback(
                    f"🛡️ 스팸 방어 휴식 중...\n"
                    f"• {cooldown_min:.1f}분 뒤 다음 배치 발송 예정\n"
                    f"• 현재까지 성공: {sent}명 / 남은 대상: {remaining}명"
                )
            await asyncio.sleep(cooldown)

            # Fetch next batch
            batch = _fetch_next_batch()
            batch_done = []
            sent_in_current_break = 0

        # ── Cleanup: Delete from Saved Messages ───────────────────────────────
        try:
            await client.delete_messages("me", saved_msg_id)
        except Exception:
            pass

    return {"total": total_unsent, "sent": sent, "failed": failed, "skipped": skipped}
