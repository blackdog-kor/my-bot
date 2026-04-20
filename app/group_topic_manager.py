"""
Group Topic Manager: 포럼 토픽 자동 생성 및 콘텐츠 라우팅.
"""
from __future__ import annotations

import asyncio
from typing import Any

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.group_topic_db import (
    ensure_forum_topics_table,
    get_topic_by_content_type,
    list_topics,
    save_topic,
)
from app.logging_config import get_logger

logger = get_logger("group_topic_manager")

__all__ = [
    "ensure_forum_topics_table",
    "list_topics",
    "save_topic",
    "get_topic_by_content_type",
    "create_forum_topics",
    "classify_content",
    "post_to_topic",
    "auto_post_campaign_to_topics",
    "DEFAULT_TOPICS",
]

# ── 기본 토픽 정의 ─────────────────────────────────────────────────────────────

DEFAULT_TOPICS: list[dict[str, Any]] = [
    {
        "name": "📢 공지사항",
        "icon_color": 0x6FB9F0,
        "content_type": "announcement",
        "description": "운영 공지, 규칙, 이벤트 안내",
    },
    {
        "name": "🎰 오늘의 추천",
        "icon_color": 0xFFD67E,
        "content_type": "promotion",
        "description": "일일 카지노 추천/프로모션",
    },
    {
        "name": "💰 입출금 인증",
        "icon_color": 0xCB86DB,
        "content_type": "verification",
        "description": "회원 입출금 인증 스크린샷",
    },
    {
        "name": "🏆 당첨 후기",
        "icon_color": 0x8EEE98,
        "content_type": "winning",
        "description": "대박/수익 인증",
    },
    {
        "name": "❓ 질문/문의",
        "icon_color": 0xFF93B2,
        "content_type": "question",
        "description": "가입 방법, 보너스 문의",
    },
    {
        "name": "🎁 보너스 코드",
        "icon_color": 0xFB6F5F,
        "content_type": "bonus_code",
        "description": "한정 프로모션 코드 공유 (24시간 자동삭제)",
    },
    {
        "name": "💬 자유게시판",
        "icon_color": 0xFFD67E,
        "content_type": "general",
        "description": "일반 대화",
    },
]


# ── 토픽 생성 (Telegram API) ───────────────────────────────────────────────────

async def create_forum_topics(
    bot_token: str | None = None,
    group_id: str | None = None,
) -> list[dict]:
    """그룹에 포럼 토픽을 생성하고 DB에 저장.

    Returns:
        생성된 토픽 목록 [{name, thread_id, content_type}, ...]
    """
    token = bot_token or settings.subscribe_bot_token
    gid = group_id or settings.group_id

    if not token:
        logger.error("BOT_TOKEN 미설정 — 토픽 생성 불가")
        return []
    if not gid:
        logger.error("GROUP_ID 미설정 — 토픽 생성 불가")
        return []

    bot = Bot(token=token)
    created: list[dict] = []
    existing = list_topics()
    existing_types = {t["content_type"] for t in existing}

    for topic_def in DEFAULT_TOPICS:
        if topic_def["content_type"] in existing_types:
            logger.info("토픽 이미 존재: %s — 스킵", topic_def["name"])
            continue

        try:
            result = await bot.create_forum_topic(
                chat_id=int(gid),
                name=topic_def["name"],
                icon_color=topic_def["icon_color"],
            )
            thread_id = result.message_thread_id

            save_topic(
                thread_id=thread_id,
                name=topic_def["name"],
                content_type=topic_def["content_type"],
                icon_color=topic_def["icon_color"],
                description=topic_def["description"],
            )

            created.append({
                "name": topic_def["name"],
                "thread_id": thread_id,
                "content_type": topic_def["content_type"],
            })
            logger.info("토픽 생성 완료: %s (thread_id=%d)", topic_def["name"], thread_id)

            # Rate limit 방지
            await asyncio.sleep(1.0)

        except Exception as e:
            logger.exception("토픽 생성 실패 (%s): %s", topic_def["name"], e)

    return created


# ── 콘텐츠 라우팅 (토픽별 자동 게시) ────────────────────────────────────────────


def classify_content(caption: str, file_type: str = "") -> str:
    """콘텐츠를 content_type으로 분류 (키워드 기반, file_type은 향후 확장용)."""
    text = (caption or "").lower()

    # 공지사항 키워드
    if any(kw in text for kw in ["공지", "규칙", "안내", "notice", "rule", "변경"]):
        return "announcement"

    # 보너스 코드
    if any(kw in text for kw in ["보너스코드", "bonus code", "프로모코드", "promo code", "쿠폰"]):
        return "bonus_code"

    # 입출금 인증
    if any(kw in text for kw in ["입금", "출금", "인증", "deposit", "withdraw"]):
        return "verification"

    # 당첨 후기
    if any(kw in text for kw in ["당첨", "대박", "수익", "win", "jackpot", "후기"]):
        return "winning"

    # 질문/문의
    if any(kw in text for kw in ["질문", "문의", "어떻게", "방법", "가입", "?", "question"]):
        return "question"

    # 기본: 프로모션/추천
    return "promotion"


async def post_to_topic(
    content_type: str,
    text: str,
    file_id: str | None = None,
    file_type: str = "text",
    bot_token: str | None = None,
    group_id: str | None = None,
    affiliate_url: str | None = None,
    button_text: str = "🎰 지금 플레이하기",
) -> bool:
    """지정된 content_type의 토픽에 콘텐츠를 게시."""
    token = bot_token or settings.subscribe_bot_token
    gid = group_id or settings.group_id

    if not token or not gid:
        logger.error("BOT_TOKEN 또는 GROUP_ID 미설정 — 토픽 게시 불가")
        return False

    topic = get_topic_by_content_type(content_type)
    if not topic:
        logger.warning("토픽을 찾을 수 없음: content_type=%s", content_type)
        return False

    thread_id = topic["thread_id"]
    bot = Bot(token=token)

    # 인라인 버튼 (어필리에이트 링크)
    url = affiliate_url or settings.affiliate_url or settings.vip_url
    keyboard = None
    if url and content_type in ("promotion", "announcement", "bonus_code"):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(text=button_text, url=url)]
        ])

    try:
        if file_type == "photo" and file_id:
            await bot.send_photo(
                chat_id=int(gid),
                photo=file_id,
                caption=text or None,
                message_thread_id=thread_id,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        elif file_type == "video" and file_id:
            try:
                await bot.send_video(
                    chat_id=int(gid),
                    video=file_id,
                    caption=text or None,
                    message_thread_id=thread_id,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            except Exception as vid_err:
                logger.warning("send_video failed, fallback to document: %s", vid_err)
                await bot.send_document(
                    chat_id=int(gid),
                    document=file_id,
                    caption=text or None,
                    message_thread_id=thread_id,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
        else:
            await bot.send_message(
                chat_id=int(gid),
                text=text,
                message_thread_id=thread_id,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )

        logger.info(
            "토픽 게시 성공: [%s] thread_id=%d, file_type=%s",
            content_type, thread_id, file_type,
        )
        return True

    except Exception as e:
        logger.exception("토픽 게시 실패 [%s]: %s", content_type, e)
        return False


async def auto_post_campaign_to_topics(
    bot_token: str | None = None,
    group_id: str | None = None,
) -> int:
    """campaign_posts의 다음 게시물을 분류하여 적절한 토픽에 게시.

    Returns:
        게시된 수
    """
    from app.pg_broadcast import get_next_post, get_campaign_config

    post = get_next_post()
    if not post or not post.get("file_id"):
        logger.info("토픽 게시 대상 없음")
        return 0

    cfg = get_campaign_config()
    affiliate_url = (cfg.get("affiliate_url") or "").strip() or settings.affiliate_url
    btn_text = (cfg.get("button_text") or "🎰 VIP 카지노 입장").strip()

    caption = post["caption"] or ""
    file_type = post["file_type"]
    content_type = classify_content(caption, file_type)

    success = await post_to_topic(
        content_type=content_type,
        text=caption,
        file_id=post["file_id"],
        file_type=file_type,
        bot_token=bot_token,
        group_id=group_id,
        affiliate_url=affiliate_url,
        button_text=btn_text,
    )

    return 1 if success else 0
