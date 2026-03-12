"""
Pyrogram UserBot broadcast sender.

Required env vars:
  BOT_TOKEN       – Telegram Bot token (for downloading the loaded file via Bot API)
  API_ID          – Telegram App API ID  (https://my.telegram.org/apps)
  API_HASH        – Telegram App API Hash
  SESSION_STRING  – Pyrogram StringSession (generate: python scripts/generate_session.py)

Optional env vars (spam-ban defense tuning):
  USER_DELAY_MIN      – min seconds between each DM        (default: 3)
  USER_DELAY_MAX      – max seconds between each DM        (default: 7)
  LONG_BREAK_EVERY    – DMs per long cooldown               (default: 50)
  LONG_BREAK_MIN      – min seconds for the long cooldown   (default: 300 = 5 min)
  LONG_BREAK_MAX      – max seconds for the long cooldown   (default: 600 = 10 min)
  VIP_URL             – URL for VIP CASINO inline button    (default: https://1wwtgq.com/?p=mskf)

Why @username targeting?
  MTProto UserBot can only DM a user by numeric ID if it has previously cached that
  peer's access_hash (e.g. met them in a group).  For cold outreach to scraped users
  the only reliable target is @username — Telegram resolves usernames server-side
  without needing a cached access_hash.

Broadcast flow:
  1. Purge username-less rows from broadcast_targets (mark is_sent=TRUE — unreachable)
  2. Download the loaded file bytes via Telegram Bot API
  3. Upload once to UserBot Saved Messages ("me") → get message_id
  4. For each unsent user with username (from PostgreSQL):
       ▸ copy_message from "me"  to  "@username"  (+ VIP CASINO button)
       ▸ per-DM random delay  USER_DELAY_MIN ~ USER_DELAY_MAX  seconds
       ▸ every LONG_BREAK_EVERY DMs → random cooldown LONG_BREAK_MIN ~ LONG_BREAK_MAX
       ▸ mark batch as is_sent=TRUE in PostgreSQL
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

    Targets users by @username (not numeric ID) to avoid PeerIdInvalid errors.
    Only users with a non-empty username in broadcast_targets are contacted.

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
            UsernameNotOccupied,
            UsernameInvalid,
            RPCError,
        )
    except ImportError:
        raise ImportError(
            "Pyrogram이 설치되지 않았습니다. 실행: pip install pyrogram tgcrypto"
        )

    from app.pg_broadcast import (
        get_unsent_users,
        count_unsent_with_username,
        mark_sent,
        purge_no_username,
    )

    api_id   = int(os.getenv("API_ID", "0") or "0")
    api_hash = (os.getenv("API_HASH") or "").strip()
    session  = (os.getenv("SESSION_STRING") or "").strip()

    if not api_id or not api_hash or not session:
        raise ValueError(
            "API_ID, API_HASH, SESSION_STRING 환경변수가 모두 설정되어야 합니다."
        )

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("VIP CASINO", url=VIP_URL)]]
    )

    # ── Step 0: Purge username-less users (PeerIdInvalid → unreachable) ──────
    purged = purge_no_username()
    if purged > 0:
        msg = f"🗑️ username 없는 유저 {purged}명 → is_sent=TRUE 처리 (선톡 불가)"
        logger.info(msg)
        if notify_callback:
            await notify_callback(msg)

    total_sendable = count_unsent_with_username()
    if total_sendable == 0:
        msg = "⚠️ 발송 가능한 유저(username 보유)가 없습니다. 수집기를 먼저 실행하세요."
        if notify_callback:
            await notify_callback(msg)
        return {"total": 0, "sent": 0, "failed": 0, "skipped": 0}

    # ── Step 1: Download file via Bot API ────────────────────────────────────
    if notify_callback:
        await notify_callback("⬇️ 파일 다운로드 중 (Bot API)...")
    logger.info("파일 다운로드 시작 (type=%s)", file_type)
    file_bytes, remote_path = await _download_via_bot_api(bot_token, file_id)
    logger.info("다운로드 완료 (%d bytes)", len(file_bytes))

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
                f"• 발송 가능 대상: {total_sendable}명 (@username 보유자)\n"
                f"• DM 간격: {USER_DELAY_MIN:.0f}~{USER_DELAY_MAX:.0f}초 랜덤\n"
                f"• {LONG_BREAK_EVERY}명마다 {LONG_BREAK_MIN/60:.0f}~{LONG_BREAK_MAX/60:.0f}분 휴식"
            )

        # ── Step 3: Send to all unsent users with username ────────────────────
        batch_done: list[int] = []

        def _fetch_batch() -> list[tuple[int, str]]:
            return get_unsent_users(limit=LONG_BREAK_EVERY)

        batch = _fetch_batch()

        while batch:
            for uid, raw_username in batch:
                # Always target by @username — avoids PeerIdInvalid for cold contacts
                username_clean = raw_username.lstrip("@").strip()
                if not username_clean:
                    # Should not happen (filtered in DB query) but guard anyway
                    logger.warning("skip uid=%s: empty username after strip", uid)
                    skipped += 1
                    batch_done.append(uid)
                    continue

                target = f"@{username_clean}"
                delivered = False

                for attempt in range(2):
                    try:
                        await client.copy_message(
                            chat_id=target,
                            from_chat_id="me",
                            message_id=saved_msg_id,
                            reply_markup=keyboard,
                        )
                        sent += 1
                        delivered = True
                        logger.debug("✅ sent → %s (uid=%s)", target, uid)
                        break

                    except FloodWait as e:
                        wait = e.value + 5
                        logger.warning(
                            "⚠️ FloodWait %ds (target=%s, attempt=%d)", wait, target, attempt
                        )
                        if notify_callback:
                            await notify_callback(
                                f"⚠️ FloodWait {wait}초 — Telegram 지시에 따라 대기 중..."
                            )
                        await asyncio.sleep(wait)
                        # attempt loop continues → retry once

                    except (UserIsBlocked, InputUserDeactivated) as e:
                        # User blocked the bot or deleted their account
                        logger.info(
                            "skip %s (uid=%s): %s — %s",
                            target, uid, type(e).__name__, e
                        )
                        skipped += 1
                        delivered = True
                        break

                    except (PeerIdInvalid, UsernameNotOccupied, UsernameInvalid) as e:
                        # Username doesn't exist / changed / never registered
                        logger.warning(
                            "skip %s (uid=%s): %s — %s",
                            target, uid, type(e).__name__, e
                        )
                        skipped += 1
                        delivered = True
                        break

                    except RPCError as e:
                        logger.error(
                            "❌ RPCError %s (uid=%s): [%s] %s",
                            target, uid, type(e).__name__, e
                        )
                        failed += 1
                        delivered = True
                        break

                    except Exception as e:
                        logger.error(
                            "❌ Unexpected %s (uid=%s): [%s] %s",
                            target, uid, type(e).__name__, e
                        )
                        failed += 1
                        delivered = True
                        break

                if delivered:
                    batch_done.append(uid)

                # ── Per-DM random delay (spam-ban defense) ────────────────────
                await asyncio.sleep(random.uniform(USER_DELAY_MIN, USER_DELAY_MAX))

            # ── Commit batch to PostgreSQL ─────────────────────────────────────
            if batch_done:
                mark_sent(batch_done)

            remaining = count_unsent_with_username()
            progress = (
                f"📤 배치 완료\n"
                f"• 성공: {sent}명 / 차단·탈퇴·없음: {skipped}명 / 실패: {failed}명\n"
                f"• 남은 발송 가능 대상: {remaining}명"
                + (f"\n⏳ 다음 배치까지 {LONG_BREAK_MIN/60:.0f}~{LONG_BREAK_MAX/60:.0f}분 휴식..." if remaining > 0 else "")
            )
            logger.info(progress.replace("\n", " | "))
            if notify_callback:
                await notify_callback(progress)

            if remaining == 0:
                break

            # ── Long cooldown every LONG_BREAK_EVERY DMs ─────────────────────
            cooldown = random.uniform(LONG_BREAK_MIN, LONG_BREAK_MAX)
            logger.info("🛡️ 스팸 방어 휴식 %.1f분 (성공 %d명 누적)", cooldown / 60, sent)
            await asyncio.sleep(cooldown)

            batch = _fetch_batch()
            batch_done = []

        # ── Cleanup: Delete from Saved Messages ───────────────────────────────
        try:
            await client.delete_messages("me", saved_msg_id)
        except Exception:
            pass

    return {"total": total_sendable, "sent": sent, "failed": failed, "skipped": skipped}
