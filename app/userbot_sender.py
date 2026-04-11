import asyncio
import io
import logging
import os
import sys
import time

import httpx

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyrogram import Client
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    RPCError,
    UserIsBlocked,
    UserNotParticipant,
    UserPrivacyRestricted,
    UsernameInvalid,
    UsernameNotOccupied,
)

logger = logging.getLogger(__name__)

# ── 환경변수 ──────────────────────────────────
API_ID   = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")

# 딜레이 설정
USER_DELAY_MIN   = int(os.getenv("USER_DELAY_MIN",   "3"))
USER_DELAY_MAX   = int(os.getenv("USER_DELAY_MAX",   "7"))
LONG_BREAK_EVERY = int(os.getenv("LONG_BREAK_EVERY", "50"))
LONG_BREAK_MIN   = int(os.getenv("LONG_BREAK_MIN",   "300"))
LONG_BREAK_MAX   = int(os.getenv("LONG_BREAK_MAX",   "600"))
BATCH_SIZE       = int(os.getenv("BATCH_SIZE",       "50"))

TRACKING_SERVER_URL = os.getenv("TRACKING_SERVER_URL", "").rstrip("/")
AFFILIATE_URL       = os.getenv("AFFILIATE_URL", "")


def _load_sessions() -> list[tuple[str, str]]:
    """SESSION_STRING_1 ~ SESSION_STRING_10 또는 SESSION_STRING 로드"""
    sessions = []
    for i in range(1, 11):
        key = f"SESSION_STRING_{i}"
        val = os.getenv(key, "").strip()
        if val:
            sessions.append((key, val))
    if not sessions:
        val = os.getenv("SESSION_STRING", "").strip()
        if val:
            sessions.append(("SESSION_STRING", val))
    return sessions


async def _download_via_bot_api(bot_token: str, file_id: str) -> bytes:
    """Bot API를 통해 파일 다운로드 후 bytes 반환."""
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
        return dl.content


async def _upload_to_saved_messages(
    client: Client,
    file_bytes: bytes,
    file_type: str,
    caption: str,
    label: str = "?",
) -> int:
    """각 세션의 Saved Messages에 미디어를 업로드하고 message_id 반환."""
    bio = io.BytesIO(file_bytes)
    bio.seek(0)

    # ── 진단 로그 ──────────────────────────────────────────────────────────
    bio.name = "media.mp4" if file_type == "video" else ("media.jpg" if file_type == "photo" else "media.file")
    is_connected = await client.get_me() is not None
    logger.info(
        "[upload-diag] label=%s | file_type=%s | file_size=%d bytes | "
        "bio.name=%s | pyrogram_connected=%s",
        label, file_type, len(file_bytes), bio.name, is_connected,
    )
    # ───────────────────────────────────────────────────────────────────────

    if file_type == "video":
        bio.name = "media.mp4"
        try:
            sent = await client.send_video(
                "me", bio,
                caption=caption,
                duration=0,
                width=0,
                height=0,
                supports_streaming=True,
            )
        except Exception:
            logger.warning("[%s] send_video 실패 → send_document 로 재시도", label)
            bio = io.BytesIO(file_bytes)
            bio.seek(0)
            bio.name = "media.mp4"
            sent = await client.send_document("me", bio, caption=caption)
    elif file_type == "photo":
        bio.name = "media.jpg"
        try:
            sent = await client.send_photo("me", bio, caption=caption)
        except Exception:
            logger.warning("[%s] send_photo 실패 → send_document 로 재시도", label)
            bio = io.BytesIO(file_bytes)
            bio.seek(0)
            bio.name = "media.jpg"
            sent = await client.send_document("me", bio, caption=caption)
    else:
        bio.name = "media.mp4"
        sent = await client.send_document("me", bio, caption=caption)
    return sent.id


async def broadcast_via_userbot(
    *,
    bot_token: str = "",
    file_id: str = "",
    file_type: str = "photo",
    caption: str = "",
    notify_callback=None,
) -> dict:
    from app.pg_broadcast import (
        generate_unique_ref,
        get_unsent_users,
        mark_sent,
        count_unsent_with_username,
    )

    async def _notify(msg: str):
        if notify_callback:
            try:
                await notify_callback(msg)
            except Exception:
                pass

    # ── 1. 파일 다운로드 ──────────────────────
    if not file_id or not bot_token:
        await _notify("❌ file_id 또는 bot_token이 없습니다.")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    await _notify("⬇️ Bot API에서 파일 다운로드 중...")
    try:
        file_bytes = await _download_via_bot_api(bot_token, file_id)
        logger.info("파일 다운로드 완료 (%d bytes)", len(file_bytes))
    except Exception as e:
        await _notify(f"❌ 파일 다운로드 실패: {e}")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    # ── 2. 세션 로드 ──────────────────────────
    sessions = _load_sessions()
    if not sessions:
        await _notify("❌ SESSION_STRING 환경변수가 없습니다.")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    # ── 3. 발송 대상 확인 ─────────────────────
    total_unsent = count_unsent_with_username()
    if total_unsent == 0:
        await _notify("ℹ️ 발송 가능한 유저가 없습니다.")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    await _notify(
        f"🚀 UserBot 발송 시작!\n"
        f"대상: {total_unsent}명 | 계정 수: {len(sessions)} | DM 간격 {USER_DELAY_MIN}~{USER_DELAY_MAX}초"
    )

    # ── 4. Pyrogram 클라이언트 초기화 및 시작 ──
    accounts = []
    for label, session_string in sessions:
        try:
            client = Client(
                name=label,
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=session_string,
                in_memory=True,
            )
            accounts.append({
                "label":          label,
                "client":         client,
                "cooldown_until": 0.0,
                "msg_id":         None,
            })
        except Exception as e:
            logger.warning("계정 초기화 실패 %s: %s", label, e)

    if not accounts:
        await _notify("❌ 사용 가능한 UserBot 계정이 없습니다.")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    started = []
    for acc in accounts:
        try:
            await acc["client"].start()
            started.append(acc)
            logger.info("계정 시작: %s", acc["label"])
        except Exception as e:
            logger.warning("계정 시작 실패 %s: %s", acc["label"], e)

    if not started:
        await _notify("❌ 시작된 UserBot 계정이 없습니다.")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    accounts = started

    # ── 5. 각 세션의 Saved Messages에 업로드 ──
    await _notify("📤 각 계정 Saved Messages에 미디어 업로드 중...")
    valid_accounts = []
    for acc in accounts:
        try:
            msg_id = await _upload_to_saved_messages(
                acc["client"], file_bytes, file_type, caption,
                label=acc["label"],
            )
            acc["msg_id"] = msg_id
            valid_accounts.append(acc)
            logger.info("%s Saved Messages 업로드 완료 (msg_id=%d)", acc["label"], msg_id)
        except Exception as e:
            logger.exception("%s 업로드 실패", acc["label"])

    if not valid_accounts:
        await _notify("❌ 미디어 업로드에 성공한 계정이 없습니다.")
        # 클라이언트 정리
        for acc in accounts:
            try:
                await acc["client"].stop()
            except Exception:
                pass
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    accounts = valid_accounts

    # ── 6. 발송 루프 ──────────────────────────
    sent    = 0
    skipped = 0
    failed  = 0
    acc_idx = 0

    try:
        while True:
            users = get_unsent_users(limit=BATCH_SIZE)
            if not users:
                break

            batch_done = []

            for uid, username in users:
                if not username:
                    skipped += 1
                    batch_done.append(uid)
                    continue

                username_clean = username.lstrip("@")
                target = f"@{username_clean}"

                # 추적 링크 생성
                ref = generate_unique_ref(uid)
                try:
                    from app.pg_broadcast import _get_conn
                    conn = _get_conn()
                    cur  = conn.cursor()
                    cur.execute(
                        "UPDATE broadcast_targets SET unique_ref=%s WHERE telegram_user_id=%s",
                        (ref, uid),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception:
                    pass

                if TRACKING_SERVER_URL:
                    link = f"{TRACKING_SERVER_URL}/track/{ref}"
                else:
                    link = AFFILIATE_URL

                user_caption = (
                    caption.replace(AFFILIATE_URL, link)
                    if AFFILIATE_URL and AFFILIATE_URL in caption
                    else caption
                )

                # 발송 시도 (최대 계정 수만큼)
                delivered = False
                attempts  = 0

                while not delivered and attempts < len(accounts):
                    acc = accounts[acc_idx % len(accounts)]
                    acc_idx += 1
                    attempts += 1

                    now = time.time()
                    cooldown = acc.get("cooldown_until") or 0.0

                    if cooldown > now:
                        wait_sec = cooldown - now
                        logger.info("%s 쿨다운 중 (%.0f초 남음)", acc["label"], wait_sec)
                        continue

                    client  = acc["client"]
                    msg_id  = acc["msg_id"]

                    # peer resolve
                    try:
                        user_obj = await client.get_users(target)
                    except FloodWait as e:
                        wait = int(e.value or 30) + 5
                        acc["cooldown_until"] = float(time.time() + wait)
                        logger.warning("%s FloodWait(get_users) %s초", acc["label"], wait)
                        continue
                    except (PeerIdInvalid, UsernameNotOccupied, UsernameInvalid,
                            UserPrivacyRestricted, InputUserDeactivated, UserIsBlocked,
                            UserNotParticipant) as e:
                        logger.warning("Skipping %s (get_users): %s", target, e)
                        skipped += 1
                        delivered = True
                        batch_done.append(uid)
                        break
                    except Exception as e:
                        logger.error("get_users 오류 %s: %s", target, e)
                        failed += 1
                        delivered = True
                        batch_done.append(uid)
                        break

                    # 메시지 발송
                    try:
                        await client.copy_message(
                            chat_id=user_obj.id,
                            from_chat_id="me",
                            message_id=msg_id,
                            caption=user_caption,
                        )
                        sent += 1
                        delivered = True
                        batch_done.append(uid)
                        logger.info("발송 성공: %s", target)
                    except FloodWait as e:
                        wait = int(e.value or 30) + 5
                        acc["cooldown_until"] = float(time.time() + wait)
                        logger.warning("%s FloodWait(copy_message) %s초", acc["label"], wait)
                        continue
                    except (PeerIdInvalid, UsernameNotOccupied, UsernameInvalid,
                            UserPrivacyRestricted, InputUserDeactivated, UserIsBlocked,
                            UserNotParticipant) as e:
                        logger.warning("Skipping %s (copy_message): %s", target, e)
                        skipped += 1
                        delivered = True
                        batch_done.append(uid)
                        break
                    except RPCError as e:
                        logger.error("RPCError %s: %s", target, e)
                        failed += 1
                        delivered = True
                        batch_done.append(uid)
                        break
                    except Exception as e:
                        logger.error("발송 오류 %s: %s", target, e)
                        failed += 1
                        delivered = True
                        batch_done.append(uid)
                        break

                if not delivered:
                    # 전 계정 쿨다운 → 가장 빠른 쿨다운까지 대기
                    next_ready = min(
                        float(a.get("cooldown_until") or 0.0) for a in accounts
                    )
                    wait_sec = max(0.0, next_ready - time.time())
                    if wait_sec > 0:
                        logger.info("전 계정 쿨다운 중 - %.0f초 대기", wait_sec)
                        await asyncio.sleep(wait_sec)
                    failed += 1
                    batch_done.append(uid)

                # 딜레이
                delay = USER_DELAY_MIN + (USER_DELAY_MAX - USER_DELAY_MIN) * (
                    (sent + skipped + failed) % 10
                ) / 10
                await asyncio.sleep(delay)

                # 긴 휴식
                total_done = sent + skipped + failed
                if total_done > 0 and total_done % LONG_BREAK_EVERY == 0:
                    break_time = LONG_BREAK_MIN + (LONG_BREAK_MAX - LONG_BREAK_MIN) // 2
                    logger.info("긴 휴식 %d초", break_time)
                    await _notify(f"⏸ 스팸 방지 휴식 중... ({break_time}초)")
                    await asyncio.sleep(break_time)

            # 배치 DB 업데이트
            if batch_done:
                mark_sent(batch_done)
                await _notify(
                    f"📦 배치 완료 | 성공: {sent} / 건너뜀: {skipped} / 실패: {failed} | "
                    f"남은: {total_unsent - sent - skipped - failed}명"
                )

    finally:
        # Saved Messages 정리 및 클라이언트 종료
        for acc in accounts:
            try:
                if acc.get("msg_id"):
                    await acc["client"].delete_messages("me", acc["msg_id"])
            except Exception:
                pass
            try:
                await acc["client"].stop()
            except Exception:
                pass

    result = {"total": total_unsent, "sent": sent, "skipped": skipped, "failed": failed}
    await _notify(
        f"✅ UserBot 발송 완료\n"
        f"성공: {sent}명 | 건너뜀: {skipped}명 | 실패: {failed}명"
    )
    return result
