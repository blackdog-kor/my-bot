import os
import sys
import json
import re
import base64
from datetime import datetime

import requests
from openai import OpenAI

from _repo_context import resolve_github_repository

GITHUB_TOKEN = os.environ.get("GH_AUTOMATION_TOKEN")

REPO = resolve_github_repository(default="blackdog-kor/casino-system")

if not GITHUB_TOKEN:
    raise Exception("GH_AUTOMATION_TOKEN not set")


if len(sys.argv) < 2:
    raise Exception("Usage: python scripts/ai_direct_pr.py \"<command>\"")

command = sys.argv[1]

print("Command received:", command)

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

prompt = f"""
You are an AI developer working on a FastAPI project.

Command:
{command}

Return JSON with this format:

{{
  "title": "PR title",
  "files": [
    {{
      "path": "file path",
      "content": "full file content"
    }}
  ]
}}
"""

print("Asking OpenAI to generate implementation plan...")

resp = client.responses.create(
    model="gpt-4.1-mini",
    input=prompt
)

text = resp.output_text

data = json.loads(text)

title = data["title"]
files = data["files"]

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "task"

branch_base = slugify(command)
branch_suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S")
branch_name = f"ai2/{branch_base}-{branch_suffix}"

print("Branch:", branch_name)
print("PR title:", title)
print("Files to create/update:", [f["path"] for f in files])

headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}

def gh_get(url):
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    return r.json()

def gh_post(url, payload):
    r = requests.post(url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()

def gh_put(url, payload):
    r = requests.put(url, headers=headers, json=payload)
    r.raise_for_status()
    return r.json()

base_branch = "main"

ref = gh_get(f"https://api.github.com/repos/{REPO}/git/ref/heads/{base_branch}")
base_sha = ref["object"]["sha"]

print("Base branch SHA:", base_sha)

print("Creating branch", branch_name)

gh_post(
    f"https://api.github.com/repos/{REPO}/git/refs",
    {
        "ref": f"refs/heads/{branch_name}",
        "sha": base_sha
    }
)

for f in files:
    path = f["path"]
    content = f["content"]

    print("Committing", path)

    encoded = base64.b64encode(content.encode()).decode()

    try:
        existing = gh_get(f"https://api.github.com/repos/{REPO}/contents/{path}")
        sha = existing["sha"]
    except:
        sha = None

    payload = {
        "message": f"AI update {path}",
        "content": encoded,
        "branch": branch_name
    }

    if sha:
        payload["sha"] = sha

    gh_put(
        f"https://api.github.com/repos/{REPO}/contents/{path}",
        payload
    )

print("Opening pull request...")

pr = gh_post(
    f"https://api.github.com/repos/{REPO}/pulls",
    {
        "title": title,
        "head": branch_name,
        "base": base_branch,
        "body": f"AI generated implementation for command:\n\n{command}"
    }
)

print("Pull request created:", pr["html_url"])
