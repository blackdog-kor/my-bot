import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from app.config import ADMIN_ID, CHANNEL_ID, DEFAULT_LANGUAGE
from app.db import (
    create_post,
    list_posts,
    get_post,
    update_post_status,
    delete_post,
    attach_media,
    attach_thumbnail,
    update_platform_meta,
    create_video_job,
    list_video_jobs,
    get_video_job,
    update_video_job_status,
    list_campaigns,
    get_campaign,
    delete_campaign,
    save_user,
    get_user,
    list_users,
    count_users,
)
from app.services.ai_service import AIService
from app.services.scheduler_service import scheduler, list_jobs, remove_job
from app.services.variant_engine import VariantEngine
from app.services.pipeline_service import PipelineService
from app.services.factory_service import FactoryService
from app.services.campaign_service import CampaignService
from app.services.video_generation_service import generate_video_from_prompt
from app.services.error_monitoring import capture_telegram_runtime_error
from app.publishers.publisher_manager import PublisherManager
from app.publishers.telegram_pub import (
    scheduled_publish_telegram,
    publish_to_telegram_channel,
)
from app.services.link_finder import find_competitor_telegram_links
from app.services.member_scraper import run_member_scraper
from app.db import count_competitor_users, export_competitor_users_to_csv_file

ai_service = AIService()
pipeline_service = PipelineService()
factory_service = FactoryService()
campaign_service = CampaignService()

BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip()


def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) == int(ADMIN_ID)
    except Exception:
        return False


def _callback_url() -> str:
    base = os.getenv("PUBLIC_BASE_URL", "").strip()
    if not base:
        return "(PUBLIC_BASE_URL 미설정)/api/video/callback"
    return f"{base.rstrip('/')}/api/video/callback"


def _build_bot_start_link(start_param: str = "promo") -> str:
    if BOT_USERNAME:
        return f"https://t.me/{BOT_USERNAME}?start={start_param}"
    return "BOT_USERNAME 미설정"


async def send_dm(bot, user_id: int, text: str):
    try:
        await bot.send_message(chat_id=user_id, text=text)
    except Exception:
        pass


def start_dm_sequence(bot, user_id: int):
    scheduler.add_job(
        send_dm,
        "date",
        run_date=datetime.utcnow() + timedelta(minutes=1),
        args=[
            bot,
            user_id,
            "🎁 무료 보너스 이벤트가 열렸습니다.\n지금 바로 확인하세요.\nhttps://example.com",
        ],
    )

    scheduler.add_job(
        send_dm,
        "date",
        run_date=datetime.utcnow() + timedelta(minutes=10),
        args=[
            bot,
            user_id,
            "🔥 아직 참여하지 않으셨나요?\n지금 참여하면 추가 혜택을 확인할 수 있습니다.\nhttps://example.com",
        ],
    )

    scheduler.add_job(
        send_dm,
        "date",
        run_date=datetime.utcnow() + timedelta(hours=1),
        args=[
            bot,
            user_id,
            "🚀 마지막 안내입니다.\n현재 진행 중인 혜택을 놓치지 마세요.\nhttps://example.com",
        ],
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if is_admin(user_id):
        text = (
            "대표님용 SNS 자동화 봇\n\n"
            "/newpost - 새 게시물 작성\n"
            "/list - 게시물 목록\n"
            "/showpost ID - 게시물 상세 보기\n"
            "/attachmedia ID media_type path - 미디어 연결\n"
            "/attachthumb ID path - 썸네일 연결\n"
            "/setmeta ID JSON - 플랫폼 메타 저장\n"
            "/requestvideo ID engine - 외부 영상 작업 생성\n"
            "/completevideo JOB_ID video_url thumbnail_url - 영상 작업 완료 처리\n"
            "/videojobs - 영상 작업 목록\n"
            "/variants ID 개수 - 게시물 변형 생성\n"
            "/autopipeline 키워드 | engine - AI 생성 + 영상 JOB 자동 생성\n"
            "/factory 키워드 | engine - 완료 후 텔레그램 자동발행\n"
            "/leadpost 키워드 - 봇 유입형 리드 게시글 생성\n"
            "/campaigncreate 이름 | 키워드 | engine | 개수\n"
            "/campaigns\n"
            "/campaigndetail ID\n"
            "/campaignrun ID\n"
            "/campaigndelete ID\n"
            "/publish ID [platform] - 즉시 발행\n"
            "/schedule ID HH:MM [platform] - 예약 발행\n"
            "/autopost HH:MM 키워드 - AI 생성 후 자동 예약\n"
            "/deletepost ID - 게시물 삭제\n"
            "/queue - 예약 작업 목록\n"
            "/canceljob JOB_ID - 예약 작업 취소\n"
            "/trend 키워드 - 트렌드형 아이디어 생성\n"
            "/ai 키워드 - AI 게시물 생성\n"
            "/rewrite 스타일 | 문장\n"
            "/translate 언어 | 문장\n"
            "/hashtags 키워드\n"
            "/ideas 키워드\n"
            "/users - 유저 목록\n"
            "/dev - 개발 제어 패널\n\n"
            "media_type: text / image / video\n"
            "platform 기본값: telegram"
        )
        await update.message.reply_text(text)
        return

    source = context.args[0] if context.args else "direct"
    username = update.effective_user.username or ""
    save_user(user_id, username, source)

    channel_url = f"https://t.me/{BOT_USERNAME}" if BOT_USERNAME else "https://example.com"
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🎁 이벤트 참여", url="https://example.com"),
                InlineKeyboardButton("📢 채널 입장", url=channel_url),
            ],
            [
                InlineKeyboardButton("💬 고객센터", url="https://example.com/support"),
            ],
        ]
    )
    await update.message.reply_text(
        "🎉 환영합니다!\n\n"
        "다양한 혜택과 이벤트 소식을 받아보세요.\n"
        "아래 버튼을 눌러 시작하세요.",
        reply_markup=keyboard,
    )
    start_dm_sequence(context.bot, user_id)


async def newpost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    context.user_data["newpost_step"] = "language"
    context.user_data["newpost_data"] = {}

    await update.message.reply_text(
        "새 게시물 작성 시작\n\n"
        "1단계: 언어를 입력하세요.\n"
        "예: 한국어 / English / 中文 / Português"
    )


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    rows = list_posts()
    if not rows:
        await update.message.reply_text("저장된 게시물이 없습니다.")
        return

    lines = []
    for row in rows:
        post_id, source, language, title, status, created_at, media_type = row
        lines.append(
            f"ID: {post_id}\n"
            f"출처: {source}\n"
            f"언어: {language}\n"
            f"제목: {title}\n"
            f"미디어: {media_type}\n"
            f"상태: {status}\n"
            f"생성일: {created_at}\n"
        )

    await update.message.reply_text("\n".join(lines))


async def showpost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("사용법: /showpost 게시물ID")
        return

    try:
        post_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("게시물 ID는 숫자여야 합니다.")
        return

    row = get_post(post_id)
    if not row:
        await update.message.reply_text("해당 게시물을 찾을 수 없습니다.")
        return

    (
        post_id,
        source,
        language,
        title,
        body,
        cta_link,
        status,
        created_at,
        media_type,
        media_path,
        thumbnail_path,
        platform_meta_json,
    ) = row

    text = (
        f"ID: {post_id}\n"
        f"출처: {source}\n"
        f"언어: {language}\n"
        f"제목: {title}\n"
        f"본문: {body}\n"
        f"링크: {cta_link}\n"
        f"상태: {status}\n"
        f"미디어 타입: {media_type}\n"
        f"미디어 경로: {media_path}\n"
        f"썸네일 경로: {thumbnail_path}\n"
        f"플랫폼 메타: {platform_meta_json}\n"
        f"생성일: {created_at}"
    )
    await update.message.reply_text(text)


async def attachmedia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 3:
        await update.message.reply_text("사용법: /attachmedia ID media_type path")
        return

    try:
        post_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("게시물 ID는 숫자여야 합니다.")
        return

    media_type = context.args[1].strip().lower()
    media_path = " ".join(context.args[2:]).strip()

    if media_type not in {"text", "image", "video"}:
        await update.message.reply_text("media_type은 text / image / video 만 가능합니다.")
        return

    updated = attach_media(post_id, media_type, media_path)
    if updated:
        await update.message.reply_text(
            f"미디어 연결 완료\nID: {post_id}\n타입: {media_type}\n경로: {media_path}"
        )
    else:
        await update.message.reply_text("해당 게시물을 찾을 수 없습니다.")


async def attachthumb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.message.reply_text("사용법: /attachthumb ID path")
        return

    try:
        post_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("게시물 ID는 숫자여야 합니다.")
        return

    thumb_path = " ".join(context.args[1:]).strip()

    updated = attach_thumbnail(post_id, thumb_path)
    if updated:
        await update.message.reply_text(
            f"썸네일 연결 완료\nID: {post_id}\n경로: {thumb_path}"
        )
    else:
        await update.message.reply_text("해당 게시물을 찾을 수 없습니다.")


async def setmeta_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.message.reply_text('사용법: /setmeta ID {"youtube":{"privacy":"private"}}')
        return

    try:
        post_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("게시물 ID는 숫자여야 합니다.")
        return

    raw_json = " ".join(context.args[1:]).strip()

    try:
        meta = json.loads(raw_json)
    except Exception as e:
        await update.message.reply_text(f"JSON 오류: {e}")
        return

    updated = update_platform_meta(post_id, meta)
    if updated:
        await update.message.reply_text(f"플랫폼 메타 저장 완료: ID {post_id}")
    else:
        await update.message.reply_text("해당 게시물을 찾을 수 없습니다.")


async def requestvideo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.message.reply_text("사용법: /requestvideo ID engine")
        return

    try:
        post_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("게시물 ID는 숫자여야 합니다.")
        return

    engine = context.args[1].strip().lower()
    row = get_post(post_id)

    if not row:
        await update.message.reply_text("해당 게시물을 찾을 수 없습니다.")
        return

    (
        _,
        source,
        language,
        title,
        body,
        cta_link,
        status,
        created_at,
        media_type,
        media_path,
        thumbnail_path,
        platform_meta_json,
    ) = row

    payload = {
        "post_id": post_id,
        "title": title,
        "body": body,
        "cta_link": cta_link,
        "language": language,
    }

    job_id = create_video_job(post_id=post_id, engine=engine, payload=payload)

    if engine == "huggingface":
        try:
            video_path = generate_video_from_prompt(
                prompt=title,
                job_id=job_id,
            )

            update_video_job_status(
                job_id=job_id,
                status="completed",
                result_video_path=video_path,
                result_thumb_path="",
                error_message="",
            )

            attach_media(post_id, "video", video_path)

            await update.message.reply_text(
                f"HuggingFace 영상 생성 완료\n\n"
                f"POST_ID: {post_id}\n"
                f"JOB_ID: {job_id}\n"
                f"VIDEO: {video_path}"
            )
            return

        except Exception as e:
            update_video_job_status(
                job_id=job_id,
                status="failed",
                result_video_path="",
                result_thumb_path="",
                error_message=str(e),
            )
            await update.message.reply_text(f"HuggingFace 영상 생성 실패: {e}")
            return

    callback_url = _callback_url()

    text = (
        f"영상 작업 생성 완료\n\n"
        f"POST_ID: {post_id}\n"
        f"JOB_ID: {job_id}\n"
        f"ENGINE: {engine}\n"
        f"CALLBACK_URL: {callback_url}\n\n"
        f'{{"secret":"CALLBACK_SECRET","job_id":"{job_id}","status":"completed","video_url":"https://filesamples.com/samples/video/mp4/sample_640x360.mp4","thumbnail_url":"https://picsum.photos/800/450"}}'
    )
    await update.message.reply_text(text)


async def completevideo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 3:
        await update.message.reply_text("사용법: /completevideo JOB_ID video_url thumbnail_url")
        return

    job_id = context.args[0].strip()
    video_url = context.args[1].strip()
    thumbnail_url = context.args[2].strip()

    job = get_video_job(job_id)
    if not job:
        await update.message.reply_text("해당 JOB_ID를 찾을 수 없습니다.")
        return

    _, post_id, engine, status, payload_json, _, _, _, _, _ = job

    update_video_job_status(
        job_id=job_id,
        status="completed",
        result_video_path=video_url,
        result_thumb_path=thumbnail_url,
        error_message="",
    )

    attach_media(post_id, "video", video_url)
    attach_thumbnail(post_id, thumbnail_url)

    await update.message.reply_text(
        f"영상 작업 완료 처리\n\n"
        f"JOB_ID: {job_id}\n"
        f"POST_ID: {post_id}\n"
        f"VIDEO: {video_url}\n"
        f"THUMB: {thumbnail_url}"
    )


async def videojobs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    rows = list_video_jobs()
    if not rows:
        await update.message.reply_text("저장된 영상 작업이 없습니다.")
        return

    lines = []
    for row in rows[:20]:
        job_id, post_id, engine, status, created_at, completed_at = row
        lines.append(
            f"JOB_ID: {job_id}\n"
            f"POST_ID: {post_id}\n"
            f"ENGINE: {engine}\n"
            f"STATUS: {status}\n"
            f"CREATED: {created_at}\n"
            f"COMPLETED: {completed_at}\n"
        )

    await update.message.reply_text("\n".join(lines))


async def variants_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.message.reply_text("사용법: /variants ID 개수")
        return

    try:
        post_id = int(context.args[0])
        count = int(context.args[1])
    except ValueError:
        await update.message.reply_text("ID와 개수는 숫자여야 합니다.")
        return

    if count < 1 or count > 20:
        await update.message.reply_text("개수는 1~20 사이만 가능합니다.")
        return

    new_ids = VariantEngine.create_variants(post_id, count)
    if not new_ids:
        await update.message.reply_text("원본 게시물을 찾을 수 없습니다.")
        return

    text = "변형 게시물 생성 완료\n\n" + "\n".join([f"ID: {x}" for x in new_ids])
    await update.message.reply_text(text)


async def autopipeline_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    raw = " ".join(context.args).strip()
    if not raw:
        await update.message.reply_text("사용법: /autopipeline 키워드 | engine")
        return

    if "|" in raw:
        keyword, engine = [x.strip() for x in raw.split("|", 1)]
    else:
        keyword = raw
        engine = "runway"

    if not keyword:
        await update.message.reply_text("키워드를 입력하세요.")
        return

    try:
        post_id, job_id = pipeline_service.create_pipeline(
            keyword=keyword,
            language=DEFAULT_LANGUAGE,
            engine=engine,
        )

        if engine == "huggingface":
            try:
                video_path = generate_video_from_prompt(
                    prompt=keyword,
                    job_id=job_id,
                )

                update_video_job_status(
                    job_id=job_id,
                    status="completed",
                    result_video_path=video_path,
                    result_thumb_path="",
                    error_message="",
                )

                attach_media(post_id, "video", video_path)

                await update.message.reply_text(
                    f"자동 파이프라인 완료\n\n"
                    f"POST_ID: {post_id}\n"
                    f"JOB_ID: {job_id}\n"
                    f"ENGINE: {engine}\n"
                    f"VIDEO: {video_path}\n\n"
                    f"/publish {post_id} telegram\n"
                    f"/publish {post_id} youtube"
                )
                return

            except Exception as e:
                update_video_job_status(
                    job_id=job_id,
                    status="failed",
                    result_video_path="",
                    result_thumb_path="",
                    error_message=str(e),
                )
                await update.message.reply_text(f"autopipeline 실패: {e}")
                return

        await update.message.reply_text(
            f"자동 파이프라인 생성 완료\n\n"
            f"POST_ID: {post_id}\n"
            f"JOB_ID: {job_id}\n"
            f"ENGINE: {engine}\n\n"
            f"/completevideo {job_id} https://filesamples.com/samples/video/mp4/sample_640x360.mp4 https://picsum.photos/800/450\n"
            f"/publish {post_id} telegram"
        )
    except Exception as e:
        await update.message.reply_text(f"autopipeline 실패: {e}")


async def factory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    raw = " ".join(context.args).strip()
    if not raw:
        await update.message.reply_text("사용법: /factory 키워드 | engine")
        return

    if "|" in raw:
        keyword, engine = [x.strip() for x in raw.split("|", 1)]
    else:
        keyword = raw
        engine = "runway"

    if not keyword:
        await update.message.reply_text("키워드를 입력하세요.")
        return

    try:
        post_id, job_id = factory_service.create_factory_job(
            keyword=keyword,
            language=DEFAULT_LANGUAGE,
            engine=engine,
        )

        if engine == "huggingface":
            try:
                video_path = generate_video_from_prompt(
                    prompt=keyword,
                    job_id=job_id,
                )

                update_video_job_status(
                    job_id=job_id,
                    status="completed",
                    result_video_path=video_path,
                    result_thumb_path="",
                    error_message="",
                )

                attach_media(post_id, "video", video_path)

                row = get_post(post_id)
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

                dummy_context = SimpleNamespace(bot=context.bot)

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

                update_post_status(post_id, "published")

                await update.message.reply_text(
                    f"factory 완료\n\n"
                    f"POST_ID: {post_id}\n"
                    f"JOB_ID: {job_id}\n"
                    f"ENGINE: {engine}\n"
                    f"VIDEO: {video_path}\n"
                    f"텔레그램 자동발행 완료"
                )
                return

            except Exception as e:
                update_video_job_status(
                    job_id=job_id,
                    status="failed",
                    result_video_path="",
                    result_thumb_path="",
                    error_message=str(e),
                )
                await update.message.reply_text(f"factory 실패: {e}")
                return

        await update.message.reply_text(
            f"factory 생성 완료\n\n"
            f"POST_ID: {post_id}\n"
            f"JOB_ID: {job_id}\n"
            f"ENGINE: {engine}\n\n"
            f"외부 엔진 완료 후 /completevideo 또는 callback이 들어오면 텔레그램 자동발행됩니다.\n\n"
            f"/completevideo {job_id} https://filesamples.com/samples/video/mp4/sample_640x360.mp4 https://picsum.photos/800/450"
        )
    except Exception as e:
        await update.message.reply_text(f"factory 실패: {e}")


async def leadpost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    keyword = " ".join(context.args).strip()
    if not keyword:
        await update.message.reply_text("사용법: /leadpost 키워드")
        return

    try:
        text = ai_service.generate_post(
            keyword=keyword,
            language=DEFAULT_LANGUAGE,
        )

        bot_link = _build_bot_start_link("promo")

        post = (
            f"{text}\n\n"
            f"🎁 무료 참여하기\n"
            f"{bot_link}"
        )

        await update.message.reply_text(post)
    except Exception as e:
        await update.message.reply_text(f"leadpost 실패: {e}")


async def campaigncreate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    raw = " ".join(context.args).strip()
    if not raw:
        await update.message.reply_text("사용법: /campaigncreate 이름 | 키워드 | engine | 개수")
        return

    parts = [x.strip() for x in raw.split("|")]
    if len(parts) != 4:
        await update.message.reply_text("사용법: /campaigncreate 이름 | 키워드 | engine | 개수")
        return

    name, keyword, engine, count_raw = parts

    try:
        post_count = int(count_raw)
    except ValueError:
        await update.message.reply_text("개수는 숫자여야 합니다.")
        return

    if post_count < 1 or post_count > 50:
        await update.message.reply_text("개수는 1~50 사이만 가능합니다.")
        return

    campaign_id = campaign_service.create_campaign_shell(
        name=name,
        keyword=keyword,
        engine=engine,
        post_count=post_count,
        language=DEFAULT_LANGUAGE,
    )

    await update.message.reply_text(
        f"캠페인 생성 완료\n\n"
        f"CAMPAIGN_ID: {campaign_id}\n"
        f"NAME: {name}\n"
        f"KEYWORD: {keyword}\n"
        f"ENGINE: {engine}\n"
        f"COUNT: {post_count}\n\n"
        f"/campaignrun {campaign_id}"
    )


async def campaigns_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    rows = list_campaigns()
    if not rows:
        await update.message.reply_text("저장된 캠페인이 없습니다.")
        return

    lines = []
    for row in rows[:20]:
        campaign_id, name, keyword, engine, post_count, status, language, created_at = row
        lines.append(
            f"CAMPAIGN_ID: {campaign_id}\n"
            f"NAME: {name}\n"
            f"KEYWORD: {keyword}\n"
            f"ENGINE: {engine}\n"
            f"COUNT: {post_count}\n"
            f"STATUS: {status}\n"
            f"LANGUAGE: {language}\n"
            f"CREATED: {created_at}\n"
        )

    await update.message.reply_text("\n".join(lines))


async def campaigndetail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("사용법: /campaigndetail ID")
        return

    try:
        campaign_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("캠페인 ID는 숫자여야 합니다.")
        return

    row = get_campaign(campaign_id)
    if not row:
        await update.message.reply_text("해당 캠페인을 찾을 수 없습니다.")
        return

    links = campaign_service.get_campaign_links(campaign_id)

    (
        _id,
        name,
        keyword,
        engine,
        post_count,
        status,
        language,
        created_at,
        meta_json,
    ) = row

    lines = [
        f"CAMPAIGN_ID: {campaign_id}",
        f"NAME: {name}",
        f"KEYWORD: {keyword}",
        f"ENGINE: {engine}",
        f"COUNT: {post_count}",
        f"STATUS: {status}",
        f"LANGUAGE: {language}",
        f"CREATED: {created_at}",
        f"LINKED_ITEMS: {len(links)}",
        "",
    ]

    for item in links[:50]:
        link_id, campaign_id, post_id, job_id, linked_at = item
        lines.append(
            f"POST_ID: {post_id} / JOB_ID: {job_id} / LINKED: {linked_at}"
        )

    await update.message.reply_text("\n".join(lines))


async def campaignrun_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("사용법: /campaignrun ID")
        return

    try:
        campaign_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("캠페인 ID는 숫자여야 합니다.")
        return

    results = campaign_service.run_campaign(campaign_id)
    if not results:
        await update.message.reply_text("해당 캠페인을 찾을 수 없거나 실행 실패했습니다.")
        return

    lines = [f"캠페인 실행 완료\n\nCAMPAIGN_ID: {campaign_id}\n"]
    for post_id, job_id in results:
        lines.append(f"POST_ID: {post_id} / JOB_ID: {job_id}")

    await update.message.reply_text("\n".join(lines))


async def campaigndelete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("사용법: /campaigndelete ID")
        return

    try:
        campaign_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("캠페인 ID는 숫자여야 합니다.")
        return

    deleted = delete_campaign(campaign_id)
    if deleted:
        await update.message.reply_text(f"캠페인 삭제 완료: {campaign_id}")
    else:
        await update.message.reply_text("해당 캠페인을 찾을 수 없습니다.")


async def publish_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("사용법: /publish 게시물ID [platform]")
        return

    try:
        post_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("게시물 ID는 숫자여야 합니다.")
        return

    platform = context.args[1].lower() if len(context.args) > 1 else "telegram"

    row = get_post(post_id)
    if not row:
        await update.message.reply_text("해당 게시물을 찾을 수 없습니다.")
        return

    (
        _,
        _,
        language,
        title,
        body,
        cta_link,
        _,
        _,
        media_type,
        media_path,
        thumbnail_path,
        platform_meta_json,
    ) = row

    try:
        manager = PublisherManager(context)
        await manager.publish(
            platform=platform,
            channel_id=CHANNEL_ID,
            title=title,
            body=body,
            link=cta_link,
            media_type=media_type,
            media_path=media_path,
            thumbnail_path=thumbnail_path,
            platform_meta_json=platform_meta_json,
        )

        update_post_status(post_id, "published")
        await update.message.reply_text(
            f"발행 완료\n\n"
            f"ID: {post_id}\n"
            f"플랫폼: {platform}\n"
            f"언어: {language}\n"
            f"제목: {title}\n"
            f"미디어: {media_type}"
        )

    except Exception as e:
        update_post_status(post_id, "failed")
        await update.message.reply_text(f"발행 실패: {e}")


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.message.reply_text("사용법: /schedule 게시물ID HH:MM [platform]")
        return

    try:
        post_id = int(context.args[0])
        time_str = context.args[1]
        hour, minute = map(int, time_str.split(":"))
    except Exception:
        await update.message.reply_text("형식 오류: /schedule 3 21:30 [platform]")
        return

    platform = context.args[2].lower() if len(context.args) > 2 else "telegram"

    row = get_post(post_id)
    if not row:
        await update.message.reply_text("해당 게시물을 찾을 수 없습니다.")
        return

    (
        _,
        _,
        _,
        title,
        body,
        cta_link,
        _,
        _,
        media_type,
        media_path,
        thumbnail_path,
        platform_meta_json,
    ) = row

    if platform != "telegram":
        await update.message.reply_text(
            "현재 예약 발행은 telegram만 연결되어 있습니다.\n"
            "다른 플랫폼은 다음 단계에서 API 연결 후 활성화합니다."
        )
        return

    job = scheduler.add_job(
        scheduled_publish_telegram,
        "cron",
        hour=hour,
        minute=minute,
        args=[
            context.bot,
            CHANNEL_ID,
            title,
            body,
            cta_link,
            media_type,
            media_path,
            thumbnail_path,
            platform_meta_json,
        ],
    )

    update_post_status(post_id, "scheduled")
    await update.message.reply_text(
        f"예약 완료: ID {post_id} / {time_str} / {platform}\nJOB_ID: {job.id}"
    )


async def autopost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.message.reply_text("사용법: /autopost HH:MM 키워드")
        return

    try:
        time_str = context.args[0]
        hour, minute = map(int, time_str.split(":"))
        keyword = " ".join(context.args[1:]).strip()
    except Exception:
        await update.message.reply_text("형식 오류: /autopost 21:30 슬롯 무료스핀 이벤트")
        return

    if not keyword:
        await update.message.reply_text("키워드를 입력하세요.")
        return

    try:
        result = ai_service.generate_post(
            keyword=keyword,
            language=DEFAULT_LANGUAGE,
        )

        title = f"[AUTO] {keyword}"
        cta_link = "https://example.com"

        post_id = create_post(
            source="auto-ai",
            language=DEFAULT_LANGUAGE,
            title=title,
            body=result,
            cta_link=cta_link,
            media_type="text",
            media_path="",
            thumbnail_path="",
            platform_meta_json="{}",
        )

        job = scheduler.add_job(
            scheduled_publish_telegram,
            "cron",
            hour=hour,
            minute=minute,
            args=[
                context.bot,
                CHANNEL_ID,
                title,
                result,
                cta_link,
                "text",
                "",
                "",
                "{}",
            ],
        )

        update_post_status(post_id, "scheduled")

        await update.message.reply_text(
            f"자동생성 + 예약 완료\n\n"
            f"ID: {post_id}\n"
            f"JOB_ID: {job.id}\n"
            f"시간: {time_str}\n"
            f"키워드: {keyword}\n\n"
            f"{result}"
        )

    except Exception as e:
        await update.message.reply_text(f"자동 예약 실패: {e}")


async def deletepost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("사용법: /deletepost 게시물ID")
        return

    try:
        post_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("게시물 ID는 숫자여야 합니다.")
        return

    deleted = delete_post(post_id)

    if deleted:
        await update.message.reply_text(f"삭제 완료: ID {post_id}")
    else:
        await update.message.reply_text("해당 게시물을 찾을 수 없습니다.")


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    jobs = list_jobs()
    if not jobs:
        await update.message.reply_text("현재 예약된 작업이 없습니다.")
        return

    lines = []
    for job in jobs:
        lines.append(
            f"JOB_ID: {job.id}\n"
            f"다음 실행: {job.next_run_time}\n"
            f"함수: {job.func.__name__}\n"
        )

    await update.message.reply_text("\n".join(lines))


async def canceljob_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("사용법: /canceljob JOB_ID")
        return

    job_id = context.args[0].strip()
    removed = remove_job(job_id)

    if removed:
        await update.message.reply_text(f"예약 취소 완료: {job_id}")
    else:
        await update.message.reply_text("해당 JOB_ID를 찾을 수 없습니다.")


async def trend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    keyword = " ".join(context.args).strip()
    if not keyword:
        await update.message.reply_text("사용법: /trend 키워드")
        return

    prompt_keyword = f"{keyword} 트렌드형 콘텐츠 아이디어"

    try:
        result = ai_service.generate_ideas(keyword=prompt_keyword)
        await update.message.reply_text(
            f"[트렌드형 아이디어]\n\n키워드: {keyword}\n\n{result}"
        )
    except Exception as e:
        await update.message.reply_text(f"Trend 생성 실패: {e}")


async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    keyword = " ".join(context.args).strip()
    if not keyword:
        await update.message.reply_text("사용법: /ai 키워드")
        return

    try:
        result = ai_service.generate_post(
            keyword=keyword,
            language=DEFAULT_LANGUAGE,
        )

        title = f"[AI] {keyword}"

        post_id = create_post(
            source="ai",
            language=DEFAULT_LANGUAGE,
            title=title,
            body=result,
            cta_link="https://example.com",
            media_type="text",
            media_path="",
            thumbnail_path="",
            platform_meta_json="{}",
        )

        await update.message.reply_text(
            f"{result}\n\n저장 완료: ID {post_id}"
        )

    except Exception as e:
        await update.message.reply_text(f"AI 생성 실패: {e}")


async def rewrite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    raw = " ".join(context.args).strip()
    if "|" not in raw:
        await update.message.reply_text("사용법: /rewrite 스타일 | 문장")
        return

    style, text = [x.strip() for x in raw.split("|", 1)]

    try:
        result = ai_service.rewrite(style=style, text=text)
        await update.message.reply_text(result)
    except Exception as e:
        await update.message.reply_text(f"Rewrite 실패: {e}")


async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    raw = " ".join(context.args).strip()
    if "|" not in raw:
        await update.message.reply_text("사용법: /translate 언어 | 문장")
        return

    target_language, text = [x.strip() for x in raw.split("|", 1)]

    try:
        result = ai_service.translate(target_language=target_language, text=text)
        await update.message.reply_text(result)
    except Exception as e:
        await update.message.reply_text(f"Translate 실패: {e}")


async def hashtags_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    keyword = " ".join(context.args).strip()
    if not keyword:
        await update.message.reply_text("사용법: /hashtags 키워드")
        return

    try:
        result = ai_service.generate_hashtags(keyword=keyword)
        await update.message.reply_text(result)
    except Exception as e:
        await update.message.reply_text(f"Hashtags 실패: {e}")


async def ideas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    keyword = " ".join(context.args).strip()
    if not keyword:
        await update.message.reply_text("사용법: /ideas 키워드")
        return

    try:
        result = ai_service.generate_ideas(keyword=keyword)
        await update.message.reply_text(result)
    except Exception as e:
        await update.message.reply_text(f"Ideas 실패: {e}")


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    count = count_users()
    rows = list_users()[:20]

    lines = [f"전체 유저: {count}명\n"]
    for row in rows:
        uid, username, join_time, source = row
        lines.append(
            f"USER_ID: {uid}\n"
            f"USERNAME: {username}\n"
            f"SOURCE: {source}\n"
            f"JOINED: {join_time}\n"
        )

    await update.message.reply_text("\n".join(lines))


async def dev_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if context.args:
        command_text = " ".join(context.args).strip()
        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "trigger_ai_pipeline.py")
        try:
            result = subprocess.run(
                [sys.executable, script_path, command_text],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                await update.message.reply_text(f"✅ AI 파이프라인 트리거 완료: {command_text}")
            else:
                await update.message.reply_text(
                    f"❌ 파이프라인 트리거 실패:\n{result.stderr.strip() or result.stdout.strip()}"
                )
        except Exception as e:
            await update.message.reply_text(f"⚠️ 파이프라인 트리거 오류: {e}")
        return

    env = os.getenv("SENTRY_ENVIRONMENT") or os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "development"
    jobs = list_jobs()
    posts = list_posts()
    user_count = count_users()
    video_jobs = list_video_jobs()
    campaigns = list_campaigns()

    status_counts: dict[str, int] = {}
    for row in posts:
        _, _, _, _, st, _, _ = row
        status_counts[st] = status_counts.get(st, 0) + 1

    status_lines = "\n".join(
        f"  {st}: {cnt}개" for st, cnt in sorted(status_counts.items())
    ) or "  없음"

    text = (
        f"[개발 제어 패널]\n\n"
        f"환경: {env}\n"
        f"봇: @{BOT_USERNAME or '(미설정)'}\n\n"
        f"[DB 현황]\n"
        f"게시물: {len(posts)}개\n"
        f"{status_lines}\n"
        f"유저: {user_count}명\n"
        f"영상 작업: {len(video_jobs)}개\n"
        f"캠페인: {len(campaigns)}개\n\n"
        f"[스케줄러]\n"
        f"예약 작업: {len(jobs)}개\n"
    )

    if jobs:
        job_lines = []
        for job in jobs:
            next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else "-"
            job_lines.append(f"  {job.id} / {next_run}")
        text += "\n".join(job_lines)

    await update.message.reply_text(text)


ADMIN_MENU_BUTTONS = {
    "find_groups": "find_groups",
    "scrape_members": "scrape_members",
    "show_stats": "show_stats",
    "export_csv": "export_csv",
}


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        print(f"DEBUG: 어드민 명령어 수신! (받은 ID: {update.effective_user.id}, 설정된 ADMIN_ID: {ADMIN_ID})")
        user_id = update.effective_user.id if update.effective_user else None

        if not is_admin(user_id):
            await update.message.reply_text(f"권한이 없습니다(ID: {user_id})")
            return

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔍 타겟 그룹 찾기",
                        callback_data=ADMIN_MENU_BUTTONS["find_groups"],
                    )
                ],
                [
                    InlineKeyboardButton(
                        "👥 유저 아이디 수집",
                        callback_data=ADMIN_MENU_BUTTONS["scrape_members"],
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📊 수집 현황 확인",
                        callback_data=ADMIN_MENU_BUTTONS["show_stats"],
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📤 CSV 내보내기",
                        callback_data=ADMIN_MENU_BUTTONS["export_csv"],
                    )
                ],
            ]
        )

        await update.message.reply_text(
            "관리자 제어 패널입니다.\n원하시는 작업을 선택하세요.",
            reply_markup=keyboard,
        )
    except Exception as e:
        print(f"DEBUG: 에러 발생! {e}")
        raise


async def _handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not update.effective_user:
        return

    if not is_admin(update.effective_user.id):
        await query.answer("권한이 없습니다.", show_alert=True)
        return

    data = query.data or ""

    if data == ADMIN_MENU_BUTTONS["find_groups"]:
        await query.answer()
        await query.edit_message_text("🔍 구글에서 경쟁사 텔레그램 그룹을 탐색 중입니다...")

        loop = context.application.loop

        async def run_in_thread():
            from asyncio import to_thread

            def _work():
                return find_competitor_telegram_links()

            links = await to_thread(_work)
            count = len(links)
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=f"✅ 타겟 그룹 탐색 완료\n발견된 텔레그램 링크: {count}개",
            )

        loop.create_task(run_in_thread())
        return

    if data == ADMIN_MENU_BUTTONS["scrape_members"]:
        await query.answer()
        await query.edit_message_text("👥 경쟁사 그룹 멤버 수집을 시작합니다...")

        loop = context.application.loop

        async def run_members():
            from asyncio import to_thread

            # Telethon 진입점은 run_member_scraper (동기 wrapper) 사용
            await to_thread(run_member_scraper)
            total = count_competitor_users()
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=(
                    "✅ 멤버 수집 작업이 완료되었습니다.\n"
                    f"현재 competitor_users 테이블 유저 수: {total}명"
                ),
            )

        loop.create_task(run_members())
        return

    if data == ADMIN_MENU_BUTTONS["show_stats"]:
        await query.answer()
        total = count_competitor_users()
        await query.edit_message_text(
            f"📊 현재 competitor_users 에 저장된 유저 수: {total}명"
        )
        return

    if data == ADMIN_MENU_BUTTONS["export_csv"]:
        await query.answer()
        await query.edit_message_text("📤 CSV 생성 중... (청크 단위 처리)")

        loop = context.application.loop

        async def run_export():
            from asyncio import to_thread

            fd, path = tempfile.mkstemp(suffix=".csv")
            try:
                os.close(fd)
                row_count = await to_thread(
                    lambda: export_competitor_users_to_csv_file(path, chunk_size=500)
                )
                filename = f"competitor_users_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
                with open(path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=update.effective_user.id,
                        document=f,
                        filename=filename,
                    )
                await query.edit_message_text(
                    f"✅ CSV 전송 완료\n총 {row_count}명"
                )
            except Exception as e:
                await query.edit_message_text(f"❌ CSV 내보내기 실패: {e}")
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass

        loop.create_task(run_export())
        return


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    step = context.user_data.get("newpost_step")
    if not step:
        return

    text = update.message.text.strip()
    data = context.user_data.get("newpost_data", {})

    if step == "language":
        data["language"] = text
        context.user_data["newpost_data"] = data
        context.user_data["newpost_step"] = "title"
        await update.message.reply_text("2단계: 제목을 입력하세요.")
        return

    if step == "title":
        data["title"] = text
        context.user_data["newpost_data"] = data
        context.user_data["newpost_step"] = "body"
        await update.message.reply_text("3단계: 본문을 입력하세요.")
        return

    if step == "body":
        data["body"] = text
        context.user_data["newpost_data"] = data
        context.user_data["newpost_step"] = "cta_link"
        await update.message.reply_text("4단계: CTA 링크를 입력하세요.")
        return

    if step == "cta_link":
        data["cta_link"] = text

        post_id = create_post(
            source="manual",
            language=data["language"],
            title=data["title"],
            body=data["body"],
            cta_link=data["cta_link"],
            media_type="text",
            media_path="",
            thumbnail_path="",
            platform_meta_json="{}",
        )

        context.user_data.pop("newpost_step", None)
        context.user_data.pop("newpost_data", None)

        await update.message.reply_text(
            f"게시물 저장 완료\n\n"
            f"ID: {post_id}\n"
            f"언어: {data['language']}\n"
            f"제목: {data['title']}\n\n"
            f"/publish {post_id} telegram\n"
            f"/schedule {post_id} 21:30 telegram"
        )


async def telegram_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    capture_telegram_runtime_error(update, context.error)


def get_handlers():
    return [
        CommandHandler("start", start_command),
        CommandHandler("admin", admin_command),
        CommandHandler("newpost", newpost_command),
        CommandHandler("list", list_command),
        CommandHandler("showpost", showpost_command),
        CommandHandler("attachmedia", attachmedia_command),
        CommandHandler("attachthumb", attachthumb_command),
        CommandHandler("setmeta", setmeta_command),
        CommandHandler("requestvideo", requestvideo_command),
        CommandHandler("completevideo", completevideo_command),
        CommandHandler("videojobs", videojobs_command),
        CommandHandler("variants", variants_command),
        CommandHandler("autopipeline", autopipeline_command),
        CommandHandler("factory", factory_command),
        CommandHandler("leadpost", leadpost_command),
        CommandHandler("campaigncreate", campaigncreate_command),
        CommandHandler("campaigns", campaigns_command),
        CommandHandler("campaigndetail", campaigndetail_command),
        CommandHandler("campaignrun", campaignrun_command),
        CommandHandler("campaigndelete", campaigndelete_command),
        CommandHandler("publish", publish_command),
        CommandHandler("schedule", schedule_command),
        CommandHandler("autopost", autopost_command),
        CommandHandler("deletepost", deletepost_command),
        CommandHandler("queue", queue_command),
        CommandHandler("canceljob", canceljob_command),
        CommandHandler("trend", trend_command),
        CommandHandler("ai", ai_command),
        CommandHandler("rewrite", rewrite_command),
        CommandHandler("translate", translate_command),
        CommandHandler("hashtags", hashtags_command),
        CommandHandler("ideas", ideas_command),
        CommandHandler("users", users_command),
        CommandHandler("dev", dev_command),
        CallbackQueryHandler(_handle_admin_callback),
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler),
    ]
