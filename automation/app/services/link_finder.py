from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Set

from scrapling.fetchers import AsyncStealthyFetcher


GOOGLE_SEARCH_URL = "https://www.google.com/search"


TARGET_BRANDS = [
    "1win telegram group",
    "1win official telegram",
    "Stake telegram group",
    "Stake official telegram",
    "BC.Game telegram group",
    "BC.Game official telegram",
]


@dataclass
class TelegramLink:
    brand_query: str
    url: str
    text: str


def _extract_telegram_links(page, brand_query: str) -> Iterable[TelegramLink]:
    """
    구글 검색 결과 페이지에서 t.me 링크만 추출합니다.
    """
    seen: Set[str] = set()

    # 일반적인 검색 결과 영역의 a 태그를 대상으로 처리
    for a in page.css("a", auto_save=False):
        href = (a.attributes.get("href") or "").strip()
        text = (a.text or "").strip()

        if not href:
            continue

        # 구글 검색 특유의 /url?q= 래핑을 벗겨내는 처리는 scrapling 쪽에 맡기고,
        # 여기서는 t.me 링크만 필터링합니다.
        if "t.me/" not in href:
            continue

        if href in seen:
            continue
        seen.add(href)

        print(f"[link_finder]   텔레그램 링크 발견: {href} (텍스트: {text})")
        yield TelegramLink(brand_query=brand_query, url=href, text=text)


async def find_telegram_links_for_query(query: str, max_results: int = 50) -> List[TelegramLink]:
    """
    하나의 검색 쿼리에 대해 구글 검색을 실행하고,
    해당 페이지에서 텔레그램(t.me) 링크를 수집합니다.
    """
    AsyncStealthyFetcher.adaptive = True

    url = f"{GOOGLE_SEARCH_URL}?q={query.replace(' ', '+')}&hl=en"
    print(f"[link_finder] 쿼리 시작: {query}")
    print(f"[link_finder]   구글 접속 URL: {url}")

    page = await AsyncStealthyFetcher.fetch(
        url,
        headless=True,
        network_idle=True,
    )
    print(f"[link_finder]   구글 검색 페이지 로딩 완료: {query}")

    links: List[TelegramLink] = []
    for link in _extract_telegram_links(page, brand_query=query):
        links.append(link)
        if len(links) >= max_results:
            break

    print(f"[link_finder]   {query} 에서 발견된 텔레그램 링크 수: {len(links)}")

    return links


async def find_competitor_telegram_links(max_results_per_query: int = 50) -> List[TelegramLink]:
    """
    1win / Stake / BC.Game 관련 구글 검색을 순회하면서
    모든 텔레그램 그룹/채널 링크를 리스트업합니다.
    """
    all_links: List[TelegramLink] = []
    seen_urls: Set[str] = set()

    for q in TARGET_BRANDS:
        print(f"[link_finder] ====== 브랜드 쿼리 처리 시작: {q} ======")
        links = await find_telegram_links_for_query(q, max_results=max_results_per_query)
        for link in links:
            if link.url in seen_urls:
                continue
            seen_urls.add(link.url)
            all_links.append(link)

        print(f"[link_finder] ====== 브랜드 쿼리 종료: {q}, 누적 고유 링크 수: {len(all_links)} ======")

    return all_links

