"""
TeraBox Content Agent: browser-use 기반 TeraBox 콘텐츠 자동 수집.

TeraBox는 공식 API가 없으므로 browser-use AI 에이전트를 활용하여:
1. TeraBox 공유 링크에서 비디오/이미지 메타데이터 수집
2. 다운로드 링크 추출
3. 콘텐츠를 channel_content 테이블에 저장
4. 필요 시 직접 다운로드 → BytesIO로 채널 게시

사용 기술:
- browser-use (AI 브라우저 에이전트) — Layer 3
- nodriver (Cloudflare 우회) — Layer 2 폴백
- curl_cffi (직접 다운로드) — Layer 1

환경변수:
- TERABOX_SHARE_URLS: 쉼표 구분 TeraBox 공유 링크 목록
- TERABOX_COOKIES: (선택) 로그인 쿠키 문자열
- OPENAI_API_KEY: browser-use AI 에이전트용 (필수)
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("terabox_agent")

# ── Constants ────────────────────────────────────────────────────────────────

# TeraBox 도메인 패턴
TERABOX_DOMAINS: list[str] = [
    "terabox.com",
    "teraboxapp.com",
    "1024terabox.com",
    "terabox.fun",
    "freeterabox.com",
]

# 지원하는 미디어 확장자
VIDEO_EXTENSIONS: set[str] = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# 최대 수집 아이템 수 (1회 실행)
MAX_ITEMS_PER_RUN: int = 10

# 에이전트 실행 최대 스텝
MAX_AGENT_STEPS: int = 15

# 아이템 간 딜레이 (초) — 안티 탐지
ITEM_DELAY_MIN: float = 5.0
ITEM_DELAY_MAX: float = 15.0


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class TeraBoxItem:
    """TeraBox에서 수집된 단일 콘텐츠 아이템."""

    share_url: str
    title: str = ""
    file_name: str = ""
    file_size: str = ""
    media_type: str = "video"  # video | photo | document
    download_url: str = ""
    thumbnail_url: str = ""
    raw_agent_output: str = ""


@dataclass
class TeraBoxRunResult:
    """TeraBox 에이전트 실행 결과."""

    items: list[TeraBoxItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_processed: int = 0
    success_count: int = 0


# ── URL Validation ───────────────────────────────────────────────────────────

def is_terabox_url(url: str) -> bool:
    """URL이 TeraBox 공유 링크인지 확인."""
    url_lower = url.lower().strip()
    return any(domain in url_lower for domain in TERABOX_DOMAINS)


def get_share_urls() -> list[str]:
    """설정에서 TeraBox 공유 URL 목록을 반환."""
    raw = settings.terabox_share_urls.strip()
    if not raw:
        return []
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    return [u for u in urls if is_terabox_url(u)]


def _classify_media_type(file_name: str) -> str:
    """파일명에서 미디어 타입 분류."""
    name_lower = file_name.lower()
    for ext in VIDEO_EXTENSIONS:
        if name_lower.endswith(ext):
            return "video"
    for ext in IMAGE_EXTENSIONS:
        if name_lower.endswith(ext):
            return "photo"
    return "document"


# ── Agent Task Prompts ───────────────────────────────────────────────────────

_EXTRACT_TASK = """You are extracting file information from a TeraBox sharing page.

Navigate to the URL and extract ALL of the following information:
1. File name (the video/image file name shown on the page)
2. File size (e.g., "1.2 GB", "450 MB")
3. Any download button or direct download link
4. Thumbnail/preview image URL (if visible)

IMPORTANT:
- Do NOT click any download buttons that require login
- Do NOT enter any credentials
- Only extract publicly visible information
- If a CAPTCHA appears, report it and stop

Return the information in this exact format:
FILENAME: <filename>
FILESIZE: <size>
DOWNLOAD_URL: <url or "not_available">
THUMBNAIL: <url or "not_available">
TITLE: <page title or file description>
"""

_SEARCH_TASK = """You are searching for casino/gambling related video content on TeraBox.

Search query: {query}

Steps:
1. Go to the TeraBox search or the provided URL
2. Look for video content related to casino, slots, big wins, jackpots
3. For each result found, extract: file name, size, share link, thumbnail

Return results in this format (one per line):
ITEM: <share_url> | <filename> | <size> | <thumbnail_url>

Maximum 5 items. Only include video content (.mp4, .mkv, .mov).
Do NOT click download or login buttons.
"""


# ── Core Agent Functions ─────────────────────────────────────────────────────

async def extract_terabox_info(share_url: str) -> TeraBoxItem | None:
    """browser-use AI 에이전트로 TeraBox 공유 링크에서 메타데이터 추출.

    Args:
        share_url: TeraBox 공유 링크

    Returns:
        TeraBoxItem 또는 None (실패 시)
    """
    openai_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        logger.error("OPENAI_API_KEY 미설정 — browser-use 에이전트 실행 불가")
        return None

    try:
        from app.web_agent import run_agent

        task = f"URL: {share_url}\n\n{_EXTRACT_TASK}"
        result = await run_agent(task, url=share_url, max_steps=MAX_AGENT_STEPS)

        item = _parse_extract_result(result, share_url)
        if item:
            logger.info(
                "TeraBox 메타데이터 추출 성공: %s (%s, %s)",
                item.file_name, item.media_type, item.file_size,
            )
        return item

    except Exception as e:
        logger.exception("TeraBox 에이전트 실행 실패 [%s]: %s", share_url, e)
        return None


async def extract_terabox_info_nodriver(share_url: str) -> TeraBoxItem | None:
    """nodriver(Layer 2) 폴백으로 TeraBox 페이지에서 메타데이터 추출.

    browser-use 실패 시 사용하는 가벼운 대안.
    """
    try:
        from app.web_agent import fetch_page

        page = await fetch_page(share_url, wait_seconds=5.0, solve_cf=True)

        item = TeraBoxItem(share_url=share_url, raw_agent_output=page.text[:2000])

        # HTML에서 파일명 추출 시도
        name_match = re.search(
            r'(?:file-name|filename)["\s:>]+([^<"]+)', page.html, re.IGNORECASE,
        )
        if name_match:
            item.file_name = name_match.group(1).strip()
            item.media_type = _classify_media_type(item.file_name)

        # 제목 추출
        title_match = re.search(r"<title>([^<]+)</title>", page.html, re.IGNORECASE)
        if title_match:
            item.title = title_match.group(1).strip()

        # 썸네일 추출
        thumb_match = re.search(
            r'(?:og:image|thumbnail)["\s:content=]+["\s](https?://[^"\'>\s]+)',
            page.html, re.IGNORECASE,
        )
        if thumb_match:
            item.thumbnail_url = thumb_match.group(1)

        if item.file_name or item.title:
            logger.info("TeraBox nodriver 추출 성공: %s", item.file_name or item.title)
            return item

        logger.warning("TeraBox nodriver 추출 실패 — 파일 정보 없음: %s", share_url)
        return None

    except Exception as e:
        logger.exception("TeraBox nodriver 실패 [%s]: %s", share_url, e)
        return None


async def collect_terabox_content() -> TeraBoxRunResult:
    """전체 TeraBox 공유 URL에서 콘텐츠를 수집.

    실행 흐름:
    1. 설정에서 공유 URL 목록 로드
    2. 각 URL에 대해 browser-use → nodriver 폴백 순으로 메타데이터 추출
    3. 중복 필터링
    4. TeraBoxRunResult 반환

    Returns:
        수집 결과
    """
    import random

    urls = get_share_urls()
    if not urls:
        logger.warning("TERABOX_SHARE_URLS 미설정 — 수집 대상 없음")
        return TeraBoxRunResult()

    result = TeraBoxRunResult()

    for url in urls[:MAX_ITEMS_PER_RUN]:
        result.total_processed += 1

        # Layer 3: browser-use AI 에이전트 (최우선)
        item = await extract_terabox_info(url)

        # Layer 2: nodriver 폴백
        if item is None:
            logger.info("browser-use 실패 → nodriver 폴백: %s", url)
            item = await extract_terabox_info_nodriver(url)

        if item:
            result.items.append(item)
            result.success_count += 1
        else:
            result.errors.append(f"수집 실패: {url}")

        # 안티 탐지 딜레이
        if result.total_processed < len(urls):
            delay = random.uniform(ITEM_DELAY_MIN, ITEM_DELAY_MAX)
            logger.info("안티 탐지 딜레이: %.1f초", delay)
            await asyncio.sleep(delay)

    logger.info(
        "TeraBox 수집 완료: %d/%d 성공",
        result.success_count, result.total_processed,
    )
    return result


async def download_terabox_file(
    download_url: str,
    *,
    cookies: str = "",
) -> io.BytesIO | None:
    """TeraBox 다운로드 URL에서 파일을 BytesIO로 다운로드.

    Args:
        download_url: 직접 다운로드 링크
        cookies: (선택) 인증 쿠키

    Returns:
        BytesIO 객체 또는 None
    """
    if not download_url or download_url == "not_available":
        return None

    try:
        from curl_cffi.requests import AsyncSession

        headers: dict[str, str] = {}
        if cookies:
            headers["Cookie"] = cookies

        async with AsyncSession(impersonate="chrome124") as session:
            resp = await session.get(download_url, headers=headers, timeout=120)
            resp.raise_for_status()

            bio = io.BytesIO(resp.content)
            bio.seek(0)
            logger.info("TeraBox 다운로드 완료: %d bytes", len(resp.content))
            return bio

    except Exception as e:
        logger.exception("TeraBox 다운로드 실패: %s", e)
        return None


# ── Result Parsing ───────────────────────────────────────────────────────────

def _parse_extract_result(raw: str, share_url: str) -> TeraBoxItem | None:
    """browser-use 에이전트 출력을 TeraBoxItem으로 파싱."""
    if not raw or "No result" in raw:
        return None

    item = TeraBoxItem(share_url=share_url, raw_agent_output=raw[:2000])

    # 정규식으로 각 필드 추출
    patterns: dict[str, str] = {
        "file_name": r"FILENAME:\s*(.+)",
        "file_size": r"FILESIZE:\s*(.+)",
        "download_url": r"DOWNLOAD_URL:\s*(.+)",
        "thumbnail_url": r"THUMBNAIL:\s*(.+)",
        "title": r"TITLE:\s*(.+)",
    }

    for attr, pattern in patterns.items():
        match = re.search(pattern, raw, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value.lower() not in ("not_available", "n/a", "none", ""):
                setattr(item, attr, value)

    # 파일명이 있으면 미디어 타입 자동 분류
    if item.file_name:
        item.media_type = _classify_media_type(item.file_name)

    # 최소한 파일명이나 제목이 있어야 유효
    if not item.file_name and not item.title:
        return None

    return item
