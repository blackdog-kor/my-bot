"""
API Discovery — autonomous network interception and token extraction.

Launches a browser session, intercepts all XHR/fetch requests, and extracts:
  - Authorization headers (Bearer tokens)
  - localStorage / sessionStorage tokens
  - Cookie-based auth tokens
  - Full request/response map for API endpoint discovery

Usage:
    result = await discover("https://1win-partners.com", login_hint="dashboard")
    tokens = result.tokens      # {accessToken, refreshToken, ...}
    endpoints = result.endpoints # [{url, method, headers, body_sample}, ...]
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_AUTH_HEADER_RE = re.compile(r"^Bearer\s+(.+)$", re.I)
_TOKEN_KEYS = {"accessToken", "refreshToken", "access_token", "refresh_token",
               "token", "authToken", "auth_token", "jwt"}


@dataclass
class DiscoveryResult:
    url: str
    tokens: dict = field(default_factory=dict)
    endpoints: list[dict] = field(default_factory=list)
    cookies: dict = field(default_factory=dict)
    raw_storage: dict = field(default_factory=dict)


# ── Network interception via Playwright ──────────────────────────────────────

async def discover(url: str, *, wait_seconds: float = 8.0,
                   navigate_paths: list[str] | None = None) -> DiscoveryResult:
    """
    Open URL in browser, intercept all network requests, extract tokens + endpoints.
    navigate_paths: additional paths to visit after landing (e.g. ["/dashboard", "/stats"])
    """
    from playwright.async_api import async_playwright

    result = DiscoveryResult(url=url)
    captured: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )

        # intercept every request
        async def on_request(request):
            hdrs = dict(request.headers)
            auth = hdrs.get("authorization", "")
            m = _AUTH_HEADER_RE.match(auth)
            if m:
                result.tokens["accessToken"] = m.group(1)
            captured.append({
                "url": request.url,
                "method": request.method,
                "headers": {k: v for k, v in hdrs.items()
                            if k.lower() not in ("cookie",)},
            })

        async def on_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                body = await response.json()
                _extract_tokens_from_body(body, result.tokens)
                origin = urlparse(url).netloc
                if origin in response.url:
                    captured[-1]["response_sample"] = _truncate(body)
            except Exception:
                pass

        page = await context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(wait_seconds)

            storage = await _extract_storage(page)
            result.raw_storage = storage
            for key, val in storage.items():
                if key in _TOKEN_KEYS:
                    result.tokens[key] = val

            for path in (navigate_paths or []):
                try:
                    await page.goto(f"{url.rstrip('/')}/{path.lstrip('/')}",
                                    wait_until="networkidle", timeout=20000)
                    await asyncio.sleep(3)
                    extra = await _extract_storage(page)
                    for key, val in extra.items():
                        if key in _TOKEN_KEYS:
                            result.tokens[key] = val
                except Exception as e:
                    logger.warning("[discovery] path %s failed: %s", path, e)

            for c in await context.cookies():
                result.cookies[c["name"]] = c["value"]
                if c["name"].lower() in {k.lower() for k in _TOKEN_KEYS}:
                    result.tokens[c["name"]] = c["value"]
        finally:
            await browser.close()

    # deduplicate endpoints
    seen = set()
    for req in captured:
        key = (req["method"], req["url"])
        if key not in seen:
            seen.add(key)
            result.endpoints.append(req)

    logger.info("[discovery] %s: %d tokens, %d endpoints",
                url, len(result.tokens), len(result.endpoints))
    return result


async def _extract_storage(page) -> dict:
    return await page.evaluate("""() => {
        const out = {};
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            try { out[k] = JSON.parse(localStorage.getItem(k)); }
            catch { out[k] = localStorage.getItem(k); }
        }
        for (let i = 0; i < sessionStorage.length; i++) {
            const k = sessionStorage.key(i);
            try { out[k] = JSON.parse(sessionStorage.getItem(k)); }
            catch { out[k] = sessionStorage.getItem(k); }
        }
        return out;
    }""")


def _extract_tokens_from_body(body, tokens: dict, depth: int = 0) -> None:
    if depth > 4:
        return
    if isinstance(body, dict):
        for k, v in body.items():
            if k in _TOKEN_KEYS and isinstance(v, str) and len(v) > 20:
                tokens[k] = v
            else:
                _extract_tokens_from_body(v, tokens, depth + 1)
    elif isinstance(body, list):
        for item in body[:5]:
            _extract_tokens_from_body(item, tokens, depth + 1)


def _truncate(obj, max_len: int = 300) -> str:
    s = json.dumps(obj, ensure_ascii=False)
    return s[:max_len] + "…" if len(s) > max_len else s


# ── 1win-specific strategy ───────────────────────────────────────────────────

async def extract_1win_tokens() -> dict:
    """
    Browser-based extraction for 1win-partners.com.
    Navigates to dashboard pages to trigger auth API calls.
    """
    result = await discover(
        "https://1win-partners.com",
        wait_seconds=6,
        navigate_paths=["dashboard", "stats", "finance"],
    )
    if not result.tokens.get("accessToken"):
        raise RuntimeError(
            "No accessToken captured. User must be logged in to 1win-partners.com "
            "in a Chrome profile, or provide credentials."
        )
    return result.tokens


async def refresh_1win_tokens(cached: dict) -> dict:
    """Refresh 1win accessToken using stored refreshToken (pure API, no browser)."""
    from app.web_agent import fetch_api

    refresh_token = cached.get("refreshToken")
    if not refresh_token:
        raise RuntimeError("No refreshToken available")

    data = await fetch_api(
        "https://1win-partners.com/api/v2/auth/refresh",
        method="POST",
        json_body={"refreshToken": refresh_token},
    )
    token = data.get("accessToken") or data.get("data", {}).get("accessToken")
    if not token:
        raise RuntimeError("refresh response missing accessToken")

    return {**cached, "accessToken": token}


# ── Register 1win strategy on import ────────────────────────────────────────

def register_1win() -> None:
    from app.token_vault import SiteStrategy, register

    register(SiteStrategy(
        site="1win-partners",
        login_url="https://1win-partners.com",
        extract=extract_1win_tokens,
        refresh=refresh_1win_tokens,
        interval_seconds=3600 * 4,
    ))
