#!/usr/bin/env python3
"""
Telegram channel post image composer.
Reads images from assets/raw_images/, composites with a dark template (left text + right image),
saves to assets/casino_images/ (used by the bot).

Usage:
  pip install Pillow
  python bot/scripts/image_maker.py   # from repo root
  # or from bot folder:
  python scripts/image_maker.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Resolve bot root (parent of scripts/)
SCRIPT_DIR = Path(__file__).resolve().parent
BOT_ROOT = SCRIPT_DIR.parent
RAW_DIR = BOT_ROOT / "assets" / "raw_images"
OUT_DIR = BOT_ROOT / "assets" / "casino_images"

# Output canvas size (square, Telegram-friendly)
CANVAS_W = 1080
CANVAS_H = 1080

# Dark background (deep navy)
BG_RGB = (18, 22, 42)

# Right panel: area for the source image (with margin)
RIGHT_MARGIN = 48
RIGHT_TOP = 48
RIGHT_BOTTOM = 48
RIGHT_LEFT = CANVAS_W // 2 + 24   # start a bit past half
IMG_MAX_W = CANVAS_W - RIGHT_LEFT - RIGHT_MARGIN
IMG_MAX_H = CANVAS_H - RIGHT_TOP - RIGHT_BOTTOM

# Left text block
LEFT_MARGIN = 56
LINE1 = "1wiN"           # large, bold
LINE2 = "viP casino"     # medium
LINE3 = "Referral code"  # small
LINE4 = "1W777W1"        # accent, large

TEXT_COLOR = (255, 255, 255)
ACCENT_COLOR = (255, 200, 80)  # gold


def _get_font(size: int, bold: bool = False):
    try:
        from PIL import ImageFont
    except ImportError:
        raise SystemExit("Pillow is required. Run: pip install Pillow")

    # Prefer a common system font
    candidates = []
    if sys.platform == "win32":
        candidates = [
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    for path in candidates:
        p = Path(path)
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def make_one(draw, font_large_bold, font_medium, font_small, font_accent, y_start: int) -> int:
    """Draw the four text lines; return next y position."""
    from PIL import ImageDraw

    y = y_start
    # 1wiN — large, bold
    draw.text((LEFT_MARGIN, y), LINE1, fill=TEXT_COLOR, font=font_large_bold)
    bbox = draw.textbbox((0, 0), LINE1, font=font_large_bold)
    y += bbox[3] - bbox[1] + 24

    # viP casino — medium
    draw.text((LEFT_MARGIN, y), LINE2, fill=TEXT_COLOR, font=font_medium)
    bbox = draw.textbbox((0, 0), LINE2, font=font_medium)
    y += bbox[3] - bbox[1] + 32

    # Referral code — small
    draw.text((LEFT_MARGIN, y), LINE3, fill=(200, 200, 200), font=font_small)
    bbox = draw.textbbox((0, 0), LINE3, font=font_small)
    y += bbox[3] - bbox[1] + 20

    # 1W777W1 — accent, large
    draw.text((LEFT_MARGIN, y), LINE4, fill=ACCENT_COLOR, font=font_accent)
    return y


def composite_image(raw_path: Path, out_path: Path) -> None:
    """Compose one template image from raw_path and save to out_path."""
    from PIL import Image, ImageDraw

    img = Image.open(raw_path).convert("RGB")
    # Scale to fit right panel while keeping aspect ratio
    r = min(IMG_MAX_W / img.width, IMG_MAX_H / img.height, 1.0)
    nw, nh = int(img.width * r), int(img.height * r)
    resample = getattr(Image, "Resampling", Image).LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    img = img.resize((nw, nh), resample)

    # Canvas: dark background
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), BG_RGB)

    # Paste image on the right, vertically centered
    x = RIGHT_LEFT + (IMG_MAX_W - nw) // 2
    y = RIGHT_TOP + (IMG_MAX_H - nh) // 2
    canvas.paste(img, (x, y))

    # Font sizes (approximate)
    font_large_bold = _get_font(72, bold=True)
    font_medium = _get_font(42, bold=False)
    font_small = _get_font(28, bold=False)
    font_accent = _get_font(56, bold=True)

    draw = ImageDraw.Draw(canvas)
    # Start text block a bit below top
    make_one(draw, font_large_bold, font_medium, font_small, font_accent, y_start=80)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=92)


def main() -> None:
    try:
        from PIL import Image
    except ImportError:
        print("Pillow is required. Run: pip install Pillow", file=sys.stderr)
        sys.exit(1)

    if not RAW_DIR.is_dir():
        print(f"Raw images folder not found: {RAW_DIR}", file=sys.stderr)
        print("Create it and add source images (e.g. .jpg, .png).", file=sys.stderr)
        sys.exit(1)

    allowed = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    raw_files = [f for f in RAW_DIR.iterdir() if f.suffix.lower() in allowed and f.is_file()]
    if not raw_files:
        print(f"No image files found in {RAW_DIR}", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for raw_path in sorted(raw_files):
        out_name = raw_path.stem + ".jpg"
        out_path = OUT_DIR / out_name
        try:
            composite_image(raw_path, out_path)
            print(f"OK: {raw_path.name} -> {out_path}")
        except Exception as e:
            print(f"SKIP {raw_path.name}: {e}", file=sys.stderr)

    print(f"Done. Output folder: {OUT_DIR}")


if __name__ == "__main__":
    main()
