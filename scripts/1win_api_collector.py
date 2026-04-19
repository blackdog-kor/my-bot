"""
1win partner stats collector — uses Win1Client for API calls.

Flow:
  1. Load tokens from token_vault DB (set via /settoken) or env fallback
  2. Fetch affiliate link metadata via Win1Client
  3. POST to Railway affiliate endpoint for DB storage

Run: python3 scripts/1win_api_collector.py
Schedule: 00:00 UTC daily (app/scheduler.py)

Note: stats/common is Cloudflare-blocked from server IPs.
      Use the browser bookmarklet (/api/1win/bookmarklet) for daily stats push.
      This script collects links and promo metadata only.
"""
import asyncio
import logging
import os
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)

RAILWAY_URL = os.getenv("RAILWAY_PUBLIC_URL", "").rstrip("/")
if not RAILWAY_URL:
    RAILWAY_URL = "http://localhost:8000"
    logger.warning("[1win] RAILWAY_PUBLIC_URL not set — using localhost (dev mode)")

WEBHOOK_SECRET = os.getenv("AFFILIATE_WEBHOOK_SECRET", "")


async def _post_to_railway(payload: dict) -> dict:
    """POST collected metadata to the Railway affiliate endpoint."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{RAILWAY_URL}/api/affiliate/stats", json=payload)
        r.raise_for_status()
        return r.json()


async def collect() -> str:
    """Collect 1win affiliate link metadata and push to Railway DB."""
    # Import inside function to avoid circular imports at module load time
    from app.win1_client import get_client_from_vault

    client = get_client_from_vault()

    # Refresh access token if vault returned only a refresh token (env fallback path)
    if not client.access_token:
        logger.info("[1win] no cached accessToken — refreshing via refreshToken")
        await client.refresh_access_token()

    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # stats/common is Cloudflare-blocked on Railway — skip, use bookmarklet instead
    links_raw = await client.links()

    links = [
        {
            "code": lnk.get("name") or lnk.get("link", ""),
            "source_id": lnk.get("source_id") or lnk.get("sourceId"),
            "clicks": int(lnk.get("clicks") or lnk.get("clickCount") or 0),
            "registrations": int(lnk.get("registrations") or lnk.get("regCount") or 0),
        }
        for lnk in links_raw
    ]

    payload = {
        "secret": WEBHOOK_SECRET,
        "date_from": yesterday,
        "date_to": yesterday,
        "clicks": 0,
        "registrations": 0,
        "ftd_count": 0,
        "deposits": 0,
        "revenue": 0,
        "commission": 0,
        "source": "api-links-only",
        "links": links,
        "extra": {
            "note": "stats skipped — Cloudflare blocks server IP; use bookmarklet",
            "link_count": len(links),
        },
    }

    try:
        await _post_to_railway(payload)
    except httpx.HTTPStatusError as exc:
        logger.exception("[1win] Railway POST failed (HTTP %s)", exc.response.status_code)
        raise
    except httpx.RequestError as exc:
        logger.exception("[1win] Railway POST connection error: %s", exc)
        raise

    summary = (
        f"1win metadata collected {yesterday}: "
        f"{len(links)} links synced. "
        f"Use bookmarklet for full stats."
    )
    logger.info(summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(collect()))
