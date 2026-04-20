"""
bot.handlers — 구독봇 핸들러 공통 모듈.

공유 상수, 유틸 함수, 키보드 빌더를 제공합니다.
"""
from __future__ import annotations

import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger("subscribe_bot")

# ── 환경변수 ──────────────────────────────────────────────────────────────────
SUBSCRIBE_BOT_TOKEN = (os.getenv("SUBSCRIBE_BOT_TOKEN") or "").strip()
AFFILIATE_URL = (os.getenv("AFFILIATE_URL") or "https://t.me").strip()
ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID: int | None = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None
CHANNEL_ID_RAW = (os.getenv("CHANNEL_ID") or "").strip()
CHANNEL_ID: int = int(CHANNEL_ID_RAW) if CHANNEL_ID_RAW.lstrip("-").isdigit() else 0

# ── 콜백 데이터 상수 ──────────────────────────────────────────────────────────
CB_HOME = "sub_home"
CB_SEND = "sub_send"
CB_STATUS = "sub_status"
CB_CONFIRM = "sub_confirm_send"
CB_CANCEL = "sub_confirm_cancel"
CB_POSTS_LIST = "sub_posts_list"
CB_POST_ADD = "sub_post_add"
CB_POST_DELETE = "sub_post_delete"
# 설정 관리
CB_CONFIG = "sub_config"
CB_CONFIG_URL = "sub_cfg_url"
CB_CONFIG_VIEW = "sub_cfg_view"
CB_CONFIG_BTN_TEXT = "sub_cfg_btn_text"
# 토픽 관리
CB_TOPICS_LIST = "sub_topics_list"
CB_TOPICS_CREATE = "sub_topics_create"
CB_TOPICS_POST = "sub_topics_post"

# context.user_data 키: 텍스트 입력 대기 중인 필드명
AWAITING_KEY = "sub_awaiting"

# 입력 대기 필드 → 표시 이름 매핑
FIELD_LABELS: dict[str, str] = {
    "affiliate_url": "어필리에이트 링크",
    "button_text": "DM 버튼 텍스트",
}


# ── 유틸 함수 ─────────────────────────────────────────────────────────────────


def is_admin(user_id: int | None) -> bool:
    """관리자 여부 확인."""
    return ADMIN_ID is not None and user_id is not None and user_id == ADMIN_ID


# ── 키보드 빌더 ──────────────────────────────────────────────────────────────


def admin_keyboard() -> InlineKeyboardMarkup:
    """관리자 메인 메뉴 키보드."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 게시물 목록", callback_data=CB_POSTS_LIST)],
        [InlineKeyboardButton("➕ 게시물 추가", callback_data=CB_POST_ADD)],
        [InlineKeyboardButton("🗑 게시물 삭제", callback_data=CB_POST_DELETE)],
        [InlineKeyboardButton("📤 즉시 전체 발송", callback_data=CB_SEND)],
        [InlineKeyboardButton("📊 구독자 현황", callback_data=CB_STATUS)],
        [InlineKeyboardButton("📌 그룹 토픽 관리", callback_data=CB_TOPICS_LIST)],
        [InlineKeyboardButton("⚙️ 캠페인 설정", callback_data=CB_CONFIG)],
    ])


def config_keyboard() -> InlineKeyboardMarkup:
    """캠페인 설정 메뉴 키보드."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 링크 변경", callback_data=CB_CONFIG_URL)],
        [InlineKeyboardButton("🔘 DM 버튼 텍스트 변경", callback_data=CB_CONFIG_BTN_TEXT)],
        [InlineKeyboardButton("👁 현재 설정 확인", callback_data=CB_CONFIG_VIEW)],
        [InlineKeyboardButton("🏠 메인 메뉴", callback_data=CB_HOME)],
    ])


def home_keyboard() -> InlineKeyboardMarkup:
    """메인 메뉴로 돌아가기 키보드."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 메인 메뉴", callback_data=CB_HOME)]]
    )


def posts_delete_keyboard(posts: list[dict]) -> InlineKeyboardMarkup:
    """게시물별 삭제 버튼 키보드."""
    rows = []
    for p in posts[:10]:
        cap_preview = (p["caption"] or "")[:20] or "(캡션없음)"
        label = f"🗑 #{p['id']} [{p['file_type']}] {cap_preview}"
        rows.append([InlineKeyboardButton(label, callback_data=f"sub_del_{p['id']}")])
    rows.append([InlineKeyboardButton("🏠 메인 메뉴", callback_data=CB_HOME)])
    return InlineKeyboardMarkup(rows)
