"""
Telegram commands for 1win-partners affiliate dashboard — admin only.

Commands:
  /win1info    — account info (balance, cooperation model, revenue share)
  /win1links   — affiliate link list
  /win1sources — traffic source list
  /win1promo   — promo code list
  /win1stats   — today/yesterday stats from DB (browser-push data)
  /win1report [days] — N-day stats summary from DB
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")


def _is_admin(update: Update) -> bool:
    return bool(ADMIN_ID and update.effective_user and update.effective_user.id == ADMIN_ID)


async def _notify_error(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Send error DM to admin (best-effort, never raises)."""
    if not ADMIN_ID:
        return
    try:
        await context.bot.send_message(ADMIN_ID, f"[win1_cmd] {text}")
    except Exception:
        pass


# ── /win1info ─────────────────────────────────────────────────────────────────

async def cmd_win1info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/win1info — show account balance, model, revenue share."""
    if not _is_admin(update):
        await update.message.reply_text("Access denied.")
        return

    await update.message.reply_text("Fetching account info...")
    try:
        from app.win1_client import get_client_from_vault
        client = get_client_from_vault()
        info = await client.user_info()
    except Exception as exc:
        logger.exception("[win1info] user_info failed")
        await update.message.reply_text(f"Error: {exc}")
        await _notify_error(context, f"/win1info failed: {exc}")
        return

    balance = info.get("balance") or info.get("wallet_balance") or "N/A"
    model = info.get("cooperation_model") or info.get("model") or "N/A"
    rate = info.get("revenue_share") or info.get("revshare") or "N/A"
    login = info.get("login") or info.get("email") or "N/A"
    currency = info.get("currency") or "USD"

    await update.message.reply_text(
        f"1win Account Info\n\n"
        f"Login: {login}\n"
        f"Balance: {balance} {currency}\n"
        f"Model: {model}\n"
        f"Revenue Share: {rate}",
    )


# ── /win1links ────────────────────────────────────────────────────────────────

async def cmd_win1links(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/win1links — list all affiliate links."""
    if not _is_admin(update):
        await update.message.reply_text("Access denied.")
        return

    await update.message.reply_text("Fetching links...")
    try:
        from app.win1_client import get_client_from_vault
        client = get_client_from_vault()
        items = await client.links()
    except Exception as exc:
        logger.exception("[win1links] links() failed")
        await update.message.reply_text(f"Error: {exc}")
        await _notify_error(context, f"/win1links failed: {exc}")
        return

    if not items:
        await update.message.reply_text("No links found.")
        return

    lines = [f"Affiliate Links ({len(items)} total)\n"]
    for lnk in items[:20]:  # cap at 20 to avoid message too long
        name = lnk.get("name") or lnk.get("link") or "—"
        promo = " [PROMO]" if lnk.get("is_promo") else ""
        hidden = " [hidden]" if lnk.get("is_hidden") else ""
        src_id = lnk.get("source_id") or "—"
        lines.append(f"• {name}{promo}{hidden} (src:{src_id})")

    await update.message.reply_text("\n".join(lines))


# ── /win1sources ──────────────────────────────────────────────────────────────

async def cmd_win1sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/win1sources — list traffic sources."""
    if not _is_admin(update):
        await update.message.reply_text("Access denied.")
        return

    await update.message.reply_text("Fetching sources...")
    try:
        from app.win1_client import get_client_from_vault
        client = get_client_from_vault()
        items = await client.sources()
    except Exception as exc:
        logger.exception("[win1sources] sources() failed")
        await update.message.reply_text(f"Error: {exc}")
        await _notify_error(context, f"/win1sources failed: {exc}")
        return

    if not items:
        await update.message.reply_text("No sources found.")
        return

    lines = [f"Traffic Sources ({len(items)} total)\n"]
    for src in items[:20]:
        name = src.get("name") or "—"
        src_type = src.get("type") or "—"
        status = src.get("verificationStatus") or src.get("status") or "—"
        lines.append(f"• [{src_type}] {name} — {status}")

    await update.message.reply_text("\n".join(lines))


# ── /win1promo ────────────────────────────────────────────────────────────────

async def cmd_win1promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/win1promo — list promo codes."""
    if not _is_admin(update):
        await update.message.reply_text("Access denied.")
        return

    await update.message.reply_text("Fetching promo codes...")
    try:
        from app.win1_client import get_client_from_vault
        client = get_client_from_vault()
        items = await client.promo_codes()
    except Exception as exc:
        logger.exception("[win1promo] promo_codes() failed")
        await update.message.reply_text(f"Error: {exc}")
        await _notify_error(context, f"/win1promo failed: {exc}")
        return

    if not items:
        await update.message.reply_text("No promo codes found.")
        return

    lines = [f"Promo Codes ({len(items)} total)\n"]
    for p in items[:20]:
        code = p.get("link") or p.get("code") or "—"
        src = p.get("source_name") or "—"
        created = (p.get("created_at") or "")[:10] or "—"
        lines.append(f"• {code} | src:{src} | {created}")

    await update.message.reply_text("\n".join(lines))


# ── /win1stats ────────────────────────────────────────────────────────────────

async def cmd_win1stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/win1stats — today + yesterday stats from DB (browser-push data)."""
    if not _is_admin(update):
        await update.message.reply_text("Access denied.")
        return

    try:
        from app.affiliate_tracker import get_recent_stats
        rows = get_recent_stats(limit=2)
    except Exception as exc:
        logger.exception("[win1stats] get_recent_stats failed")
        await update.message.reply_text(f"DB error: {exc}")
        await _notify_error(context, f"/win1stats failed: {exc}")
        return

    if not rows:
        await update.message.reply_text(
            "No stats in DB yet.\n"
            "Use the bookmarklet to push stats from your browser:\n"
            "GET /api/1win/bookmarklet"
        )
        return

    lines = ["Recent Stats (from browser push)\n"]
    for row in rows:
        d_from = str(row.get("date_from") or "")[:10]
        d_to = str(row.get("date_to") or "")[:10]
        period = d_from if d_from == d_to else f"{d_from}~{d_to}"
        lines.append(
            f"{period}\n"
            f"  Clicks: {row.get('clicks', 0):,}\n"
            f"  Regs: {row.get('registrations', 0):,}\n"
            f"  FTD: {row.get('ftd_count', 0):,}\n"
            f"  Commission: ${float(row.get('commission') or 0):,.2f}"
        )

    await update.message.reply_text("\n".join(lines))


# ── /win1report ───────────────────────────────────────────────────────────────

async def cmd_win1report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/win1report [days=7] — aggregated N-day report from DB."""
    if not _is_admin(update):
        await update.message.reply_text("Access denied.")
        return

    args = context.args or []
    try:
        days = int(args[0]) if args else 7
        days = max(1, min(days, 90))  # clamp 1–90
    except ValueError:
        await update.message.reply_text("Usage: /win1report [days]\nExample: /win1report 14")
        return

    try:
        from app.affiliate_tracker import get_recent_stats
        rows = get_recent_stats(limit=days)
    except Exception as exc:
        logger.exception("[win1report] get_recent_stats failed")
        await update.message.reply_text(f"DB error: {exc}")
        await _notify_error(context, f"/win1report failed: {exc}")
        return

    if not rows:
        await update.message.reply_text("No stats found in DB.")
        return

    # Aggregate totals
    totals: dict[str, float] = {
        "clicks": 0, "registrations": 0, "ftd_count": 0,
        "deposits": 0, "revenue": 0, "commission": 0,
    }
    for row in rows:
        for key in totals:
            totals[key] += float(row.get(key) or 0)

    oldest = str(rows[-1].get("date_from") or "")[:10]
    newest = str(rows[0].get("date_to") or "")[:10]

    await update.message.reply_text(
        f"1win Report ({len(rows)} records, {oldest} ~ {newest})\n\n"
        f"Clicks: {int(totals['clicks']):,}\n"
        f"Registrations: {int(totals['registrations']):,}\n"
        f"FTD: {int(totals['ftd_count']):,}\n"
        f"Deposits: ${totals['deposits']:,.2f}\n"
        f"Revenue: ${totals['revenue']:,.2f}\n"
        f"Commission: ${totals['commission']:,.2f}"
    )
