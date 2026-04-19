#!/usr/bin/env python3
"""
Strategy debate: Claude proposal → GPT-4o critique → synthesis prompt.

Usage:
    echo "Claude's strategy here" | python3 scripts/strategy_debate.py
    python3 scripts/strategy_debate.py "strategy text"
"""
import sys
import os
import json
import urllib.request
import urllib.error


SYSTEM_PROMPT = """You are a critical strategy reviewer for a Telegram bot automation project.

Your role:
1. Find REAL flaws in the proposed strategy (not nitpicks)
2. Identify assumptions that could be wrong
3. Suggest concrete alternatives where the strategy is weak
4. Rate each concern: HIGH / MEDIUM / LOW impact

Project context:
- Casino affiliate Telegram bot
- Auto DM campaign: group discovery → member scrape → DM send → click tracking
- Stack: Python, FastAPI, Pyrogram, Telethon, PostgreSQL, Railway
- Single developer, production system

Be direct and specific. If the strategy is solid, say so clearly.
Format your response as:

## Flaws & Risks
[list with impact ratings]

## Assumptions to Verify
[list]

## Recommended Adjustments
[concrete changes]

## Verdict
APPROVE / REVISE / REJECT — one sentence why."""


def get_api_key() -> str:
    config_path = os.path.expanduser("~/.codex/config.toml")
    try:
        with open(config_path) as f:
            for line in f:
                if line.startswith("api_key"):
                    return line.split("=", 1)[1].strip().strip('"')
    except FileNotFoundError:
        pass
    return os.environ.get("OPENAI_API_KEY", "")


def critique(proposal: str) -> str:
    api_key = get_api_key()
    if not api_key:
        return "ERROR: OPENAI_API_KEY not configured"

    payload = json.dumps({
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Review this strategy:\n\n{proposal}"}
        ],
        "max_tokens": 1500,
        "temperature": 0.7,
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.load(resp)
            choices = data.get("choices", [])
            if not choices:
                return "ERROR: empty response from GPT-4o"
            return choices[0].get("message", {}).get("content", "ERROR: no content")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return f"ERROR: {body}"


def main():
    if len(sys.argv) > 1:
        proposal = " ".join(sys.argv[1:])
    else:
        proposal = sys.stdin.read()

    if not proposal.strip():
        print("Usage: echo 'strategy' | python3 strategy_debate.py")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("   GPT-4o Strategy Review")
    print("=" * 60 + "\n")

    result = critique(proposal)
    print(result)
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
