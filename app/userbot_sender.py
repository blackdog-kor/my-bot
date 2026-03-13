"""
Pyrogram UserBot broadcast sender (통합 app 공용).

Required env: BOT_TOKEN, API_ID, API_HASH, SESSION_STRING
Optional: USER_DELAY_MIN/MAX, LONG_BREAK_*, VIP_URL, AFFILIATE_URL, TRACKING_SERVER_URL
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Awaitable, Callable

logger = logging.getLogger("userbot_sender")

USER_DELAY_MIN   = float(os.getenv("USER_DELAY_MIN",   "3"))
USER_DELAY_MAX   = float(os.getenv("USER_DELAY_MAX",   "7"))
LONG_BREAK_EVERY = int(  os.getenv("LONG_BREAK_EVERY", "50"))
LONG_BREAK_MIN   = float(os.getenv("LONG_BREAK_MIN",   "300"))
LONG_BREAK_MAX   = float(os.getenv("LONG_BREAK_MAX",   "600"))
VIP_URL = os.getenv("VIP_URL", "https://1wwtgq.com/?p=mskf")
AFFILIATE_URL = (os.getenv("AFFILIATE_URL") or "").strip()
TRACKING_SERVER_URL = (os.getenv("TRACKING_SERVER_URL") or "").rstrip("/")


async def broadcast_via_userbot(
    *,
    bot_token: str,
    file_id: str,
    file_type: str,
    caption: str,
    notify_callback: Callable[[str], Awaitable[None]] | None = None,
) -> dict:
    """UserBot으로 is_sent=FALSE 유저에게 발송. 반환: {total, sent, failed, skipped}."""
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
            UserPrivacyRestricted,
            UserNotParticipant,
            RPCError,
        )
    except ImportError:
        raise ImportError("pip install pyrogram tgcrypto")

    from app.pg_broadcast import (
        get_unsent_users,
        count_unsent_with_username,
        mark_sent,
        purge_no_username,
        generate_unique_ref,
    )

    api_id = int(os.getenv("API_ID", "0") or "0")
    api_hash = (os.getenv("API_HASH") or "").strip()

    # SESSION_STRING_1 ~ SESSION_STRING_N 자동 감지, 없으면 SESSION_STRING 사용
    sessions: list[tuple[str, str]] = []
    i = 1
    while True:
        val = (os.getenv(f"SESSION_STRING_{i}") or "").strip()
        if not val:
            break
        sessions.append((f"SESSION_STRING_{i}", val))
        i += 1
    if not sessions:
        legacy = (os.getenv("SESSION_STRING") or os.getenv("SESSION_STRING_1") or "").strip()
        if legacy:
            sessions.append(("SESSION_STRING_1", legacy))

    if not api_id or not api_hash or not sessions:
        raise ValueError("API_ID, API_HASH, and at least one SESSION_STRING_* must be set.")

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("VIP CASINO", url=VIP_URL)]])

    purged = purge_no_username()
    if purged > 0:
        msg = f"🗑️ username 없는 유저 {purged}명 → is_sent=TRUE"
        logger.info(msg)
        if notify_callback:
            await notify_callback(msg)

    total_sendable = count_unsent_with_username()
    if total_sendable == 0:
        msg = "⚠️ 발송 가능한 유저(username 보유)가 없습니다."
        if notify_callback:
            await notify_callback(msg)
        return {"total": 0, "sent": 0, "failed": 0, "skipped": 0}

    # 계정별 Client 준비
    accounts = []
    for label, session in sessions:
        client = Client(
            name=f"userbot_broadcast_{label}",
            api_id=api_id,
            api_hash=api_hash,
            session_string=session,
        )
        await client.start()

        accounts.append(
            {
                "label": label,
                "client": client,
                "cooldown_until": 0.0,
            }
        )

    if notify_callback:
        await notify_callback(
            f"🚀 UserBot 발송 시작! 대상: {total_sendable}명 | "
            f"계정 수: {len(accounts)} | DM 간격 {USER_DELAY_MIN:.0f}~{USER_DELAY_MAX:.0f}초"
        )

    sent = failed = skipped = 0
    base_track_url = TRACKING_SERVER_URL or ""
    batch_done: list[int] = []
    acc_index = 0

    def _fetch_batch() -> list[tuple[int, str]]:
        return get_unsent_users(limit=LONG_BREAK_EVERY)

    async def _pick_account(now: float):
        nonlocal acc_index
        n = len(accounts)
        for _ in range(n):
            acc = accounts[acc_index]
            acc_index = (acc_index + 1) % n
            if acc["cooldown_until"] <= now:
                return acc
        return None

    try:
        batch = _fetch_batch()

        while batch:
            for uid, raw_username in batch:
                username_clean = raw_username.lstrip("@").strip()
                if not username_clean:
                    skipped += 1
                    batch_done.append(uid)
                    continue

                target = f"@{username_clean}"
                tracking_url = None
                try:
                    if base_track_url and AFFILIATE_URL:
                        ref = generate_unique_ref(uid)
                        if ref:
                            tracking_url = f"{base_track_url}/track/{ref}"
                except Exception as e:
                    logger.warning("generate_unique_ref %s: %s", uid, e)

                user_caption = (
                    (caption or "").replace(AFFILIATE_URL, tracking_url)
                    if (tracking_url and AFFILIATE_URL)
                    else caption
                )

                delivered = False
                attempts_for_user = 0
                max_attempts = len(accounts) * 3

                while attempts_for_user < max_attempts and not delivered:
                    attempts_for_user += 1
                    now = asyncio.get_event_loop().time()
                    acc = await _pick_account(now)
                    if acc is None:
                        # 전체 계정이 FloodWait 중 → 가장 빠른 cooldown까지 대기
                        next_ready = min(a["cooldown_until"] for a in accounts)
                        wait = max(1.0, next_ready - now)
                        if notify_callback:
                            await notify_callback(f"⏳ 모든 계정 FloodWait, {wait:.0f}초 대기 후 재시도...")
                        await asyncio.sleep(wait)
                        continue

                    client = acc["client"]

                    # 1) username을 실제 User 객체로 resolve (get_users) → 캐시 등록 + id 확보
                    try:
                        user = await client.get_users(target)
                    except FloodWait as e:
                        wait = e.value + 5
                        acc["cooldown_until"] = now + wait
                        warn = (
                            f"⚠️ [{acc['label']}] FloodWait {wait}초 (get_users) — 계정 쿨다운 후 "
                            f"다음 계정으로 로테이션."
                        )
                        logger.warning(warn)
                        if notify_callback:
                            await notify_callback(warn)
                        continue
                    except (
                        UserIsBlocked,
                        InputUserDeactivated,
                        PeerIdInvalid,
                        UsernameNotOccupied,
                        UsernameInvalid,
                        UserPrivacyRestricted,
                        UserNotParticipant,
                    ) as e:
                        # 발송이 구조적으로 불가능한 유저 → 스킵 및 재시도 방지
                        logger.warning("Skipping %s (get_users): %s", target, e)
                        skipped += 1
                        delivered = True
                        batch_done.append(uid)
                        break
                    except RPCError as e:
                        failed += 1
                        logger.error("RPCError (get_users) for %s: %s", target, e)
                        delivered = True
                        break
                    except Exception as e:
                        failed += 1
                        logger.error("Unexpected error (get_users) for %s: %s", target, e)
                        delivered = True
                        break

                    # 2) loaded_message 의 file_id 를 직접 사용해서 발송
                    try:
                        if file_type == "photo":
                            await client.send_photo(
                                chat_id=user.id,
                                photo=file_id,
                                caption=user_caption,
                                reply_markup=keyboard,
                            )
                        elif file_type == "video":
                            await client.send_video(
                                chat_id=user.id,
                                video=file_id,
                                caption=user_caption,
                                reply_markup=keyboard,
                            )
                        else:
                            await client.send_document(
                                chat_id=user.id,
                                document=file_id,
                                caption=user_caption,
                                reply_markup=keyboard,
                            )
                        sent += 1
                        delivered = True
                        break
                    except FloodWait as e:
                        wait = e.value + 5
                        acc["cooldown_until"] = now + wait
                        warn = (
                            f"⚠️ [{acc['label']}] FloodWait {wait}초 — 계정 쿨다운 후 "
                            f"다음 계정으로 로테이션."
                        )
                        logger.warning(warn)
                        if notify_callback:
                            await notify_callback(warn)
                        # 다른 계정으로 시도
                        continue
                    except (
                        UserIsBlocked,
                        InputUserDeactivated,
                        PeerIdInvalid,
                        UsernameNotOccupied,
                        UsernameInvalid,
                        UserPrivacyRestricted,
                        UserNotParticipant,
                    ) as e:
                        logger.warning("Skipping %s (send): %s", target, e)
                        skipped += 1
                        delivered = True
                        break
                    except RPCError as e:
                        failed += 1
                        logger.error("RPCError for %s: %s", target, e)
                        delivered = True
                        break
                    except Exception as e:
                        failed += 1
                        logger.error("Unexpected error for %s: %s", target, e)
                        delivered = True
                        break

                if delivered:
                    batch_done.append(uid)

                await asyncio.sleep(random.uniform(USER_DELAY_MIN, USER_DELAY_MAX))

            if batch_done:
                mark_sent(batch_done)
            remaining = count_unsent_with_username()
            progress = (
                f"📤 배치 완료 | 성공: {sent} / 건너뜀: {skipped} / 실패: {failed} | 남은: {remaining}명"
            )
            logger.info(progress)
            if notify_callback:
                await notify_callback(progress)

            if remaining == 0:
                break
            await asyncio.sleep(random.uniform(LONG_BREAK_MIN, LONG_BREAK_MAX))
            batch = _fetch_batch()
            batch_done = []

    finally:
        # 클라이언트 종료
        for acc in accounts:
            client = acc["client"]
            try:
                await client.stop()
            except Exception:
                pass

    return {"total": total_sendable, "sent": sent, "failed": failed, "skipped": skipped}
