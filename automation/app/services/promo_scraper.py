import re
from typing import Iterable

from scrapling.fetchers import StealthyFetcher

from app.db import save_promotion


PERCENT_RE = re.compile(r"(\d{1,3})\s*%")


COMPETITOR_SITES = [
    {
        "source": "stake",
        "url": "https://stake.com/promotions",
    },
    {
        "source": "bcgame",
        "url": "https://bc.game/promotion",
    },
]


def _extract_bonus_percents_from_text(text: str) -> list[int]:
    return [int(m.group(1)) for m in PERCENT_RE.finditer(text)]


def _extract_titles(page) -> Iterable[str]:
    # Heuristic: take visible headings as promotion titles.
    for el in page.css("h1, h2, h3", auto_save=False):
        t = (el.text or "").strip()
        if len(t) >= 5:
            yield t


def scrape_competitor_promos() -> None:
    """
    Scrape competitor promotion pages using scrapling's StealthyFetcher
    with anti-bot friendly settings, then persist (source, title, bonus%)
    into the promotions table.
    """
    StealthyFetcher.adaptive = True

    for site in COMPETITOR_SITES:
        source = site["source"]
        url = site["url"]

        page = StealthyFetcher.fetch(
            url,
            headless=True,
            network_idle=True,
        )

        full_text = page.text or ""
        global_bonuses = _extract_bonus_percents_from_text(full_text)
        global_top_bonus = max(global_bonuses) if global_bonuses else 0

        for title in _extract_titles(page):
            bonuses = _extract_bonus_percents_from_text(title) or global_bonuses
            bonus = max(bonuses) if bonuses else global_top_bonus

            snippet = title
            save_promotion(
                source=source,
                title=title,
                bonus_percent=bonus,
                raw_snippet=snippet,
            )
        

