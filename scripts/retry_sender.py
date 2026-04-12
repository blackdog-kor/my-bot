"""
재발송: is_sent=TRUE, click_count=0, retry_sent=FALSE, sent_at 기준 3일 경과.
RETRY_CAPTION 환경변수로 별도 캡션 사용 (없으면 원본 캡션 유지).
실행: python scripts/retry_sender.py (또는 스케줄러 12:00)

발송 흐름:
  1. loaded_message 에서 file_id / file_type 읽기
  2. get_retry_targets() 로 재발송 대상 조회
  3. Bot API 파일 다운로드 → Pyrogram 다중 계정으로 발송
  4. mark_retry_sent() 로 DB 업데이트
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import random
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "bot" / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("retry_sender")

API_ID   = int((os.getenv("API_ID")   or "0").strip())
API_HASH = (os.getenv("API_HASH") or "").strip()
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None
RETRY_CAPTION = (os.getenv("RETRY_CAPTION") or "").strip()

VIP_URL          = (os.getenv("VIP_URL") or "https://1wwtgq.com/?p=mskf").strip()
USER_DELAY_MIN   = float(os.getenv("USER_DELAY_MIN",   "3"))
USER_DELAY_MAX   = float(os.getenv("USER_DELAY_MAX",   "7"))
LONG_BREAK_EVERY = int(  os.getenv("LONG_BREAK_EVERY", "50"))
LONG_BREAK_MIN   = float(os.getenv("LONG_BREAK_MIN",   "300"))
LONG_BREAK_MAX   = float(os.getenv("LONG_BREAK_MAX",   "600"))


def _load_sessions() -> list[tuple[str, str]]:
    sessions: list[tuple[str, str]] = []
    for i in range(1, 11):
        val = (os.getenv(f"SESSION_STRING_{i}") or "").strip()
        if val:
            sessions.append((f"SESSION_STRING_{i}", val))
    if not sessions:
        val = (os.getenv("SESSION_STRING") or "").strip()
        if val:
            sessions.append(("SESSION_STRING", val))
    return sessions


async def _notify(text: str) -> None:
    if not BOT_TOKEN or not ADMIN_ID:
        return
    try:
        async with httpx.AsyncClient(timeout=15) as hc:
            await hc.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": ADMIN_ID,
                    "text": (text or "")[:4000],
                    "disable_web_page_preview": True,
                },
            )
    except Exception:
        pass


async def _download_via_bot_api(bot_token: str, file_id: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=120) as hc:
        r = await hc.get(
            f"https://api.telegram.org/bot{bot_token}/getFile",
            params={"file_id": file_id},
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"getFile 실패: {data}")
        remote_path: str = data["result"]["file_path"]
        dl = await hc.get(
            f"https://api.telegram.org/file/bot{bot_token}/{remote_path}",
        )
        dl.raise_for_status()
        return dl.content, remote_path


async def main() -> None:
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
    from app.pg_broadcast import get_retry_targets, mark_retry_sent
    from bot.handlers.callbacks import get_loaded_message_full

    print("\n" + "=" * 62)
    print("   재발송 스크립트  (3일 경과 미클릭 유저)")
    print("=" * 62)

    # ── 1. 장전된 메시지 확인 ──────────────────────────────────────────────────
    loaded = get_loaded_message_full()
    if not loaded:
        msg = "❌ 재발송 실패: 장전된 메시지가 없습니다."
        print(msg)
        await _notify(msg)
        return

    _chat_id, _msg_id, file_id, file_type, original_caption = loaded
    if not file_id:
        msg = "❌ 재발송 실패: loaded_message에 file_id가 비어 있습니다."
        print(msg)
        await _notify(msg)
        return

    caption = RETRY_CAPTION or original_caption

    # ── 2. 재발송 대상 확인 ───────────────────────────────────────────────────
    targets = get_retry_targets()
    if not targets:
        print("ℹ️  재발송 대상 없음 (3일 경과 미클릭 유저 없음)")
        await _notify("ℹ️  재발송 대상 없음 — 3일 경과 미클릭 유저가 없습니다.")
        return

    print(f"✅ 재발송 대상: {len(targets)}명")
    await _notify(
        f"🔁 재발송 시작\n"
        f"• 대상: {len(targets)}명\n"
        f"• 캡션: {'RETRY_CAPTION' if RETRY_CAPTION else '원본 유지'}"
    )

    # ── 3. 파일 다운로드 ──────────────────────────────────────────────────────
    try:
        file_bytes, remote_path = await _download_via_bot_api(BOT_TOKEN, file_id)
        logger.info("파일 다운로드 완료 (%d bytes)", len(file_bytes))
    except Exception as e:
        await _notify(
            f"❌ 재발송 파일 다운로드 실패\n"
            f"에러타입: {type(e).__name__}\n에러내용: {e}"
        )
        return

    # ── 4. 세션 로드 + 클라이언트 시작 ───────────────────────────────────────
    sessions = _load_sessions()
    if not sessions:
        await _notify("❌ SESSION_STRING 환경변수가 없습니다.")
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("VIP CASINO", url=VIP_URL)]]
    )
    all_started: list[dict] = []
    accounts:    list[dict] = []

    for label, session_str in sessions:
        client_obj = None
        try:
            client_obj = Client(
                name=label,
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=session_str,
                in_memory=True,
            )
            await client_obj.start()
            acc_entry = {
                "label":          label,
                "client":         client_obj,
                "cooldown_until": 0.0,
                "cached_file_id": None,
            }
            all_started.append(acc_entry)
            me = await client_obj.get_me()
            logger.info("세션 연결 성공: %s @%s", label, me.username)
            accounts.append(acc_entry)
        except Exception as e:
            logger.exception("세션 시작 실패: %s", label)
            await _notify(
                f"⚠️ {label} 세션 만료 — 건너뜀\n{type(e).__name__}: {e}"
            )
            if client_obj and all_started and all_started[-1]["label"] == label:
                try:
                    await client_obj.stop()
                except Exception:
                    pass
                all_started.pop()

    if not accounts:
        await _notify("❌ 정상 연결된 UserBot 계정이 없습니다.")
        return

    # ── 헬퍼 ─────────────────────────────────────────────────────────────────
    def _make_bio() -> io.BytesIO:
        bio = io.BytesIO(file_bytes)
        bio.seek(0)
        if file_type == "video":
            bio.name = "media.mp4"
        elif file_type == "photo":
            bio.name = "media.jpg"
        else:
            ext = remote_path.rsplit(".", 1)[-1] if "." in remote_path else "bin"
            bio.name = f"media.{ext}"
        return bio

    SKIP_ERRORS = (
        UserIsBlocked,
        InputUserDeactivated,
        PeerIdInvalid,
        UsernameNotOccupied,
        UsernameInvalid,
        UserPrivacyRestricted,
        UserNotParticipant,
    )

    # ── 5. 발송 루프 ──────────────────────────────────────────────────────────
    sent    = 0
    skipped = 0
    failed  = 0
    acc_idx = 0
    done_ids: list[int] = []

    try:
        for uid, username in targets:
            username_clean = (username or "").lstrip("@").strip()
            if not username_clean:
                skipped += 1
                done_ids.append(uid)
                continue

            target    = f"@{username_clean}"
            delivered = False
            attempts  = 0

            while not delivered and attempts < len(accounts):
                acc     = accounts[acc_idx % len(accounts)]
                acc_idx += 1
                attempts += 1

                if (acc.get("cooldown_until") or 0.0) > time.time():
                    continue

                client: Client = acc["client"]

                # Step A: peer 해석
                try:
                    await client.get_users(target)
                except FloodWait as e:
                    wait = int(e.value or 30) + 5
                    acc["cooldown_until"] = time.time() + wait
                    logger.warning("%s get_users FloodWait %ds", acc["label"], wait)
                    continue
                except SKIP_ERRORS as e:
                    logger.info("skip %s (get_users): %s", target, type(e).__name__)
                    skipped += 1
                    delivered = True
                    done_ids.append(uid)
                    break
                except Exception as e:
                    logger.exception("get_users 실패: %s", target)
                    failed += 1
                    delivered = True
                    done_ids.append(uid)
                    break

                # Step B: 발송
                try:
                    cached = acc["cached_file_id"]
                    src    = cached if cached else _make_bio()

                    if file_type == "video":
                        msg = await client.send_video(
                            target, src,
                            caption=caption,
                            duration=0, width=0, height=0,
                            supports_streaming=True,
                            reply_markup=keyboard,
                        )
                        if not cached and msg.video:
                            acc["cached_file_id"] = msg.video.file_id
                    elif file_type == "photo":
                        msg = await client.send_photo(
                            target, src,
                            caption=caption,
                            reply_markup=keyboard,
                        )
                        if not cached and msg.photo:
                            acc["cached_file_id"] = msg.photo.file_id
                    else:
                        msg = await client.send_document(
                            target, src,
                            caption=caption,
                            reply_markup=keyboard,
                        )
                        if not cached and msg.document:
                            acc["cached_file_id"] = msg.document.file_id

                    sent += 1
                    delivered = True
                    done_ids.append(uid)
                    logger.info(
                        "✅ 재발송 성공: %s (계정=%s, 누적 sent=%d)",
                        target, acc["label"], sent,
                    )

                except FloodWait as e:
                    wait = int(e.value or 30) + 5
                    acc["cooldown_until"] = time.time() + wait
                    logger.warning("%s send FloodWait %ds", acc["label"], wait)

                except SKIP_ERRORS as e:
                    logger.info("skip %s (send): %s", target, type(e).__name__)
                    skipped += 1
                    delivered = True
                    done_ids.append(uid)

                except (RPCError, Exception) as e:
                    logger.exception("재발송 실패: %s", target)
                    await _notify(
                        f"❌ 재발송 실패\n"
                        f"계정: {acc['label']}\n대상: {target}\n"
                        f"에러타입: {type(e).__name__}\n에러내용: {e}"
                    )
                    failed += 1
                    delivered = True
                    done_ids.append(uid)

            if not delivered:
                failed += 1
                done_ids.append(uid)

            await asyncio.sleep(random.uniform(USER_DELAY_MIN, USER_DELAY_MAX))

            total_done = sent + skipped + failed
            if total_done > 0 and total_done % LONG_BREAK_EVERY == 0:
                break_sec = random.uniform(LONG_BREAK_MIN, LONG_BREAK_MAX)
                logger.info("스팸 방지 휴식 %.1f분", break_sec / 60)
                await _notify(
                    f"⏸ 재발송 휴식 {break_sec / 60:.0f}분 (누적 {total_done}명)"
                )
                await asyncio.sleep(break_sec)

    finally:
        if done_ids:
            mark_retry_sent(done_ids)
        for acc in all_started:
            try:
                await acc["client"].stop()
            except Exception:
                pass

    summary = (
        f"✅ 재발송 완료\n"
        f"• 성공: {sent}명\n"
        f"• 건너뜀(차단·탈퇴·없음): {skipped}명\n"
        f"• 실패: {failed}명"
    )
    print(summary)
    await _notify(summary)


if __name__ == "__main__":
    asyncio.run(main())
