"""
1win stats webhook — receives browser-pushed stats and bookmarklet delivery.

Endpoints:
  POST /api/1win/stats        — receive stats pushed from user's browser
  GET  /api/1win/bookmarklet  — return installable bookmarklet JS
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.getenv("AFFILIATE_WEBHOOK_SECRET", "")
RAILWAY_URL = os.getenv("RAILWAY_PUBLIC_URL", "").rstrip("/")

router = APIRouter(prefix="/api/1win", tags=["1win"])


# ── Pydantic model ────────────────────────────────────────────────────────────

class StatsPayload(BaseModel):
    """Payload sent by the bookmarklet from the user's browser."""

    secret: str = ""
    date: str = ""          # YYYY-MM-DD collected on
    stats: dict = {}        # raw /api/v2/stats/common response
    links: list[dict] = []  # optional per-link breakdown


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_stats(raw: dict, date_str: str) -> dict:
    """Normalize raw stats API response to affiliate_tracker schema."""
    # 1win may nest data inside 'data' key
    data = raw.get("data") or raw

    return {
        "date_from": date_str,
        "date_to": date_str,
        "clicks": int(data.get("clicks") or data.get("clickCount") or 0),
        "registrations": int(data.get("registrations") or data.get("regCount") or 0),
        "ftd_count": int(data.get("ftd") or data.get("ftdCount") or 0),
        "deposits": float(data.get("deposits") or data.get("depositAmount") or 0),
        "revenue": float(data.get("revenue") or data.get("profit") or 0),
        "commission": float(data.get("commission") or data.get("earnings") or 0),
        "source": "bookmarklet",
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/stats")
async def receive_stats(payload: StatsPayload):
    """Accept stats pushed by the browser bookmarklet and save to DB."""
    if WEBHOOK_SECRET and payload.secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    if not payload.date:
        raise HTTPException(status_code=400, detail="date field required (YYYY-MM-DD)")

    normalized = _extract_stats(payload.stats, payload.date)

    try:
        from app.affiliate_tracker import save_affiliate_snapshot
        row_id = save_affiliate_snapshot(normalized, payload.links or [])
    except Exception as exc:
        logger.exception("[win1_webhook] save_affiliate_snapshot failed")
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info(
        "[win1_webhook] stats saved id=%s date=%s clicks=%s commission=%s",
        row_id, payload.date,
        normalized["clicks"], normalized["commission"],
    )
    return {"ok": True, "id": row_id, "date": payload.date}


@router.get("/bookmarklet")
def get_bookmarklet():
    """Return the bookmarklet JS and installation instructions."""
    base = RAILWAY_URL or "https://your-railway-app.railway.app"
    secret = WEBHOOK_SECRET or "SET_AFFILIATE_WEBHOOK_SECRET"

    # Bookmarklet fetches today's stats from 1win and POSTs to Railway
    js = (
        "javascript:(function(){"
        "var today=new Date().toISOString().slice(0,10);"
        "fetch('https://1win-partners.com/api/v2/stats/common"
        "?dateFrom='+today+'&dateTo='+today,{credentials:'include'})"
        ".then(function(r){return r.json()})"
        f".then(function(d){{return fetch('{base}/api/1win/stats',{{"
        "method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        f"body:JSON.stringify({{secret:'{secret}',stats:d,date:today}})"
        "})}})"
        ".then(function(){alert('Stats sent to Railway!')})"
        ".catch(function(e){alert('Error: '+e)})"
        "})();"
    )

    return {
        "bookmarklet": js,
        "instructions": [
            "1) Copy the bookmarklet value below",
            "2) In Chrome: Bookmarks bar → right-click → Add page",
            "3) Paste the JS as the URL, name it '1win Stats Push'",
            "4) Log in to 1win-partners.com in the same browser",
            "5) Click the bookmark — stats will be pushed to Railway",
            f"6) Check: GET {base}/api/affiliate/report",
        ],
        "railway_endpoint": f"{base}/api/1win/stats",
        "note": (
            "stats/common is blocked by Cloudflare on server IPs, "
            "so the bookmarklet runs in your authenticated browser session."
        ),
    }
