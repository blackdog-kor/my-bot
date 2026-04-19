"""
경쟁사 텔레그램 멤버 자동 수집기 — Telethon 사용.
매일 00:00 UTC 스케줄러에서 실행.

흐름:
  1. SESSION_STRING_TELETHON (Telethon StringSession)으로 연결
  2. discovered_groups 테이블의 미수집 그룹/채널 로드
  3. TARGET_GROUPS 환경변수 추가 그룹 로드
  4. 브로드캐스트 계정(SESSION_STRING_1~10)을 각 그룹에 join — PEER_ID_INVALID 예방
  5. 그룹/슈퍼그룹 → iter_participants()
     채널 → 방법1: 연결된 토론 그룹 iter_participants()
             방법2: 최근 메시지 댓글 작성자 수집
  6. broadcast_targets 테이블에 저장
  7. 완료 후 관리자 DM 알림
"""
from __future__ import annotations

import asyncio
import os
import sys
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
PER_USER_DELAY_SEC       = float(os.getenv("SCRAPER_USER_DELAY",       "0.05"))
PER_GROUP_DELAY_SEC      = float(os.getenv("SCRAPER_GROUP_DELAY",      "5.0"))
MAX_MEMBERS_PER_GROUP    = int(os.getenv("SCRAPER_MAX_MEMBERS",        "3000"))
MAX_CHANNEL_MESSAGES     = int(os.getenv("SCRAPER_CHANNEL_MESSAGES",   "200"))
MAX_REPLIES_PER_MSG      = int(os.getenv("SCRAPER_REPLIES_PER_MSG",    "100"))


def _get_pyrogram_sessions() -> list[tuple[str, str]]:
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
    DM 발송 시 PEER_ID_INVALID 방지.
    """
    from pyrogram import Client
    from pyrogram.errors import FloodWait

    sessions = _get_pyrogram_sessions()
    if not sessions:
        print("⚠️  [join] 브로드캐스트 SESSION_STRING_1..10 없음 — skip")
        return

    print(f"\n🔗 [join] 브로드캐스트 계정 {len(sessions)}개 × 그룹 {len(groups)}개 join 시도...")

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


def _flush_batch(batch: list, saved_ref: list[int]) -> None:
    """batch를 DB에 저장하고 비움. saved_ref[0]에 누적 저장 수 반영."""
    from app.pg_broadcast import save_broadcast_batch
    if batch:
        save_broadcast_batch(list(batch))
        saved_ref[0] += len(batch)
        batch.clear()


async def scrape_group_telethon(client, handle: str) -> tuple[int, int]:
    """그룹/슈퍼그룹: iter_participants()로 멤버 수집."""
    from telethon.errors import (
        ChatAdminRequiredError,
        ChannelPrivateError,
        FloodWaitError,
        UsernameNotOccupiedError,
        UsernameInvalidError,
    )

    saved_ref = [0]
    skipped = 0
    batch: list[tuple[int, str, str]] = []
    BATCH_SIZE = 200

    print(f"\n  🏷️  [{handle}] 그룹 멤버 수집 (iter_participants)...")
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
                _flush_batch(batch, saved_ref)
                print(f"    💾 중간 저장 (누적 {count}명)")
            if PER_USER_DELAY_SEC > 0:
                await asyncio.sleep(PER_USER_DELAY_SEC)

        _flush_batch(batch, saved_ref)

    except FloodWaitError as e:
        wait = e.seconds + 10
        print(f"    ⏳ FloodWait {wait}초 대기...")
        await asyncio.sleep(wait)
    except ChatAdminRequiredError:
        # 채널이면 채널 전용 수집으로 위임
        raise
    except (ChannelPrivateError, UsernameNotOccupiedError, UsernameInvalidError):
        print(f"    ⚠️ [{handle}] 접근 불가 또는 존재하지 않음")
    except Exception as e:
        print(f"    ❌ [{handle}] 에러: {type(e).__name__} — {e}")

    print(f"    ✅ [{handle}] 저장 {saved_ref[0]}명 / 건너뜀 {skipped}명")
    return saved_ref[0], skipped


async def scrape_channel_telethon(client, handle: str) -> tuple[int, int]:
    """
    채널 전용 수집.
    방법1: GetFullChannelRequest → 연결된 토론 그룹 iter_participants()
    방법2: iter_messages() → 댓글 작성자 username 수집
    """
    from telethon.tl.functions.channels import GetFullChannelRequest
    from telethon.errors import FloodWaitError, ChannelPrivateError

    saved_ref = [0]
    skipped = 0
    seen_users: set[int] = set()
    batch: list[tuple[int, str, str]] = []
    BATCH_SIZE = 200

    print(f"\n  📡 [{handle}] 채널 수집 시작...")

    # ── 방법1: 연결된 토론 그룹 iter_participants() ───────────────────
    linked_saved = 0
    try:
        full_chat = await client(GetFullChannelRequest(handle))
        linked_chat_id = getattr(full_chat.full_chat, "linked_chat_id", None)

        if linked_chat_id:
            print(f"    🔗 [{handle}] 연결된 토론 그룹 발견 (id={linked_chat_id})")
            # Telethon 계정을 토론 그룹에 직접 join — iter_participants 권한 확보
            try:
                from telethon.tl.functions.channels import JoinChannelRequest
                await client(JoinChannelRequest(linked_chat_id))
                print(f"    ➕ [{handle}] 토론 그룹 join 완료")
                await asyncio.sleep(2.0)
            except Exception as je:
                print(f"    ℹ️  [{handle}] 토론 그룹 join: {type(je).__name__} — {je}")

            print(f"    ▶️  iter_participants 실행...")
            count = 0
            async for member in client.iter_participants(linked_chat_id, limit=MAX_MEMBERS_PER_GROUP):
                if getattr(member, "bot", False) or getattr(member, "deleted", False):
                    skipped += 1
                    continue
                username = (getattr(member, "username", None) or "").strip()
                if not username:
                    skipped += 1
                    continue
                if member.id in seen_users:
                    continue
                seen_users.add(member.id)
                batch.append((member.id, username, handle))
                count += 1
                if len(batch) >= BATCH_SIZE:
                    _flush_batch(batch, saved_ref)
                    print(f"    💾 토론그룹 중간 저장 (누적 {count}명)")
                if PER_USER_DELAY_SEC > 0:
                    await asyncio.sleep(PER_USER_DELAY_SEC)
            _flush_batch(batch, saved_ref)
            linked_saved = saved_ref[0]
            print(f"    ✅ [{handle}] 토론그룹 저장 {linked_saved}명")
        else:
            print(f"    ℹ️  [{handle}] 연결된 토론 그룹 없음")

    except FloodWaitError as e:
        wait = e.seconds + 10
        print(f"    ⏳ FloodWait {wait}초 대기...")
        await asyncio.sleep(wait)
    except ChannelPrivateError:
        print(f"    ⚠️ [{handle}] 비공개 채널 — 접근 불가")
        return 0, 0
    except Exception as e:
        print(f"    ⚠️ [{handle}] GetFullChannel 실패: {type(e).__name__} — {e}")

    # ── 방법2: 최근 댓글 작성자 수집 ─────────────────────────────────
    comment_saved_before = saved_ref[0]
    try:
        msg_count = 0
        async for message in client.iter_messages(handle, limit=MAX_CHANNEL_MESSAGES):
            replies_info = getattr(message, "replies", None)
            if not replies_info or not getattr(replies_info, "replies", 0):
                continue
            try:
                async for reply in client.iter_messages(
                    handle,
                    reply_to=message.id,
                    limit=MAX_REPLIES_PER_MSG,
                ):
                    try:
                        sender = await reply.get_sender()
                    except Exception:
                        continue
                    if not sender:
                        continue
                    if getattr(sender, "bot", False) or getattr(sender, "deleted", False):
                        skipped += 1
                        continue
                    username = (getattr(sender, "username", None) or "").strip()
                    if not username:
                        skipped += 1
                        continue
                    if sender.id in seen_users:
                        continue
                    seen_users.add(sender.id)
                    batch.append((sender.id, username, handle))
                    if len(batch) >= BATCH_SIZE:
                        _flush_batch(batch, saved_ref)
            except Exception as e:
                print(f"      ⚠️ 댓글 조회 실패 (msg_id={message.id}): {e}")
            msg_count += 1
            await asyncio.sleep(0.2)

        _flush_batch(batch, saved_ref)
        comment_saved = saved_ref[0] - comment_saved_before
        print(f"    ✅ [{handle}] 댓글 작성자 저장 {comment_saved}명 (메시지 {msg_count}개 스캔)")

    except FloodWaitError as e:
        wait = e.seconds + 10
        print(f"    ⏳ FloodWait {wait}초 대기...")
        await asyncio.sleep(wait)
    except Exception as e:
        print(f"    ❌ [{handle}] iter_messages 실패: {type(e).__name__} — {e}")

    print(f"    ✅ [{handle}] 채널 수집 완료 — 총 저장 {saved_ref[0]}명 / 건너뜀 {skipped}명")
    return saved_ref[0], skipped


async def scrape_handle(client, handle: str) -> tuple[int, int]:
    """
    그룹이면 iter_participants(), 채널이면 채널 전용 수집으로 자동 분기.
    ChatAdminRequiredError = 채널로 판단.
    """
    from telethon.errors import ChatAdminRequiredError
    try:
        return await scrape_group_telethon(client, handle)
    except ChatAdminRequiredError:
        print(f"    ℹ️  [{handle}] 채널로 판단 — 채널 수집 방식으로 전환")
        return await scrape_channel_telethon(client, handle)


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
    print("   경쟁사 멤버 자동 수집기  (Telethon — 그룹+채널)")
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

    # 수집 대상 목록 구성
    all_handles: list[str] = []
    seen_lower: set[str] = set()
    discovered_group_map: dict[str, int] = {}

    # 1) discovered_groups 테이블 (그룹 + 채널 모두)
    limit = int(os.getenv("MAX_GROUPS_PER_RUN", "20"))
    unscraped = get_unscraped_groups(limit=limit)
    for group_id, username, title in unscraped:
        if not username:
            continue
        h = f"@{username}" if not username.startswith("@") else username
        if h.lower() not in seen_lower:
            seen_lower.add(h.lower())
            all_handles.append(h)
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
            all_handles.append(h)
            print(f"  ➕ TARGET_GROUPS: {h}")

    if not all_handles:
        msg = (
            "⚠️ 수집 대상이 없습니다.\n"
            "원인: discovered_groups 비어있음 / TARGET_GROUPS 미설정\n"
            "확인: group_finder 먼저 실행 또는 TARGET_GROUPS 환경변수 설정"
        )
        print(f"\n{msg}")
        _telegram_notify(f"⚠️ member_scraper — {msg}")
        sys.exit(0)

    # 브로드캐스트 계정을 각 그룹에 join (PEER_ID_INVALID 예방)
    if os.getenv("JOIN_BROADCAST_ACCOUNTS", "1").strip() != "0":
        await join_groups_for_broadcast_accounts(all_handles)
    else:
        print("ℹ️  JOIN_BROADCAST_ACCOUNTS=0 — 브로드캐스트 계정 join 생략")

    print(f"📋 총 {len(all_handles)}개 대상에서 멤버 수집 시작")
    _telegram_notify(
        f"🔍 멤버 수집 시작 (Telethon — 그룹+채널)\n"
        f"• 대상: {len(all_handles)}개\n"
        f"• 목록: {', '.join(all_handles[:8])}{'...' if len(all_handles) > 8 else ''}"
    )

    total_saved = total_skipped = 0
    ok_count = fail_count = 0

    async with TelegramClient(
        StringSession(SESSION_STRING_TELETHON),
        API_ID,
        API_HASH,
    ) as client:
        me = await client.get_me()
        print(f"✅ Telethon 연결: @{me.username or me.id}\n")

        for i, handle in enumerate(all_handles):
            gid = discovered_group_map.get(handle.lower())
            try:
                s, sk = await scrape_handle(client, handle)
                total_saved += s
                total_skipped += sk
                ok_count += 1
                if gid:
                    mark_group_scraped(gid)
                _telegram_notify(
                    f"📤 수집 완료 ({i+1}/{len(all_handles)})\n"
                    f"• {handle} → 저장 {s}명 / 건너뜀 {sk}명\n"
                    f"• 누적 저장: {total_saved}명"
                )
            except Exception as e:
                print(f"  ❌ [{handle}] 처리 실패: {e}")
                fail_count += 1
                if gid:
                    mark_group_scrape_failed(gid)
                _telegram_notify(f"❌ 수집 실패 [{handle}]\n{type(e).__name__}: {e}")

            if i < len(all_handles) - 1:
                await asyncio.sleep(PER_GROUP_DELAY_SEC)

    summary = (
        f"🎉 멤버 수집 완료!\n"
        f"• 처리: 성공 {ok_count}개 / 실패 {fail_count}개\n"
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
