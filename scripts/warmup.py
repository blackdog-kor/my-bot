#!/usr/bin/env python
"""
매일 08:00 KST (23:00 UTC) 자동 워밍업 스크립트.

단계별 액션:
  1~2일차: 저장된 연락처에 랜덤 메시지 1~2건
  3~5일차: discovered_groups에서 그룹 1~2개 가입 + 최근 메시지 읽기
  6~7일차: 가입한 그룹 멤버에게 DM 5건 이하 (자연스러운 인사)
  7일차 완료 시 status='completed' 기록

각 액션 사이 랜덤 딜레이 30~180초.
진행 상태는 warmup_status 테이블(PostgreSQL)에 세션별로 기록.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=True)
load_dotenv(ROOT / "bot" / ".env", override=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("warmup")

DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
API_ID       = int((os.getenv("API_ID") or "0").strip())
API_HASH     = (os.getenv("API_HASH") or "").strip()
BOT_TOKEN    = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID     = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

# 연락처에 보낼 자연스러운 메시지 풀
_CONTACT_MSGS = [
    "안녕하세요! 오랜만이에요 😊 잘 지내시나요?",
    "반갑습니다~ 요즘 어떻게 지내세요?",
    "안녕하세요, 좋은 하루 되세요 ☀️",
    "오랜만에 안부 전해요! 건강히 지내시죠?",
    "안녕! 잘 지내고 있어? 😄",
    "Hi! Long time no chat, how are you?",
    "Hello~ Hope you're doing well! 😊",
    "Hey, just wanted to say hi! 👋",
]

# 그룹 가입 후 읽기에 사용할 공개 그룹 (discovered_groups 없을 때 폴백)
_FALLBACK_GROUPS = [
    "telegram",
    "durov",
]

# 그룹 멤버에게 보낼 자연스러운 DM 풀
_DM_MSGS = [
    "안녕하세요! 같은 그룹에 있어서 인사 드려요 😊",
    "Hello! Saw you in the group, nice to meet you! 👋",
    "안녕~ 반갑습니다! 좋은 하루 되세요 😄",
    "Hi there! Hope you're having a great day 🙂",
    "안녕하세요, 잘 부탁드립니다 😊",
]


# ── DB 헬퍼 ──────────────────────────────────────────────────────────────────

def _get_conn():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def ensure_warmup_table() -> None:
    if not DATABASE_URL:
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS warmup_status (
                session_label TEXT PRIMARY KEY,
                warmup_day    INTEGER NOT NULL DEFAULT 1,
                started_at    TIMESTAMPTZ DEFAULT NOW(),
                last_run_at   TIMESTAMPTZ,
                status        TEXT NOT NULL DEFAULT 'active'
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        logger.info("warmup_status 테이블 준비 완료")
    except Exception as e:
        logger.warning("ensure_warmup_table 실패: %s", e)


def get_warmup_day(session_label: str) -> tuple[int, str]:
    """(warmup_day, status) 반환. 없으면 (1, 'active')."""
    if not DATABASE_URL:
        return (1, "active")
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT warmup_day, status FROM warmup_status WHERE session_label = %s",
            (session_label,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return (row[0], row[1])
        return (1, "active")
    except Exception as e:
        logger.warning("get_warmup_day 실패 (%s): %s", session_label, e)
        return (1, "active")


def save_warmup_progress(session_label: str, day: int, status: str = "active") -> None:
    if not DATABASE_URL:
        return
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO warmup_status (session_label, warmup_day, status, last_run_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (session_label) DO UPDATE
                SET warmup_day  = EXCLUDED.warmup_day,
                    status      = EXCLUDED.status,
                    last_run_at = NOW()
        """, (session_label, day, status))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning("save_warmup_progress 실패 (%s): %s", session_label, e)


def get_target_groups(limit: int = 5) -> list[str]:
    """discovered_groups에서 username 목록 반환. 없으면 fallback 사용."""
    if not DATABASE_URL:
        return _FALLBACK_GROUPS
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT username FROM discovered_groups
            WHERE username IS NOT NULL AND username <> ''
            ORDER BY member_count DESC NULLS LAST
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        if rows:
            return [r[0] for r in rows]
    except Exception as e:
        logger.warning("get_target_groups 실패: %s", e)
    return _FALLBACK_GROUPS


def _notify_admin(text: str) -> None:
    if not BOT_TOKEN or not ADMIN_ID:
        return
    try:
        import httpx
        httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_ID, "text": text[:4000], "disable_web_page_preview": True},
            timeout=10,
        )
    except Exception as e:
        logger.warning("_notify_admin 실패: %s", e)


# ── 딜레이 헬퍼 ──────────────────────────────────────────────────────────────

async def _delay(min_sec: float = 30.0, max_sec: float = 180.0) -> None:
    sec = random.uniform(min_sec, max_sec)
    logger.info("딜레이 %.0f초 대기", sec)
    await asyncio.sleep(sec)


# ── 단계별 워밍업 액션 ────────────────────────────────────────────────────────

async def _action_day1_2(client, label: str) -> str:
    """1~2일차: 저장된 연락처에 랜덤 메시지 1~2건."""
    from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated

    try:
        contacts = await client.get_contacts()
    except Exception as e:
        return f"연락처 조회 실패: {e}"

    if not contacts:
        return "저장된 연락처 없음 — 스킵"

    targets = random.sample(contacts, min(random.randint(1, 2), len(contacts)))
    sent = 0
    for contact in targets:
        try:
            msg = random.choice(_CONTACT_MSGS)
            await client.send_message(contact.id, msg)
            sent += 1
            logger.info("[%s] 연락처 메시지 발송 → user_id=%s", label, contact.id)
            await _delay(30, 120)
        except FloodWait as e:
            wait = int(e.value or 60) + 10
            logger.warning("[%s] FloodWait %d초", label, wait)
            await asyncio.sleep(wait)
        except (UserIsBlocked, InputUserDeactivated):
            continue
        except Exception as e:
            logger.warning("[%s] 연락처 메시지 실패 (user_id=%s): %s", label, contact.id, e)

    return f"연락처 메시지 {sent}건 발송"


async def _action_day3_5(client, label: str) -> str:
    """3~5일차: 그룹 1~2개 가입 + 최근 메시지 읽기."""
    from pyrogram.errors import FloodWait, UserAlreadyParticipant, ChannelsTooMuch

    group_usernames = get_target_groups(limit=10)
    random.shuffle(group_usernames)
    targets = group_usernames[:random.randint(1, 2)]

    joined = []
    for username in targets:
        try:
            await client.join_chat(username)
            joined.append(username)
            logger.info("[%s] 그룹 가입: @%s", label, username)
            await _delay(20, 60)
        except UserAlreadyParticipant:
            joined.append(username)
            logger.info("[%s] 이미 가입된 그룹: @%s", label, username)
        except ChannelsTooMuch:
            logger.warning("[%s] 가입 가능한 그룹 수 초과", label)
            break
        except FloodWait as e:
            wait = int(e.value or 60) + 10
            logger.warning("[%s] 가입 FloodWait %d초", label, wait)
            await asyncio.sleep(wait)
        except Exception as e:
            logger.warning("[%s] 그룹 가입 실패 (@%s): %s", label, username, e)

    # 가입한 그룹의 최근 메시지 읽기 (get_history)
    read_count = 0
    for username in joined:
        try:
            msgs = await client.get_chat_history(username, limit=20)
            # async generator 소비
            async for _ in msgs:
                read_count += 1
            logger.info("[%s] @%s 최근 메시지 읽기 완료", label, username)
            await _delay(15, 60)
        except Exception as e:
            logger.warning("[%s] 메시지 읽기 실패 (@%s): %s", label, username, e)

    return f"그룹 {len(joined)}개 가입·읽기, 메시지 {read_count}건 확인"


async def _action_day6_7(client, label: str) -> str:
    """6~7일차: 가입한 그룹 멤버에게 DM 5건 이하."""
    from pyrogram.errors import (
        FloodWait, UserIsBlocked, InputUserDeactivated,
        UserPrivacyRestricted, PeerIdInvalid,
    )

    # 현재 가입된 그룹에서 멤버 수집
    group_usernames = get_target_groups(limit=5)
    candidates: list[int] = []

    for username in group_usernames:
        if len(candidates) >= 20:
            break
        try:
            async for member in client.get_chat_members(username, limit=30):
                if (
                    member.user
                    and not member.user.is_bot
                    and not member.user.is_deleted
                    and member.user.id != (await client.get_me()).id
                ):
                    candidates.append(member.user.id)
                    if len(candidates) >= 20:
                        break
            await _delay(10, 30)
        except Exception as e:
            logger.warning("[%s] 멤버 수집 실패 (@%s): %s", label, username, e)

    if not candidates:
        return "DM 대상 없음 — 스킵"

    targets = random.sample(candidates, min(random.randint(3, 5), len(candidates)))
    sent = 0
    skip_errors = (UserIsBlocked, InputUserDeactivated, UserPrivacyRestricted, PeerIdInvalid)

    for user_id in targets:
        try:
            msg = random.choice(_DM_MSGS)
            await client.send_message(user_id, msg)
            sent += 1
            logger.info("[%s] DM 발송 → user_id=%s", label, user_id)
            await _delay(60, 180)
        except FloodWait as e:
            wait = int(e.value or 60) + 10
            logger.warning("[%s] DM FloodWait %d초", label, wait)
            await asyncio.sleep(wait)
        except skip_errors as e:
            logger.info("[%s] DM 스킵 (user_id=%s): %s", label, user_id, type(e).__name__)
        except Exception as e:
            logger.warning("[%s] DM 실패 (user_id=%s): %s", label, user_id, e)

    return f"모르는 유저 DM {sent}건 발송"


# ── 세션별 워밍업 실행 ────────────────────────────────────────────────────────

async def _warmup_session(label: str, session_string: str) -> dict:
    from pyrogram import Client
    from pyrogram.errors import AuthKeyUnregistered, AuthKeyDuplicated

    day, status = get_warmup_day(label)
    result = {"label": label, "day": day, "status": status, "action": "", "error": ""}

    if status == "completed":
        logger.info("[%s] 워밍업 완료(7일차 종료) — 스킵", label)
        result["action"] = "이미 완료됨"
        return result

    if status == "failed":
        logger.info("[%s] 이전에 실패 처리됨 — 스킵", label)
        result["action"] = "실패 상태 유지"
        return result

    client = Client(
        name=label,
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=session_string,
        in_memory=True,
    )

    try:
        await client.start()
        me = await client.get_me()
        logger.info("[%s] 세션 연결 성공 (id=%s @%s)", label, me.id, me.username)
    except (AuthKeyUnregistered, AuthKeyDuplicated) as e:
        logger.warning("[%s] 세션 만료: %s", label, e)
        save_warmup_progress(label, day, "failed")
        result["status"] = "failed"
        result["error"] = f"{type(e).__name__}: {e}"
        return result
    except Exception as e:
        logger.warning("[%s] 세션 연결 실패: %s", label, e)
        save_warmup_progress(label, day, "failed")
        result["status"] = "failed"
        result["error"] = str(e)
        return result

    try:
        if day <= 2:
            action_result = await _action_day1_2(client, label)
        elif day <= 5:
            action_result = await _action_day3_5(client, label)
        else:
            action_result = await _action_day6_7(client, label)

        next_day = day + 1
        next_status = "completed" if next_day > 7 else "active"
        save_warmup_progress(label, next_day, next_status)

        result["action"] = action_result
        result["status"] = next_status
        result["day"] = day
        logger.info(
            "[%s] 워밍업 %d일차 완료 → %s | %s",
            label, day, next_status, action_result,
        )

    except Exception as e:
        logger.exception("[%s] 워밍업 액션 예외", label)
        save_warmup_progress(label, day, "failed")
        result["status"] = "failed"
        result["error"] = str(e)

    finally:
        try:
            await client.stop()
        except Exception:
            pass

    return result


# ── 진입점 ────────────────────────────────────────────────────────────────────

def _load_sessions() -> list[tuple[str, str]]:
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


async def main() -> None:
    if not API_ID or not API_HASH:
        logger.error("API_ID 또는 API_HASH가 설정되지 않았습니다.")
        sys.exit(1)

    sessions = _load_sessions()
    if not sessions:
        logger.error("SESSION_STRING 환경변수가 없습니다.")
        sys.exit(1)

    ensure_warmup_table()

    _notify_admin(f"🏋️ 워밍업 시작 ({len(sessions)}개 계정)")

    results: list[dict] = []
    for label, session_string in sessions:
        try:
            r = await _warmup_session(label, session_string)
            results.append(r)
        except Exception as e:
            logger.exception("_warmup_session 예외 (%s)", label)
            results.append({"label": label, "day": 0, "status": "failed", "error": str(e)})
        # 계정 간 딜레이
        await _delay(30, 90)

    # 관리자 요약 보고
    lines = ["🏋️ <b>워밍업 완료 요약</b>"]
    for r in results:
        icon = "✅" if r["status"] == "active" else ("🏁" if r["status"] == "completed" else "❌")
        lines.append(
            f"{icon} {r['label']} — {r['day']}일차\n"
            f"   {r.get('action') or r.get('error', '')}"
        )
    summary = "\n".join(lines)
    logger.info(summary)
    _notify_admin(summary)


if __name__ == "__main__":
    asyncio.run(main())
