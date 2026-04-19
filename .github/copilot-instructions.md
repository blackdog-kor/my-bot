# Copilot Instructions — my-bot Project

This document provides project-specific instructions for GitHub Copilot
when working on this repository. It mirrors the rules in CLAUDE.md to ensure
both AI agents (Claude Code and Copilot) operate under identical constraints.

---

## Project Overview

Casino affiliate automation pipeline:
Target Group Discovery → Member Scraping → DM Sending (with Jitter) → Channel Intake → Bot Signup

- **Repository:** blackdog-kor/my-bot
- **Infrastructure:** Railway (single-service deploy)
- **Runtime:** Python 3.11
- **Web Server:** FastAPI + uvicorn
- **Bot Frameworks:**
  - `python-telegram-bot` (subscription/admin bot API)
  - `Pyrogram 2.0.106` (DM automation)
  - `Telethon` (member scraping)
- **Database:** Railway PostgreSQL
- **Scheduler:** APScheduler (`BackgroundScheduler`)

---

## Critical Rules (MUST FOLLOW)

### File Paths — Active Directory Map

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI entry point, thread startup |
| `app/userbot_sender.py` | Pyrogram DM send logic (MAIN FILE) |
| `app/pg_broadcast.py` | PostgreSQL CRUD |
| `app/scheduler.py` | APScheduler job definitions |
| `bot/subscribe_bot.py` | Subscription bot logic |
| `scripts/` | Local session generation & batch scripts |

### Absolute Prohibitions

1. **NEVER modify `bot/app/userbot_sender.py`** — it is deprecated. Always use `app/userbot_sender.py`.
2. **NEVER reintroduce Saved Messages upload pattern** — use BytesIO + caching only.
3. **NEVER assume account validity** without `get_me()` after `client.start()`.
4. **NEVER use `logger.warning` alone for errors** — use `logger.exception()` + admin DM notification.
5. **NEVER omit `client.stop()`** in `finally` blocks.

### Code Standards

- **Type hints required** on all new functions and classes.
- **Async safety:** No deadlocks between scheduler and bot loops.
- **Ruff compatible:** Write clean, standard Python.
- **Anti-detection:** Always apply Jitter + Exponential Backoff for Telegram API calls.
- **Structured logging:** Include context (User ID, Session ID, File ID) in exception handling.

### Pyrogram BytesIO Send Pattern (Reference)

```python
bio = io.BytesIO(file_bytes)
bio.seek(0)
bio.name = "media.mp4"  # Extension required
sent = await client.send_video(target, bio, duration=0, width=0, height=0)
```

### file_id Caching

- `msg.video.file_id` — Pyrogram (single object)
- `msg.photo[-1].file_id` — python-telegram-bot (list)
- Do NOT confuse these two patterns.

---

## Database Schema

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `broadcast_targets` | Target user management | `telegram_user_id`(PK), `username`, `is_sent`, `clicked_at` |
| `campaign_posts` | Media cache & rotation | `id`(PK), `file_id`, `file_type`, `caption`, `last_sent_at` |
| `campaign_config` | System settings | `id=1`(single row), `affiliate_url`, `subscribe_bot_link` |

---

## Environment Variables

Required: `BOT_TOKEN`, `SUBSCRIBE_BOT_TOKEN`, `API_ID`, `API_HASH`,
`SESSION_STRING_1~10`, `SESSION_STRING_TELETHON`, `BRIGHTDATA_API_TOKEN`,
`DATABASE_URL`, `ADMIN_ID`

Optional: `CHANNEL_ID`, `AFFILIATE_URL`, `VIP_URL`, `TRACKING_SERVER_URL`,
`GEMINI_API_KEY`, `USER_DELAY_MIN/MAX`, `LONG_BREAK_EVERY`,
`LONG_BREAK_MIN/MAX`, `BATCH_SIZE`, `DAILY_LIMIT_PER_ACCOUNT`

---

## Workflow Rules

- **Branch strategy:** Work in feature branches, create PRs to `main`.
- **Never push directly to `main`** from Copilot agent — always via PR.
- **Testing sequence:** syntax check → `/debug/session-test` → `/debug/dm-test`
- **Prefer proven open-source packages** over custom implementations.
- **Design for resilience** — exponential backoff, jitter, cooldowns.

---

## Collaboration Protocol (Dual-Agent)

This project uses both Claude Code and GitHub Copilot as development agents.
To prevent conflicts:

1. **Copilot works via PRs** — never direct push to main.
2. **Claude Code may push directly to main** — its changes are authoritative.
3. **Both agents read CLAUDE.md** as the source of truth for project rules.
4. **File ownership:** No exclusive locks — both agents can modify any file.
5. **Conflict resolution:** If a PR has conflicts, rebase onto latest main.
