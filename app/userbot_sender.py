"""
UserBot 브로드캐스트 발송 (Pyrogram MTProto).

발송 흐름:
  1. Bot API getFile → BytesIO 다운로드
  2. Pyrogram 세션 시작 + get_me() 즉시 검증 (만료 세션 조기 제거)
  3. 유저별 직접 send_video/send_photo/send_document
     - 계정당 첫 발송: BytesIO 업로드 → file_id 캐시
     - 이후 발송: 캐시된 file_id 재사용 (재업로드 없음)
  4. 실패 시 에러 상세를 admin DM으로 즉시 전송
  5. finally: 시작된 모든 클라이언트 종료
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import random
import sys
import time

import httpx

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

# ── 환경변수 ──────────────────────────────────────────────────────────────────
API_ID   = int((os.getenv("API_ID")   or "0").strip())
API_HASH = (os.getenv("API_HASH") or "").strip()

USER_DELAY_MIN         = float(os.getenv("USER_DELAY_MIN",          "15"))
USER_DELAY_MAX         = float(os.getenv("USER_DELAY_MAX",          "45"))
LONG_BREAK_EVERY       = int(  os.getenv("LONG_BREAK_EVERY",        "50"))
LONG_BREAK_MIN         = float(os.getenv("LONG_BREAK_MIN",          "300"))
LONG_BREAK_MAX         = float(os.getenv("LONG_BREAK_MAX",          "600"))
BATCH_SIZE             = int(  os.getenv("BATCH_SIZE",               "50"))
DAILY_LIMIT_PER_ACCOUNT = int( os.getenv("DAILY_LIMIT_PER_ACCOUNT", "100"))

VIP_URL             = (os.getenv("VIP_URL") or "https://1wwtgq.com/?p=mskf").strip()
AFFILIATE_URL       = (os.getenv("AFFILIATE_URL") or "").strip()  # campaign_config 폴백 전용
TRACKING_SERVER_URL = (os.getenv("TRACKING_SERVER_URL") or "").rstrip("/")
GEMINI_API_KEY      = (os.getenv("GEMINI_API_KEY") or "").strip()


async def personalize_caption(caption: str, username: str) -> str:
    """Gemini 1.5 Flash로 username 기반 언어 감지 후 캡션 재작성. 실패 시 원본 반환."""
    if not GEMINI_API_KEY or not caption or not username:
        return caption
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = (
            f"You are a casino marketing expert.\n"
            f"Detect the likely language/region from the Telegram username \"@{username}\" "
            f"(common Indonesian names/words → Bahasa Indonesia, "
            f"Korean name patterns or hangul characters → Korean, "
            f"otherwise English).\n"
            f"Rewrite the following promotional caption in that detected language.\n"
            f"Rules:\n"
            f"- Keep ALL URLs exactly as-is (do not translate or modify URLs)\n"
            f"- Keep ALL emojis in place\n"
            f"- Preserve line breaks and overall structure\n"
            f"- Only translate the natural language text portions\n"
            f"Respond with ONLY the rewritten caption, nothing else.\n\n"
            f"Caption:\n{caption}"
        )
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, model.generate_content, prompt)
        result = (response.text or "").strip()
        return result if result else caption
    except Exception as e:
        logger.warning("Gemini 개인화 실패 (@%s): %s — 원본 캡션 사용", username, e)
        return caption


# ── 세션 로더 ─────────────────────────────────────────────────────────────────
def _load_sessions() -> list[tuple[str, str]]:
    """SESSION_STRING_1 ~ _10, 없으면 SESSION_STRING 로드."""
    sessions: list[tuple[str, str]] = []
    for i in range(1, 11):
        key = f"SESSION_STRING_{i}"
        val = (os.getenv(key) or "").strip()
        if val:
            sessions.append((key, val))
    if not sessions:
        val = (os.getenv("SESSION_STRING") or "").strip()
        if val:
            sessions.append(("SESSION_STRING", val))
    return sessions


# ── Bot API 다운로드 ───────────────────────────────────────────────────────────
async def _download_via_bot_api(bot_token: str, file_id: str) -> tuple[bytes, str]:
    """Bot API getFile → 파일 bytes + remote_path 반환."""
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


# ── 메인 브로드캐스트 함수 ────────────────────────────────────────────────────
async def broadcast_via_userbot(
    *,
    bot_token: str = "",
    file_id: str = "",
    file_type: str = "photo",
    caption: str = "",
    notify_callback=None,
) -> dict:
    """
    is_sent=FALSE 유저 전원에게 미디어 DM 발송.

    Saved Messages 업로드 없이 BytesIO를 유저에게 직접 발송.
    계정당 첫 발송에서 file_id를 캐시해 이후 재업로드를 방지.
    """
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
    from app.pg_broadcast import (
        generate_unique_ref,
        get_unsent_users,
        mark_sent,
        count_unsent_with_username,
    )

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("VIP CASINO", url=VIP_URL)]]
    )

    async def _notify(msg: str) -> None:
        if notify_callback:
            try:
                await notify_callback(msg)
            except Exception:
                pass

    # ── 0. campaign_config 로드 (DB 우선, 환경변수는 완전히 폴백) ───────────
    try:
        from app.pg_broadcast import get_campaign_config
        _cfg = get_campaign_config()
    except Exception as _cfg_err:
        logger.warning("campaign_config 로드 실패, 환경변수 폴백 사용: %s", _cfg_err)
        _cfg = {}

    # affiliate_url: DB 값이 있으면 사용, 없으면 AFFILIATE_URL 환경변수 폴백
    effective_affiliate_url = (_cfg.get("affiliate_url") or "").strip() or AFFILIATE_URL
    _db_caption_tmpl        = (_cfg.get("caption_template") or "").strip()
    _db_promo_code          = (_cfg.get("promo_code") or "").strip()

    # caption_template이 DB에 있으면 우선 사용, 없으면 장전 캡션 그대로
    effective_caption = _db_caption_tmpl or caption
    if _db_promo_code and "{promo_code}" in effective_caption:
        effective_caption = effective_caption.replace("{promo_code}", _db_promo_code)

    # ── 1. 파일 다운로드 ──────────────────────────────────────────────────────
    if not file_id or not bot_token:
        await _notify("❌ file_id 또는 bot_token이 없습니다.")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    await _notify("⬇️ Bot API에서 파일 다운로드 중...")
    try:
        file_bytes, remote_path = await _download_via_bot_api(bot_token, file_id)
        logger.info("파일 다운로드 완료 (%d bytes, path=%s)", len(file_bytes), remote_path)
    except Exception as e:
        await _notify(
            f"❌ 파일 다운로드 실패\n"
            f"에러타입: {type(e).__name__}\n"
            f"에러내용: {e}"
        )
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    # ── 2. 세션 로드 ──────────────────────────────────────────────────────────
    sessions = _load_sessions()
    if not sessions:
        await _notify("❌ SESSION_STRING 환경변수가 없습니다.")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    # ── 3. 발송 대상 확인 ─────────────────────────────────────────────────────
    total_unsent = count_unsent_with_username()
    if total_unsent == 0:
        await _notify("ℹ️ 발송 가능한 유저(username 보유)가 없습니다.")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    # ── 4. 클라이언트 시작 + get_me() 즉시 검증 ──────────────────────────────
    # all_started : start()까지 성공 (cleanup용)
    # accounts    : get_me()까지 통과한 정상 계정만
    all_started: list[dict] = []
    accounts:    list[dict] = []

    for label, session_string in sessions:
        client_obj = None
        try:
            client_obj = Client(
                name=label,
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=session_string,
                in_memory=True,
            )
            await client_obj.start()
            acc_entry = {
                "label":          label,
                "client":         client_obj,
                "cooldown_until": 0.0,
                "cached_file_id": None,   # 첫 발송 성공 후 Telegram file_id 캐시
                "daily_sent":     0,      # 당일 발송 건수
            }
            all_started.append(acc_entry)

            me = await client_obj.get_me()
            logger.info("세션 연결 성공: %s (id=%s @%s)", label, me.id, me.username)
            accounts.append(acc_entry)

        except Exception as e:
            logger.exception("세션 시작/검증 실패: %s", label)
            await _notify(
                f"⚠️ {label} 세션 만료 또는 연결 실패 — 건너뜀\n"
                f"에러타입: {type(e).__name__}\n"
                f"에러내용: {e}"
            )
            # start()에 성공했으나 get_me()에서 실패한 경우 즉시 정리
            if client_obj is not None and all_started and all_started[-1]["label"] == label:
                try:
                    await client_obj.stop()
                except Exception:
                    pass
                all_started.pop()

    if not accounts:
        await _notify("❌ 정상 연결된 UserBot 계정이 없습니다.")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    await _notify(
        f"✅ 정상 계정 {len(accounts)}/{len(sessions)}개 준비됨 "
        f"({', '.join(a['label'] for a in accounts)})\n"
        f"대상: {total_unsent}명 | DM 간격 {USER_DELAY_MIN:.0f}~{USER_DELAY_MAX:.0f}초"
    )

    # ── 헬퍼: BytesIO 생성 ───────────────────────────────────────────────────
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

    # ── 헬퍼: 미디어 직접 발송 ──────────────────────────────────────────────
    async def _send_to_user(
        acc: dict,
        chat_id: str,          # "@username" 문자열 — get_users() 캐시된 peer를 username key로 조회
        user_caption: str,
    ) -> None:
        """
        미디어를 유저에게 직접 발송.

        chat_id는 반드시 "@username" 문자열이어야 한다.
        호출 전에 같은 client로 get_users(chat_id)를 호출해
        peer cache를 채운 상태여야 PEER_ID_INVALID를 피할 수 있다.

        ❌ user_obj.id 정수 사용 금지:
           in_memory 세션에서 정수→InputPeer 매핑이 누락돼 PEER_ID_INVALID 발생.
        ✅ "@username" 문자열 사용:
           Pyrogram이 get_users()로 캐시된 peer를 username key로 직접 조회.

        - cached_file_id 없음 → BytesIO 업로드 후 file_id 캐시
        - cached_file_id 있음 → 캐시된 file_id 재사용 (재업로드 없음)
        """
        client: Client = acc["client"]
        cached = acc["cached_file_id"]
        src    = cached if cached else _make_bio()

        if file_type == "video":
            msg = await client.send_video(
                chat_id, src,
                caption=user_caption,
                duration=0,
                width=0,
                height=0,
                supports_streaming=True,
                reply_markup=keyboard,
            )
            if not cached and msg.video:
                acc["cached_file_id"] = msg.video.file_id

        elif file_type == "photo":
            msg = await client.send_photo(
                chat_id, src,
                caption=user_caption,
                reply_markup=keyboard,
            )
            if not cached and msg.photo:
                acc["cached_file_id"] = msg.photo.file_id

        else:
            msg = await client.send_document(
                chat_id, src,
                caption=user_caption,
                reply_markup=keyboard,
            )
            if not cached and msg.document:
                acc["cached_file_id"] = msg.document.file_id

    # ── 5. 발송 루프 ──────────────────────────────────────────────────────────
    sent    = 0
    skipped = 0
    failed  = 0
    acc_idx = 0

    # 건너뛰어야 할 예외 집합 (재시도 불필요)
    SKIP_ERRORS = (
        UserIsBlocked,
        InputUserDeactivated,
        PeerIdInvalid,
        UsernameNotOccupied,
        UsernameInvalid,
        UserPrivacyRestricted,
        UserNotParticipant,
    )

    try:
        while True:
            users = get_unsent_users(limit=BATCH_SIZE)
            if not users:
                break

            batch_done: list[int] = []

            for uid, username in users:
                username_clean = (username or "").lstrip("@").strip()
                if not username_clean:
                    skipped += 1
                    batch_done.append(uid)
                    continue

                target = f"@{username_clean}"

                # 추적 링크 생성
                try:
                    ref = generate_unique_ref(uid)
                    from app.pg_broadcast import _get_conn
                    conn = _get_conn()
                    cur  = conn.cursor()
                    cur.execute(
                        "UPDATE broadcast_targets SET unique_ref=%s "
                        "WHERE telegram_user_id=%s",
                        (ref, uid),
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception:
                    ref = None

                if ref and TRACKING_SERVER_URL:
                    link = f"{TRACKING_SERVER_URL}/track/{ref}"
                    user_caption = (
                        effective_caption.replace(effective_affiliate_url, link)
                        if effective_affiliate_url and effective_affiliate_url in effective_caption
                        else effective_caption
                    )
                else:
                    user_caption = effective_caption

                # 구독봇 링크 추가
                _sub_line = "👉 VIP 채널 구독하기\nt.me/blackdog_eve_casino_bot"
                if _sub_line not in user_caption:
                    user_caption = f"{user_caption}\n{_sub_line}"

                # ── Gemini 캡션 개인화 (언어 감지 후 재작성) ────────────────
                user_caption = await personalize_caption(user_caption, username_clean)

                # ── 계정 순환 발송 ───────────────────────────────────────────
                delivered = False
                attempts  = 0

                while not delivered and attempts < len(accounts):
                    acc     = accounts[acc_idx % len(accounts)]
                    acc_idx += 1
                    attempts += 1

                    now      = time.time()
                    cooldown = acc.get("cooldown_until") or 0.0
                    if cooldown > now:
                        logger.info(
                            "%s 쿨다운 중 (%.0f초 남음)", acc["label"], cooldown - now
                        )
                        continue

                    if acc["daily_sent"] >= DAILY_LIMIT_PER_ACCOUNT:
                        logger.info(
                            "%s 일일 한도 도달 (%d/%d) — 건너뜀",
                            acc["label"], acc["daily_sent"], DAILY_LIMIT_PER_ACCOUNT,
                        )
                        continue

                    client: Client = acc["client"]

                    # ── Step A: @username → user.id 해석 ────────────────────
                    try:
                        user_obj = await client.get_users(target)
                        user_id  = user_obj.id
                        logger.info(
                            "[get_users] %s → id=%s @%s (계정=%s)",
                            target, user_id, user_obj.username, acc["label"],
                        )
                    except FloodWait as e:
                        wait = int(e.value or 30) + 5
                        acc["cooldown_until"] = time.time() + wait
                        logger.warning("%s get_users FloodWait %d초", acc["label"], wait)
                        await _notify(f"⚠️ {acc['label']} get_users FloodWait {wait}초")
                        continue   # 다음 계정으로
                    except SKIP_ERRORS as e:
                        logger.info("skip %s (get_users): %s", target, type(e).__name__)
                        skipped += 1
                        delivered = True
                        batch_done.append(uid)
                        break
                    except Exception as e:
                        logger.exception("get_users 실패 %s", target)
                        await _notify(
                            f"❌ get_users 실패\n"
                            f"계정: {acc['label']}\n"
                            f"대상: {target}\n"
                            f"에러타입: {type(e).__name__}\n"
                            f"에러내용: {e}"
                        )
                        failed += 1
                        delivered = True
                        batch_done.append(uid)
                        break

                    # ── Step B: @username 문자열로 발송 (peer cache 활용) ────
                    try:
                        await _send_to_user(acc, target, user_caption)
                        sent += 1
                        acc["daily_sent"] += 1
                        delivered = True
                        batch_done.append(uid)
                        logger.info(
                            "✅ 발송 성공: %s (user_id=%s, db_uid=%s, 계정=%s, "
                            "누적 sent=%d / skip=%d / fail=%d, 계정일일=%d/%d)",
                            target, user_id, uid, acc["label"],
                            sent, skipped, failed,
                            acc["daily_sent"], DAILY_LIMIT_PER_ACCOUNT,
                        )

                    except FloodWait as e:
                        wait = int(e.value or 30) + 5
                        acc["cooldown_until"] = time.time() + wait
                        logger.warning("%s send FloodWait %d초", acc["label"], wait)
                        await _notify(f"⚠️ {acc['label']} send FloodWait {wait}초")
                        # 쿨다운 → 다음 계정으로 재시도

                    except SKIP_ERRORS as e:
                        logger.info("skip %s (send): %s", target, type(e).__name__)
                        skipped += 1
                        delivered = True
                        batch_done.append(uid)

                    except (RPCError, Exception) as e:
                        logger.exception("발송 실패 %s (user_id=%s)", target, user_id)
                        await _notify(
                            f"❌ 발송 실패 상세\n"
                            f"계정: {acc['label']}\n"
                            f"대상: {target} (user_id={user_id})\n"
                            f"에러타입: {type(e).__name__}\n"
                            f"에러내용: {e}"
                        )
                        failed += 1
                        delivered = True
                        batch_done.append(uid)

                if not delivered:
                    # 전 계정이 한도 초과인지 확인
                    all_maxed = all(
                        a["daily_sent"] >= DAILY_LIMIT_PER_ACCOUNT for a in accounts
                    )
                    if all_maxed:
                        await _notify(
                            f"🛑 전 계정 일일 한도 도달 ({DAILY_LIMIT_PER_ACCOUNT}건/계정) — 발송 중단"
                        )
                        batch_done.append(uid)
                        break

                    # 전 계정 쿨다운 → 가장 빠른 해제까지 대기 후 failed 처리
                    next_ready = min(
                        float(a.get("cooldown_until") or 0.0) for a in accounts
                    )
                    wait_sec = max(0.0, next_ready - time.time())
                    if wait_sec > 0:
                        logger.info("전 계정 쿨다운 — %.0f초 대기", wait_sec)
                        await asyncio.sleep(wait_sec)
                    failed += 1
                    batch_done.append(uid)

                # 유저 간 랜덤 딜레이
                await asyncio.sleep(random.uniform(USER_DELAY_MIN, USER_DELAY_MAX))

                # 긴 휴식 (스팸 방지)
                total_done = sent + skipped + failed
                if total_done > 0 and total_done % LONG_BREAK_EVERY == 0:
                    break_sec = random.uniform(LONG_BREAK_MIN, LONG_BREAK_MAX)
                    logger.info("스팸 방지 휴식 %.1f분", break_sec / 60)
                    await _notify(
                        f"⏸ 스팸 방지 휴식 {break_sec / 60:.0f}분 "
                        f"(누적 {total_done}명 처리)"
                    )
                    await asyncio.sleep(break_sec)

            # 배치 완료 → DB 업데이트
            if batch_done:
                mark_sent(batch_done)
                remaining = count_unsent_with_username()
                await _notify(
                    f"📦 배치 완료\n"
                    f"• 성공: {sent}명 / 건너뜀: {skipped}명 / 실패: {failed}명\n"
                    f"• 남은 발송 가능 대상: {remaining}명"
                )
                if remaining == 0:
                    break

            # 전 계정 일일 한도 초과 시 발송 중단
            if all(a["daily_sent"] >= DAILY_LIMIT_PER_ACCOUNT for a in accounts):
                break

    finally:
        # 시작된 모든 클라이언트 종료 (성공/실패 무관)
        for acc in all_started:
            try:
                await acc["client"].stop()
            except Exception:
                pass

    await _notify(
        f"✅ UserBot 발송 완료\n"
        f"• 성공: {sent}명\n"
        f"• 건너뜀(차단·탈퇴·없음): {skipped}명\n"
        f"• 실패: {failed}명"
    )
    return {"total": total_unsent, "sent": sent, "skipped": skipped, "failed": failed}
