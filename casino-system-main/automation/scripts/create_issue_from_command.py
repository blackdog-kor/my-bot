import os
import sys
import requests
from openai import OpenAI

if len(sys.argv) < 2:
    raise Exception('Usage: python scripts/create_issue_from_command.py "<command>"')

command = sys.argv[1]

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

prompt = f"""
Convert this instruction into a GitHub development task.

Instruction:
{command}

Output format:
Title:
Body:
"""

resp = client.responses.create(
    model="gpt-4.1-mini",
    input=prompt
)

text = resp.output_text

if "Body:" in text:
    title = text.split("Body:")[0].replace("Title:", "").strip()
    body = text.split("Body:")[1].strip()
else:
    lines = [l for l in text.replace("Title:", "").strip().splitlines() if l.strip()]
    title = lines[0] if lines else command
    body = command

repo = os.environ.get("GITHUB_REPOSITORY")
if not repo:
    raise Exception("GITHUB_REPOSITORY environment variable is not set")

token = os.environ["GH_TOKEN"]

url = f"https://api.github.com/repos/{repo}/issues"

headers = {
    "Authorization": f"token {token}",
    "Accept": "application/vnd.github+json"
}

payload = {
    "title": title[:250],
    "body": body[:5000],
}

r = requests.post(url, json=payload, headers=headers)

print("Issue created:", r.status_code)
print(r.text)

if r.status_code == 201:
    issue_number = r.json().get("number")
    if issue_number:
        comment_url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
        comment_payload = {
            "body": "@copilot Please implement this issue and open a pull request."
        }

        try:
            rc = requests.post(comment_url, json=comment_payload, headers=headers)
            print("Copilot comment posted:", rc.status_code)
        except Exception as e:
            print("Failed to post Copilot comment:", e)

else:
    print("Issue creation failed, skipping Copilot comment.")
