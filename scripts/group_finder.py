"""
텔레그램 그룹 자동 발굴 (Pyrogram search_global).
매일 03:00 스케줄러에서 실행.

흐름:
  1. SESSION_STRING_1 (없으면 SESSION_STRING) 으로 Pyrogram 연결
  2. SEARCH_KEYWORDS 키워드별 search_global 호출
  3. 그룹/슈퍼그룹/채널 중 username이 있는 것만 discovered_groups 테이블에 저장
  4. 완료 후 관리자 DM 알림
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
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "bot" / ".env")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

API_ID   = int((os.getenv("API_ID")   or "0").strip())
API_HASH = (os.getenv("API_HASH") or "").strip()
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

MAX_GROUPS_PER_RUN      = int(os.getenv("MAX_GROUPS_PER_RUN",      "20"))
MAX_RESULTS_PER_KEYWORD = int(os.getenv("MAX_RESULTS_PER_KEYWORD", "50"))
KEYWORD_DELAY_SEC       = float(os.getenv("KEYWORD_DELAY_SEC",     "5.0"))
MIN_MEMBER_COUNT        = int(os.getenv("MIN_MEMBER_COUNT",        "1000"))

# 환경변수 SEARCH_KEYWORDS 가 있으면 덮어쓴다 (쉼표 구분)
_DEFAULT_KEYWORDS = [
    "카지노", "바카라", "슬롯", "온라인카지노",
    "스포츠배팅", "토토", "해외배팅",
]
_kw_env = os.getenv("SEARCH_KEYWORDS", "").strip()
SEARCH_KEYWORDS: list[str] = (
    [k.strip() for k in _kw_env.split(",") if k.strip()]
    if _kw_env
    else _DEFAULT_KEYWORDS
)


def _notify(text: str) -> None:
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


def _get_session() -> tuple[str, str] | None:
    """SESSION_STRING_1 우선, 없으면 SESSION_STRING."""
    for i in range(1, 11):
        val = (os.getenv(f"SESSION_STRING_{i}") or "").strip()
        if val:
            return (f"SESSION_STRING_{i}", val)
    val = (os.getenv("SESSION_STRING") or "").strip()
    if val:
        return ("SESSION_STRING", val)
    return None


async def search_groups_by_keyword(
    client,
    keyword: str,
    seen_ids: set[int],
    max_per_keyword: int,
    min_members: int = 1000,
) -> list[dict]:
    """
    keyword로 search_global 호출 → 그룹/슈퍼그룹/채널 추출.
    반환: [{"id": int, "username": str, "title": str, "member_count": int}, ...]
    """
    from pyrogram.enums import ChatType
    from pyrogram.errors import FloodWait

    results: list[dict] = []
    valid_types = {ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL}

    try:
        count = 0
        async for message in client.search_global(keyword, limit=max_per_keyword):
            chat = message.chat
            if not chat or not chat.username:
                continue
            if chat.type not in valid_types:
                continue
            if chat.id in seen_ids:
                continue
            member_count = getattr(chat, "members_count", 0) or 0
            if member_count < min_members:
                continue
            seen_ids.add(chat.id)
            results.append({
                "id":           chat.id,
                "username":     chat.username,
                "title":        chat.title or "",
                "member_count": member_count,
            })
            count += 1
            if count >= max_per_keyword:
                break

    except FloodWait as e:
        wait = int(e.value or 30) + 5
        print(f"    ⏳ search_global FloodWait {wait}초 대기...")
        await asyncio.sleep(wait)
    except Exception as e:
        print(f"    ⚠️ '{keyword}' 검색 실패: {type(e).__name__} — {e}")

    return results


async def main() -> None:
    from pyrogram import Client
    from app.pg_broadcast import (
        ensure_discovered_groups_table,
        truncate_discovered_groups,
        save_discovered_group,
        count_discovered_groups,
    )

    print("\n" + "=" * 62)
    print("   텔레그램 그룹 자동 발굴  (Pyrogram search_global)")
    print("=" * 62)

    session_info = _get_session()
    if not session_info:
        print("❌ SESSION_STRING 환경변수가 없습니다.")
        _notify("❌ group_finder 실패: SESSION_STRING 없음")
        sys.exit(1)

    label, session_string = session_info
    print(f"✅ 세션 사용: {label}")
    print(f"🔑 검색 키워드 {len(SEARCH_KEYWORDS)}개: {', '.join(SEARCH_KEYWORDS)}")
    print(f"👥 멤버 수 필터: {MIN_MEMBER_COUNT:,}명 이상")

    ensure_discovered_groups_table()
    deleted = truncate_discovered_groups()
    print(f"🗑️  기존 데이터 {deleted}개 삭제 (discovered_groups 초기화)\n")

    _notify(
        f"🔍 그룹 발굴 시작\n"
        f"• 키워드: {len(SEARCH_KEYWORDS)}개\n"
        f"• 최대 발굴: {MAX_GROUPS_PER_RUN}개\n"
        f"• 멤버 최소: {MIN_MEMBER_COUNT:,}명\n"
        f"• 기존 데이터 {deleted}개 삭제"
    )

    total_new = 0
    total_dup = 0
    seen_ids: set[int] = set()

    async with Client(
        name=f"finder_{label}",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=session_string,
        in_memory=True,
    ) as client:
        me = await client.get_me()
        print(f"✅ Pyrogram 연결: @{me.username or me.id}\n")

        for i, keyword in enumerate(SEARCH_KEYWORDS):
            if total_new >= MAX_GROUPS_PER_RUN:
                print(f"⚠️  최대 발굴 수 {MAX_GROUPS_PER_RUN}개 도달 — 검색 중단")
                break

            remaining = MAX_GROUPS_PER_RUN - total_new
            per_kw = min(MAX_RESULTS_PER_KEYWORD, remaining * 3)

            print(f"  [{i+1}/{len(SEARCH_KEYWORDS)}] 검색: '{keyword}'")
            groups = await search_groups_by_keyword(client, keyword, seen_ids, per_kw, MIN_MEMBER_COUNT)

            for g in groups:
                if total_new >= MAX_GROUPS_PER_RUN:
                    break
                is_new = save_discovered_group(
                    g["id"], g["username"], g["title"], g["member_count"]
                )
                if is_new:
                    total_new += 1
                    print(
                        f"    ✅ @{g['username']} (멤버 {g['member_count']:,}명) 저장"
                    )
                else:
                    total_dup += 1

            print(
                f"    📊 이번 키워드: +{len(groups)}개 발견 "
                f"(누적 신규={total_new} / 중복={total_dup})"
            )

            if i < len(SEARCH_KEYWORDS) - 1:
                await asyncio.sleep(KEYWORD_DELAY_SEC)

    stats = count_discovered_groups()
    summary = (
        f"🎉 그룹 발굴 완료\n"
        f"• 신규 저장: {total_new}개\n"
        f"• 중복 스킵: {total_dup}개\n"
        f"• DB 전체: {stats['total']}개 / 미수집 대기: {stats['pending']}개"
    )
    print("\n" + "=" * 62)
    print(summary)
    print("=" * 62 + "\n")
    _notify(summary)


if __name__ == "__main__":
    asyncio.run(main())
