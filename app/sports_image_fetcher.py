"""
Sports Image Fetcher: high-quality contextual images for sports posts.

Priority chain:
  1. Pexels API — dynamic search, content-type aware queries
  2. Curated league images — public-domain fallback (no API key needed)

Pexels free plan: 200 req/hr, 20,000 req/month.
In-process LRU cache (50 entries, 1h TTL) prevents redundant calls.
"""
from __future__ import annotations

import random
import time
from typing import Literal

import httpx

_PEXELS_TIMEOUT = 8.0    # seconds for Pexels search requests
_DOWNLOAD_TIMEOUT = 15.0  # seconds for image binary download

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("sports_image_fetcher")

# ── Content-type → Pexels search query strategy ──────────────────────────────

# Base league keywords for Pexels (en, gives best results)
_LEAGUE_KEYWORDS: dict[int, str] = {
    39:  "Premier League football stadium Anfield Old Trafford",
    140: "La Liga football stadium Spain soccer",
    135: "Serie A football Italy stadium soccer",
    78:  "Bundesliga football Germany stadium soccer",
    61:  "Ligue 1 football France Paris stadium",
    2:   "UEFA Champions League night stadium lights",
    3:   "UEFA Europa League stadium soccer",
    1:   "FIFA World Cup 2026 stadium fans",
    253: "MLS soccer stadium United States",
    98:  "J1 League Japan football soccer stadium",
    71:  "Brazilian football stadium Maracana soccer",
    292: "Korean football Seoul stadium soccer",
    88:  "Eredivisie Netherlands football stadium",
    94:  "Primeira Liga Portugal football stadium",
}

# Content-type modifier appended to query
_TYPE_SUFFIX: dict[str, str] = {
    "sports_preview":        "match crowd atmosphere action",
    "sports_review":         "match result celebration fans",
    "sports_standings":      "league table stadium aerial view",
    "sports_weekly_roundup": "football week schedule fixtures",
    "sports_top_scorers":    "football player scoring goal action",
    "sports_monthly_report": "football analytics trophy award",
}

# ── Curated Wikipedia Commons fallbacks (public domain, no API key) ───────────

_LEAGUE_IMAGES: dict[int, str] = {
    39:  "https://upload.wikimedia.org/wikipedia/commons/thumb/3/34/Anfield_stadium_from_air.jpg/1200px-Anfield_stadium_from_air.jpg",
    140: "https://upload.wikimedia.org/wikipedia/commons/thumb/1/15/Camp_Nou_2018.jpg/1200px-Camp_Nou_2018.jpg",
    135: "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9f/San_Siro_from_above.jpg/1200px-San_Siro_from_above.jpg",
    61:  "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f8/Parc_des_Princes_%28aerial_view%29.jpg/1200px-Parc_des_Princes_%28aerial_view%29.jpg",
    78:  "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4a/Signal_Iduna_Park_-_Westfalenstadion-2.jpg/1200px-Signal_Iduna_Park_-_Westfalenstadion-2.jpg",
    2:   "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Wembley_Stadium_interior.jpg/1200px-Wembley_Stadium_interior.jpg",
    3:   "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Wembley_Stadium_interior.jpg/1200px-Wembley_Stadium_interior.jpg",
    1:   "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/Estadio_Azteca_2015.jpg/1200px-Estadio_Azteca_2015.jpg",  # WC 2026 — Azteca
    253: "https://upload.wikimedia.org/wikipedia/commons/thumb/8/85/Allegiant_Stadium_August_2020.jpg/1200px-Allegiant_Stadium_August_2020.jpg",  # MLS — Allegiant
    98:  "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b4/Saitama_Stadium_2002.jpg/1200px-Saitama_Stadium_2002.jpg",  # J1 — Saitama
    71:  "https://upload.wikimedia.org/wikipedia/commons/thumb/7/72/Maracan%C3%A3_Stadium.jpg/1200px-Maracan%C3%A3_Stadium.jpg",  # Brasileirao — Maracanã
    292: "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a3/Seoul_World_Cup_Stadium_-_exterior_01.jpg/1200px-Seoul_World_Cup_Stadium_-_exterior_01.jpg",  # K League
    88:  "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Wembley_Stadium_interior.jpg/1200px-Wembley_Stadium_interior.jpg",
    94:  "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Wembley_Stadium_interior.jpg/1200px-Wembley_Stadium_interior.jpg",
}
_DEFAULT_IMAGE = _LEAGUE_IMAGES[2]  # Wembley — generic fallback

# ── In-process cache (query → (url, expires_ts)) ─────────────────────────────

_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 3600.0   # 1 hour
_CACHE_MAX = 60       # max entries


def _cache_get(key: str) -> str | None:
    entry = _CACHE.get(key)
    if entry and time.monotonic() < entry[1]:
        return entry[0]
    _CACHE.pop(key, None)
    return None


def _cache_set(key: str, url: str) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        # Evict oldest entry
        oldest = min(_CACHE, key=lambda k: _CACHE[k][1])
        _CACHE.pop(oldest, None)
    _CACHE[key] = (url, time.monotonic() + _CACHE_TTL)


# ── Pexels fetcher ────────────────────────────────────────────────────────────

async def _pexels_search(query: str) -> str | None:
    """Search Pexels for a landscape image. Returns URL of best match or None."""
    cached = _cache_get(query)
    if cached:
        logger.debug("Pexels cache hit: %s", query[:40])
        return cached

    try:
        async with httpx.AsyncClient(timeout=_PEXELS_TIMEOUT) as client:
            resp = await client.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": settings.pexels_api_key},
                params={"query": query, "per_page": 10, "orientation": "landscape"},
            )
        if resp.status_code != 200:
            logger.warning("Pexels %d for query: %s", resp.status_code, query[:40])
            return None

        photos = resp.json().get("photos", [])
        # Filter: minimum width 1200px (landscape quality guard)
        wide = [p for p in photos if p.get("width", 0) >= 1200]
        pool = wide or photos
        if not pool:
            return None

        # Randomly pick from top 5 for post variety
        photo = random.choice(pool[:5])
        src = photo.get("src", {})
        url = src.get("large2x") or src.get("large") or src.get("original")
        if url:
            _cache_set(query, url)
            logger.info("Pexels: '%s' → %s", query[:40], url[:60])
        return url

    except httpx.TimeoutException:
        logger.warning("Pexels timeout: %s", query[:40])
        return None
    except httpx.RequestError as e:
        logger.warning("Pexels network error: %s", e)
        return None
    except Exception as e:
        logger.warning("Pexels unexpected error: %s", e)
        return None


# ── Public API ────────────────────────────────────────────────────────────────

ContentType = Literal[
    "sports_preview", "sports_review", "sports_standings",
    "sports_weekly_roundup", "sports_top_scorers", "sports_monthly_report",
]


async def fetch_sport_image(
    league_id: int | None = None,
    home_team: str = "",
    away_team: str = "",
    league_name: str = "",
    content_type: ContentType | None = None,
) -> str:
    """Return an image URL for a sports post.

    Strategy:
      1. Pexels: team-specific query (preview/review only)
      2. Pexels: league + content-type query
      3. Curated league fallback (Wikipedia Commons)
      4. Default Wembley image

    Args:
        league_id: API-Football league ID.
        home_team: Home team name (used for team-specific Pexels query).
        away_team: Away team name.
        league_name: League name.
        content_type: Post type key to select query modifier.

    Returns:
        HTTPS image URL — always returns a value.
    """
    if not settings.pexels_api_key:
        return _LEAGUE_IMAGES.get(league_id or 0, _DEFAULT_IMAGE)

    type_suffix = _TYPE_SUFFIX.get(content_type, "football soccer stadium")

    # Pass 1: team-specific (preview & review benefit most from this)
    if home_team and away_team and content_type in ("sports_preview", "sports_review", ""):
        team_query = f"{home_team} {away_team} soccer football {type_suffix}"
        url = await _pexels_search(team_query)
        if url:
            return url

    # Pass 2: league + content-type
    league_kw = _LEAGUE_KEYWORDS.get(league_id or 0, league_name or "football soccer")
    league_query = f"{league_kw} {type_suffix}"
    url = await _pexels_search(league_query)
    if url:
        return url

    # Pass 3: curated fallback
    if league_id and league_id in _LEAGUE_IMAGES:
        return _LEAGUE_IMAGES[league_id]

    return _DEFAULT_IMAGE


async def image_url_to_bytes(url: str) -> bytes | None:
    """Download image bytes from URL. Returns None on failure."""
    try:
        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.content
            logger.warning("Image download HTTP %d: %s", resp.status_code, url[:80])
            return None
    except Exception as e:
        logger.warning("Image download error: %s", e)
        return None
