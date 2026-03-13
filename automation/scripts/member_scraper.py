"""
경쟁사 텔레그램 멤버 자동 수집기
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[자동화 흐름]
  Phase 1 ▶ 구글 검색으로 경쟁사 텔레그램 그룹 자동 발굴
              (link_finder.py 의 쿼리 목록으로 t.me 링크 수집)
  Phase 2 ▶ 발굴된 링크 중 @username 형태의 공개 그룹 필터링
  Phase 3 ▶ Pyrogram UserBot으로 각 그룹 멤버 수집
              (@username 있는 유저만 → UserBot 선톡 가능)
  Phase 4 ▶ PostgreSQL broadcast_targets에 저장 (중복 안전)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

사용법:
  cd "c:\\my bot"
  python automation/scripts/member_scraper.py

필요 환경변수 (bot/.env 또는 Railway Variables):
  SESSION_STRING  – Pyrogram 세션 문자열
  API_ID          – 37398454 (기본값 내장)
  API_HASH        – a73350e09f51f516d8eac08498967750 (기본값 내장)
  DATABASE_URL    – PostgreSQL 연결 문자열

추가 수동 타겟 (옵션):
  EXTRA_GROUPS 리스트에 직접 아는 그룹 주소를 추가하면
  구글 발굴 결과에 합산됩니다.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation"))
sys.path.insert(0, str(ROOT / "bot"))

# .env 로드
from dotenv import load_dotenv
load_dotenv(ROOT / "bot" / ".env")
load_dotenv(ROOT / "automation" / ".env")

import psycopg2
from pyrogram import Client
from pyrogram.errors import (
    ChatAdminRequired,
    ChannelPrivate,
    FloodWait,
    InviteHashExpired,
    RPCError,
    UsernameNotOccupied,
    UsernameInvalid,
)

# ── 자격증명 ──────────────────────────────────────────────────────────────────
API_ID         = int(os.getenv("API_ID", "37398454"))
API_HASH       = os.getenv("API_HASH", "a73350e09f51f516d8eac08498967750")
SESSION_STRING = os.getenv("SESSION_STRING", "")
DATABASE_URL   = os.getenv("DATABASE_URL", "")

# ── 추가 수동 타겟 (구글 자동 발굴에 더해서 직접 지정 가능) ───────────────────
EXTRA_GROUPS: list[str] = [
    # "@casino_korea_vip",  # 예시: 직접 아는 그룹 주소 추가
]

# ── 딜레이 설정 (차단 방지) ───────────────────────────────────────────────────
PER_USER_DELAY_SEC  = float(os.getenv("SCRAPER_USER_DELAY",  "0.05"))
PER_GROUP_DELAY_SEC = float(os.getenv("SCRAPER_GROUP_DELAY", "5.0"))
MAX_MEMBERS_PER_GROUP = int(os.getenv("SCRAPER_MAX_MEMBERS", "3000"))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 1: 구글 자동 발굴
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _tme_url_to_handle(url: str) -> str | None:
    """
    t.me/groupname → '@groupname'
    t.me/+invite  → None  (초대링크는 건너뜀)
    t.me/joinchat → None
    """
    try:
        path = urlparse(url).path.lstrip("/")
    except Exception:
        return None

    # 초대 링크 / 봇 / 공유 링크 등 제외
    if not path:
        return None
    if path.startswith("+") or path.startswith("joinchat"):
        return None
    if "/" in path:          # t.me/s/channel 형태 등 sub-path
        path = path.split("/")[0]
    if not path:
        return None

    # 짧은 핸들이나 숫자만인 경우 제외
    if len(path) < 4 or path.isdigit():
        return None

    return f"@{path}"


def discover_groups_via_google() -> list[str]:
    """
    link_finder.py 를 사용해 구글 검색으로 t.me 링크를 자동 발굴,
    @handle 형태의 공개 그룹 주소 목록을 반환합니다.
    """
    print("\n🔍 [Phase 1] 구글 검색으로 경쟁사 그룹 자동 발굴 중...")
    try:
        from app.services.link_finder import find_competitor_telegram_links
    except ImportError as e:
        print(f"  ⚠️ link_finder 임포트 실패: {e}")
        print("  → 구글 자동 발굴을 건너뜁니다. EXTRA_GROUPS만 사용합니다.")
        return []

    try:
        raw_links = find_competitor_telegram_links()
    except Exception as e:
        print(f"  ⚠️ 구글 검색 실패: {e}")
        print("  → EXTRA_GROUPS만 사용합니다.")
        return []

    handles: list[str] = []
    seen: set[str] = set()
    for link in raw_links:
        handle = _tme_url_to_handle(link.url)
        if handle and handle not in seen:
            seen.add(handle)
            handles.append(handle)
            print(f"  ✅ 발굴: {handle}  (출처 쿼리: {link.brand_query})")

    print(f"\n  📋 발굴된 공개 그룹 핸들: {len(handles)}개\n")
    return handles


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 4: PostgreSQL 저장
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _get_conn():
    if not DATABASE_URL:
        print("❌ DATABASE_URL이 설정되지 않았습니다. bot/.env를 확인하세요.")
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
    print("✅ broadcast_targets 테이블 준비 완료")


def save_user_batch(conn, batch: list[tuple[int, str, str]]) -> int:
    """
    batch = [(telegram_user_id, username, source), ...]
    중복은 무시. 새로 삽입된 행 수 반환.
    """
    if not batch:
        return 0
    inserted = 0
    with conn:
        with conn.cursor() as cur:
            for uid, username, source in batch:
                cur.execute("""
                    INSERT INTO broadcast_targets (telegram_user_id, username, source)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (telegram_user_id) DO NOTHING
                """, (uid, username, source))
                inserted += cur.rowcount
    return inserted


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase 3: Pyrogram 멤버 수집
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def scrape_group(
    app: Client,
    conn,
    handle: str,
) -> tuple[int, int]:
    """
    단일 그룹 멤버 수집.
    Returns: (새로 저장된 수, 건너뛴 수)
    """
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

            # 배치 단위로 DB 저장 (메모리 절약)
            if len(batch) >= BATCH_SIZE:
                saved += save_user_batch(conn, batch)
                batch.clear()

            if PER_USER_DELAY_SEC > 0:
                await asyncio.sleep(PER_USER_DELAY_SEC)

            if count >= MAX_MEMBERS_PER_GROUP:
                print(f"    ⚠️ 최대 수집 한도({MAX_MEMBERS_PER_GROUP}명) 도달 — 다음 그룹으로")
                break

        # 나머지 배치 저장
        if batch:
            saved += save_user_batch(conn, batch)

    except (ChatAdminRequired, ChannelPrivate) as e:
        print(f"    ⚠️ [{handle}] 멤버 조회 권한 없음 — {type(e).__name__}")
    except (UsernameNotOccupied, UsernameInvalid) as e:
        print(f"    ⚠️ [{handle}] 존재하지 않는 그룹 — {type(e).__name__}")
    except FloodWait as e:
        wait = e.value + 10
        print(f"    ⏳ FloodWait {wait}초 대기 중... (스팸 방지)")
        await asyncio.sleep(wait)
    except RPCError as e:
        print(f"    ❌ [{handle}] RPCError: {type(e).__name__} — {e}")
    except Exception as e:
        print(f"    ❌ [{handle}] 에러: {type(e).__name__} — {e}")

    print(f"    ✅ [{handle}] 완료 → 신규 저장 {saved}명 / 건너뜀 {skipped}명")
    return saved, skipped


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def main():
    print()
    print("=" * 62)
    print("   경쟁사 멤버 자동 수집기  (구글 발굴 + Pyrogram + PG)")
    print("=" * 62)

    # 환경변수 체크
    if not SESSION_STRING:
        print("\n❌ SESSION_STRING 환경변수가 없습니다.")
        print("   생성 방법: python bot/scripts/generate_session.py")
        sys.exit(1)

    # ── Phase 1: 구글로 그룹 자동 발굴 ───────────────────────────────────────
    auto_groups = discover_groups_via_google()

    # EXTRA_GROUPS 합산 (중복 제거)
    all_groups: list[str] = []
    seen_handles: set[str] = set(h.lower() for h in auto_groups)
    all_groups.extend(auto_groups)
    for h in EXTRA_GROUPS:
        handle = h if h.startswith("@") else f"@{h}"
        if handle.lower() not in seen_handles:
            seen_handles.add(handle.lower())
            all_groups.append(handle)
            print(f"  ➕ 수동 추가: {handle}")

    if not all_groups:
        print("\n⚠️ 수집 가능한 그룹이 없습니다.")
        print("   → EXTRA_GROUPS에 직접 그룹 주소를 추가하거나,")
        print("     구글 검색이 정상 작동하는지 확인하세요.")
        sys.exit(0)

    print(f"\n📋 총 {len(all_groups)}개 그룹에서 멤버 수집 시작합니다.")
    print(f"   그룹 목록: {all_groups}\n")

    # ── Phase 2 + 3 + 4: DB 연결 → Pyrogram 세션 → 수집 → 저장 ──────────────
    conn = _get_conn()
    ensure_table(conn)

    total_saved = total_skipped = 0
    success_groups = failed_groups = 0

    async with Client(
        name="scraper_session",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING,
    ) as app:
        for i, handle in enumerate(all_groups):
            try:
                saved, skipped = await scrape_group(app, conn, handle)
                total_saved   += saved
                total_skipped += skipped
                success_groups += 1
            except Exception as e:
                print(f"  ❌ [{handle}] 예외 처리 실패: {e}")
                failed_groups += 1

            # 그룹 사이 딜레이 (마지막 그룹 제외)
            if i < len(all_groups) - 1:
                print(f"  ⏳ 다음 그룹까지 {PER_GROUP_DELAY_SEC:.0f}초 대기 (스팸 방지)...")
                await asyncio.sleep(PER_GROUP_DELAY_SEC)

    conn.close()

    print()
    print("=" * 62)
    print("  🎉 전체 수집 완료!")
    print(f"  • 처리 그룹: 성공 {success_groups}개 / 실패 {failed_groups}개")
    print(f"  • 신규 저장: {total_saved}명  (is_sent=FALSE — 발송 대기 중)")
    print(f"  • 건너뜀:   {total_skipped}명  (username 없음 / 봇 / 삭제계정)")
    print()
    print("  ▶ 발송하려면 텔레그램 봇 /admin → 🚀 장전된 메시지 발사")
    print("=" * 62)
    print()


if __name__ == "__main__":
    asyncio.run(main())
