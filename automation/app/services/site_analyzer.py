import json
import os
from typing import Any, Dict

import httpx

from app.db import save_site_snapshot


CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()

CF_BASE_URL = "https://api.cloudflare.com/client/v4"


class CloudflareConfigError(RuntimeError):
    pass


def _ensure_cf_config() -> None:
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
        raise CloudflareConfigError(
            "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN must be set to use the crawl API."
        )


def fetch_site_markdown(target_url: str) -> str:
    """
    Call Cloudflare's Browser Rendering Markdown API to get a Markdown
    representation of the target URL.

    Docs (conceptual):
      POST /accounts/:account_id/browser-rendering/markdown
      Body: {\"url\": \"https://example.com\"}
      Headers:
        Authorization: Bearer <token>
        Accept: text/markdown
    """
    _ensure_cf_config()

    endpoint = (
        f\"{CF_BASE_URL}/accounts/{CLOUDFLARE_ACCOUNT_ID}/browser-rendering/markdown\"
    )

    headers = {
        \"Authorization\": f\"Bearer {CLOUDFLARE_API_TOKEN}\",
        \"Accept\": \"text/markdown\",
        \"Content-Type\": \"application/json\",
    }
    payload: Dict[str, Any] = {\"url\": target_url}

    resp = httpx.post(endpoint, headers=headers, content=json.dumps(payload), timeout=30.0)
    resp.raise_for_status()

    # Cloudflare responds with Markdown in the body when Accept: text/markdown
    return resp.text or \"\"


def analyze_and_store_site(target_url: str, source: str = \"\") -> int:
    """
    High-level helper:
      1) Fetch Markdown via Cloudflare crawl/markdown API
      2) Store the snapshot in the site_data table

    Returns the created site_data id.
    """
    markdown = fetch_site_markdown(target_url)

    meta = {
        \"cloudflare_account_id\": CLOUDFLARE_ACCOUNT_ID,
        \"provider\": \"cloudflare_markdown_crawl\",
    }

    return save_site_snapshot(
        url=target_url,
        markdown=markdown,
        source=source or \"cloudflare_crawl\",
        meta=meta,
    )

