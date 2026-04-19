"""
1win partner stats collector — pure API approach (no browser needed).

Flow:
  1. Load refresh_token from env
  2. Exchange for access_token via 1win API
  3. Fetch stats + links
  4. POST to Railway affiliate endpoint for DB storage + Telegram alert

Run: python3 scripts/1win_api_collector.py
Schedule: 00:00 UTC daily (app/scheduler.py)
"""
import asyncio
import logging
import os
from datetime import date, timedelta

from app.web_agent import fetch_api

logger = logging.getLogger(__name__)

API_BASE = "https://1win-partners.com"
REFRESH_TOKEN = os.getenv("1WIN_REFRESH_TOKEN", "")
RAILWAY_URL = os.getenv("RAILWAY_PUBLIC_URL", "").rstrip("/")
if not RAILWAY_URL:
    # fallback for local dev only
    RAILWAY_URL = "http://localhost:8000"
    logger.warning("[1win] RAILWAY_PUBLIC_URL not set — using localhost (dev mode)")
WEBHOOK_SECRET = os.getenv("AFFILIATE_WEBHOOK_SECRET", "")


async def get_access_token() -> str:
    if not REFRESH_TOKEN:
        raise RuntimeError("1WIN_REFRESH_TOKEN env var not set")

    data = await fetch_api(
        f"{API_BASE}/api/v2/auth/refresh",
        method="POST",
        json_body={"refreshToken": REFRESH_TOKEN},
    )
    token = data.get("accessToken") or data.get("data", {}).get("accessToken")
    if not token:
        # avoid logging raw response — may contain token fragments
        raise RuntimeError("Token refresh failed: empty accessToken in response")
    logger.info("[1win] access token refreshed OK")
    return token


async def fetch_stats(token: str, date_from: str, date_to: str) -> dict:
    url = f"{API_BASE}/api/v5/stats/common?dateFrom={date_from}&dateTo={date_to}&currency=USD"
    try:
        data = await fetch_api(url, headers={"Authorization": f"Bearer {token}"})
        if not isinstance(data, dict):
            logger.warning("[1win] unexpected stats response type: %s", type(data))
            return {}
        return data.get("data") or data.get("stats") or data or {}
    except Exception as e:
        logger.warning("[1win] fetch_stats failed: %s", e)
        return {}


async def fetch_links(token: str) -> list[dict]:
    try:
        data = await fetch_api(
            f"{API_BASE}/api/v2/links/info",
            headers={"Authorization": f"Bearer {token}"},
        )
        raw = data.get("data", {}).get("links") or data.get("links") or []
        if not isinstance(raw, list):
            return []
        return [
            {
                "code": lnk.get("code") or lnk.get("link", ""),
                "source_id": lnk.get("source_id") or lnk.get("sourceId"),
                "clicks": lnk.get("clicks") or lnk.get("clickCount", 0),
                "registrations": lnk.get("registrations") or lnk.get("regCount", 0),
            }
            for lnk in raw
        ]
    except Exception as e:
        logger.warning("[1win] links fetch failed: %s", e)
        return []


async def post_to_railway(payload: dict) -> dict:
    endpoint = f"{RAILWAY_URL}/api/affiliate/stats"
    data = await fetch_api(endpoint, method="POST", json_body=payload)
    return data


async def collect() -> str:
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    token = await get_access_token()
    stats = await fetch_stats(token, yesterday, yesterday)
    links = await fetch_links(token)

    payload = {
        "secret": WEBHOOK_SECRET,
        "date_from": yesterday,
        "date_to": yesterday,
        "clicks":        int(stats.get("clicks") or stats.get("clickCount") or 0),
        "registrations": int(stats.get("registrations") or stats.get("regCount") or 0),
        "ftd_count":     int(stats.get("ftd") or stats.get("ftdCount") or 0),
        "deposits":    float(stats.get("deposits") or stats.get("depositAmount") or 0),
        "revenue":     float(stats.get("revenue") or stats.get("profit") or 0),
        "commission":  float(stats.get("commission") or stats.get("earnings") or 0),
        "source": "api",
        "links": links,
        "extra": {"raw_stats": stats},
    }

    result = await post_to_railway(payload)
    summary = (
        f"✅ 1win {yesterday}: "
        f"클릭 {payload['clicks']}, "
        f"가입 {payload['registrations']}, "
        f"커미션 ${payload['commission']:.2f}"
    )
    logger.info(summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(collect()))
