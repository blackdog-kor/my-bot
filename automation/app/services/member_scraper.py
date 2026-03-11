from __future__ import annotations

import asyncio
import os
import time
from typing import Iterable

from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.tl.types import User, UserStatusOffline, UserStatusOnline, UserStatusRecently

from app.db import save_competitor_user
from app.services.link_finder import TelegramLink, find_competitor_telegram_links


TG_API_ID = int(os.getenv("TG_API_ID", "0") or 0)
TG_API_HASH = os.getenv("TG_API_HASH", "").strip()
TG_SESSION_NAME = os.getenv("TG_SESSION_NAME", "competitor-member-scraper")


class TelegramConfigError(RuntimeError):
    pass


def _ensure_telegram_config() -> None:
    if not TG_API_ID or not TG_API_HASH:
        raise TelegramConfigError(
            "TG_API_ID and TG_API_HASH must be set in the environment to run member_scraper."
        )


def _status_to_str(status) -> str:
    if isinstance(status, UserStatusOnline):
        return "online"
    if isinstance(status, UserStatusRecently):
        return "recently"
    if isinstance(status, UserStatusOffline):
        # has .was_online datetime
        return f"offline:{getattr(status, 'was_online', '')}"
    return str(status or "")


async def _scrape_group_members_for_link(
    client: TelegramClient,
    link: TelegramLink,
    per_user_delay: float = 0.1,
) -> None:
    """
    주어진 텔레그램 링크(그룹/채널)에 접속해 멤버 정보를 수집합니다.
    """
    try:
        print(f"[member_scraper]   그룹 엔티티 조회 시도: {link.url}")
        entity = await client.get_entity(link.url)
    except RPCError as e:
        # 접근 권한 문제, 삭제된 그룹 등은 조용히 스킵
        print(f"[member_scraper] skip {link.url}: {e}")
        return

    print(f"[member_scraper]   참가자 목록 조회 시작: {link.url}")

    count = 0
    async for user in client.iter_participants(entity):
        if not isinstance(user, User):
            continue

        telegram_user_id = user.id
        username = user.username or ""
        last_seen = _status_to_str(user.status)

        save_competitor_user(
            source=link.brand_query,
            group_url=link.url,
            telegram_user_id=telegram_user_id,
            username=username,
            last_seen=last_seen,
        )

        # 너무 빠르게 긁지 않도록 사용자 단위 짧은 지연
        if per_user_delay > 0:
            await asyncio.sleep(per_user_delay)

        count += 1

    print(f"[member_scraper]   참가자 목록 조회 완료: {link.url}, 수집 인원: {count}")


async def _scrape_all_members(
    per_group_delay: float = 3.0,
    per_user_delay: float = 0.1,
) -> None:
    _ensure_telegram_config()
    client = TelegramClient(TG_SESSION_NAME, TG_API_ID, TG_API_HASH)
    print("[member_scraper] 설정 확인 완료. TG_API_ID/TG_API_HASH 로 세션을 엽니다.")
    print(f"[member_scraper] Telethon 클라이언트 세션 생성: {TG_SESSION_NAME}.session")

    # 먼저 텔레그램 세션부터 안정적으로 로그인/연결
    await client.start()
    print("[member_scraper] Telethon 세션 start() 완료. 구글 검색을 시작합니다.")

    print("🔍 구글에서 경쟁사 그룹 주소를 찾는 중입니다... 잠시만 기다려주세요.")
    links_iter: Iterable[TelegramLink] = find_competitor_telegram_links()
    links = list(links_iter)
    print(f"[member_scraper] 구글 검색에서 총 {len(links)}개 링크를 발견 (실제 순회 시작).")

    async with client:
        print("[member_scraper] Telethon 세션 접속 완료. 그룹 순회를 시작합니다.")
        for link in links:
            print(f"[member_scraper] >>> 그룹 멤버 수집 시작: {link.url} ({link.brand_query})")
            await _scrape_group_members_for_link(
                client,
                link,
                per_user_delay=per_user_delay,
            )

            # 그룹/채널 사이에는 더 긴 지연을 넣어 차단 위험을 줄입니다.
            if per_group_delay > 0:
                print(f"[member_scraper]   그룹 간 지연: {per_group_delay}초 대기")
                time.sleep(per_group_delay)

    print("[member_scraper] 모든 그룹에 대한 멤버 수집이 완료되었습니다.")


def run_member_scraper() -> None:
    """
    경쟁사 텔레그램 그룹/채널의 멤버 정보를 수집해
    competitor_users 테이블에 저장하는 진입점입니다.
    """
    import sys  # 지역 import (터미널 환경 가정)

    print("🚀 [START] 스크래퍼 진입 완료", flush=True)

    try:
        print("🔑 텔레그램 비동기 루프(asyncio) 시작 시도...", flush=True)
        asyncio.run(_scrape_all_members())
        print("✅ [END] 모든 작업이 성공적으로 끝났습니다.", flush=True)
    except KeyboardInterrupt:
        print("\n🛑 사용자에 의해 중단되었습니다.", flush=True)
    except Exception as e:
        print(f"❌ 실행 중 에러 발생: {e}", flush=True)
        import traceback

        traceback.print_exc()

