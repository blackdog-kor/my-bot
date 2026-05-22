"""
Sports Image Fetcher: Fetch high-quality sports images for posts.

Priority:
1. Pexels API (requires PEXELS_API_KEY) — dynamic search per team/league
2. Curated league images — stable Wikipedia Commons JPEGs, no API key needed
"""
from __future__ import annotations

import httpx

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("sports_image_fetcher")

# Curated Wikipedia Commons JPEG images per league (stable public-domain URLs)
_LEAGUE_IMAGES: dict[int, str] = {
    39: "https://upload.wikimedia.org/wikipedia/commons/thumb/3/34/Anfield_stadium_from_air.jpg/1200px-Anfield_stadium_from_air.jpg",  # Premier League — Anfield
    140: "https://upload.wikimedia.org/wikipedia/commons/thumb/1/15/Camp_Nou_2018.jpg/1200px-Camp_Nou_2018.jpg",  # La Liga — Camp Nou
    135: "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9f/San_Siro_from_above.jpg/1200px-San_Siro_from_above.jpg",  # Serie A — San Siro
    61: "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f8/Parc_des_Princes_%28aerial_view%29.jpg/1200px-Parc_des_Princes_%28aerial_view%29.jpg",  # Ligue 1 — Parc des Princes
    78: "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4a/Signal_Iduna_Park_-_Westfalenstadion-2.jpg/1200px-Signal_Iduna_Park_-_Westfalenstadion-2.jpg",  # Bundesliga — Signal Iduna
    2: "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Wembley_Stadium_interior.jpg/1200px-Wembley_Stadium_interior.jpg",  # UCL — Wembley
    3: "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Wembley_Stadium_interior.jpg/1200px-Wembley_Stadium_interior.jpg",  # UEL
    292: "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a3/Seoul_World_Cup_Stadium_-_exterior_01.jpg/1200px-Seoul_World_Cup_Stadium_-_exterior_01.jpg",  # K League — Seoul WC Stadium
}

_DEFAULT_IMAGE = "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Wembley_Stadium_interior.jpg/1200px-Wembley_Stadium_interior.jpg"


async def fetch_pexels_image(query: str) -> str | None:
    """Search Pexels for a sports image matching the query. Returns image URL or None."""
    api_key = settings.pexels_api_key
    if not api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": api_key},
                params={"query": query, "per_page": 5, "orientation": "landscape"},
            )
            if resp.status_code != 200:
                logger.warning("Pexels API error: %d", resp.status_code)
                return None

            data = resp.json()
            photos = data.get("photos", [])
            if not photos:
                return None

            # Pick the largest available size under ~3MB
            photo = photos[0]
            src = photo.get("src", {})
            url = src.get("large2x") or src.get("large") or src.get("original")
            logger.info("Pexels image found: %s", url)
            return url

    except Exception as e:
        logger.warning("Pexels fetch failed: %s", e)
        return None


async def fetch_sport_image(
    league_id: int | None = None,
    home_team: str = "",
    away_team: str = "",
    league_name: str = "",
) -> str:
    """Return an image URL for a sports post.

    Tries Pexels first, then falls back to curated league image.

    Args:
        league_id: API-Football league ID for curated fallback.
        home_team: Home team name (used in Pexels query).
        away_team: Away team name (used in Pexels query).
        league_name: League name (used in Pexels query).

    Returns:
        HTTPS image URL (always returns a value).
    """
    # 1) Pexels — dynamic search
    if settings.pexels_api_key:
        query_parts = [p for p in [home_team, away_team, league_name, "football soccer stadium"] if p]
        query = " ".join(query_parts[:3])
        url = await fetch_pexels_image(query)
        if url:
            return url

    # 2) Curated league fallback (always available)
    if league_id and league_id in _LEAGUE_IMAGES:
        return _LEAGUE_IMAGES[league_id]

    return _DEFAULT_IMAGE


async def image_url_to_bytes(url: str) -> bytes | None:
    """Download image bytes from URL. Returns None on failure."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.content
            logger.warning("Image download failed: HTTP %d for %s", resp.status_code, url)
            return None
    except Exception as e:
        logger.warning("Image download error: %s", e)
        return None
