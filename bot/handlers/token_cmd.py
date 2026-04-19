"""
Telegram commands for managing site tokens from the admin's phone.

Commands (admin only):
  /settoken <site> <token>   — store an accessToken directly into vault
  /tokeninfo [site]          — show vault status for all or specific site
  /refreshtoken <site>       — force-refresh a site's token now

These let the admin inject tokens captured from browser DevTools
without needing shell access.
"""
import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")


def _is_admin(update: Update) -> bool:
    return bool(ADMIN_ID and update.effective_user and update.effective_user.id == ADMIN_ID)


async def cmd_settoken(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /settoken <site> <accessToken> [refreshToken]

    Stores token(s) directly into the vault DB.
    Example: /settoken 1win-partners eyJhbGci...
    """
    if not _is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /settoken <site> <accessToken> [refreshToken]\n"
            "Example: /settoken 1win-partners eyJhbGci..."
        )
        return

    site = args[0]
    access_token = args[1]
    refresh_token = args[2] if len(args) > 2 else None

    try:
        from app.token_vault import _save
        tokens = {"accessToken": access_token}
        if refresh_token:
            tokens["refreshToken"] = refresh_token
        _save(site, tokens)
        keys = list(tokens.keys())
        await update.message.reply_text(
            f"✅ Token saved for `{site}`\n"
            f"Keys: {keys}\n"
            f"Access: `{access_token[:20]}...`",
            parse_mode="Markdown"
        )
        logger.info("[token_cmd] Token saved for site=%s keys=%s", site, keys)
    except Exception as exc:
        logger.exception("[token_cmd] settoken failed: %s", exc)
        await update.message.reply_text(f"❌ Failed: {exc}")


async def cmd_tokeninfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tokeninfo [site] — show vault status."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return

    import os
    import json
    import psycopg2
    from datetime import datetime, timezone

    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        await update.message.reply_text("❌ DATABASE_URL not set")
        return

    site_filter = (context.args or [None])[0]

    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                if site_filter:
                    cur.execute(
                        "SELECT site, tokens, expires_at, extracted_at FROM token_vault WHERE site = %s",
                        (site_filter,)
                    )
                else:
                    cur.execute("SELECT site, tokens, expires_at, extracted_at FROM token_vault ORDER BY site")
                rows = cur.fetchall()

        if not rows:
            await update.message.reply_text("📭 Vault is empty — no tokens stored.")
            return

        now = datetime.now(timezone.utc)
        lines = ["🔐 *Token Vault Status*\n"]
        for site, tokens_raw, expires_at, extracted_at in rows:
            tokens = json.loads(tokens_raw) if isinstance(tokens_raw, str) else (tokens_raw or {})
            keys = list(tokens.keys())
            expired = expires_at and expires_at.replace(tzinfo=timezone.utc) < now
            status = "❌ expired" if expired else "✅ valid"
            lines.append(
                f"*{site}*\n"
                f"  Keys: {keys}\n"
                f"  Status: {status}\n"
                f"  Expires: {expires_at}\n"
            )

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    except Exception as exc:
        logger.exception("[token_cmd] tokeninfo failed: %s", exc)
        await update.message.reply_text(f"❌ Error: {exc}")


async def cmd_refreshtoken(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/refreshtoken <site> — force refresh token now."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text("Usage: /refreshtoken <site>")
        return

    site = args[0]
    await update.message.reply_text(f"🔄 Refreshing token for `{site}`...", parse_mode="Markdown")

    try:
        from app.token_vault import get_tokens
        tokens = await get_tokens(site)
        if tokens.get("accessToken"):
            t = tokens["accessToken"]
            await update.message.reply_text(
                f"✅ Token refreshed for `{site}`\n`{t[:30]}...`",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(f"❌ No accessToken returned for `{site}`")
    except Exception as exc:
        logger.exception("[token_cmd] refreshtoken failed: %s", exc)
        await update.message.reply_text(f"❌ Refresh failed: {exc}")
