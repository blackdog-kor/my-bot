"""
Notion Sync: auto-update DevLog pages on job completion and git commits.

Pages:
  MAIN       Casino Bot DevLog   35b63e43-49a8-81e3-ae8b-d6940558c4cf
  STATUS     시스템 현황          35b63e43-49a8-81f8-92eb-f7c044f5ff87
  DEVLOG     개발 일지            35b63e43-49a8-81a4-8273-e0b56f1c5c14
  TODO       TODO                35b63e43-49a8-81e3-b7c3-e810e636b7d7
  SCHEDULE   스케줄 현황          35b63e43-49a8-81f3-8fbe-f2119821ca2b
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# ── Page IDs ─────────────────────────────────────────────────────────────────

PAGE_STATUS   = "35b63e43-49a8-81f8-92eb-f7c044f5ff87"
PAGE_DEVLOG   = "35b63e43-49a8-81a4-8273-e0b56f1c5c14"
PAGE_TODO     = "35b63e43-49a8-81e3-b7c3-e810e636b7d7"
PAGE_SCHEDULE = "35b63e43-49a8-81f3-8fbe-f2119821ca2b"


def _token() -> str:
    return os.getenv("NOTION_TOKEN", "")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _api(method: str, path: str, body: dict | None = None) -> dict:
    """Call Notion API. Returns response dict (may contain 'object':'error')."""
    url = f"https://api.notion.com/v1{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())
    except Exception as e:
        return {"object": "error", "message": str(e)}


# ── Block helpers ─────────────────────────────────────────────────────────────

def _h2(text: str) -> dict:
    return {"object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"text": {"content": text}}]}}


def _p(text: str, bold: bool = False) -> dict:
    rt: dict = {"text": {"content": text}}
    if bold:
        rt["annotations"] = {"bold": True}
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [rt]}}


def _bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"text": {"content": text}}]}}


def _divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def _callout(text: str, emoji: str = "📌", color: str = "yellow_background") -> dict:
    return {"object": "block", "type": "callout",
            "callout": {"rich_text": [{"text": {"content": text}}],
                        "icon": {"emoji": emoji}, "color": color}}


def _append(page_id: str, blocks: list[dict]) -> bool:
    """Append blocks to an existing page. Returns True on success."""
    if not _token():
        return False
    result = _api("PATCH", f"/blocks/{page_id}/children", {"children": blocks})
    return result.get("object") != "error"


def _now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")


# ── Public API ────────────────────────────────────────────────────────────────

def log_job_result(job_name: str, success: bool, detail: str = "") -> bool:
    """Append a job result entry to 스케줄 현황 page.

    Called from scheduler.py after each job completes.
    """
    if not _token():
        return False
    icon = "✅" if success else "❌"
    status = "성공" if success else "실패"
    text = f"{icon} [{_now_kst()}] {job_name} — {status}"
    if detail:
        text += f" | {detail[:120]}"
    return _append(PAGE_SCHEDULE, [_bullet(text)])


def log_devlog_entry(title: str, done: list[str], issues: list[str],
                     next_steps: list[str]) -> bool:
    """Append a dev session entry to 개발 일지 page.

    Called from git post-commit hook.
    """
    if not _token():
        return False
    blocks: list[dict] = [
        _divider(),
        _h2(f"{_now_kst()} | {title}"),
    ]
    if done:
        blocks.append(_p("✅ 완료", bold=True))
        blocks.extend(_bullet(d) for d in done)
    if issues:
        blocks.append(_p("❌ 이슈", bold=True))
        blocks.extend(_bullet(i) for i in issues)
    if next_steps:
        blocks.append(_p("➡ 다음 할 일", bold=True))
        blocks.extend(_bullet(n) for n in next_steps)
    return _append(PAGE_DEVLOG, blocks)


def update_system_status(status_lines: list[str]) -> bool:
    """Append a timestamped status snapshot to 시스템 현황 page."""
    if not _token():
        return False
    blocks: list[dict] = [
        _divider(),
        _callout(f"자동 업데이트: {_now_kst()}", "🔄", "gray_background"),
    ]
    blocks.extend(_bullet(line) for line in status_lines)
    return _append(PAGE_STATUS, blocks)


def ping() -> bool:
    """Return True if Notion API is reachable with current token."""
    if not _token():
        return False
    r = _api("GET", "/users/me")
    return r.get("object") == "user"


if __name__ == "__main__":
    print("Notion ping:", ping())
    ok = log_job_result("테스트", True, "notion_sync.py 직접 실행")
    print("log_job_result:", ok)
