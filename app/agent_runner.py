"""
Autonomous agent runner: Plan → Execute → Verify loop.

Orchestrates the full pipeline for a natural language task:
  1. Call agent_planner to produce an ordered Step list
  2. Execute each step via agent_tools
  3. Verify each result via agent_verifier
  4. On failure, retry with failed history injected into re-plan (max 3 total attempts)
  5. Return a structured RunResult with all step outputs
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3


@dataclass
class StepResult:
    """Result of executing a single plan step."""
    tool: str
    action: str
    expect: str
    output: dict
    passed: bool
    reason: str = ""


@dataclass
class RunResult:
    """Final outcome of an agent run."""
    task: str
    goal: str
    steps: list[StepResult] = field(default_factory=list)
    success: bool = False
    attempts: int = 0
    summary: str = ""


async def run(task: str, notify: Optional[callable] = None) -> RunResult:
    """
    Execute a natural language task through the Plan→Execute→Verify loop.

    Args:
        task:   Natural language instruction from the user.
        notify: Optional async callback(msg: str) for progress updates.

    Returns:
        RunResult with all step outcomes and overall success flag.
    """
    from app.agent_planner import plan
    from app.agent_tools import execute_step
    from app.agent_verifier import verify

    async def _notify(msg: str) -> None:
        if notify:
            try:
                await notify(msg)
            except Exception:
                pass

    failed_history: list[dict] = []
    result = RunResult(task=task, goal="")

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        result.attempts = attempt
        logger.info("[agent_runner] Attempt %d/%d for task: %s", attempt, _MAX_ATTEMPTS, task)
        await _notify(f"🔄 Attempt {attempt}/{_MAX_ATTEMPTS}: planning…")

        current_plan = await plan(task, failed_history=failed_history or None)
        result.goal = current_plan.goal

        if not current_plan.steps:
            logger.warning("[agent_runner] Planner returned empty plan on attempt %d", attempt)
            failed_history.append({"attempt": attempt, "error": "empty plan"})
            continue

        step_results: list[StepResult] = []
        attempt_succeeded = True

        for i, step in enumerate(current_plan.steps, start=1):
            await _notify(f"⚙️ Step {i}/{len(current_plan.steps)}: {step.tool} — {step.action}")
            logger.info("[agent_runner] Step %d: %s / %s", i, step.tool, step.action)

            output = await execute_step(step.tool, step.action, step.args)
            passed, reason = await verify(step.expect, output)

            sr = StepResult(
                tool=step.tool,
                action=step.action,
                expect=step.expect,
                output=output,
                passed=passed,
                reason=reason,
            )
            step_results.append(sr)

            if not passed:
                logger.warning(
                    "[agent_runner] Step %d failed: %s — %s", i, step.action, reason
                )
                await _notify(f"❌ Step {i} failed: {reason}")
                failed_history.append({
                    "attempt": attempt,
                    "step": i,
                    "tool": step.tool,
                    "action": step.action,
                    "reason": reason,
                })
                attempt_succeeded = False
                break

        result.steps = step_results

        if attempt_succeeded:
            result.success = True
            result.summary = f"✅ Completed in {attempt} attempt(s): {current_plan.goal}"
            await _notify(result.summary)
            logger.info("[agent_runner] Task completed on attempt %d", attempt)
            return result

        if attempt < _MAX_ATTEMPTS:
            await _notify(f"♻️ Retrying with a different strategy…")
            await asyncio.sleep(2)

    result.summary = f"❌ Failed after {_MAX_ATTEMPTS} attempts: {task}"
    await _notify(result.summary)
    logger.error("[agent_runner] Task failed after all attempts: %s", task)
    return result
