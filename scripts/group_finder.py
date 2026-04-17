"""
텔레그램 그룹 자동 발굴 — Bright Data SERP API + Pyrogram get_chat() 검증.
매일 03:00 UTC 스케줄러에서 실행.

흐름:
  1. BRIGHTDATA_API_TOKEN으로 Bright Data SERP API 호출 → t.me 링크 수집
  2. t.me 링크에서 username 추출
  3. SESSION_STRING_1 (없으면 SESSION_STRING)으로 Pyrogram 연결
  4. get_chat()으로 username + 실제 멤버 수 재확인
  5. 조건 통과 시 discovered_groups 테이블에 저장
  6. 완료 후 관리자 DM 알림
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup
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
BRIGHTDATA_API_TOKEN = (os.getenv("BRIGHTDATA_API_TOKEN") or "").strip()

MAX_GROUPS_PER_RUN      = int(os.getenv("MAX_GROUPS_PER_RUN",      "20"))
MAX_RESULTS_PER_KEYWORD = int(os.getenv("MAX_RESULTS_PER_KEYWORD", "50"))
KEYWORD_DELAY_SEC       = float(os.getenv("KEYWORD_DELAY_SEC",     "3.0"))
MIN_MEMBER_COUNT        = int(os.getenv("MIN_MEMBER_COUNT",        "1000"))

# 환경변수 SEARCH_KEYWORDS 가 있으면 덮어쓴다 (쉼표 구분)
_DEFAULT_KEYWORDS = [
    "cassino brasil",
    "fortune tiger grupo",
    "tigrinho apostas",
    "aviator brasil",
    "1win brasil",
    "apostas esportivas grupo",
    "crypto cassino brasil",
    "betano grupo telegram",
    "stake brasil telegram",
    "bonus cassino telegram",
    "cassino online brasil",
    "slots brasil grupo",
    "gates of olympus telegram",
    "crash game brasil",
    "bitcoin cassino grupo",
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
    for i in range(1, 11):
        val = (os.getenv(f"SESSION_STRING_{i}") or "").strip()
        if val:
            return (f"SESSION_STRING_{i}", val)
    val = (os.getenv("SESSION_STRING") or "").strip()
    if val:
        return ("SESSION_STRING", val)
    return None


_TME_RE = re.compile(r"(?:https?://)?t\.me/[A-Za-z0-9_@+/]+")


def _extract_tme_from_html(html: str) -> list[str]:
    """
    HTML에서 t.me URL 추출.
    1단계: BeautifulSoup으로 <a href> 파싱 (https://, http://, t.me/ 모두 커버)
    2단계: 정규식으로 텍스트 전체 스캔 (fallback)
    """
    found: list[str] = []

    # 1단계: BeautifulSoup href 파싱
    try:
        soup = BeautifulSoup(html, "lxml")
        links = soup.find_all("a", href=True)
        t_me_urls = [a["href"] for a in links if "t.me/" in a["href"]]
        found.extend(t_me_urls)
    except Exception:
        pass

    # 2단계: 정규식 스캔 (https?:// 없는 순수 t.me/ 형태도 포함)
    for match in _TME_RE.findall(html):
        found.append(match)

    return found


def _search_brightdata(query: str) -> list[str]:
    """
    Bright Data SERP API로 Google 검색 → t.me URL 목록 반환.
    응답이 JSON이면 organic 결과 파싱, 아니면 HTML 파싱 fallback.
    """
    if not BRIGHTDATA_API_TOKEN:
        return []

    # site:t.me 는 URL에 하드코딩 (quote()로 인코딩하면 %3A로 변환돼 연산자 인식 안 됨)
    google_url = (
        f"https://www.google.com/search"
        f"?q=site:t.me+{quote_plus(query)}&num=20&gl=br&hl=pt-BR"
    )

    try:
        with httpx.Client(timeout=60) as hc:
            resp = hc.post(
                "https://api.brightdata.com/request",
                headers={
                    "Authorization": f"Bearer {BRIGHTDATA_API_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={"zone": "serp", "url": google_url, "format": "raw",
                      "country": "BR"},
            )
    except Exception as e:
        print(f"    ⚠️ Bright Data 요청 실패: {type(e).__name__} — {e}")
        return []

    if resp.status_code != 200:
        print(f"    ⚠️ Bright Data HTTP {resp.status_code}: {resp.text[:300]}")
        return []

    content_type = resp.headers.get("content-type", "")
    print(f"    📡 응답 status={resp.status_code} content-type={content_type} len={len(resp.text)}")

    urls: list[str] = []

    if "json" in content_type:
        try:
            data = resp.json()
            for item in data.get("organic", data.get("results", [])):
                link = item.get("link") or item.get("url") or ""
                if "t.me/" in link:
                    urls.append(link)
                for field in ("snippet", "description", "title"):
                    text = item.get(field) or ""
                    urls.extend(_TME_RE.findall(text))
        except Exception:
            pass

    if not urls:
        urls = _extract_tme_from_html(resp.text)

    # ── 디버그: 추출된 URL 전체 출력 ─────────────────────────────
    if urls:
        print(f"    🔗 추출된 t.me URL {len(urls)}개:")
        for u in urls:
            print(f"      {u}")
    else:
        print(f"    🔗 추출된 t.me URL 없음 (응답 앞부분): {resp.text[:400]}")

    return urls


def _tme_url_to_username(url: str) -> str | None:
    """t.me URL → username. 초대링크(+, joinchat) 는 None. 프로토콜 없는 형태도 처리."""
    try:
        if not url.startswith("http"):
            url = "https://" + url.lstrip("/")
        path = urlparse(url).path.lstrip("/")
    except Exception:
        return None
    if not path:
        return None
    slug = path.split("/")[0]
    if slug.startswith("+") or slug.lower().startswith("joinchat"):
        return None
    if len(slug) < 4 or slug.isdigit():
        return None
    return slug


async def _verify_groups(
    client,
    usernames: list[str],
    seen_ids: set[int],
    min_members: int,
) -> list[dict]:
    """
    Pyrogram get_chat()으로 각 username을 검증.
    반환: [{"id", "username", "title", "member_count"}, ...]
    """
    from pyrogram.errors import FloodWait

    results: list[dict] = []
    no_username = low_members = fail_count = 0

    for uname in usernames:
        try:
            full = await client.get_chat(f"@{uname}")
        except FloodWait as e:
            wait = int(e.value or 30) + 5
            print(f"    ⏳ get_chat FloodWait {wait}초 대기...")
            await asyncio.sleep(wait)
            try:
                full = await client.get_chat(f"@{uname}")
            except Exception as e2:
                fail_count += 1
                print(f"    ⚠️ get_chat 재시도 실패 @{uname}: {e2}")
                continue
        except Exception as e:
            fail_count += 1
            print(f"    ⚠️ get_chat 실패 @{uname}: {type(e).__name__} — {e}")
            continue

        chat_id = getattr(full, "id", None)
        if not chat_id or chat_id in seen_ids:
            continue

        actual_username = getattr(full, "username", None) or ""
        if not actual_username:
            no_username += 1
            continue

        member_count = getattr(full, "members_count", 0) or 0
        if member_count > 0 and member_count < min_members:
            low_members += 1
            continue

        seen_ids.add(chat_id)
        results.append({
            "id":           chat_id,
            "username":     actual_username,
            "title":        getattr(full, "title", "") or uname,
            "member_count": member_count,
        })
        await asyncio.sleep(0.4)

    print(
        f"    ✅ get_chat_fail={fail_count} / no_username={no_username} "
        f"/ low_members={low_members} / 최종={len(results)}"
    )
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
    print("   텔레그램 그룹 자동 발굴  (Bright Data SERP + Pyrogram)")
    print("=" * 62)

    if not BRIGHTDATA_API_TOKEN:
        msg = "❌ BRIGHTDATA_API_TOKEN 환경변수가 없습니다."
        print(msg)
        _notify(f"❌ group_finder 실패: {msg}")
        sys.exit(1)

    session_info = _get_session()
    if not session_info:
        msg = "❌ SESSION_STRING 환경변수가 없습니다."
        print(msg)
        _notify(f"❌ group_finder 실패: {msg}")
        sys.exit(1)

    label, session_string = session_info
    print(f"✅ 세션 사용: {label}")
    print(f"🔑 검색 키워드 {len(SEARCH_KEYWORDS)}개: {', '.join(SEARCH_KEYWORDS[:3])}...")
    print(f"👥 멤버 수 필터: {MIN_MEMBER_COUNT:,}명 이상")

    ensure_discovered_groups_table()
    deleted = truncate_discovered_groups()
    print(f"🗑️  기존 데이터 {deleted}개 삭제 (discovered_groups 초기화)\n")

    _notify(
        f"🔍 그룹 발굴 시작 (Bright Data SERP)\n"
        f"• 키워드: {len(SEARCH_KEYWORDS)}개\n"
        f"• 최대 발굴: {MAX_GROUPS_PER_RUN}개\n"
        f"• 멤버 최소: {MIN_MEMBER_COUNT:,}명\n"
        f"• 기존 데이터 {deleted}개 삭제"
    )

    # Phase 1: Bright Data SERP → username 후보 수집
    print("\n[Phase 1] Bright Data SERP API로 t.me 링크 수집 중...\n")
    username_candidates: list[str] = []
    seen_usernames: set[str] = set()

    for i, keyword in enumerate(SEARCH_KEYWORDS):
        print(f"  [{i+1}/{len(SEARCH_KEYWORDS)}] 검색: '{keyword}'")
        raw_urls = _search_brightdata(keyword)
        new_this_kw = 0
        for url in raw_urls:
            uname = _tme_url_to_username(url)
            if not uname:
                continue
            uname_lower = uname.lower()
            if uname_lower not in seen_usernames:
                seen_usernames.add(uname_lower)
                username_candidates.append(uname)
                new_this_kw += 1
        print(f"    🔎 raw_urls={len(raw_urls)} / 신규 username={new_this_kw} / 누적={len(username_candidates)}")
        if i < len(SEARCH_KEYWORDS) - 1:
            time.sleep(KEYWORD_DELAY_SEC)

    print(f"\n  📋 Phase 1 완료: username 후보 {len(username_candidates)}개\n")

    if not username_candidates:
        msg = "⚠️ Bright Data SERP에서 t.me 링크를 찾지 못했습니다."
        print(msg)
        _notify(f"⚠️ group_finder — {msg}")
        sys.exit(0)

    # Phase 2: Pyrogram get_chat()으로 실제 그룹 정보 검증
    print("[Phase 2] Pyrogram get_chat()으로 그룹 검증 중...\n")
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

        groups = await _verify_groups(
            client,
            username_candidates[:MAX_GROUPS_PER_RUN * 5],
            seen_ids,
            MIN_MEMBER_COUNT,
        )

        for g in groups:
            if total_new >= MAX_GROUPS_PER_RUN:
                break
            is_new = save_discovered_group(
                g["id"], g["username"], g["title"], g["member_count"]
            )
            if is_new:
                total_new += 1
                print(f"  ✅ @{g['username']} (멤버 {g['member_count']:,}명) 저장")
            else:
                total_dup += 1

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
