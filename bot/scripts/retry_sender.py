#!/usr/bin/env python3
"""
UserBot DM 재발송(retry) 캠페인 스크립트.

목적:
  - 이미 1차 DM을 받았지만 링크를 클릭하지 않은 유저에게
    3일 후 다른 메시지(RETRY_CAPTION)로 한 번 더 발송.

재발송 대상 조건 (broadcast_targets):
  - is_sent = TRUE  (1차 발송 완료)
  - COALESCE(click_count, 0) = 0  (한 번도 클릭하지 않음)
  - retry_sent = FALSE           (재발송 아직 안 함)
  - sent_at <= now - 3 days
  - username IS NOT NULL AND username <> ''

메시지:
  - 환경변수 RETRY_CAPTION 사용 (필수)
  - 기존 AFFILIATE_URL → {TRACKING_SERVER_URL}/track/{unique_ref} 로 치환
    (userbot_sender 와 동일한 추적 로직 재사용)

실행 예:
  python3.12 bot/scripts/retry_sender.py
"""
from __future__ import annotations

import asyncio
import os
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

import sys  # noqa: E402

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pg_broadcast import (  # type: ignore  # noqa: E402
    get_retry_targets,
    mark_retry_sent,
    generate_unique_ref,
    get_campaign_stats,
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

# 스팸 방어 파라미터 (userbot_sender 와 동일한 방식)
USER_DELAY_MIN = float(os.getenv("USER_DELAY_MIN", "3"))
USER_DELAY_MAX = float(os.getenv("USER_DELAY_MAX", "7"))
LONG_BREAK_EVERY = int(os.getenv("LONG_BREAK_EVERY", "50"))
LONG_BREAK_MIN = float(os.getenv("LONG_BREAK_MIN", "300"))  # 5분
LONG_BREAK_MAX = float(os.getenv("LONG_BREAK_MAX", "600"))  # 10분


async def _notify(text: str) -> None:
    """관리자에게 진행 상황/에러를 Bot API로 전송 (실패는 무시)."""
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
        pass


async def _download_via_bot_api(file_id: str) -> tuple[bytes, str]:
    """Bot API로 file_id 에 해당하는 파일을 다운로드."""
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
        remote_path: str = data["result"]["file_path"]
        dl = await hc.get(
            f"https://api.telegram.org/file/bot{BOT_TOKEN}/{remote_path}",
        )
        dl.raise_for_status()
        return dl.content, remote_path


async def run_retry_campaign() -> None:
    if not API_ID or not API_HASH or not SESSION_STRING:
        print("❌ API_ID / API_HASH / SESSION_STRING 이 설정되지 않았습니다.")
        return
    if not RETRY_CAPTION:
        print("❌ RETRY_CAPTION 환경변수가 비어 있습니다. 재발송 메시지를 설정해주세요.")
        return

    # 재발송 대상 조회
    targets = get_retry_targets()
    if not targets:
        await _notify("🔁 재발송 대상이 없습니다. (조건을 만족하는 유저 없음)")
        return

    await _notify(
        "🔁 재발송 캠페인 시작\n"
        f"재발송 대상: {len(targets)}명\n"
        "조건: 3일 전 발송, 미클릭(click_count=0), retry_sent=FALSE"
    )

    # 장전된 미디어(loaded_message)에서 file_id, file_type 읽기 (dm_campaign_runner 와 공유)
    db_path = ROOT / "data" / "users.db"
    if not db_path.is_file():
        await _notify("❌ 재발송 실패: loaded_message DB가 없습니다.")
        return

    import sqlite3

    conn_sql = sqlite3.connect(str(db_path))
    try:
        cur = conn_sql.execute(
            "SELECT file_id, file_type FROM loaded_message WHERE id = 1"
        )
        row = cur.fetchone()
    finally:
        conn_sql.close()

    if not row:
        await _notify("❌ 재발송 실패: loaded_message 레코드가 없습니다.")
        return

    file_id, file_type = row
    file_id = file_id or ""
    file_type = file_type or "photo"
    if not file_id:
        await _notify("❌ 재발송 실패: loaded_message.file_id 가 비어 있습니다.")
        return

    # 파일 다운로드
    await _notify("⬇️ 재발송용 미디어 다운로드 중 (Bot API)...")
    file_bytes, remote_path = await _download_via_bot_api(file_id)

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("VIP CASINO", url=VIP_URL)]]
    )

    sent = failed = 0
    total = len(targets)

    async with Client(
        name="userbot_retry_campaign",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING,
    ) as client:
        # Saved Messages 에 1회 업로드
        import io

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
            f"🔁 재발송 DM 시작\n"
            f"대상: {total}명\n"
            f"DM 간격: {USER_DELAY_MIN:.0f}~{USER_DELAY_MAX:.0f}초 / "
            f"{LONG_BREAK_EVERY}명마다 {LONG_BREAK_MIN/60:.0f}~{LONG_BREAK_MAX/60:.0f}분 휴식"
        )

        batch_done: list[int] = []

        for idx, (uid, raw_username) in enumerate(targets, start=1):
            username_clean = (raw_username or "").lstrip("@").strip()
            if not username_clean:
                continue
            target = f"@{username_clean}"

            # 유저별 추적 링크 생성
            user_caption = RETRY_CAPTION
            tracking_url = None
            if AFFILIATE_URL and TRACKING_SERVER_URL:
                try:
                    ref = generate_unique_ref(uid)
                    if ref:
                        tracking_url = f"{TRACKING_SERVER_URL}/track/{ref}"
                except Exception as e:
                    print(f"generate_unique_ref 실패 uid={uid}: {e}")
            if tracking_url:
                try:
                    user_caption = RETRY_CAPTION.replace(AFFILIATE_URL, tracking_url)
                except Exception:
                    user_caption = RETRY_CAPTION

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
                    wait = e.value + 5
                    await _notify(f"⚠️ FloodWait {wait}초 (retry, {target})")
                    await asyncio.sleep(wait)
                except (UserIsBlocked, InputUserDeactivated):
                    delivered = True
                    break
                except (PeerIdInvalid, UsernameNotOccupied, UsernameInvalid):
                    delivered = True
                    break
                except RPCError as e:
                    print(f"RPCError retry uid={uid}: {e}")
                    failed += 1
                    delivered = True
                    break
                except Exception as e:
                    print(f"Unexpected retry error uid={uid}: {e}")
                    failed += 1
                    delivered = True
                    break

            if delivered:
                batch_done.append(uid)

            # per-user delay
            await asyncio.sleep(
                max(0.0, min(USER_DELAY_MAX, USER_DELAY_MIN))
                if USER_DELAY_MAX <= USER_DELAY_MIN
                else __import__("random").uniform(USER_DELAY_MIN, USER_DELAY_MAX)
            )

            # 배치 단위로 retry_sent 플래그 업데이트 + 휴식
            if idx % LONG_BREAK_EVERY == 0 or idx == total:
                if batch_done:
                    mark_retry_sent(batch_done)
                remaining = max(0, total - idx)
                await _notify(
                    f"🔁 재발송 진행 상황: {idx}/{total}명 처리 "
                    f"(성공 {sent}명 / 실패 {failed}명 / 남은 {remaining}명)"
                )
                if remaining > 0:
                    import random

                    cooldown = random.uniform(LONG_BREAK_MIN, LONG_BREAK_MAX)
                    await _notify(
                        f"🛡️ 재발송 스팸 방지 휴식 {cooldown/60:.1f}분 후 재개"
                    )
                    await asyncio.sleep(cooldown)
                batch_done = []

        # Saved Messages 정리
        try:
            await client.delete_messages("me", saved_msg_id)
        except Exception:
            pass

    # 통계/리포트
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

