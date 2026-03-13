"""
경쟁사 텔레그램 그룹 멤버 수집기 (Pyrogram + PostgreSQL)

사용법:
  1) .env 또는 환경변수에 SESSION_STRING, API_ID, API_HASH, DATABASE_URL 설정
  2) TARGET_GROUPS 리스트에 수집할 그룹 주소 입력 (예: @casino_vip)
  3) python automation/scripts/member_scraper.py

수집 기준:
  - username(@아이디)이 있는 유저만 broadcast_targets에 저장
  - username 없는 유저는 MTProto UserBot으로 선톡 불가 → 건너뜀
  - ON CONFLICT DO NOTHING → 중복 실행 안전
"""
import asyncio
import os
import sys
from pathlib import Path

# .env 로드 (automation/.env 또는 루트 .env)
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / "bot" / ".env")
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import psycopg2
from pyrogram import Client
from pyrogram.errors import ChatAdminRequired, ChannelPrivate, FloodWait, RPCError

# ── 설정 ──────────────────────────────────────────────────────────────────────

# ★ 수집할 경쟁사 그룹/채널 목록 (@ 포함, 여러 개 가능)
TARGET_GROUPS = [
    # "@casino_group_1",
    # "@casino_group_2",
]

# 환경변수에서 자격증명 읽기
API_ID         = int(os.getenv("API_ID", "37398454"))
API_HASH       = os.getenv("API_HASH", "a73350e09f51f516d8eac08498967750")
SESSION_STRING = os.getenv("SESSION_STRING", "")
DATABASE_URL   = os.getenv("DATABASE_URL", "")

# ── 유저당 딜레이 (차단 방지) ──────────────────────────────────────────────────
PER_USER_DELAY_SEC  = 0.05   # 멤버 1명 처리마다 (초)
PER_GROUP_DELAY_SEC = 3.0    # 그룹 사이 (초)


# ── DB 저장 ───────────────────────────────────────────────────────────────────

def _get_conn():
    url = DATABASE_URL
    if not url:
        print("❌ DATABASE_URL이 설정되지 않았습니다. .env를 확인하세요.")
        sys.exit(1)
    return psycopg2.connect(url)


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


def save_user(conn, user_id: int, username: str, source: str) -> bool:
    """Return True if a new row was inserted."""
    with conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO broadcast_targets (telegram_user_id, username, source)
                VALUES (%s, %s, %s)
                ON CONFLICT (telegram_user_id) DO NOTHING
            """, (user_id, username, source))
            return cur.rowcount > 0


# ── 수집 로직 ─────────────────────────────────────────────────────────────────

async def scrape_group(app: Client, conn, group: str) -> tuple[int, int]:
    """그룹 멤버 수집. (저장된 수, 건너뛴 수) 반환."""
    print(f"\n🔍 [{group}] 멤버 수집 시작...")
    saved = skipped = 0
    try:
        async for member in app.get_chat_members(group):
            user = member.user
            if not user or user.is_bot or user.is_deleted:
                skipped += 1
                continue

            username = (user.username or "").strip()
            if not username:
                # username 없는 유저 → UserBot 선톡 불가 → 건너뜀
                skipped += 1
                continue

            inserted = save_user(conn, user.id, username, source=group)
            if inserted:
                saved += 1

            if PER_USER_DELAY_SEC > 0:
                await asyncio.sleep(PER_USER_DELAY_SEC)

    except (ChatAdminRequired, ChannelPrivate) as e:
        print(f"  ⚠️ [{group}] 멤버 조회 권한 없음 — {e}")
    except FloodWait as e:
        print(f"  ⚠️ FloodWait {e.value}초 대기 중...")
        await asyncio.sleep(e.value + 5)
    except RPCError as e:
        print(f"  ❌ RPCError [{group}]: {e}")
    except Exception as e:
        print(f"  ❌ 알 수 없는 에러 [{group}]: {type(e).__name__} — {e}")

    print(f"  ✅ [{group}] 완료: 신규 저장 {saved}명 / 건너뜀(username 없음 등) {skipped}명")
    return saved, skipped


async def main():
    if not TARGET_GROUPS:
        print()
        print("❌ TARGET_GROUPS가 비어 있습니다.")
        print("   이 파일 상단의 TARGET_GROUPS 리스트에 그룹 주소를 입력하세요.")
        print("   예: TARGET_GROUPS = ['@casino_vip', '@casino_group2']")
        print()
        sys.exit(1)

    if not SESSION_STRING:
        print("❌ SESSION_STRING 환경변수가 없습니다.")
        print("   bot/.env 또는 Railway Variables에 SESSION_STRING을 추가하세요.")
        print("   생성 방법: python bot/scripts/generate_session.py")
        sys.exit(1)

    print("=" * 58)
    print("  경쟁사 멤버 수집기 (Pyrogram + PostgreSQL)")
    print("=" * 58)
    print(f"  대상 그룹: {TARGET_GROUPS}")
    print()

    conn = _get_conn()
    ensure_table(conn)

    total_saved = total_skipped = 0

    async with Client(
        name="scraper_session",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING,
    ) as app:
        for i, group in enumerate(TARGET_GROUPS):
            saved, skipped = await scrape_group(app, conn, group)
            total_saved   += saved
            total_skipped += skipped

            if i < len(TARGET_GROUPS) - 1 and PER_GROUP_DELAY_SEC > 0:
                print(f"  ⏳ 다음 그룹까지 {PER_GROUP_DELAY_SEC:.0f}초 대기...")
                await asyncio.sleep(PER_GROUP_DELAY_SEC)

    conn.close()

    print()
    print("=" * 58)
    print(f"  🎉 전체 수집 완료!")
    print(f"  • 신규 저장: {total_saved}명")
    print(f"  • 건너뜀:   {total_skipped}명 (username 없음/봇/삭제된 계정)")
    print("=" * 58)


if __name__ == "__main__":
    asyncio.run(main())
