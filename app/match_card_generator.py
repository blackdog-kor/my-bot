"""
Match Card Generator: create premium visual match cards using Pillow.

Produces 1200x630px cards with:
- League-colored gradient background
- Home vs Away team names
- Real odds (1X2, Over/Under)
- Pick recommendation with confidence stars
- Branding footer

Korean font (NanumGothic) is downloaded once and cached in /tmp/.
Falls back to ASCII-only if download fails.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING

from app.logging_config import get_logger

if TYPE_CHECKING:
    from app.odds_fetcher import MatchOdds

logger = get_logger("match_card_generator")

# Card dimensions
W, H = 1200, 630

# League accent colors (RGB)
LEAGUE_COLORS: dict[int, tuple[int, int, int]] = {
    39:  (56, 0, 252),    # Premier League — purple-blue
    140: (207, 19, 47),   # La Liga — red
    135: (0, 102, 178),   # Serie A — blue
    61:  (0, 80, 160),    # Ligue 1 — blue
    78:  (220, 0, 0),     # Bundesliga — red
    2:   (255, 184, 0),   # Champions League — gold
    3:   (255, 102, 0),   # Europa League — orange
    292: (0, 164, 102),   # K League — green
}
_DEFAULT_ACCENT = (30, 90, 200)

# Background palette
_BG_DARK = (14, 17, 35)
_BG_MID  = (22, 28, 55)
_TEXT_WHITE = (255, 255, 255)
_TEXT_LIGHT = (200, 210, 230)
_TEXT_GOLD  = (255, 215, 0)
_CARD_GRAY  = (35, 42, 72)

_FONT_CACHE: Path = Path("/tmp/nanum_gothic.ttf")
_FONT_URL = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
_FONT_BOLD_URL = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothicBold.ttf"
_FONT_BOLD_CACHE: Path = Path("/tmp/nanum_gothic_bold.ttf")


def _ensure_font() -> bool:
    """Download NanumGothic font if not cached. Returns True on success."""
    if _FONT_CACHE.exists() and _FONT_BOLD_CACHE.exists():
        return True
    try:
        import httpx
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            for url, path in [(_FONT_URL, _FONT_CACHE), (_FONT_BOLD_URL, _FONT_BOLD_CACHE)]:
                if not path.exists():
                    resp = client.get(url)
                    if resp.status_code == 200:
                        path.write_bytes(resp.content)
                        logger.info("Font downloaded: %s", path.name)
                    else:
                        logger.warning("Font download failed: HTTP %d", resp.status_code)
                        return False
        return True
    except Exception as e:
        logger.warning("Font download error: %s", e)
        return False


def _get_fonts(has_korean: bool) -> dict[str, Any]:
    """Return font objects keyed by role."""
    from PIL import ImageFont

    def load(path: Path, size: int):
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            return ImageFont.load_default()

    if has_korean:
        return {
            "title": load(_FONT_BOLD_CACHE, 52),
            "team":  load(_FONT_BOLD_CACHE, 54),
            "odds":  load(_FONT_CACHE, 34),
            "pick":  load(_FONT_BOLD_CACHE, 42),
            "sub":   load(_FONT_CACHE, 28),
            "brand": load(_FONT_CACHE, 26),
        }
    from PIL import ImageFont
    def_font = ImageFont.load_default()
    return {k: def_font for k in ("title", "team", "odds", "pick", "sub", "brand")}


def _draw_gradient(img, color_top, color_bot):
    from PIL import Image
    for y in range(H):
        t = y / H
        r = int(color_top[0] * (1 - t) + color_bot[0] * t)
        g = int(color_top[1] * (1 - t) + color_bot[1] * t)
        b = int(color_top[2] * (1 - t) + color_bot[2] * t)
        img.paste(Image.new("RGB", (W, 1), (r, g, b)), (0, y))


def generate_match_card(
    home_team: str,
    away_team: str,
    league_name: str,
    league_id: int,
    match_date_str: str,
    pick: str,
    stars: int,
    confidence_pct: int,
    odds: "MatchOdds | None" = None,
    monthly_accuracy: str = "",
) -> bytes | None:
    """Generate a 1200x630 match card PNG. Returns raw bytes or None on failure."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.error("Pillow not installed — skipping card generation")
        return None

    has_korean = _ensure_font()
    fonts = _get_fonts(has_korean)
    accent = LEAGUE_COLORS.get(league_id, _DEFAULT_ACCENT)

    # ── Background ────────────────────────────────────────────────
    img = Image.new("RGB", (W, H), _BG_DARK)
    _draw_gradient(img, _BG_DARK, _BG_MID)
    draw = ImageDraw.Draw(img)

    # Accent top bar
    draw.rectangle([(0, 0), (W, 8)], fill=accent)

    # Subtle accent side stripe
    draw.rectangle([(0, 0), (6, H)], fill=accent)

    # ── League header ─────────────────────────────────────────────
    draw.text((40, 30), f"  {league_name.upper()}", font=fonts["title"], fill=accent)
    draw.text((W - 40, 30), match_date_str, font=fonts["sub"], fill=_TEXT_LIGHT, anchor="ra")

    # ── VS divider line ───────────────────────────────────────────
    mid_y = 270
    draw.line([(40, mid_y), (W - 40, mid_y)], fill=(*accent, 80), width=1)

    # ── Team names ────────────────────────────────────────────────
    home_short = home_team[:18]
    away_short = away_team[:18]
    draw.text((W // 4, mid_y - 60), home_short, font=fonts["team"], fill=_TEXT_WHITE, anchor="mm")
    draw.text((W // 2, mid_y - 20), "VS", font=fonts["odds"], fill=(*accent,), anchor="mm")
    draw.text((3 * W // 4, mid_y - 60), away_short, font=fonts["team"], fill=_TEXT_WHITE, anchor="mm")

    # ── Odds table ────────────────────────────────────────────────
    odds_y = mid_y + 30
    if odds and odds.has_odds:
        h2h = f"홈승 {odds.home_win:.2f}   무 {odds.draw:.2f}   원정 {odds.away_win:.2f}" if has_korean else f"Home {odds.home_win:.2f}  Draw {odds.draw:.2f}  Away {odds.away_win:.2f}"
        draw.text((W // 2, odds_y), h2h, font=fonts["odds"], fill=_TEXT_LIGHT, anchor="mm")

        if odds.over_2_5:
            ou = f"오버2.5  {odds.over_2_5:.2f}   │   언더2.5  {odds.under_2_5:.2f}" if has_korean else f"O2.5  {odds.over_2_5:.2f}   |   U2.5  {odds.under_2_5:.2f}"
            draw.text((W // 2, odds_y + 48), ou, font=fonts["sub"], fill=_TEXT_LIGHT, anchor="mm")
            odds_y += 48
    else:
        draw.text((W // 2, odds_y), "배당 정보 로딩 중..." if has_korean else "Odds loading...", font=fonts["sub"], fill=_TEXT_LIGHT, anchor="mm")

    # ── Pick recommendation ───────────────────────────────────────
    pick_y = odds_y + 70
    draw.rectangle([(80, pick_y - 10), (W - 80, pick_y + 60)], fill=_CARD_GRAY, outline=accent, width=2)
    stars_str = "⭐" * stars if has_korean else "*" * stars
    pick_label = f"🎯  픽: {pick}   {stars_str}  신뢰도 {confidence_pct}%" if has_korean else f"PICK: {pick}  {stars_str}  {confidence_pct}% confidence"
    draw.text((W // 2, pick_y + 25), pick_label, font=fonts["pick"], fill=_TEXT_GOLD, anchor="mm")

    # ── Footer ────────────────────────────────────────────────────
    footer_y = H - 45
    draw.rectangle([(0, footer_y - 8), (W, H)], fill=(8, 10, 22))
    brand = f"📊 이번 달 적중률 {monthly_accuracy}" if (monthly_accuracy and has_korean) else ""
    if brand:
        draw.text((40, footer_y + 10), brand, font=fonts["brand"], fill=_TEXT_LIGHT)
    draw.text((W - 40, footer_y + 10), "@blackdog_eve_casino_bot", font=fonts["brand"], fill=accent, anchor="ra")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    logger.info("Match card generated: %dx%d PNG, %d bytes", W, H, len(buf.getvalue()))
    return buf.getvalue()
