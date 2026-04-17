"""
경쟁사 텔레그램 멤버 자동 수집기 — Telethon iter_participants() 사용.
매일 00:00 UTC 스케줄러에서 실행.

흐름:
  1. SESSION_STRING_TELETHON (Telethon StringSession)으로 연결
  2. discovered_groups 테이블의 미수집 그룹 로드
  3. TARGET_GROUPS 환경변수 추가 그룹 로드
  4. 브로드캐스트 계정(SESSION_STRING_1~10)을 각 그룹에 join — PEER_ID_INVALID 예방
  5. Telethon iter_participants()로 username 있는 멤버 수집
  6. broadcast_targets 테이블에 저장
  7. 완료 후 관리자 DM 알림
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)
load_dotenv(ROOT / "bot" / ".env", override=True)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

API_ID_RAW = (os.getenv("API_ID") or "0").strip()
API_ID = int(API_ID_RAW) if API_ID_RAW.isdigit() else 0
API_HASH = (os.getenv("API_HASH") or "").strip()
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID = (os.getenv("ADMIN_ID") or "").strip()
SESSION_STRING_TELETHON = (os.getenv("SESSION_STRING_TELETHON") or "").strip()

TARGET_GROUPS_ENV = os.getenv("TARGET_GROUPS", "").strip()
PER_USER_DELAY_SEC  = float(os.getenv("SCRAPER_USER_DELAY",   "0.05"))
PER_GROUP_DELAY_SEC = float(os.getenv("SCRAPER_GROUP_DELAY",  "5.0"))
MAX_MEMBERS_PER_GROUP = int(os.getenv("SCRAPER_MAX_MEMBERS",  "3000"))


def _get_pyrogram_sessions() -> list[tuple[str, str]]:
    """SESSION_STRING_1~10 + fallback SESSION_STRING 수집 (Pyrogram 브로드캐스트 계정용)."""
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


def _telegram_notify(text: str) -> None:
    if not BOT_TOKEN or not ADMIN_ID:
        return
    try:
        with httpx.Client(timeout=10) as hc:
            hc.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_ID, "text": (text or "")[:4000],
                      "disable_web_page_preview": True},
            )
    except Exception:
        pass


async def join_groups_for_broadcast_accounts(groups: list[str]) -> None:
    """
    브로드캐스트 계정(SESSION_STRING_1..10)을 수집 그룹에 join시킴.
    그룹 멤버의 peer access_hash를 브로드캐스트 계정 세션에 캐싱하여
    DM 발송 시 PEER_ID_INVALID를 방지.
    """
    from pyrogram import Client
    from pyrogram.errors import FloodWait

    sessions = _get_pyrogram_sessions()
    if not sessions:
        print("⚠️  [join] 브로드캐스트 SESSION_STRING_1..10 없음 — skip")
        return

    print(f"\n🔗 [join] 브로드캐스트 계정 {len(sessions)}개 × 그룹 {len(groups)}개 join 시도...")
    _telegram_notify(
        f"🔗 브로드캐스트 계정 그룹 join 시작\n"
        f"• 계정: {len(sessions)}개 / 그룹: {len(groups)}개"
    )

    for label, session_str in sessions:
        joined = failed = already = 0
        try:
            async with Client(
                name=f"join_{label}",
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=session_str,
                in_memory=True,
            ) as client:
                me = await client.get_me()
                print(f"  ✅ [{label}] @{me.username or me.id}")

                for handle in groups:
                    try:
                        await client.join_chat(handle)
                        joined += 1
                        print(f"    ➕ [{label}] join: {handle}")
                        await asyncio.sleep(2.0)
                    except Exception as e:
                        err_name = type(e).__name__
                        if "already" in str(e).lower() or err_name == "UserAlreadyParticipant":
                            already += 1
                        elif isinstance(e, FloodWait):
                            wait = int(getattr(e, "value", 30)) + 5
                            print(f"    ⏳ [{label}] FloodWait {wait}초...")
                            await asyncio.sleep(wait)
                            try:
                                await client.join_chat(handle)
                                joined += 1
                            except Exception:
                                failed += 1
                        else:
                            failed += 1
                            print(f"    ❌ [{label}] {handle}: {err_name} — {e}")

        except Exception as e:
            print(f"  ❌ [{label}] 연결 실패: {type(e).__name__} — {e}")
            _telegram_notify(f"❌ [{label}] 세션 연결 실패\n{type(e).__name__}: {e}")
            continue

        print(f"  📊 [{label}] 신규 {joined} / 이미참여 {already} / 실패 {failed}")

    print("🔗 [join] 완료\n")


async def scrape_group_telethon(client, handle: str) -> tuple[int, int]:
    """Telethon iter_participants()로 단일 그룹 멤버 수집."""
    from app.pg_broadcast import save_broadcast_batch
    from telethon.errors import (
        ChatAdminRequiredError,
        ChannelPrivateError,
        FloodWaitError,
        UsernameNotOccupiedError,
        UsernameInvalidError,
    )

    saved = skipped = 0
    batch: list[tuple[int, str, str]] = []
    BATCH_SIZE = 200

    print(f"\n  🏷️  [{handle}] 멤버 수집 중...")
    try:
        count = 0
        async for member in client.iter_participants(handle, limit=MAX_MEMBERS_PER_GROUP):
            if getattr(member, "bot", False) or getattr(member, "deleted", False):
                skipped += 1
                continue
            username = (getattr(member, "username", None) or "").strip()
            if not username:
                skipped += 1
                continue
            batch.append((member.id, username, handle))
            count += 1
            if len(batch) >= BATCH_SIZE:
                save_broadcast_batch(batch)
                saved += len(batch)
                batch.clear()
                print(f"    💾 중간 저장 (누적 {count}명)")
            if PER_USER_DELAY_SEC > 0:
                await asyncio.sleep(PER_USER_DELAY_SEC)

        if batch:
            save_broadcast_batch(batch)
            saved += len(batch)

    except FloodWaitError as e:
        wait = e.seconds + 10
        print(f"    ⏳ FloodWait {wait}초 대기...")
        await asyncio.sleep(wait)
    except (ChatAdminRequiredError, ChannelPrivateError):
        print(f"    ⚠️ [{handle}] 멤버 조회 권한 없음")
    except (UsernameNotOccupiedError, UsernameInvalidError):
        print(f"    ⚠️ [{handle}] 존재하지 않는 그룹")
    except Exception as e:
        print(f"    ❌ [{handle}] 에러: {type(e).__name__} — {e}")

    print(f"    ✅ [{handle}] 저장 {saved}명 / 건너뜀 {skipped}명")
    return saved, skipped


async def main() -> None:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from app.pg_broadcast import (
        ensure_pg_table,
        ensure_discovered_groups_table,
        get_unscraped_groups,
        mark_group_scraped,
        mark_group_scrape_failed,
    )

    print("\n" + "=" * 62)
    print("   경쟁사 멤버 자동 수집기  (Telethon iter_participants)")
    print("=" * 62)

    if not API_ID or not API_HASH:
        msg = "❌ API_ID 또는 API_HASH 환경변수가 설정되지 않았습니다."
        print(msg)
        _telegram_notify(f"❌ member_scraper 실패\n{msg}")
        sys.exit(1)

    if not SESSION_STRING_TELETHON:
        msg = (
            "❌ SESSION_STRING_TELETHON 환경변수가 없습니다.\n"
            "scripts/generate_telethon_session.py 로 생성 후 Railway에 등록하세요."
        )
        print(msg)
        _telegram_notify(f"❌ member_scraper 실패\n{msg}")
        sys.exit(1)

    ensure_pg_table()
    ensure_discovered_groups_table()
    print("✅ PostgreSQL broadcast_targets / discovered_groups 준비 완료\n")

    # 수집 대상 그룹 목록 구성
    all_groups: list[str] = []
    seen_lower: set[str] = set()
    discovered_group_map: dict[str, int] = {}

    # 1) discovered_groups 테이블에서 미수집 그룹 로드
    limit = int(os.getenv("MAX_GROUPS_PER_RUN", "20"))
    unscraped = get_unscraped_groups(limit=limit)
    for group_id, username, title in unscraped:
        if not username:
            continue
        h = f"@{username}" if not username.startswith("@") else username
        if h.lower() not in seen_lower:
            seen_lower.add(h.lower())
            all_groups.append(h)
            print(f"  ➕ discovered_groups: {h} ({title})")
        discovered_group_map[h.lower()] = group_id
    if unscraped:
        print(f"  📋 discovered_groups에서 {len(unscraped)}개 로드\n")

    # 2) TARGET_GROUPS 환경변수 추가
    for raw in TARGET_GROUPS_ENV.split(","):
        raw = raw.strip()
        if not raw:
            continue
        h = raw if raw.startswith("@") else f"@{raw}"
        if h.lower() not in seen_lower:
            seen_lower.add(h.lower())
            all_groups.append(h)
            print(f"  ➕ TARGET_GROUPS: {h}")

    if not all_groups:
        msg = (
            "⚠️ 수집 대상 그룹이 없습니다.\n"
            "원인: discovered_groups 비어있음 / TARGET_GROUPS 미설정\n"
            "확인: group_finder 먼저 실행 또는 TARGET_GROUPS 환경변수 설정"
        )
        print(f"\n{msg}")
        _telegram_notify(f"⚠️ member_scraper — {msg}")
        sys.exit(0)

    # 브로드캐스트 계정을 각 그룹에 join (PEER_ID_INVALID 예방)
    if os.getenv("JOIN_BROADCAST_ACCOUNTS", "1").strip() != "0":
        await join_groups_for_broadcast_accounts(all_groups)
    else:
        print("ℹ️  JOIN_BROADCAST_ACCOUNTS=0 — 브로드캐스트 계정 join 생략")

    print(f"📋 총 {len(all_groups)}개 그룹에서 멤버 수집 시작")
    _telegram_notify(
        f"🔍 멤버 수집 시작 (Telethon)\n"
        f"• 그룹: {len(all_groups)}개\n"
        f"• 목록: {', '.join(all_groups[:8])}{'...' if len(all_groups) > 8 else ''}"
    )

    total_saved = total_skipped = 0
    ok_groups = fail_groups = 0

    async with TelegramClient(
        StringSession(SESSION_STRING_TELETHON),
        API_ID,
        API_HASH,
    ) as client:
        me = await client.get_me()
        print(f"✅ Telethon 연결: @{me.username or me.id}\n")

        for i, handle in enumerate(all_groups):
            gid = discovered_group_map.get(handle.lower())
            try:
                s, sk = await scrape_group_telethon(client, handle)
                total_saved += s
                total_skipped += sk
                ok_groups += 1
                if gid:
                    mark_group_scraped(gid)
                _telegram_notify(
                    f"📤 그룹 완료 ({i+1}/{len(all_groups)})\n"
                    f"• {handle} → 저장 {s}명 / 건너뜀 {sk}명\n"
                    f"• 누적 저장: {total_saved}명"
                )
            except Exception as e:
                print(f"  ❌ [{handle}] 처리 실패: {e}")
                fail_groups += 1
                if gid:
                    mark_group_scrape_failed(gid)
                _telegram_notify(f"❌ 그룹 실패 [{handle}]\n{type(e).__name__}: {e}")

            if i < len(all_groups) - 1:
                await asyncio.sleep(PER_GROUP_DELAY_SEC)

    summary = (
        f"🎉 멤버 수집 완료!\n"
        f"• 처리 그룹: 성공 {ok_groups}개 / 실패 {fail_groups}개\n"
        f"• 신규 저장: {total_saved}명 → broadcast_targets\n"
        f"• 건너뜀: {total_skipped}명"
    )
    _telegram_notify(summary)
    print("\n" + "=" * 62)
    print("  🎉 전체 수집 완료!")
    print(f"  • 신규 저장: {total_saved}명  → broadcast_targets")
    print(f"  • 건너뜀:   {total_skipped}명")
    print("=" * 62 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
