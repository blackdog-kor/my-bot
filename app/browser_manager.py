"""
Persistent Chrome singleton using Playwright launch_persistent_context.

Maintains a long-lived browser session with saved cookies and localStorage
so that affiliate partner logins persist across restarts.

Environment:
    CHROME_PROFILE_DIR — path to persistent profile directory (default: /data/chrome-profile)
"""
import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

PROFILE_DIR = os.getenv("CHROME_PROFILE_DIR", "/data/chrome-profile")

# Chromium launch args for stealth and Railway compatibility
_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--no-first-run",
    "--no-default-browser-check",
]


class NotLoggedInError(Exception):
    """Raised when the browser session has expired or the user is not logged in."""


class PersistentBrowser:
    """
    Singleton wrapper around a persistent Playwright Chromium context.

    Keeps a single browser + context alive and reuses pages to avoid
    repeated login flows. All public methods are async-safe via a shared lock.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._playwright = None
        self._context = None
        self._page = None

    async def _ensure_started(self) -> None:
        """Launch the browser and apply stealth if not already running."""
        if self._context is not None:
            return

        from playwright.async_api import async_playwright
        from app.browser_stealth import apply_stealth

        logger.info("[browser_manager] Launching persistent context at %s", PROFILE_DIR)
        os.makedirs(PROFILE_DIR, exist_ok=True)

        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=True,
            args=_LAUNCH_ARGS,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1280, "height": 800},
        )
        await apply_stealth(self._context)
        logger.info("[browser_manager] Browser context ready")

    async def get_page(self, url: Optional[str] = None):
        """
        Return the active page, optionally navigating to a URL.

        Args:
            url: If provided, navigate the page to this URL first.

        Returns:
            Playwright Page object
        """
        async with self._lock:
            await self._ensure_started()
            pages = self._context.pages
            self._page = pages[0] if pages else await self._context.new_page()
            if url:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            return self._page

    async def is_logged_in(self, url: str) -> bool:
        """
        Check whether the current session is authenticated.

        Navigates to the URL and inspects whether the browser was redirected
        to a login or auth page.

        Args:
            url: The protected page URL to check.

        Returns:
            True if the current URL does NOT contain login/auth indicators.
        """
        try:
            page = await self.get_page(url)
            final_url = page.url.lower()
            logged_out_signals = ("/login", "/auth", "/signin", "/sign-in", "?next=", "?redirect=")
            is_out = any(sig in final_url for sig in logged_out_signals)
            logger.info("[browser_manager] is_logged_in=%s final_url=%s", not is_out, page.url)
            return not is_out
        except Exception as exc:
            logger.warning("[browser_manager] is_logged_in check failed: %s", exc)
            return False

    async def extract_tokens(self) -> dict:
        """
        Extract auth tokens from the current page's localStorage and cookies.

        Returns:
            Dict with keys 'localStorage' (dict) and 'cookies' (list of dicts).
        """
        async with self._lock:
            await self._ensure_started()
            if self._page is None:
                return {}

            try:
                local_storage: dict = await self._page.evaluate(
                    "() => Object.fromEntries(Object.entries(localStorage))"
                )
            except Exception:
                local_storage = {}

            try:
                cookies = await self._context.cookies()
            except Exception:
                cookies = []

            return {"localStorage": local_storage, "cookies": cookies}

    async def navigate_authenticated(self, url: str):
        """
        Navigate to a URL, raising NotLoggedInError if the session is expired.

        Args:
            url: Target URL requiring authentication.

        Returns:
            Playwright Page object at the given URL.

        Raises:
            NotLoggedInError: If redirected to a login page.
        """
        logged_in = await self.is_logged_in(url)
        if not logged_in:
            raise NotLoggedInError(
                f"Session expired — browser redirected to login when visiting {url}. "
                "Run scripts/bootstrap_profile.py to re-authenticate."
            )
        page = await self.get_page()
        return page

    async def health_check(self) -> bool:
        """
        Quick liveness check — ensures the browser is responsive.

        Returns:
            True if the browser context is active and can evaluate JS.
        """
        try:
            async with self._lock:
                await self._ensure_started()
                pages = self._context.pages
                page = pages[0] if pages else await self._context.new_page()
                result = await page.evaluate("() => navigator.userAgent")
                return bool(result)
        except Exception as exc:
            logger.warning("[browser_manager] health_check failed: %s", exc)
            return False

    async def close(self) -> None:
        """Gracefully shut down the browser context and Playwright instance."""
        async with self._lock:
            if self._context:
                try:
                    await self._context.close()
                except Exception:
                    pass
                self._context = None
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            self._page = None
            logger.info("[browser_manager] Browser closed")


# Module-level singleton — import and use directly
browser = PersistentBrowser()
