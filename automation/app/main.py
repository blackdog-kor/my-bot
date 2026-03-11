import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI, Request, HTTPException
from telegram import BotCommand, Update
from telegram.ext import Application

from app.config import ADMIN_ID, BOT_TOKEN, CHANNEL_ID
from app.db import (
    ensure_db,
    get_video_job,
    update_video_job_status,
    attach_media,
    attach_thumbnail,
    get_post,
    count_competitor_users,
)
from app.services.member_scraper import run_member_scraper
from app.services.scheduler_service import scheduler
from app.bot import get_handlers, telegram_error_handler
from app.publishers.telegram_pub import publish_to_telegram_channel
from app.api.user_entry import router as user_entry_router
from app.api.routes import health
from app.services.error_monitoring import (
    init_error_monitoring,
    capture_exception,
    build_telegram_update_context,
)

logger = logging.getLogger("uvicorn.error")

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
CALLBACK_SECRET = os.getenv("CALLBACK_SECRET", "")

telegram_app: Application | None = None
CURRENT_WEBHOOK_URL = ""
_telegram_bot_ref = None
_main_loop_ref = None


async def _install_playwright_chromium_in_background() -> None:
    """Playwright용 Chromium을 백그라운드에서 설치한다. 실패해도 서버는 죽지 않는다."""
    try:
        logger.info("Playwright Chromium 설치를 백그라운드에서 시작합니다.")
        # CPU 바운드/IO 작업을 메인 이벤트 루프와 분리
        await asyncio.to_thread(os.system, "python -m playwright install chromium")
        logger.info("Playwright Chromium 설치가 완료되었습니다.")
    except Exception:
        # 여기서 예외를 다시 올리지 않는다. 서버 기동을 막지 않기 위함.
        logger.exception("Playwright Chromium 설치 중 오류가 발생했습니다.")


def _daily_member_scrape_and_report() -> None:
    """매일 새벽 4시에 실행: 멤버 수집 후 ADMIN_ID로 보고서 전송."""
    global _telegram_bot_ref, _main_loop_ref
    try:
        before = count_competitor_users()
        run_member_scraper()
        after = count_competitor_users()
        report = (
            "📋 수집 완료 보고서\n"
            f"이번 수집: {after - before}명\n"
            f"현재 DB 총: {after}명"
        )
    except Exception as e:
        report = f"❌ 수집 중 오류\n{e!s}"
    bot = _telegram_bot_ref
    loop = _main_loop_ref
    if bot and loop and ADMIN_ID:
        try:
            fut = asyncio.run_coroutine_threadsafe(
                bot.send_message(chat_id=int(ADMIN_ID), text=report),
                loop,
            )
            fut.result(timeout=15)
        except Exception:
            pass


async def ensure_webhook() -> dict:
    global telegram_app, CURRENT_WEBHOOK_URL

    if telegram_app is None:
        raise RuntimeError("telegram app not ready")

    info = await telegram_app.bot.get_webhook_info()

    actual_url = info.url or ""
    expected_url = CURRENT_WEBHOOK_URL
    healed = False

    if not actual_url or actual_url != expected_url:
        await telegram_app.bot.delete_webhook(drop_pending_updates=False)
        await telegram_app.bot.set_webhook(url=expected_url)
        healed = True

        info = await telegram_app.bot.get_webhook_info()
        actual_url = info.url or ""

    return {
        "ok": True,
        "expected_url": expected_url,
        "actual_url": actual_url,
        "pending_update_count": info.pending_update_count,
        "last_error_message": getattr(info, "last_error_message", None),
        "has_custom_certificate": info.has_custom_certificate,
        "healed": healed,
    }


async def auto_publish_telegram_if_needed(post_id: int, payload_json: str):
    global telegram_app

    if telegram_app is None:
        return

    try:
        payload = json.loads(payload_json or "{}")
    except Exception:
        payload = {}

    if not payload.get("auto_publish_on_complete"):
        return

    platforms = payload.get("auto_publish_platforms", [])
    if "telegram" not in platforms:
        return

    row = get_post(post_id)
    if not row:
        return

    (
        _post_id,
        _source,
        _language,
        title,
        body,
        cta_link,
        _status,
        _created_at,
        media_type,
        media_path,
        thumbnail_path,
        platform_meta_json,
    ) = row

    dummy_context = SimpleNamespace(bot=telegram_app.bot)

    await publish_to_telegram_channel(
        context=dummy_context,
        channel_id=CHANNEL_ID,
        title=title,
        body=body,
        cta_link=cta_link,
        media_type=media_type,
        media_path=media_path,
        thumbnail_path=thumbnail_path,
        platform_meta_json=platform_meta_json,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app, CURRENT_WEBHOOK_URL, _telegram_bot_ref, _main_loop_ref

    init_error_monitoring()

    ensure_db()

    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN is not set. Telegram features disabled.")
        telegram_app = None
        CURRENT_WEBHOOK_URL = ""
        yield
        return

    telegram_app = Application.builder().token(BOT_TOKEN).build()

    for handler in get_handlers():
        telegram_app.add_handler(handler)
    telegram_app.add_error_handler(telegram_error_handler)

    await telegram_app.initialize()
    await telegram_app.start()

    await telegram_app.bot.set_my_commands(
        [BotCommand("admin", "관리자 메뉴")]
    )

    _telegram_bot_ref = telegram_app.bot
    _main_loop_ref = asyncio.get_running_loop()
    scheduler.add_job(
        _daily_member_scrape_and_report,
        "cron",
        hour=4,
        minute=0,
        timezone="Asia/Seoul",
        id="daily_member_scrape",
    )

    if not PUBLIC_BASE_URL or not WEBHOOK_SECRET:
        logger.warning("PUBLIC_BASE_URL or WEBHOOK_SECRET is not set. Webhook auto-heal disabled.")
        CURRENT_WEBHOOK_URL = ""
    else:
        CURRENT_WEBHOOK_URL = f"{PUBLIC_BASE_URL}/telegram/{WEBHOOK_SECRET}"
        status = await ensure_webhook()

        if status["healed"]:
            logger.info("Webhook set")
        else:
            logger.info("Webhook already correct")

        logger.info("Webhook URL: %s", CURRENT_WEBHOOK_URL)

    # Playwright Chromium 설치를 백그라운드 태스크로 실행 (서버 기동은 먼저 완료)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_install_playwright_chromium_in_background())
    except Exception:
        logger.exception("Playwright Chromium 백그라운드 설치 태스크 등록 실패")

    logger.info("🚀 서버가 성공적으로 시작되었습니다!")

    yield

    await telegram_app.stop()
    await telegram_app.shutdown()


app = FastAPI(lifespan=lifespan)

app.include_router(health.router)
app.include_router(user_entry_router)


@app.get("/webhook-status")
async def webhook_status():
    global telegram_app

    if telegram_app is None:
        raise HTTPException(status_code=503, detail="telegram app not ready")

    status = await ensure_webhook()
    return status


@app.post("/webhook-heal")
async def webhook_heal():
    global telegram_app

    if telegram_app is None:
        raise HTTPException(status_code=503, detail="telegram app not ready")

    status = await ensure_webhook()
    return status


@app.post("/telegram/{secret}")
async def telegram_webhook(secret: str, request: Request):
    global telegram_app

    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="invalid webhook secret")

    if telegram_app is None:
        raise HTTPException(status_code=503, detail="telegram app not ready")

    data = await request.json()
    logger.warning("🔔 메시지 수신 성공!")
    logger.warning("[telegram_webhook] incoming update JSON: %s", data)
    update = Update.de_json(data, telegram_app.bot)
    logger.warning(
        "[telegram_webhook] enqueue update: user_id=%s text=%s",
        getattr(update.effective_user, "id", None),
        getattr(getattr(update, "message", None), "text", None),
    )
    try:
        await telegram_app.update_queue.put(update)
    except Exception as e:
        logger.exception("ERROR while enqueueing update")
        capture_exception(
            e,
            tags={"component": "telegram-webhook"},
            context={
                "path": "/telegram/{secret}",
                "telegram_update": build_telegram_update_context(update),
            },
        )
        raise
    return {"ok": True}


@app.post("/api/video/callback")
async def video_callback(request: Request):
    data = await request.json()

    secret = str(data.get("secret", "")).strip()
    if CALLBACK_SECRET and secret != CALLBACK_SECRET:
        raise HTTPException(status_code=403, detail="invalid callback secret")

    job_id = str(data.get("job_id", "")).strip()
    status = str(data.get("status", "")).strip().lower()
    video_path = str(data.get("video_path", "") or data.get("video_url", "")).strip()
    thumbnail_path = str(data.get("thumbnail_path", "") or data.get("thumbnail_url", "")).strip()
    error_message = str(data.get("error_message", "")).strip()

    if not job_id:
        raise HTTPException(status_code=400, detail="job_id_required")

    job = get_video_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job_not_found")

    _, post_id, engine, old_status, payload_json, _, _, _, _, _ = job

    if status == "completed":
        update_video_job_status(
            job_id=job_id,
            status="completed",
            result_video_path=video_path,
            result_thumb_path=thumbnail_path,
            error_message="",
        )

        if video_path:
            attach_media(post_id, "video", video_path)

        if thumbnail_path:
            attach_thumbnail(post_id, thumbnail_path)

        await auto_publish_telegram_if_needed(post_id, payload_json)

        return {
            "ok": True,
            "job_id": job_id,
            "post_id": post_id,
            "status": "completed",
            "video_path": video_path,
            "thumbnail_path": thumbnail_path,
        }

    if status == "failed":
        update_video_job_status(
            job_id=job_id,
            status="failed",
            result_video_path="",
            result_thumb_path="",
            error_message=error_message or "external_engine_failed",
        )
        return {
            "ok": True,
            "job_id": job_id,
            "post_id": post_id,
            "status": "failed",
            "error_message": error_message or "external_engine_failed",
        }

    raise HTTPException(status_code=400, detail="status_must_be_completed_or_failed")
