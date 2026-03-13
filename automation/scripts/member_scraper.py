"""
경쟁사 텔레그램 멤버 자동 수집기
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[자동화 흐름]
  Phase 1 ▶ DuckDuckGo 검색으로 경쟁사 텔레그램 그룹 자동 발굴
              (브라우저 불필요, httpx 단순 HTTP 요청으로 동작)
  Phase 2 ▶ 발굴된 t.me 링크에서 @username 형태의 공개 그룹 필터링
  Phase 3 ▶ Pyrogram UserBot으로 각 그룹 멤버 수집
              (@username 있는 유저만 → UserBot 선톡 가능)
  Phase 4 ▶ PostgreSQL broadcast_targets에 저장 (중복 안전)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

사용법:
  cd "c:\\my bot"
  python3.12 automation/scripts/member_scraper.py

필요 환경변수 (bot/.env):
  SESSION_STRING  – Pyrogram 세션 문자열
  API_ID / API_HASH – 기본값 내장
  DATABASE_URL    – PostgreSQL 연결 문자열

진행 알림 (선택):
  BOT_TOKEN + ADMIN_ID 를 .env에 넣으면 채굴 시작/그룹 완료/전체 완료 시
  해당 채팅으로 텔레그램 알림이 전송됩니다.

EXTRA_GROUPS: 직접 아는 그룹을 추가하면 자동 발굴 결과에 합산됩니다.
"""
from __future__ import annotations

import asyncio
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, unquote, urlparse

# ── 경로 / 환경변수 ────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation"))
sys.path.insert(0, str(ROOT / "bot"))

from dotenv import load_dotenv
load_dotenv(ROOT / "bot" / ".env")
load_dotenv(ROOT / "automation" / ".env")

import httpx
import psycopg2
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

# ── 자격증명 ──────────────────────────────────────────────────────────────────
API_ID         = int(os.getenv("API_ID", "37398454"))
API_HASH       = os.getenv("API_HASH", "a73350e09f51f516d8eac08498967750")
SESSION_STRING = os.getenv("SESSION_STRING", "")
DATABASE_URL   = os.getenv("DATABASE_URL", "")
BOT_TOKEN      = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID       = (os.getenv("ADMIN_ID") or "").strip()  # 채굴 진행 알림 받을 채팅 ID

# ── 검색 타겟 쿼리 목록 (자동 발굴 범위) ──────────────────────────────────────
SEARCH_QUERIES = [
    # 한국어 카지노/베팅 커뮤니티
    "카지노 텔레그램 그룹 site:t.me",
    "온라인카지노 텔레그램 그룹",
    "바카라 텔레그램 커뮤니티",
    "슬롯 텔레그램 그룹",
    "해외배팅 텔레그램 채널",
    "원윈 텔레그램",
    "1win 텔레그램 한국",
    # 글로벌 브랜드
    "1win telegram group",
    "Stake casino telegram group",
    "BC.Game telegram community",
    "Rollbit telegram group",
    "online casino telegram members",
    "casino telegram channel korea",
    "gambling telegram group link",
]

# ── 직접 아는 그룹 추가 (옵션) ────────────────────────────────────────────────
EXTRA_GROUPS: list[str] = [
    # "@my_casino_group",   # 예: 직접 아는 그룹 주소
]

# ── 딜레이 설정 ───────────────────────────────────────────────────────────────
PER_USER_DELAY_SEC    = float(os.getenv("SCRAPER_USER_DELAY",    "0.05"))
PER_GROUP_DELAY_SEC   = float(os.getenv("SCRAPER_GROUP_DELAY",   "5.0"))
SEARCH_DELAY_SEC      = float(os.getenv("SCRAPER_SEARCH_DELAY",  "3.0"))
MAX_MEMBERS_PER_GROUP = int(  os.getenv("SCRAPER_MAX_MEMBERS",   "3000"))

# DuckDuckGo 검색 시 브라우저 위장용 User-Agent 목록
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 텔레그램 진행 알림 (BOT_TOKEN + ADMIN_ID 설정 시에만 동작)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _telegram_notify(text: str) -> None:
    """관리자(ADMIN_ID)에게 텔레그램 메시지 전송. 실패 시 무시."""
    if not BOT_TOKEN or not ADMIN_ID:
        return
    text = (text or "")[:4000]  # API 제한
    try:
        with httpx.Client(timeout=10) as hc:
            r = hc.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_ID, "text": text, "disable_web_page_preview": True},
            )
            if r.status_code != 200:
                pass  # 로그만 생략
    except Exception:
        pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 1: DuckDuckGo 검색으로 t.me 링크 자동 발굴
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _extract_tme_from_html(html: str) -> list[str]:
    """HTML에서 t.me/... 형태의 URL 추출."""
    soup = BeautifulSoup(html, "lxml")
    found: list[str] = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        # DuckDuckGo 리다이렉트 URL 벗기기
        if "uddg=" in href:
            try:
                href = unquote(re.search(r"uddg=([^&]+)", href).group(1))
            except Exception:
                pass
        if "/url?q=" in href:
            try:
                href = unquote(href.split("/url?q=")[1].split("&")[0])
            except Exception:
                pass
        if "t.me/" in href:
            found.append(href)
    # 텍스트에서 직접 t.me 패턴 추출 (a 태그에 없는 것 보완)
    for match in re.findall(r"https?://t\.me/[A-Za-z0-9_@+/]+", html):
        found.append(match)
    return found


def _search_duckduckgo(query: str) -> list[str]:
    """
    DuckDuckGo HTML 검색으로 t.me 링크 수집.
    브라우저 없이 단순 HTTP 요청으로 동작 (scrapling 불필요).
    """
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
        print(f"    ⚠️ DuckDuckGo 검색 실패 ({query[:30]}...): {e}")
        return []


def _tme_url_to_handle(url: str) -> str | None:
    """
    'https://t.me/groupname'  →  '@groupname'
    초대링크 (t.me/+..., joinchat) → None
    """
    try:
        path = urlparse(url).path.lstrip("/")
    except Exception:
        return None
    if not path:
        return None
    if path.startswith("+") or path.lower().startswith("joinchat"):
        return None   # 초대링크
    path = path.split("/")[0]
    if len(path) < 4 or path.isdigit():
        return None   # 너무 짧거나 숫자만
    return f"@{path}"


def discover_groups() -> list[str]:
    """
    SEARCH_QUERIES를 DuckDuckGo로 검색해 @username 그룹 핸들 목록 반환.
    """
    print("\n🔍 [Phase 1] DuckDuckGo 검색으로 경쟁사 그룹 자동 발굴 중...")
    handles: list[str] = []
    seen: set[str] = set()

    for i, query in enumerate(SEARCH_QUERIES):
        print(f"  [{i+1}/{len(SEARCH_QUERIES)}] 검색 중: {query}")
        raw_urls = _search_duckduckgo(query)

        found_this = 0
        for url in raw_urls:
            handle = _tme_url_to_handle(url)
            if handle and handle.lower() not in seen:
                seen.add(handle.lower())
                handles.append(handle)
                found_this += 1
                print(f"    ✅ 발굴: {handle}")

        if found_this == 0:
            print(f"    → t.me 링크 없음")

        # 검색 간 딜레이 (차단 방지)
        if i < len(SEARCH_QUERIES) - 1:
            time.sleep(SEARCH_DELAY_SEC)

    print(f"\n  📋 자동 발굴 완료: 공개 그룹 {len(handles)}개\n")
    return handles


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 4: PostgreSQL 저장
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _get_conn():
    if not DATABASE_URL:
        print("❌ DATABASE_URL이 없습니다. bot/.env를 확인하세요.")
        sys.exit(1)
    return psycopg2.connect(DATABASE_URL)


def ensure_table(conn) -> None:
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS broadcast_targets (
                    telegram_user_id BIGINT PRIMARY KEY,
                    username         TEXT        NOT NULL DEFAULT '',
                    source           TEXT        NOT NULL DEFAULT 'scraper',
                    added_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    is_sent          BOOLEAN     NOT NULL DEFAULT FALSE,
                    sent_at          TIMESTAMPTZ
                )
            """)


def save_batch(conn, batch: list[tuple[int, str, str]]) -> int:
    """username 자동 보정 포함 배치 저장.

    - 신규 유저: INSERT
    - 기존 유저:
        • 기존 username이 비어 있거나(NULL/''), 새 username과 다르면 → UPDATE로 username/source 갱신
        • 이미 username이 동일하면 아무 작업 안 함
    """
    if not batch:
        return 0
    inserted_or_updated = 0
    with conn:
        with conn.cursor() as cur:
            for uid, username, source in batch:
                cur.execute("""
                    INSERT INTO broadcast_targets (telegram_user_id, username, source)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (telegram_user_id) DO UPDATE
                    SET
                        username = EXCLUDED.username,
                        source   = EXCLUDED.source
                    WHERE
                        broadcast_targets.username IS NULL
                        OR broadcast_targets.username = ''
                        OR broadcast_targets.username <> EXCLUDED.username
                """, (uid, username, source))
                inserted_or_updated += cur.rowcount
    return inserted_or_updated


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 3: Pyrogram 멤버 수집
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def scrape_group(app: Client, conn, handle: str) -> tuple[int, int]:
    """단일 그룹 멤버 수집. Returns: (저장된 수, 건너뜀 수)"""
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
                saved += save_batch(conn, batch)
                batch.clear()
                print(f"    💾 중간 저장 완료 (누적 {count}명 처리)")

            if PER_USER_DELAY_SEC > 0:
                await asyncio.sleep(PER_USER_DELAY_SEC)

            if count >= MAX_MEMBERS_PER_GROUP:
                print(f"    ⚠️ 최대 수집 한도 {MAX_MEMBERS_PER_GROUP}명 도달")
                break

        if batch:
            saved += save_batch(conn, batch)

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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def main():
    print()
    print("=" * 62)
    print("   경쟁사 멤버 자동 수집기  (DuckDuckGo + Pyrogram + PG)")
    print("=" * 62)

    if not SESSION_STRING:
        print("\n❌ SESSION_STRING 환경변수가 없습니다.")
        print("   생성: python3.12 bot/scripts/generate_session.py")
        sys.exit(1)

    # ── Phase 1: 자동 발굴 ────────────────────────────────────────────────────
    auto_groups = discover_groups()

    # EXTRA_GROUPS 합산 (중복 제거)
    all_groups: list[str] = list(auto_groups)
    seen_lower: set[str] = {h.lower() for h in auto_groups}
    for raw in EXTRA_GROUPS:
        h = raw if raw.startswith("@") else f"@{raw}"
        if h.lower() not in seen_lower:
            seen_lower.add(h.lower())
            all_groups.append(h)
            print(f"  ➕ 수동 추가: {h}")

    if not all_groups:
        print("\n⚠️ 수집 가능한 그룹이 없습니다.")
        print("  → EXTRA_GROUPS에 직접 그룹 주소를 추가하거나")
        print("    SEARCH_QUERIES 쿼리를 조정하세요.")
        sys.exit(0)

    print(f"\n📋 총 {len(all_groups)}개 그룹에서 멤버 수집 시작합니다.")

    _telegram_notify(
        "🔍 채굴(멤버 수집) 시작\n"
        f"• 발굴된 그룹: {len(all_groups)}개\n"
        f"• 목록: {', '.join(all_groups[:10])}{'...' if len(all_groups) > 10 else ''}"
    )

    # ── Phase 2~4: Pyrogram 수집 + DB 저장 ───────────────────────────────────
    conn = _get_conn()
    ensure_table(conn)
    print("✅ PostgreSQL 연결 완료\n")

    total_saved = total_skipped = 0
    ok_groups = fail_groups = 0

    async with Client(
        name="scraper_session",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING,
    ) as app:
        for i, handle in enumerate(all_groups):
            try:
                s, sk = await scrape_group(app, conn, handle)
                total_saved   += s
                total_skipped += sk
                ok_groups += 1
                _telegram_notify(
                    f"📤 그룹 완료 ({i+1}/{len(all_groups)})\n"
                    f"• {handle} → 신규 저장 {s}명 / 건너뜀 {sk}명\n"
                    f"• 누적 저장: {total_saved}명"
                )
            except Exception as e:
                print(f"  ❌ [{handle}] 처리 실패: {e}")
                fail_groups += 1
                _telegram_notify(f"❌ 그룹 실패 [{handle}]\n{type(e).__name__}: {e}")

            if i < len(all_groups) - 1:
                print(f"  ⏳ 다음 그룹까지 {PER_GROUP_DELAY_SEC:.0f}초 대기...")
                await asyncio.sleep(PER_GROUP_DELAY_SEC)

    conn.close()

    summary = (
        f"🎉 채굴(멤버 수집) 완료!\n"
        f"• 처리 그룹: 성공 {ok_groups}개 / 실패 {fail_groups}개\n"
        f"• 신규 저장: {total_saved}명 → Railway PG\n"
        f"• 건너뜀: {total_skipped}명\n"
        f"▶ 발송: 봇 /admin → 🚀 장전된 메시지 발사"
    )
    _telegram_notify(summary)

    print()
    print("=" * 62)
    print("  🎉 전체 수집 완료!")
    print(f"  • 처리 그룹: 성공 {ok_groups}개 / 실패 {fail_groups}개")
    print(f"  • 신규 저장: {total_saved}명  → PostgreSQL broadcast_targets")
    print(f"  • 건너뜀:   {total_skipped}명  (username 없음/봇/삭제계정)")
    print()
    print("  ▶ 발송: 텔레그램 봇 /admin → 🚀 장전된 메시지 발사")
    print("=" * 62)
    print()


if __name__ == "__main__":
    asyncio.run(main())
