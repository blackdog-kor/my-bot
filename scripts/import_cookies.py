"""
Cookie Importer — inject browser cookies into token vault.

Usage:
    python3 scripts/import_cookies.py '[ {"name":"...", "value":"..."}, ... ]'
    or pipe from file:
    cat cookies.json | python3 scripts/import_cookies.py

Workflow:
    1. User exports cookies from Cookie-Editor extension (JSON format)
    2. This script injects them into a Playwright browser session
    3. Extracts accessToken/refreshToken from authenticated page
    4. Stores in token_vault DB for auto-refresh
"""
import asyncio
import json
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def import_and_extract(cookies_json: str, site_url: str = "https://1win-partners.com") -> dict:
    from playwright.async_api import async_playwright
    from app.token_vault import _save
    from app.api_discovery import _extract_storage, _extract_tokens_from_body, _AUTH_HEADER_RE

    cookies = json.loads(cookies_json)
    tokens = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        # inject cookies
        playwright_cookies = []
        for c in cookies:
            pc = {
                "name": c.get("name", ""),
                "value": c.get("value", ""),
                "domain": c.get("domain", ".1win-partners.com"),
                "path": c.get("path", "/"),
                "httpOnly": c.get("httpOnly", False),
                "secure": c.get("secure", False),
                "sameSite": c.get("sameSite", "Lax") or "Lax",
            }
            if c.get("expirationDate"):
                pc["expires"] = int(c["expirationDate"])
            playwright_cookies.append(pc)

        await context.add_cookies(playwright_cookies)
        logger.info("Injected %d cookies", len(playwright_cookies))

        # intercept auth headers
        async def on_request(req):
            auth = req.headers.get("authorization", "")
            m = _AUTH_HEADER_RE.match(auth)
            if m:
                tokens["accessToken"] = m.group(1)

        async def on_response(resp):
            try:
                if "json" not in resp.headers.get("content-type", ""):
                    return
                body = await resp.json()
                _extract_tokens_from_body(body, tokens)
            except Exception:
                pass

        page = await context.new_page()
        page.on("request", on_request)
        page.on("response", on_response)

        # navigate to trigger API calls
        for path in ["/dashboard", "/stats", "/finance"]:
            try:
                await page.goto(f"{site_url}{path}", wait_until="networkidle", timeout=20000)
                await asyncio.sleep(3)
                storage = await _extract_storage(page)
                for k, v in storage.items():
                    if k in {"accessToken", "refreshToken", "access_token", "refresh_token"} and isinstance(v, str):
                        tokens[k] = v
            except Exception as e:
                logger.warning("  %s: %s", path, e)

        await browser.close()

    if not tokens.get("accessToken"):
        raise RuntimeError("No accessToken captured — cookies may be expired or insufficient")

    # save to vault
    _save("1win-partners", tokens)
    logger.info("✅ Tokens saved to vault: %s", list(tokens.keys()))
    return tokens


async def main():
    if sys.stdin.isatty() and len(sys.argv) < 2:
        print("Usage: python3 scripts/import_cookies.py '<cookies_json>'")
        print("       cat cookies.json | python3 scripts/import_cookies.py")
        sys.exit(1)

    if len(sys.argv) >= 2:
        raw = sys.argv[1]
    else:
        raw = sys.stdin.read()

    tokens = await import_and_extract(raw.strip())
    print(f"\n토큰 추출 완료:")
    print(f"  accessToken : {tokens.get('accessToken', '')[:40]}...")
    if tokens.get("refreshToken"):
        print(f"  refreshToken: {tokens.get('refreshToken', '')[:40]}...")


if __name__ == "__main__":
    asyncio.run(main())
