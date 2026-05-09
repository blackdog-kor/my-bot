"""
Web Content Scraper: fetch content from external casino/gambling news sites.

Zero account-ban risk — no Telegram API usage.
Uses httpx + BeautifulSoup only (crawl4ai removed; Playwright unavailable on Railway).

Sources:
- casino.org/news/  — casino news
- bigwinboard.com   — slot big-win screenshots/videos
- calvinayre.com    — gambling industry news
- gamblingnews.com  — casino/betting news
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

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
        # Confirmed working: 49 articles, div.blog-post-item structure
        "name": "casino_org",
        "url": "https://www.casino.org/news/",
        "type": "news",
        "selectors": {
            "articles": "div.blog-post-item",
            "title": "h4.blog-post-item__title, h3.blog-post-item__title, h2, h3",
            "text": ".blog-post-item__excerpt, p",
            "link": "a[href]",
            "image": "img",
        },
    },
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
}


def _get_web_sources() -> list[dict[str, Any]]:
    """Load sources from config extra URLs or return defaults."""
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


# ── Scraping with httpx + BeautifulSoup ──────────────────────────────────────

async def _scrape_with_httpx(source: dict[str, Any]) -> list[WebArticle]:
    """Scrape static site with httpx + BeautifulSoup4."""
    import httpx
    from bs4 import BeautifulSoup

    articles: list[WebArticle] = []
    url = source["url"]
    selectors = source["selectors"]

    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        article_elements = soup.select(selectors["articles"])[:20]

        for el in article_elements:
            title_el = el.select_one(selectors["title"])
            text_el = el.select_one(selectors["text"])
            img_el = el.select_one(selectors.get("image", "img"))

            # Find the primary link — prefer link on the title
            link = ""
            link_el = title_el.select_one("a[href]") if title_el else None
            if not link_el:
                link_el = el.select_one("a[href]")
            if link_el and link_el.get("href"):
                href = link_el["href"]
                link = href if href.startswith("http") else urljoin(url, href)

            title = title_el.get_text(strip=True) if title_el else ""
            text = text_el.get_text(strip=True) if text_el else ""

            # Skip navigation/footer junk with trivially short content
            if not title or len(title) < 10:
                continue
            if not text or len(text) < 20:
                # Use title alone as text if it's descriptive enough
                if len(title) >= 40:
                    text = title
                else:
                    continue

            image_url = None
            if img_el:
                raw = img_el.get("src") or img_el.get("data-src") or ""
                if raw:
                    image_url = raw if raw.startswith("http") else urljoin(url, raw)

            combined = f"{title}\n\n{text}" if text and text != title else title
            articles.append(WebArticle(
                title=title,
                text=combined,
                url=link or url,
                source_site=source["name"],
                media_type="photo" if image_url else "text",
                image_url=image_url,
            ))

        logger.info("httpx scrape: %s → %d articles", source["name"], len(articles))

    except Exception as e:
        logger.warning("httpx scrape failed (%s): %s", source["name"], e)

    return articles


# ── Public API ────────────────────────────────────────────────────────────────

async def scrape_web_sources() -> list[dict[str, Any]]:
    """Collect content from all external web sources.

    Returns dicts compatible with Telethon scraper format:
        text, media_type, views, source_channel, message_id, date, has_media
    """
    sources = _get_web_sources()
    all_articles: list[WebArticle] = []

    for source in sources:
        try:
            articles = await _scrape_with_httpx(source)
            all_articles.extend(articles)
        except Exception as e:
            logger.warning("source %s failed entirely: %s", source["name"], e)

        # Inter-site delay to avoid IP blocks
        await asyncio.sleep(random.uniform(2.0, 5.0))

    results: list[dict[str, Any]] = []
    for article in all_articles:
        if not article.text.strip():
            continue

        # Deterministic ID from URL so same article isn't re-scraped
        url_hash = hashlib.sha256(article.url.encode()).hexdigest()
        msg_id = int(url_hash[:8], 16) % (10**9)

        results.append({
            "text": article.text,
            "media_type": article.media_type,
            "views": 1000,
            "source_channel": f"web:{article.source_site}",
            "message_id": msg_id,
            "date": article.published_at or datetime.now(timezone.utc),
            "has_media": article.image_url is not None,
            "url": article.url,
            "image_url": article.image_url,
        })

    logger.info("web scrape total: %d articles collected", len(results))
    return results


if __name__ == "__main__":
    results = asyncio.run(scrape_web_sources())
    for r in results[:10]:
        print(f"[{r['source_channel']}] {r['text'][:100]}")
