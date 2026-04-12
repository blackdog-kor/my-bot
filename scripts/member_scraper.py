"""
경쟁사 텔레그램 멤버 자동 수집기 (통합 scripts/).
Phase 1: DuckDuckGo → t.me 링크 발굴
Phase 2~3: Pyrogram 그룹 멤버 수집
Phase 4: app.pg_broadcast (ensure_pg_table, save_broadcast_batch)로 저장

실행: repo root에서 python scripts/member_scraper.py (또는 스케줄러에서 호출)
"""
from __future__ import annotations

import asyncio
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "bot" / ".env")

import httpx
from bs4 import BeautifulSoup
from pyrogram import Client
from pyrogram.errors import (
    ChatAdminRequired,
    ChannelPrivate,
    FloodWait,
    RPCError,
    UsernameNotOccupied,
    UsernameInvalid,
)

API_ID = int(os.getenv("API_ID", "37398454"))
API_HASH = os.getenv("API_HASH", "a73350e09f51f516d8eac08498967750")
SESSION_STRING = os.getenv("SESSION_STRING", "")
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID = (os.getenv("ADMIN_ID") or "").strip()

# 수동으로 지정할 그룹 목록 (쉼표 구분, 예: "@group1,@group2")
TARGET_GROUPS_ENV = os.getenv("TARGET_GROUPS", "").strip()

SEARCH_QUERIES = [
    "카지노 텔레그램 그룹 site:t.me",
    "온라인카지노 텔레그램 그룹",
    "바카라 텔레그램 커뮤니티",
    "슬롯 텔레그램 그룹",
    "해외배팅 텔레그램 채널",
    "원윈 텔레그램",
    "1win 텔레그램 한국",
    "1win telegram group",
    "Stake casino telegram group",
    "BC.Game telegram community",
    "Rollbit telegram group",
    "online casino telegram members",
    "casino telegram channel korea",
    "gambling telegram group link",
]

EXTRA_GROUPS: list[str] = []

PER_USER_DELAY_SEC = float(os.getenv("SCRAPER_USER_DELAY", "0.05"))
PER_GROUP_DELAY_SEC = float(os.getenv("SCRAPER_GROUP_DELAY", "5.0"))
SEARCH_DELAY_SEC = float(os.getenv("SCRAPER_SEARCH_DELAY", "3.0"))
MAX_MEMBERS_PER_GROUP = int(os.getenv("SCRAPER_MAX_MEMBERS", "3000"))

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def _telegram_notify(text: str) -> None:
    if not BOT_TOKEN or not ADMIN_ID:
        return
    text = (text or "")[:4000]
    try:
        with httpx.Client(timeout=10) as hc:
            hc.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_ID, "text": text, "disable_web_page_preview": True},
            )
    except Exception:
        pass


def _extract_tme_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    found: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "uddg=" in href:
            try:
                m = re.search(r"uddg=([^&]+)", href)
                if m:
                    href = unquote(m.group(1))
            except Exception:
                pass
        if "/url?q=" in href:
            try:
                href = unquote(href.split("/url?q=")[1].split("&")[0])
            except Exception:
                pass
        if "t.me/" in href:
            found.append(href)
    for match in re.findall(r"https?://t\.me/[A-Za-z0-9_@+/]+", html):
        found.append(match)
    return found


def _search_duckduckgo(query: str) -> list[str]:
    headers = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://duckduckgo.com/",
    }
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as hc:
            resp = hc.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "kl": "kr-ko"},
                headers=headers,
            )
            if resp.status_code != 200:
                return []
            return _extract_tme_from_html(resp.text)
    except Exception as e:
        print(f"    ⚠️ DuckDuckGo 검색 실패: {e}")
        return []


def _tme_url_to_handle(url: str) -> str | None:
    try:
        path = urlparse(url).path.lstrip("/")
    except Exception:
        return None
    if not path or path.startswith("+") or path.lower().startswith("joinchat"):
        return None
    path = path.split("/")[0]
    if len(path) < 4 or path.isdigit():
        return None
    return f"@{path}"


def discover_groups() -> list[str]:
    print("\n🔍 [Phase 1] DuckDuckGo 검색으로 경쟁사 그룹 자동 발굴 중...")
    handles: list[str] = []
    seen: set[str] = set()
    for i, query in enumerate(SEARCH_QUERIES):
        print(f"  [{i+1}/{len(SEARCH_QUERIES)}] 검색 중: {query}")
        raw_urls = _search_duckduckgo(query)
        for url in raw_urls:
            handle = _tme_url_to_handle(url)
            if handle and handle.lower() not in seen:
                seen.add(handle.lower())
                handles.append(handle)
                print(f"    ✅ 발굴: {handle}")
        if i < len(SEARCH_QUERIES) - 1:
            time.sleep(SEARCH_DELAY_SEC)
    print(f"\n  📋 자동 발굴 완료: 공개 그룹 {len(handles)}개\n")
    return handles


async def join_groups_for_broadcast_accounts(groups: list[str]) -> None:
    """
    브로드캐스트 계정(SESSION_STRING_1..10)이 수집 그룹에 join하도록 강제.
    그룹 멤버 peer access_hash를 브로드캐스트 계정 세션에 캐싱하기 위함.
    이를 통해 나중에 해당 그룹 멤버에게 DM 발송 시 PEER_ID_INVALID를 방지.
    """
    sessions: list[tuple[str, str]] = []
    for i in range(1, 11):
        key = f"SESSION_STRING_{i}"
        val = (os.getenv(key) or "").strip()
        if val:
            sessions.append((key, val))

    if not sessions:
        print("⚠️  [join] 브로드캐스트 SESSION_STRING_1..10 없음 — skip")
        return

    print(f"\n🔗 [join] 브로드캐스트 계정 {len(sessions)}개가 그룹 {len(groups)}개에 join 시도 중...")
    _telegram_notify(
        f"🔗 브로드캐스트 계정 그룹 join 시작\n"
        f"• 계정 수: {len(sessions)}개\n"
        f"• 그룹 수: {len(groups)}개"
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
                print(f"  ✅ [{label}] 연결 성공: @{me.username or me.id}")

                for handle in groups:
                    try:
                        await client.join_chat(handle)
                        joined += 1
                        print(f"    ➕ [{label}] join: {handle}")
                        await asyncio.sleep(2.0)
                    except Exception as e:
                        err_name = type(e).__name__
                        if "already" in str(e).lower() or err_name in ("UserAlreadyParticipant",):
                            already += 1
                            print(f"    ℹ️  [{label}] 이미 참여: {handle}")
                        elif err_name == "FloodWait":
                            wait = getattr(e, "value", 30) + 5
                            print(f"    ⏳ [{label}] FloodWait {wait}초 대기...")
                            await asyncio.sleep(wait)
                            try:
                                await client.join_chat(handle)
                                joined += 1
                            except Exception as e2:
                                failed += 1
                                print(f"    ❌ [{label}] 재시도 실패 {handle}: {e2}")
                        else:
                            failed += 1
                            print(f"    ❌ [{label}] join 실패 {handle}: {err_name} — {e}")

        except Exception as e:
            print(f"  ❌ [{label}] 세션 연결 실패: {type(e).__name__} — {e}")
            _telegram_notify(f"❌ [{label}] 세션 연결 실패\n{type(e).__name__}: {e}")
            continue

        print(f"  📊 [{label}] join 완료: 신규 {joined}개 / 이미참여 {already}개 / 실패 {failed}개")
        _telegram_notify(
            f"✅ [{label}] 그룹 join 완료\n"
            f"• 신규: {joined}개 / 이미참여: {already}개 / 실패: {failed}개"
        )

    print("🔗 [join] 전체 완료\n")


async def scrape_group(app: Client, handle: str) -> tuple[int, int]:
    """단일 그룹 멤버 수집. app.pg_broadcast.save_broadcast_batch 사용."""
    from app.pg_broadcast import save_broadcast_batch

    saved = skipped = 0
    batch: list[tuple[int, str, str]] = []
    BATCH_SIZE = 200
    print(f"\n  🏷️  [{handle}] 멤버 수집 시작...")
    try:
        count = 0
        async for member in app.get_chat_members(handle):
            user = member.user
            if not user or user.is_bot or user.is_deleted:
                skipped += 1
                continue
            username = (user.username or "").strip()
            if not username:
                skipped += 1
                continue
            batch.append((user.id, username, handle))
            count += 1
            if len(batch) >= BATCH_SIZE:
                save_broadcast_batch(batch)
                saved += len(batch)
                batch.clear()
                print(f"    💾 중간 저장 완료 (누적 {count}명 처리)")
            if PER_USER_DELAY_SEC > 0:
                await asyncio.sleep(PER_USER_DELAY_SEC)
            if count >= MAX_MEMBERS_PER_GROUP:
                print(f"    ⚠️ 최대 수집 한도 {MAX_MEMBERS_PER_GROUP}명 도달")
                break
        if batch:
            save_broadcast_batch(batch)
            saved += len(batch)
    except (ChatAdminRequired, ChannelPrivate):
        print(f"    ⚠️ [{handle}] 멤버 조회 권한 없음")
    except (UsernameNotOccupied, UsernameInvalid):
        print(f"    ⚠️ [{handle}] 존재하지 않는 그룹")
    except FloodWait as e:
        wait = e.value + 10
        print(f"    ⏳ FloodWait {wait}초 대기...")
        await asyncio.sleep(wait)
    except RPCError as e:
        print(f"    ❌ [{handle}] RPCError: {type(e).__name__} — {e}")
    except Exception as e:
        print(f"    ❌ [{handle}] 에러: {type(e).__name__} — {e}")
    print(f"    ✅ [{handle}] → 신규 저장 {saved}명 / 건너뜀 {skipped}명")
    return saved, skipped


async def main() -> None:
    print("\n" + "=" * 62)
    print("   경쟁사 멤버 자동 수집기  (DuckDuckGo + Pyrogram + PG)")
    print("=" * 62)
    if not SESSION_STRING:
        print("\n❌ SESSION_STRING 환경변수가 없습니다.")
        sys.exit(1)

    from app.pg_broadcast import (
        ensure_pg_table,
        ensure_discovered_groups_table,
        get_unscraped_groups,
        mark_group_scraped,
        mark_group_scrape_failed,
    )
    ensure_pg_table()
    ensure_discovered_groups_table()
    print("✅ PostgreSQL broadcast_targets / discovered_groups 준비 완료\n")

    auto_groups = discover_groups()
    all_groups: list[str] = list(auto_groups)
    seen_lower: set[str] = {h.lower() for h in auto_groups}
    for raw in EXTRA_GROUPS:
        h = raw if raw.startswith("@") else f"@{raw}"
        if h.lower() not in seen_lower:
            seen_lower.add(h.lower())
            all_groups.append(h)
            print(f"  ➕ 수동 추가 (EXTRA_GROUPS): {h}")

    # TARGET_GROUPS 환경변수에서 그룹 추가
    for raw in TARGET_GROUPS_ENV.split(","):
        raw = raw.strip()
        if not raw:
            continue
        h = raw if raw.startswith("@") else f"@{raw}"
        if h.lower() not in seen_lower:
            seen_lower.add(h.lower())
            all_groups.append(h)
            print(f"  ➕ TARGET_GROUPS 추가: {h}")

    # discovered_groups 테이블에서 scraped=FALSE 그룹 추가
    # handle → group_id 매핑 (scrape 완료/실패 후 DB 업데이트용)
    discovered_group_map: dict[str, int] = {}
    unscraped = get_unscraped_groups(limit=int(os.getenv("MAX_GROUPS_PER_RUN", "20")))
    for group_id, username, title in unscraped:
        if not username:
            continue
        h = f"@{username}" if not username.startswith("@") else username
        if h.lower() not in seen_lower:
            seen_lower.add(h.lower())
            all_groups.append(h)
            print(f"  ➕ discovered_groups 추가: {h} ({title})")
        discovered_group_map[h.lower()] = group_id
    if unscraped:
        print(f"  📋 discovered_groups 에서 {len(unscraped)}개 로드\n")

    if not all_groups:
        print("\n⚠️ 수집 가능한 그룹이 없습니다.")
        sys.exit(0)

    # 브로드캐스트 계정들을 수집 그룹에 join — PEER_ID_INVALID 방지의 핵심
    # JOIN_BROADCAST_ACCOUNTS=0 으로 명시해야만 생략 가능 (기본: 항상 실행)
    if os.getenv("JOIN_BROADCAST_ACCOUNTS", "1").strip() != "0":
        await join_groups_for_broadcast_accounts(all_groups)
    else:
        print("ℹ️  JOIN_BROADCAST_ACCOUNTS=0 — 브로드캐스트 계정 join 생략")

    print(f"\n📋 총 {len(all_groups)}개 그룹에서 멤버 수집 시작합니다.")
    _telegram_notify(
        "🔍 채굴(멤버 수집) 시작\n"
        f"• 발굴된 그룹: {len(all_groups)}개\n"
        f"• 목록: {', '.join(all_groups[:10])}{'...' if len(all_groups) > 10 else ''}"
    )

    total_saved = total_skipped = 0
    ok_groups = fail_groups = 0

    async with Client(
        name="scraper_session",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING,
    ) as app:
        for i, handle in enumerate(all_groups):
            gid = discovered_group_map.get(handle.lower())
            try:
                s, sk = await scrape_group(app, handle)
                total_saved += s
                total_skipped += sk
                ok_groups += 1
                if gid:
                    mark_group_scraped(gid)
                _telegram_notify(
                    f"📤 그룹 완료 ({i+1}/{len(all_groups)})\n"
                    f"• {handle} → 신규 저장 {s}명 / 건너뜀 {sk}명\n"
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
        f"🎉 채굴(멤버 수집) 완료!\n"
        f"• 처리 그룹: 성공 {ok_groups}개 / 실패 {fail_groups}개\n"
        f"• 신규 저장: {total_saved}명 → PostgreSQL\n"
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
