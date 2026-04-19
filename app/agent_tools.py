"""
Tool executors for the autonomous agent pipeline.

Each function corresponds to a planner tool name and returns a dict result.
Tools are selected by agent_runner based on the Step.tool field from agent_planner.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def run_fetch_api(action: str, args: dict) -> dict:
    """Direct HTTP call using curl_cffi TLS spoofing."""
    from app.web_agent import fetch_api
    url = args.get("url", action)
    method = args.get("method", "GET")
    headers = args.get("headers", {})
    json_body = args.get("json_body")
    try:
        data = await fetch_api(url, method=method, headers=headers, json_body=json_body)
        return {"ok": True, "data": data}
    except Exception as exc:
        logger.warning("[agent_tools] fetch_api failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def run_api_discovery(action: str, args: dict) -> dict:
    """Intercept network traffic to extract API tokens and endpoints."""
    from app.api_discovery import discover
    target_url = args.get("target_url", action)
    wait_seconds = int(args.get("wait_seconds", 5))
    try:
        result = await discover(target_url, wait_seconds=wait_seconds)
        return {"ok": True, "data": result}
    except Exception as exc:
        logger.warning("[agent_tools] api_discovery failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def run_web_agent(action: str, args: dict) -> dict:
    """AI-powered browser agent via browser-use."""
    from app.web_agent import run_agent
    task = args.get("task", action)
    url = args.get("url", "")
    max_steps = int(args.get("max_steps", 10))
    if url:
        task = f"Navigate to {url} then: {task}"
    try:
        result = await run_agent(task, max_steps=max_steps)
        return {"ok": True, "data": result}
    except Exception as exc:
        logger.warning("[agent_tools] web_agent failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def run_browser_manager(action: str, args: dict) -> dict:
    """Persistent Chrome session operations."""
    from app.browser_manager import browser, NotLoggedInError
    cmd = args.get("action", action)
    url = args.get("url", "")
    try:
        if cmd == "health_check":
            ok = await browser.health_check()
            return {"ok": ok, "data": {"alive": ok}}
        elif cmd == "is_logged_in":
            logged = await browser.is_logged_in(url)
            return {"ok": True, "data": {"logged_in": logged}}
        elif cmd == "navigate_authenticated":
            page = await browser.navigate_authenticated(url)
            return {"ok": True, "data": {"url": page.url}}
        elif cmd == "extract_tokens":
            tokens = await browser.extract_tokens()
            return {"ok": True, "data": tokens}
        else:
            return {"ok": False, "error": f"Unknown browser_manager action: {cmd}"}
    except NotLoggedInError as exc:
        return {"ok": False, "error": str(exc), "requires_login": True}
    except Exception as exc:
        logger.warning("[agent_tools] browser_manager failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def run_token_vault(action: str, args: dict) -> dict:
    """Read stored auth tokens from the vault DB."""
    from app.token_vault import get_tokens
    service = args.get("service", action)
    try:
        tokens = await get_tokens(service)
        if tokens:
            return {"ok": True, "data": tokens}
        return {"ok": False, "error": f"No tokens in vault for service: {service}"}
    except Exception as exc:
        logger.warning("[agent_tools] token_vault failed: %s", exc)
        return {"ok": False, "error": str(exc)}


_ALLOWED_TABLES = frozenset({"affiliate_stats", "broadcast_targets", "campaign_posts", "campaign_config"})


async def run_db_query(action: str, args: dict) -> dict:
    """Query affiliate stats from PostgreSQL."""
    import psycopg2
    import os
    table = args.get("table", "affiliate_stats")
    if table not in _ALLOWED_TABLES:
        return {"ok": False, "error": f"Table not in allowlist: {table}"}
    filters = args.get("filters", {})
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        logger.error("[agent_tools] DATABASE_URL not set — db_query cannot proceed")
        return {"ok": False, "error": "DATABASE_URL not set"}
    try:
        where_parts = [f"{k} = %s" for k in filters]
        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        query = f"SELECT * FROM {table} {where_clause} ORDER BY id DESC LIMIT 50"
        values = list(filters.values())
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)
                cols = [desc[0] for desc in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        return {"ok": True, "data": rows}
    except psycopg2.Error as exc:
        logger.warning("[agent_tools] db_query psycopg2 error: %s", exc)
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.warning("[agent_tools] db_query failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# Dispatch table mapping planner tool names to executor functions
TOOL_DISPATCH: dict[str, Any] = {
    "fetch_api":       run_fetch_api,
    "api_discovery":   run_api_discovery,
    "web_agent":       run_web_agent,
    "browser_manager": run_browser_manager,
    "token_vault":     run_token_vault,
    "db_query":        run_db_query,
}


async def execute_step(tool: str, action: str, args: dict) -> dict:
    """
    Execute a single planner Step by dispatching to the appropriate tool.

    Args:
        tool:   Tool name from Step.tool (must be in TOOL_DISPATCH).
        action: Specific action or endpoint from Step.action.
        args:   Arguments dict from Step.args.

    Returns:
        Result dict with at least 'ok' (bool) and either 'data' or 'error'.
    """
    fn = TOOL_DISPATCH.get(tool)
    if fn is None:
        logger.error("[agent_tools] Unknown tool: %s", tool)
        return {"ok": False, "error": f"Unknown tool: {tool}"}
    logger.info("[agent_tools] Executing %s / %s", tool, action)
    return await fn(action, args)
