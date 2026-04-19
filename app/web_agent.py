"""
Web Agent — AI-powered browser automation with Cloudflare bypass.

Layer 1: curl_cffi  → fast API calls, TLS fingerprint spoofing (no browser)
Layer 2: nodriver   → undetected Chrome for bot-protected pages
Layer 3: browser-use → AI agent for complex page interaction (LLM-driven)
"""
import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


# ── Layer 1: curl_cffi (fast, no browser) ────────────────────────────────────

async def fetch_api(url: str, *, method: str = "GET", headers: dict | None = None,
                    json_body: dict | None = None, impersonate: str = "chrome124") -> dict:
    """
    HTTP request with browser TLS fingerprint.
    Works against basic Cloudflare bot detection (not Turnstile).
    """
    from curl_cffi.requests import AsyncSession

    async with AsyncSession(impersonate=impersonate) as session:
        if method.upper() == "POST":
            resp = await session.post(url, headers=headers or {}, json=json_body)
        else:
            resp = await session.get(url, headers=headers or {})

        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {"text": resp.text, "status": resp.status_code}


# ── Layer 2: nodriver (undetected Chrome) ────────────────────────────────────

@dataclass
class PageResult:
    url: str
    html: str
    text: str
    cookies: dict


async def fetch_page(url: str, *, wait_seconds: float = 3.0,
                     solve_cf: bool = True) -> PageResult:
    """
    Navigate to a URL with undetected Chrome.
    Attempts Cloudflare checkbox bypass if solve_cf=True.
    """
    import nodriver as uc

    browser = await uc.start(headless=True, browser_args=["--no-sandbox"])
    try:
        tab = await browser.get(url)
        await asyncio.sleep(wait_seconds)

        if solve_cf:
            try:
                await tab.verify_cf()
                await asyncio.sleep(1.5)
            except Exception:
                pass  # no CF challenge present

        html = await tab.get_content()
        text = await tab.evaluate("document.body.innerText")
        cookies = {c["name"]: c["value"] for c in await tab.browser.cookies.get_all()}

        return PageResult(url=tab.url, html=html, text=text or "", cookies=cookies)
    finally:
        browser.stop()


# ── Layer 3: browser-use AI agent ────────────────────────────────────────────

async def run_agent(task: str, *, url: str | None = None,
                    max_steps: int = 20) -> str:
    """
    AI agent that navigates and interacts with a website using natural language task.
    Uses GPT-4o as LLM (OPENAI_API_KEY required).

    Example:
        result = await run_agent(
            task="1win 파트너 대시보드에서 어제 통계(클릭, 가입, 커미션)를 가져와줘",
            url="https://1win-partners.com/dashboard"
        )
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set — cannot run AI agent")

    from langchain_openai import ChatOpenAI
    from browser_use import Agent, Browser, BrowserConfig

    config = BrowserConfig(headless=True, disable_security=True)
    browser = Browser(config=config)

    full_task = f"URL: {url}\n\n{task}" if url else task

    agent = Agent(
        task=full_task,
        llm=ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY),
        browser=browser,
        max_actions_per_step=5,
    )

    try:
        result = await agent.run(max_steps=max_steps)
        return str(result.final_result() or "No result")
    finally:
        await browser.close()


# ── Layer selector: auto-pick the right layer ────────────────────────────────

async def smart_fetch(url: str, task: str | None = None,
                      prefer_api: bool = False) -> Any:
    """
    Auto-selects the right layer:
    - prefer_api=True  → curl_cffi (fastest, for known API endpoints)
    - task provided    → browser-use AI agent (most capable)
    - fallback         → nodriver (undetected Chrome)
    """
    if prefer_api:
        logger.info("[web_agent] Layer 1: curl_cffi → %s", url)
        return await fetch_api(url)

    if task:
        logger.info("[web_agent] Layer 3: browser-use AI agent → %s", url)
        return await run_agent(task, url=url)

    logger.info("[web_agent] Layer 2: nodriver → %s", url)
    return await fetch_page(url)
