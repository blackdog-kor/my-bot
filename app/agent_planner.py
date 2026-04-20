"""
GPT-4o based planner that converts natural language prompts to execution steps.

The planner selects tools in preference order:
  1. fetch_api       — cheapest, direct API calls with TLS spoofing
  2. api_discovery   — network interception + token extraction
  3. web_agent       — AI browser agent (browser-use / nodriver)
  4. browser_manager — persistent Chrome session (requires prior login)
  5. token_vault     — read stored tokens from DB
  6. db_query        — query affiliate stats from PostgreSQL

Failed history is injected so the planner avoids repeating unsuccessful strategies.
"""
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

try:
    from openai import AsyncOpenAI as _AsyncOpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _AsyncOpenAI = None  # type: ignore[assignment,misc]
    _OPENAI_AVAILABLE = False

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
_PLANNER_MODEL = "gpt-4o"

_SYSTEM_PROMPT = """You are a planning agent for a Telegram casino affiliate bot.

Your job is to convert user requests into ordered execution steps.

Available tools (use in this preference order — cheapest first):
1. fetch_api       — Direct HTTP call with TLS fingerprint spoofing. Args: {url, method, headers, json_body}
2. api_discovery   — Intercept network traffic to extract API tokens. Args: {target_url, wait_seconds}
3. web_agent       — AI-powered browser that interacts with pages. Args: {task, url, max_steps}
4. browser_manager — Persistent Chrome with saved login session. Args: {action, url}
                     Actions: navigate_authenticated | extract_tokens | is_logged_in | health_check
5. token_vault     — Read stored auth tokens from database. Args: {service}
6. db_query        — Query affiliate stats from PostgreSQL. Args: {table, filters}
7. terabox_agent   — Extract file info from TeraBox share links. Args: {share_url}
                     Returns: file_name, media_type, file_size, download_url, title

Rules:
- Start with fetch_api when a direct API endpoint is known.
- Use api_discovery when auth tokens are needed but not yet stored.
- Use browser_manager only when login state must be maintained (cookies).
- Use token_vault before api_discovery to avoid redundant network calls.
- Use terabox_agent for TeraBox share URLs to extract content metadata.
- Each step must have a clear expect field describing what success looks like.
- Output ONLY valid JSON — no explanations outside the JSON block.

Output format:
{
  "goal": "one-sentence description of the overall task",
  "steps": [
    {
      "tool": "<tool_name>",
      "action": "<specific action or endpoint>",
      "args": { ... },
      "expect": "<what success looks like>"
    }
  ]
}
"""


@dataclass
class Step:
    """Single execution step produced by the planner."""
    tool: str    # fetch_api | api_discovery | web_agent | browser_manager | token_vault | db_query
    action: str  # specific action or API path
    args: dict = field(default_factory=dict)
    expect: str = ""  # human-readable success criterion


@dataclass
class Plan:
    """Full execution plan for a user prompt."""
    steps: list[Step] = field(default_factory=list)
    goal: str = ""


def _build_user_message(prompt: str, failed_history: Optional[list[dict]]) -> str:
    """Combine the user prompt and failure history into a single message."""
    msg = f"Task: {prompt}"
    if failed_history:
        history_text = json.dumps(failed_history, ensure_ascii=False, indent=2)
        msg += (
            f"\n\nPrevious attempts failed — choose a DIFFERENT strategy:\n{history_text}"
        )
    return msg


def _parse_plan(raw: str) -> Plan:
    """Parse GPT-4o JSON response into a Plan object."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Attempt to extract JSON block from markdown code fences
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
        else:
            logger.error("[agent_planner] Could not parse planner response: %s", raw[:200])
            return Plan(goal="parse error", steps=[])

    steps = [
        Step(
            tool=s.get("tool", ""),
            action=s.get("action", ""),
            args=s.get("args", {}),
            expect=s.get("expect", ""),
        )
        for s in data.get("steps", [])
    ]
    return Plan(goal=data.get("goal", ""), steps=steps)


async def plan(prompt: str, failed_history: Optional[list[dict]] = None) -> Plan:
    """
    Call GPT-4o to produce an execution plan for the given prompt.

    Args:
        prompt:         Natural language user request.
        failed_history: List of previous failure dicts to avoid repeating bad strategies.

    Returns:
        Plan with ordered Steps.
    """
    if not _OPENAI_AVAILABLE:
        logger.error("[agent_planner] openai package not installed")
        return Plan(goal="config error", steps=[])

    if not OPENAI_API_KEY:
        logger.error("[agent_planner] OPENAI_API_KEY not set")
        return Plan(goal="config error", steps=[])

    client = _AsyncOpenAI(api_key=OPENAI_API_KEY)
    user_message = _build_user_message(prompt, failed_history)

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        choices = response.choices or []
        raw = choices[0].message.content if choices else "{}"
        raw = raw or "{}"
        parsed = _parse_plan(raw)
        logger.info(
            "[agent_planner] Plan ready: goal=%r steps=%d",
            parsed.goal, len(parsed.steps),
        )
        return parsed
    except Exception as exc:
        logger.exception("[agent_planner] GPT-4o call failed: %s", exc)
        return Plan(goal="llm error", steps=[])
