import asyncio
import logging
import os
import sys
import time

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


async def broadcast_via_userbot(
    *,
    bot_token: str = "",
    notify_callback=None,
) -> dict:
    from app.pg_broadcast import (
        generate_unique_ref,
        get_loaded_message,
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

    # ── 1. 장전 메시지 확인 ──────────────────
    loaded = get_loaded_message()
    if not loaded:
        await _notify("❌ 장전된 메시지가 없습니다. /admin 에서 미디어를 장전해 주세요.")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    saved_msg_id = int(loaded[0])
    file_type    = str(loaded[1]) if loaded[1] else "photo"
    caption      = str(loaded[2]) if loaded[2] else ""

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

    # ── 4. Pyrogram 클라이언트 초기화 ─────────
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
                "cooldown_until": float(0),
            })
        except Exception as e:
            logger.warning("계정 초기화 실패 %s: %s", label, e)

    if not accounts:
        await _notify("❌ 사용 가능한 UserBot 계정이 없습니다.")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    # 클라이언트 시작
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

    # ── 5. 발송 루프 ──────────────────────────
    sent    = 0
    skipped = 0
    failed  = 0
    acc_idx = 0  # 라운드 로빈 인덱스

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

                user_caption = caption.replace(AFFILIATE_URL, link) if AFFILIATE_URL and AFFILIATE_URL in caption else caption

                # 발송 시도 (최대 계정 수만큼)
                delivered = False
                attempts  = 0

                while not delivered and attempts < len(accounts):
                    # 계정 선택 (라운드 로빈)
                    acc = accounts[acc_idx % len(accounts)]
                    acc_idx += 1
                    attempts += 1

                    now = time.time()
                    cooldown = float(acc.get("cooldown_until") or 0)

                    if cooldown > now:
                        wait_sec = cooldown - now
                        logger.info("%s 쿨다운 중 (%.0f초 남음)", acc["label"], wait_sec)
                        continue

                    client = acc["client"]

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
                            message_id=saved_msg_id,
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
                    # 모든 계정이 쿨다운 중 → 가장 빠른 쿨다운까지 대기
                    next_ready = min(
                        float(a.get("cooldown_until") or 0) for a in accounts
                    )
                    wait_sec = max(0.0, next_ready - time.time())
                    if wait_sec > 0:
                        logger.info("전 계정 쿨다운 중 - %.0f초 대기", wait_sec)
                        await asyncio.sleep(wait_sec)
                    # 재시도 없이 실패 처리
                    failed += 1
                    batch_done.append(uid)

                # 딜레이
                delay = USER_DELAY_MIN + (USER_DELAY_MAX - USER_DELAY_MIN) * (
                    (sent + skipped + failed) % 10
                ) / 10
                await asyncio.sleep(delay)

                # 긴 휴식
                if (sent + skipped + failed) % LONG_BREAK_EVERY == 0 and (sent + skipped + failed) > 0:
                    break_time = LONG_BREAK_MIN + (LONG_BREAK_MAX - LONG_BREAK_MIN) // 2
                    logger.info("긴 휴식 %d초", break_time)
                    await _notify(f"⏸ 스팸 방지 휴식 중... ({break_time}초)")
                    await asyncio.sleep(break_time)

            # 배치 DB 업데이트
            if batch_done:
                mark_sent(batch_done)
                await _notify(
                    f"📦 배치 완료 | 성공: {sent} / 건너뜀: {skipped} / 실패: {failed} | 남은: {total_unsent - sent - skipped - failed}명"
                )

    finally:
        for acc in accounts:
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