# Image maker (Telegram post template)

Composites images from `assets/raw_images/` with a dark template and saves to `assets/casino_images/` (used by the channel post bot).

## Setup

```bash
pip install Pillow
```

## Run

From **repo root** (`c:\my bot`):

```bash
python bot/scripts/image_maker.py
```

From **bot folder** (`c:\my bot\bot`):

```bash
python scripts/image_maker.py
```

## Folders

- **Input:** `bot/assets/raw_images/` — put source images here (`.jpg`, `.png`, `.webp`, etc.).
- **Output:** `bot/assets/casino_images/` — composited images (JPEG); the bot picks randomly from here for channel posts.

## Template

- Dark navy background; source image scaled on the right with margin.
- Left side: **1wiN** (large bold), **viP casino** (medium), **Referral code** (small), **1W777W1** (accent color, large).
