"""
Telegram command handler for the autonomous agent pipeline.

Commands (admin only):
  /agent <task>  — submit a natural language task to the agent queue
  /agentstatus   — show current queue length
"""
import logging
import os
import uuid

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")


def _is_admin(update: Update) -> bool:
    return bool(ADMIN_ID and update.effective_user and update.effective_user.id == ADMIN_ID)


async def cmd_agent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /agent <task> — submit task to the autonomous pipeline."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return

    args = context.args or []
    prompt = " ".join(args).strip()
    if not prompt:
        await update.message.reply_text(
            "Usage: /agent <natural language task>\n"
            "Example: /agent 1win 어제 통계 수집해서 요약해줘"
        )
        return

    task_id = uuid.uuid4().hex[:8]
    chat_id = update.effective_chat.id
    bot = context.bot

    await update.message.reply_text(f"🚀 Task `{task_id}` queued:\n_{prompt}_", parse_mode="Markdown")

    async def notify(msg: str) -> None:
        try:
            await bot.send_message(chat_id=chat_id, text=msg)
        except Exception as exc:
            logger.warning("[agent_cmd] notify failed: %s", exc)

    from app.task_queue import queue
    await queue.submit(task_id, prompt, notify=notify)


async def cmd_agent_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /agentstatus — show queue depth."""
    if not _is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return

    from app.task_queue import queue
    depth = queue._queue.qsize()
    await update.message.reply_text(f"📋 Agent queue: {depth} task(s) pending")
