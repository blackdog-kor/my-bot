#!/usr/bin/env python3
import sys
import os
import json
import urllib.request
import urllib.error

api_key = ""
config_path = os.path.expanduser("~/.codex/config.toml")
try:
    with open(config_path) as f:
        for line in f:
            if line.startswith("api_key"):
                api_key = line.split("=", 1)[1].strip().strip('"')
                break
except FileNotFoundError:
    pass
if not api_key:
    api_key = os.environ.get("OPENAI_API_KEY", "")

if not api_key:
    print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
    sys.exit(1)

prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read()
if not prompt.strip():
    prompt = sys.stdin.read()

payload = json.dumps({
    "model": "gpt-4o",
    "messages": [
        {"role": "system", "content": "You are a senior code reviewer. Review code concisely and identify bugs, security issues, and anti-patterns."},
        {"role": "user", "content": prompt}
    ],
    "max_tokens": 2000
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
        print(data["choices"][0]["message"]["content"])
except urllib.error.HTTPError as e:
    body = json.load(e)
    print(f"ERROR: {body.get('error', {}).get('message', str(e))}", file=sys.stderr)
    sys.exit(1)
