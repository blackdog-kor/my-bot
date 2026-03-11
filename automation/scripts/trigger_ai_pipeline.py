import os
import sys
import requests

from _repo_context import resolve_github_repository


repo = resolve_github_repository(default="blackdog-kor/casino-system")
workflow = "ai-control.yml"

token = os.getenv("GH_AUTOMATION_TOKEN")

if not token:
    raise Exception("GH_AUTOMATION_TOKEN not set")

if len(sys.argv) < 2:
    raise Exception("Provide command string")

command = sys.argv[1]

url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"

headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json"
}

payload = {
    "ref": "main",
    "inputs": {
        "command": command
    }
}

r = requests.post(url, json=payload, headers=headers)

print("Status:", r.status_code)
print(r.text)
