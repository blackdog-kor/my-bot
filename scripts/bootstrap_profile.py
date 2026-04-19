"""
Bootstrap the persistent Chrome profile by logging into affiliate sites manually.

Run this locally (or in Codespace) when:
- Setting up the bot for the first time
- After a session expires and login is required again

Usage:
    python3 scripts/bootstrap_profile.py [--site 1win]

The browser opens in headed mode so you can log in manually.
Once logged in, press Enter — the profile is saved automatically.
"""
import asyncio
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

PROFILE_DIR = os.getenv("CHROME_PROFILE_DIR", "/data/chrome-profile")

SITE_URLS = {
    "1win": "https://1win-partners.com/login",
}


async def bootstrap(site: str) -> None:
    from playwright.async_api import async_playwright
    from app.browser_stealth import apply_stealth

    url = SITE_URLS.get(site)
    if not url:
        logger.error("Unknown site '%s'. Available: %s", site, list(SITE_URLS.keys()))
        sys.exit(1)

    os.makedirs(PROFILE_DIR, exist_ok=True)
    logger.info("Profile dir: %s", PROFILE_DIR)
    logger.info("Opening browser for site: %s → %s", site, url)

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,  # headed so the user can interact
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 1280, "height": 800},
        )
        await apply_stealth(context)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        print("\n" + "=" * 60)
        print(f"Browser opened at: {url}")
        print("Log in manually, then press ENTER here to save the session.")
        print("=" * 60 + "\n")
        input()  # wait for user to complete login

        # Extract and display tokens for verification
        try:
            storage = await page.evaluate("() => Object.fromEntries(Object.entries(localStorage))")
            token_keys = [k for k in storage if "token" in k.lower() or "auth" in k.lower()]
            if token_keys:
                logger.info("Tokens found in localStorage: %s", token_keys)
            else:
                logger.warning("No token keys found in localStorage — check if login succeeded")
        except Exception as e:
            logger.warning("Could not read localStorage: %s", e)

        await context.close()

    logger.info("✅ Profile saved to: %s", PROFILE_DIR)
    logger.info("Copy this directory to your Railway volume at CHROME_PROFILE_DIR.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap persistent Chrome profile")
    parser.add_argument("--site", default="1win", choices=list(SITE_URLS.keys()))
    args = parser.parse_args()
    asyncio.run(bootstrap(args.site))


if __name__ == "__main__":
    main()
