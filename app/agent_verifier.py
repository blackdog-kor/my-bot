"""
GPT-4o-mini verifier for the autonomous agent pipeline.

After each step executes, the verifier checks whether the result satisfies
the Step.expect criterion. On failure it returns a structured reason so
agent_runner can decide to retry with a different strategy.
"""
import logging
import os

logger = logging.getLogger(__name__)

_VERIFIER_MODEL = "gpt-4o-mini"
_MAX_CONTENT_CHARS = 3000  # stay well under gpt-4o-mini context limit
_SYSTEM_PROMPT = """You are a verification agent for an autonomous task pipeline.

Given:
- expect: the success criterion defined by the planner
- result: the actual output from the tool executor

Decide if the result satisfies the criterion.

Respond ONLY with valid JSON:
{"pass": true}
or
{"pass": false, "reason": "brief one-sentence explanation of what is missing"}

No other text outside the JSON.
"""


async def verify(expect: str, result: dict) -> tuple[bool, str]:
    """
    Verify whether a step result meets the expected outcome.

    Args:
        expect: Human-readable success criterion from the planner Step.
        result: Dict returned by agent_tools.execute_step().

    Returns:
        Tuple of (passed: bool, reason: str).
        reason is empty string when passed=True.
    """
    # Fast-fail: tool itself reported failure
    if not result.get("ok"):
        error = result.get("error", "unknown error")
        return False, f"Tool reported failure: {error}"

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    # Minimal sanity check: OpenAI keys start with "sk-" and are >20 chars
    if not openai_key or not openai_key.startswith("sk-") or len(openai_key) < 20:
        # No LLM available — do a basic non-empty data check
        data = result.get("data")
        if data is not None and data != {} and data != []:
            return True, ""
        return False, "Result data is empty and no verifier LLM available"

    try:
        from openai import AsyncOpenAI
        import json

        client = AsyncOpenAI(api_key=openai_key)
        # Limit to ~3000 chars to stay well within gpt-4o-mini's context without wasting tokens
        user_content = json.dumps(
            {"expect": expect, "result": result}, ensure_ascii=False
        )[:3000]

        response = await client.chat.completions.create(
            model=_VERIFIER_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = ""
        if response.choices and response.choices[0].message.content:
            raw = response.choices[0].message.content
        verdict = json.loads(raw) if raw else {}
        passed = bool(verdict.get("pass", False))
        reason = verdict.get("reason", "") if not passed else ""
        logger.info("[agent_verifier] pass=%s reason=%r", passed, reason)
        return passed, reason

    except Exception as exc:
        logger.warning("[agent_verifier] LLM call failed: %s", exc)
        ok = result.get("ok", False)
        return ok, "" if ok else str(exc)
