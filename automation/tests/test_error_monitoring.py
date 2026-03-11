import os
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from app.services.error_monitoring import (
    build_telegram_update_context,
    capture_exception,
    capture_telegram_runtime_error,
    init_error_monitoring,
    _trim_text,
)
import app.services.error_monitoring as _em_module


# ---------------------------------------------------------------------------
# build_telegram_update_context
# ---------------------------------------------------------------------------


def test_build_telegram_update_context_with_command_text():
    update = SimpleNamespace(
        update_id=101,
        effective_user=SimpleNamespace(id=10, username="tester"),
        effective_chat=SimpleNamespace(id=20),
        effective_message=SimpleNamespace(text="/start promo"),
        callback_query=None,
    )

    context = build_telegram_update_context(update)

    assert context["has_update"] is True
    assert context["update_id"] == 101
    assert context["user_id"] == 10
    assert context["chat_id"] == 20
    assert context["command"] == "/start"
    assert context["message_text"] == "/start promo"
    assert context["callback_data"] is None


def test_build_telegram_update_context_without_update():
    context = build_telegram_update_context(None)
    assert context == {"has_update": False}


def test_build_telegram_update_context_with_callback_query():
    update = SimpleNamespace(
        update_id=202,
        effective_user=SimpleNamespace(id=30, username="cb_user"),
        effective_chat=SimpleNamespace(id=40),
        effective_message=SimpleNamespace(text=None),
        callback_query=SimpleNamespace(data="btn_action"),
    )

    context = build_telegram_update_context(update)

    assert context["has_update"] is True
    assert context["command"] is None
    assert context["message_text"] is None
    assert context["callback_data"] == "btn_action"


def test_build_telegram_update_context_plain_text_not_a_command():
    update = SimpleNamespace(
        update_id=303,
        effective_user=SimpleNamespace(id=50, username="plain"),
        effective_chat=SimpleNamespace(id=60),
        effective_message=SimpleNamespace(text="hello world"),
        callback_query=None,
    )

    context = build_telegram_update_context(update)

    assert context["command"] is None
    assert context["message_text"] == "hello world"


# ---------------------------------------------------------------------------
# _trim_text
# ---------------------------------------------------------------------------


def test_trim_text_short_value_unchanged():
    assert _trim_text("short") == "short"


def test_trim_text_none_returns_none():
    assert _trim_text(None) is None


def test_trim_text_long_value_truncated():
    long_str = "x" * 1500
    result = _trim_text(long_str)
    assert result is not None
    assert result.endswith("...(truncated)")
    assert len(result) < 1500


# ---------------------------------------------------------------------------
# init_error_monitoring — no DSN
# ---------------------------------------------------------------------------


def test_init_error_monitoring_without_dsn_returns_false(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setattr(_em_module, "_MONITORING_ENABLED", False)

    result = init_error_monitoring()

    assert result is False
    assert _em_module._MONITORING_ENABLED is False


def test_init_error_monitoring_empty_dsn_returns_false(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "   ")
    monkeypatch.setattr(_em_module, "_MONITORING_ENABLED", False)

    result = init_error_monitoring()

    assert result is False


# ---------------------------------------------------------------------------
# capture_exception — monitoring disabled
# ---------------------------------------------------------------------------


def test_capture_exception_does_nothing_when_disabled(monkeypatch):
    monkeypatch.setattr(_em_module, "_MONITORING_ENABLED", False)

    # Should not raise even when monitoring is off
    capture_exception(RuntimeError("test"), tags={"k": "v"}, context={"a": 1})


# ---------------------------------------------------------------------------
# capture_telegram_runtime_error — smoke test
# ---------------------------------------------------------------------------


def test_capture_telegram_runtime_error_smoke(monkeypatch):
    monkeypatch.setattr(_em_module, "_MONITORING_ENABLED", False)

    update = SimpleNamespace(
        update_id=1,
        effective_user=SimpleNamespace(id=1, username="u"),
        effective_chat=SimpleNamespace(id=1),
        effective_message=SimpleNamespace(text="/cmd"),
        callback_query=None,
    )

    # Should not raise when monitoring is disabled
    capture_telegram_runtime_error(update, ValueError("boom"))
