"""
bot/handlers/callbacks.py 핸들러 동작을 검증한다.

실제 핸들러: admin_command, callback, admin_load_message_handler
(이전 코드에 있던 start / send_user_entry_event 는 제거됨)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

import bot.handlers.callbacks as cb


# ── _is_admin() ──────────────────────────────────────────────────────────────

def test_is_admin_correct_id(monkeypatch):
    monkeypatch.setattr(cb, "ADMIN_ID", 123)
    assert cb._is_admin(123) is True


def test_is_admin_wrong_id(monkeypatch):
    monkeypatch.setattr(cb, "ADMIN_ID", 123)
    assert cb._is_admin(456) is False


def test_is_admin_none_user_id(monkeypatch):
    monkeypatch.setattr(cb, "ADMIN_ID", 123)
    assert cb._is_admin(None) is False


def test_is_admin_no_admin_configured(monkeypatch):
    monkeypatch.setattr(cb, "ADMIN_ID", None)
    assert cb._is_admin(123) is False


# ── admin_command() ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_command_rejects_non_admin(monkeypatch):
    """관리자가 아닌 유저는 '권한이 없습니다.' 응답을 받아야 한다."""
    monkeypatch.setattr(cb, "ADMIN_ID", 999)

    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 42  # NOT admin

    await cb.admin_command(update, MagicMock())

    update.message.reply_text.assert_called_once_with("권한이 없습니다.")


@pytest.mark.asyncio
async def test_admin_command_sends_menu_to_admin(monkeypatch):
    """관리자에게는 관리자 메뉴 텍스트를 포함한 reply가 전송돼야 한다."""
    monkeypatch.setattr(cb, "ADMIN_ID", 42)

    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 42  # Admin

    await cb.admin_command(update, MagicMock())

    update.message.reply_text.assert_called_once()
    call_args = update.message.reply_text.call_args
    # 첫 번째 위치 인자에 '관리자'가 포함돼야 한다.
    text = call_args.args[0] if call_args.args else call_args.kwargs.get("text", "")
    assert "관리자" in text


@pytest.mark.asyncio
async def test_admin_command_no_op_without_message(monkeypatch):
    """update.message 가 None 이면 아무 것도 하지 않아야 한다."""
    monkeypatch.setattr(cb, "ADMIN_ID", 42)

    update = MagicMock()
    update.message = None  # No message
    update.effective_user = MagicMock()
    update.effective_user.id = 42

    # Should not raise
    await cb.admin_command(update, MagicMock())
