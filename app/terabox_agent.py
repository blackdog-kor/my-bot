"""
TeraBox Content Agent: cookie-based API, no browser required on Railway.

SETUP: Log into terabox.com → DevTools → Application → Cookies
  Google login:  TERABOX_COOKIES="ndus=xxx;csrfToken=yyy;browserid=zzz"
  Baidu login:   TERABOX_COOKIES="BDUSS=xxx;BAIDUID=yyy"
"""
from __future__ import annotations

import asyncio
import io
import random
from dataclasses import dataclass, field

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("terabox_agent")

_BASE = "https://www.terabox.com"
TERABOX_DOMAINS = ["terabox.com", "teraboxapp.com", "1024terabox.com", "terabox.fun"]
_VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
_IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_CASINO_KW = ["casino", "카지노", "1win", "slot", "슬롯", "jackpot", "gambling", "베팅"]
MAX_ITEMS_PER_RUN = 10; ITEM_DELAY_MIN, ITEM_DELAY_MAX = 3.0, 8.0
_APP_ID = "250528"  # TeraBox web app ID (public constant used in all API calls)
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"


@dataclass
class TeraBoxItem:
    share_url: str
    title: str = ""
    file_name: str = ""
    file_size: str = ""
    media_type: str = "video"
    download_url: str = ""
    thumbnail_url: str = ""
    raw_agent_output: str = ""


@dataclass
class TeraBoxRunResult:
    items: list[TeraBoxItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_processed: int = 0
    success_count: int = 0


def is_terabox_url(url: str) -> bool:
    return any(d in url.lower() for d in TERABOX_DOMAINS)

def is_share_url(url: str) -> bool:
    """True only for /s/ share links — not AI workspace/index pages."""
    return "/s/" in url or "/sharing/" in url

def get_share_urls() -> list[str]:
    raw = settings.terabox_share_urls.strip()
    if not raw: return []
    urls = [u.strip() for u in raw.split(",") if u.strip()]
    valid = [u for u in urls if is_terabox_url(u) and is_share_url(u)]
    if len(urls) > len(valid):
        logger.warning("Skipped %d non-share TeraBox URL(s) (index/AI pages unsupported)", len(urls) - len(valid))
    return valid

def _cookies(s: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in s.split(";"):
        if "=" in p:
            k, _, v = p.strip().partition("=")
            out[k.strip()] = v.strip()
    return out

def _classify(name: str) -> str:
    lo = name.lower()
    if any(lo.endswith(e) for e in _VIDEO_EXT): return "video"
    if any(lo.endswith(e) for e in _IMG_EXT): return "photo"
    return "document"

def _sz(b: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024: return f"{b:.1f} {u}"
        b /= 1024  # type: ignore[assignment]
    return f"{b:.1f} TB"

async def _tb_get(path: str, params: dict, ck: dict) -> dict:
    from curl_cffi.requests import AsyncSession
    async with AsyncSession(impersonate="chrome124") as s:
        r = await s.get(f"{_BASE}{path}", params=params,
            headers={"User-Agent": _UA, "Referer": f"{_BASE}/main", "Accept": "application/json"},
            cookies=ck)
        return r.json()

async def _api_list(ck: dict, path: str = "/") -> list[dict]:
    data = await _tb_get("/api/list", {"app_id": _APP_ID, "web": "1", "path": path, "order": "time", "num": "100"}, ck)
    if data.get("errno", -1) != 0:
        logger.warning("TeraBox /api/list errno=%s", data.get("errno"))
        return []
    return data.get("list", [])

async def _dlink(fsid: str, ck: dict) -> str:
    data = await _tb_get("/api/filemetas", {"app_id": _APP_ID, "web": "1", "dlink": "1", "fsids": f"[{fsid}]"}, ck)
    if data.get("errno", -1) != 0: return ""
    lst = data.get("list", [])
    return lst[0].get("dlink", "") if lst else ""


def _item(f: dict, fsid: str = "", dl: str = "") -> TeraBoxItem:
    name = f.get("server_filename", "")
    return TeraBoxItem(
        share_url=f"{_BASE}/main?id={fsid}" if fsid else _BASE,
        title=name, file_name=name, file_size=_sz(f.get("size", 0)),
        media_type=_classify(name), download_url=dl,
        thumbnail_url=f.get("thumbs", {}).get("url3", ""),
    )


async def extract_terabox_info(share_url: str) -> TeraBoxItem | None:
    """Get info for a single TeraBox share link (requires TERABOX_COOKIES)."""
    if not is_share_url(share_url):
        logger.warning("Not a share URL — AI/index pages unsupported: %s", share_url[:80])
        return None
    ck_str = settings.terabox_cookies.strip()
    if not ck_str:
        logger.error("TERABOX_COOKIES not set")
        return None
    ck = _cookies(ck_str)
    try:
        files = await _api_list(ck)
        if not files: return None
        f = files[0]
        fsid = str(f.get("fs_id", ""))
        return _item(f, fsid, await _dlink(fsid, ck) if fsid else "")
    except Exception as e:
        logger.exception("extract_terabox_info [%s]: %s", share_url, e)
        return None


async def collect_terabox_content() -> TeraBoxRunResult:
    """Collect casino videos from authenticated TeraBox storage.

    Requires TERABOX_COOKIES with 'ndus' (Google login) or 'BDUSS' (Baidu login).
    """
    result = TeraBoxRunResult()
    ck_str = settings.terabox_cookies.strip()
    if not ck_str:
        logger.warning("TERABOX_COOKIES not set — Google login: 'ndus=xxx', Baidu login: 'BDUSS=xxx'")
        return result
    ck = _cookies(ck_str)
    if "ndus" not in ck and "BDUSS" not in ck:
        logger.error("TERABOX_COOKIES must include 'ndus' (Google login) or 'BDUSS' (Baidu login)")
        result.errors.append("ndus/BDUSS missing from TERABOX_COOKIES")
        return result
    try:
        files = await _api_list(ck)
    except Exception as e:
        logger.exception("TeraBox list failed: %s", e)
        result.errors.append(str(e))
        return result

    videos = [f for f in files if _classify(f.get("server_filename", "")) == "video"]
    casino = [f for f in videos if any(kw in f.get("server_filename", "").lower() for kw in _CASINO_KW)]
    targets = casino or videos

    for f in targets[:MAX_ITEMS_PER_RUN]:
        name = f.get("server_filename", "")
        fsid = str(f.get("fs_id", ""))
        result.total_processed += 1
        try:
            dl = await _dlink(fsid, ck) if fsid else ""
            result.items.append(_item(f, fsid, dl))
            if dl: result.success_count += 1
        except Exception as e:
            logger.warning("Skip %s: %s", name, e)
            result.errors.append(f"{name}: {e}")
        if result.total_processed < len(targets):
            await asyncio.sleep(random.uniform(ITEM_DELAY_MIN, ITEM_DELAY_MAX))

    logger.info("TeraBox: %d items, %d with download URLs", len(result.items), result.success_count)
    return result


async def download_terabox_file(download_url: str, *, cookies: str = "") -> io.BytesIO | None:
    """Download TeraBox file to BytesIO using a direct download URL."""
    if not download_url or download_url == "not_available":
        return None
    try:
        from curl_cffi.requests import AsyncSession
        ck = _cookies(cookies or settings.terabox_cookies)
        async with AsyncSession(impersonate="chrome124") as s:
            resp = await s.get(
                download_url, timeout=120,
                headers={"User-Agent": _UA}, cookies=ck,
            )
            resp.raise_for_status()
            bio = io.BytesIO(resp.content)
            bio.seek(0)
            logger.info("TeraBox download: %d bytes", len(resp.content))
            return bio
    except Exception as e:
        logger.exception("TeraBox download failed: %s", e)
        return None
