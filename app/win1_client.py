"""1win-partners.com API client — cookie-based auth only."""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

BASE = "https://1win-partners.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": BASE,
    "Referer": f"{BASE}/panel/",
}


class Win1Client:
    """Cookie-based 1win-partners API client.

    All endpoints require cookie auth — Authorization header is rejected.
    """

    def __init__(self, access_token: str, refresh_token: str) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token

    @property
    def _cookies(self) -> dict[str, str]:
        return {
            "accessToken": self.access_token,
            "refreshToken": self.refresh_token,
            "app_lang": "en-001",
        }

    async def _get(self, path: str, params: dict | None = None) -> dict:
        """Perform authenticated GET — raises on non-2xx."""
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{BASE}{path}",
                params=params,
                cookies=self._cookies,
                headers=_HEADERS,
            )
            r.raise_for_status()
            return r.json()

    async def user_info(self) -> dict:
        """Return account info: balance, cooperation model, revenue share."""
        data = await self._get("/api/v2/user/info")
        return data.get("user", data)

    async def links(self) -> list[dict]:
        """Return affiliate link list with id, source_id, name, is_promo."""
        data = await self._get("/api/v2/links/info")
        return data.get("links", [])

    async def sources(self) -> list[dict]:
        """Return traffic source list with id, type, name, verificationStatus."""
        data = await self._get("/api/v2/sources/list")
        return data.get("results", [])

    async def promo_codes(self) -> list[dict]:
        """Return promo code list with id, link, source_name, created_at."""
        data = await self._get("/api/v2/promo/list")
        return data.get("links", [])

    async def refresh_access_token(self) -> str:
        """Exchange refreshToken for a new accessToken via POST."""
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{BASE}/api/v2/auth/refresh",
                json={"refreshToken": self.refresh_token},
                headers=_HEADERS,
            )
            r.raise_for_status()
            data = r.json()
            token = data.get("accessToken") or data.get("data", {}).get("accessToken")
            if not token:
                raise RuntimeError("refresh returned no accessToken")
            self.access_token = token
            return token


def get_client_from_vault() -> Win1Client:
    """Build Win1Client from token_vault DB or env var fallback."""
    try:
        from app.token_vault import _load
        stored = _load("1win-partners")
        if stored and stored.get("accessToken") and stored.get("refreshToken"):
            return Win1Client(stored["accessToken"], stored["refreshToken"])
    except Exception as e:
        logger.warning("[win1] vault load failed: %s", e)

    # Fallback: build with refresh token only; first call will refresh
    refresh = os.getenv("1WIN_REFRESH_TOKEN", "").strip()
    if not refresh:
        raise RuntimeError(
            "No 1win tokens available. Use /settoken 1win-partners or set 1WIN_REFRESH_TOKEN"
        )
    return Win1Client("", refresh)
