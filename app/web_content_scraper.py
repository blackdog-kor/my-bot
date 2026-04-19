"""
Web Content Scraper: 외부 카지노/겜블링 뉴스 사이트에서 콘텐츠 수집.

계정 차단 위험 0% — Telegram API를 전혀 사용하지 않음.
이미 설치된 스택 활용: crawl4ai, httpx, beautifulsoup4, lxml.

소스 사이트:
- casino.org/news/ — 카지노 뉴스
- bigwinboard.com — 슬롯 빅윈 스크린샷/영상
- calvinayre.com — 겜블링 산업 뉴스
"""
from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("web_content_scraper")


@dataclass
class WebArticle:
    """Scraped web article data."""

    title: str
    text: str
    url: str
    source_site: str
    media_type: str = "text"
    image_url: str | None = None
    published_at: datetime | None = None
    tags: list[str] = field(default_factory=list)


# ── Source definitions ────────────────────────────────────────────────────────

WEB_SOURCES: list[dict[str, Any]] = [
    {
        "name": "casino_org",
        "url": "https://www.casino.org/news/",
        "type": "news",
        "selectors": {
            "articles": "article.post-item, article.entry, .news-item",
            "title": "h2 a, h3 a, .entry-title a",
            "text": ".entry-content p, .post-excerpt, .summary",
            "link": "h2 a, h3 a, .entry-title a",
            "image": "img.wp-post-image, .post-thumbnail img",
        },
    },
    {
        "name": "bigwinboard",
        "url": "https://bigwinboard.com/",
        "type": "bigwin",
        "selectors": {
            "articles": ".win-card, .post-card, article",
            "title": "h2, h3, .card-title",
            "text": ".card-text, .excerpt, p",
            "link": "a[href]",
            "image": "img",
        },
    },
    {
        "name": "calvinayre",
        "url": "https://calvinayre.com/",
        "type": "news",
        "selectors": {
            "articles": "article, .post-item, .story-card",
            "title": "h2 a, h3 a, .headline a",
            "text": ".excerpt, .summary, .post-content p",
            "link": "h2 a, h3 a, .headline a",
            "image": ".post-thumbnail img, .featured-image img",
        },
    },
]


def _get_web_sources() -> list[dict[str, Any]]:
    """설정에서 추가 소스 URL을 로드하거나 기본값 반환."""
    extra = settings.web_scrape_sources.strip()
    sources = list(WEB_SOURCES)
    if extra:
        for url in extra.split(","):
            url = url.strip()
            if url:
                sources.append({
                    "name": re.sub(r"https?://|www\.|/.*", "", url),
                    "url": url,
                    "type": "custom",
                    "selectors": {
                        "articles": "article, .post, .entry",
                        "title": "h2, h3",
                        "text": "p, .content",
                        "link": "a[href]",
                        "image": "img",
                    },
                })
    return sources


# ── Scraping with httpx + BeautifulSoup (lightweight, fast) ──────────────────

async def _scrape_with_httpx(source: dict[str, Any]) -> list[WebArticle]:
    """httpx + BeautifulSoup4로 정적 사이트 스크래핑."""
    import httpx
    from bs4 import BeautifulSoup

    articles: list[WebArticle] = []
    url = source["url"]
    selectors = source["selectors"]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
    }

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=headers,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        article_elements = soup.select(selectors["articles"])[:15]

        for el in article_elements:
            title_el = el.select_one(selectors["title"])
            text_el = el.select_one(selectors["text"])
            link_el = el.select_one(selectors["link"])
            img_el = el.select_one(selectors.get("image", "img"))

            title = title_el.get_text(strip=True) if title_el else ""
            text = text_el.get_text(strip=True) if text_el else ""
            link = ""
            if link_el and link_el.get("href"):
                link = link_el["href"]
                if link.startswith("/"):
                    from urllib.parse import urljoin
                    link = urljoin(url, link)

            image_url = None
            if img_el:
                image_url = img_el.get("src") or img_el.get("data-src")
                if image_url and image_url.startswith("/"):
                    from urllib.parse import urljoin
                    image_url = urljoin(url, image_url)

            if not title and not text:
                continue

            combined_text = f"{title}\n\n{text}" if title and text else (title or text)

            articles.append(WebArticle(
                title=title,
                text=combined_text,
                url=link or url,
                source_site=source["name"],
                media_type="photo" if image_url else "text",
                image_url=image_url,
            ))

        logger.info(
            "httpx 스크래핑 완료: %s → %d개 기사",
            source["name"], len(articles),
        )

    except httpx.HTTPStatusError as e:
        logger.warning(
            "HTTP 에러 %d: %s", e.response.status_code, source["name"]
        )
    except Exception as e:
        logger.warning("httpx 스크래핑 실패 (%s): %s", source["name"], e)

    return articles


# ── Scraping with crawl4ai (JS rendering, AI extraction) ─────────────────────

async def _scrape_with_crawl4ai(source: dict[str, Any]) -> list[WebArticle]:
    """crawl4ai로 JS 렌더링이 필요한 사이트 스크래핑."""
    articles: list[WebArticle] = []
    url = source["url"]

    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

        config = CrawlerRunConfig(
            word_count_threshold=50,
            excluded_tags=["nav", "footer", "header", "aside"],
            verbose=False,
        )

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)

        if not result.success:
            logger.warning("crawl4ai 실패: %s — %s", url, result.error_message)
            return articles

        markdown_text = result.markdown or ""
        if not markdown_text.strip():
            return articles

        # Split by headings for individual articles
        sections = re.split(r"\n#{1,3}\s+", markdown_text)
        for section in sections[:10]:
            lines = section.strip().split("\n")
            if not lines:
                continue

            title = lines[0].strip("# ").strip()
            text = "\n".join(lines[1:]).strip()

            if len(title) < 10 and len(text) < 30:
                continue

            combined = f"{title}\n\n{text}" if text else title

            # Extract image URLs from markdown
            img_match = re.search(r"!\[.*?\]\((https?://[^)]+)\)", section)
            image_url = img_match.group(1) if img_match else None

            # Extract links
            link_match = re.search(r"\[.*?\]\((https?://[^)]+)\)", section)
            article_url = link_match.group(1) if link_match else url

            articles.append(WebArticle(
                title=title[:200],
                text=combined[:1500],
                url=article_url,
                source_site=source["name"],
                media_type="photo" if image_url else "text",
                image_url=image_url,
            ))

        logger.info(
            "crawl4ai 스크래핑 완료: %s → %d개 섹션",
            source["name"], len(articles),
        )

    except ImportError:
        logger.warning("crawl4ai 미설치 — httpx 폴백")
        return await _scrape_with_httpx(source)
    except Exception as e:
        logger.warning("crawl4ai 스크래핑 실패 (%s): %s", source["name"], e)

    return articles


# ── Public API ────────────────────────────────────────────────────────────────

async def scrape_web_sources() -> list[dict[str, Any]]:
    """모든 외부 웹 소스에서 콘텐츠 수집.

    Returns:
        Telethon scraper와 동일한 포맷의 dict 리스트:
        - text: str
        - media_type: str
        - views: int (웹 소스는 추정치 사용)
        - source_channel: str (source_site 대체)
        - message_id: int (URL hash 사용)
        - date: datetime
        - has_media: bool
    """
    sources = _get_web_sources()
    all_articles: list[WebArticle] = []

    for source in sources:
        try:
            # crawl4ai를 먼저 시도 (JS 렌더링), 실패하면 httpx
            articles = await _scrape_with_crawl4ai(source)
            if not articles:
                articles = await _scrape_with_httpx(source)
            all_articles.extend(articles)
        except Exception as e:
            logger.warning("소스 %s 전체 실패: %s", source["name"], e)

        # 사이트 간 딜레이 (IP 차단 방지)
        await asyncio.sleep(random.uniform(3.0, 8.0))

    # Telethon scraper와 호환되는 포맷으로 변환
    results: list[dict[str, Any]] = []
    for article in all_articles:
        if not article.text.strip():
            continue

        # URL 기반 고유 ID 생성 (deterministic — hashlib 사용)
        import hashlib
        url_hash = hashlib.sha256(article.url.encode()).hexdigest()
        msg_id = int(url_hash[:8], 16) % (10**9)

        results.append({
            "text": article.text,
            "media_type": article.media_type,
            "views": 1000,  # 웹 소스는 조회수 추정
            "source_channel": f"web:{article.source_site}",
            "message_id": msg_id,
            "date": article.published_at or datetime.now(timezone.utc),
            "has_media": article.image_url is not None,
            "url": article.url,
            "image_url": article.image_url,
        })

    logger.info("웹 스크래핑 총 %d개 콘텐츠 수집 완료", len(results))
    return results


if __name__ == "__main__":
    results = asyncio.run(scrape_web_sources())
    for r in results[:10]:
        print(f"[{r['source_channel']}] {r['text'][:100]}")
