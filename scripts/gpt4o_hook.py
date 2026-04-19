#!/usr/bin/env python3
"""
PostToolUse hook: GPT-4o 2nd-pass review with asyncRewake.

Flow:
  1. Claude edits a .py file
  2. This hook runs GPT-4o review automatically
  3. If issues found → exit(2) wakes Claude with feedback (3rd pass)
  4. If clean → exit(0), pipeline continues

Claude is woken up only once for final review — GPT-4o does not re-run.
"""
import sys
import os
import json
import subprocess

WATCHED_DIRS = [
    "/workspaces/my-bot/app/",
    "/workspaces/my-bot/scripts/",
]

REVIEW_SCRIPT = os.path.join(os.path.dirname(__file__), "gpt4o_review.py")

ISSUE_KEYWORDS = [
    "bug", "issue", "error", "security", "vulnerability",
    "anti-pattern", "blocked", "missing", "incorrect", "fail",
    "버그", "오류", "보안", "문제", "누락", "실패",
]


def should_review(file_path: str) -> bool:
    if not file_path.endswith(".py"):
        return False
    return any(file_path.startswith(d) for d in WATCHED_DIRS)


def read_file(file_path: str) -> str | None:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def run_review(file_path: str, content: str) -> str:
    prompt = (
        f"Review this Python file for the Telegram bot project: {file_path}\n\n"
        f"```python\n{content}\n```\n\n"
        "Report ONLY actual bugs, security issues, or critical anti-patterns. "
        "If the code looks good, respond with exactly: LGTM\n"
        "Be concise and actionable."
    )
    try:
        result = subprocess.run(
            [sys.executable, REVIEW_SCRIPT],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=40,
        )
    except subprocess.TimeoutExpired:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def has_issues(review: str) -> bool:
    if not review:
        return False
    if review.strip().upper().startswith("LGTM"):
        return False
    lower = review.lower()
    return any(kw in lower for kw in ISSUE_KEYWORDS)


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        hook_data = json.loads(raw)
        file_path = hook_data.get("tool_input", {}).get("file_path", "")

        if not file_path or not should_review(file_path):
            sys.exit(0)

        content = read_file(file_path)
        if content is None:
            sys.exit(0)

        review = run_review(file_path, content)

        if has_issues(review):
            # exit(2) wakes Claude with the feedback for final review
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": (
                        f"[GPT-4o Review — {os.path.basename(file_path)}]\n"
                        f"{review}\n\n"
                        "위 피드백을 검토하고 반영이 필요한 항목을 적용하거나 "
                        "문제없으면 그대로 진행하세요."
                    ),
                }
            }
            print(json.dumps(output))
            sys.exit(2)

        # Clean — no wake needed
        sys.exit(0)

    except Exception:
        sys.exit(0)


if __name__ == "__main__":
    main()
