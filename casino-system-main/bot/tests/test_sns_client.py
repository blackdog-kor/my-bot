import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def clear_sns_env(monkeypatch):
    monkeypatch.delenv("SNS_AUTOMATION_URL", raising=False)
    monkeypatch.delenv("SNS_AUTOMATION_SECRET", raising=False)


@pytest.mark.asyncio
async def test_send_user_entry_event_posts_correct_payload(monkeypatch):
    monkeypatch.setenv("SNS_AUTOMATION_URL", "https://example.com/events")
    monkeypatch.setenv("SNS_AUTOMATION_SECRET", "mysecret")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("utils.sns_client.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from utils.sns_client import send_user_entry_event
        await send_user_entry_event(telegram_user_id=123, username="alice")

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args

    assert call_kwargs.args[0] == "https://example.com/events"

    sent_payload = call_kwargs.kwargs["json"]
    assert sent_payload["event_name"] == "user_entry"
    assert sent_payload["telegram_user_id"] == 123
    assert sent_payload["username"] == "alice"
    assert "event_time" in sent_payload
    # event_time must be a valid ISO 8601 string
    from datetime import datetime
    datetime.fromisoformat(sent_payload["event_time"])

    sent_headers = call_kwargs.kwargs["headers"]
    assert sent_headers["X-Secret"] == "mysecret"


@pytest.mark.asyncio
async def test_send_user_entry_event_skips_when_url_unset():
    from utils.sns_client import send_user_entry_event

    with patch("utils.sns_client.httpx.AsyncClient") as mock_cls:
        await send_user_entry_event(telegram_user_id=1, username="bob")
        mock_cls.assert_not_called()


@pytest.mark.asyncio
async def test_send_user_entry_event_logs_and_swallows_http_error(monkeypatch, caplog):
    import logging
    monkeypatch.setenv("SNS_AUTOMATION_URL", "https://example.com/events")

    with patch("utils.sns_client.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(side_effect=Exception("conn refused"))
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from utils.sns_client import send_user_entry_event
        # Must not raise
        await send_user_entry_event(telegram_user_id=99, username="carol")


@pytest.mark.asyncio
async def test_send_user_entry_event_none_username(monkeypatch):
    monkeypatch.setenv("SNS_AUTOMATION_URL", "https://example.com/events")

    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("utils.sns_client.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from utils.sns_client import send_user_entry_event
        await send_user_entry_event(telegram_user_id=7, username=None)

    sent_payload = mock_client.post.call_args.kwargs["json"]
    assert sent_payload["username"] is None
