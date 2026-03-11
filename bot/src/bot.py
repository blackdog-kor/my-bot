import os
import asyncio
import threading
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from webhook import logger
from utils.logger import log_event
from handlers.callbacks import callback, start, text_handler

# Ensure bot/.env is loaded even when this module is the entrypoint
BOT_BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BOT_BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Flask(__name__)

# A single event loop shared across all webhook requests so the
# python-telegram-bot Application (and its HTTP connection pool) always
# runs on the same loop.
_loop = asyncio.new_event_loop()
_loop_thread_started = False
_ptb_app: Application | None = None
_ptb_app_lock = threading.Lock()


def _ensure_loop_thread() -> None:
    global _loop_thread_started
    if _loop_thread_started:
        return

    def _runner():
        asyncio.set_event_loop(_loop)
        _loop.run_forever()

    t = threading.Thread(target=_runner, name="ptb-loop", daemon=True)
    t.start()
    _loop_thread_started = True


def _get_ptb_app() -> Application | None:
    global _ptb_app
    with _ptb_app_lock:
        if _ptb_app is None and BOT_TOKEN:
            _ensure_loop_thread()
            candidate = Application.builder().token(BOT_TOKEN).build()
            candidate.add_handler(CommandHandler("start", start))
            candidate.add_handler(CallbackQueryHandler(callback))
            candidate.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
            asyncio.run_coroutine_threadsafe(candidate.initialize(), _loop).result()
            asyncio.run_coroutine_threadsafe(candidate.start(), _loop).result()
            _ptb_app = candidate
    return _ptb_app


@app.route("/webhook", methods=["POST"])
def telegram_webhook():

    update_data = request.json

    log_event(
        logger,
        "telegram_update_received",
        update_id=update_data.get("update_id")
    )

    ptb_app = _get_ptb_app()
    if ptb_app:
        update = Update.de_json(update_data, ptb_app.bot)
        asyncio.run_coroutine_threadsafe(ptb_app.process_update(update), _loop).result()

    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
