import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_update(user_id=42, username="testuser", has_message=True):
    user = MagicMock()
    user.id = user_id
    user.username = username

    update = MagicMock()
    update.effective_user = user
    update.effective_chat = MagicMock()
    update.effective_chat.id = 777
    if has_message:
        update.message = MagicMock()
        update.message.message_id = 555
    else:
        update.message = None

    return update


@pytest.mark.asyncio
async def test_start_replies_to_user():
    """start must always send the language-selection reply."""
    update = _make_update()
    context = MagicMock()
    context.user_data = {}
    context.bot.delete_message = AsyncMock()
    prompt_message = MagicMock()
    prompt_message.message_id = 999
    context.bot.send_message = AsyncMock(return_value=prompt_message)

    with patch("handlers.callbacks.send_user_entry_event", new=AsyncMock()) as mock_sns:
        from handlers.callbacks import start
        await start(update, context)

    context.bot.send_message.assert_called_once()
    reply_text = context.bot.send_message.call_args.kwargs["text"]
    assert "What is your language?" in reply_text


@pytest.mark.asyncio
async def test_start_sends_user_entry_event():
    """start must trigger exactly one sns user_entry event with correct data."""
    update = _make_update(user_id=99, username="snsuser")
    context = MagicMock()
    context.user_data = {}
    context.bot.delete_message = AsyncMock()
    prompt_message = MagicMock()
    prompt_message.message_id = 999
    context.bot.send_message = AsyncMock(return_value=prompt_message)

    with patch("handlers.callbacks.send_user_entry_event", new=AsyncMock()) as mock_sns:
        from handlers.callbacks import start
        await start(update, context)

    mock_sns.assert_called_once_with(telegram_user_id=99, username="snsuser")


@pytest.mark.asyncio
async def test_start_still_replies_when_sns_fails():
    """sns failure must not prevent the reply from being sent."""
    update = _make_update()
    context = MagicMock()
    context.user_data = {}
    context.bot.delete_message = AsyncMock()
    prompt_message = MagicMock()
    prompt_message.message_id = 999
    context.bot.send_message = AsyncMock(return_value=prompt_message)

    with patch(
        "handlers.callbacks.send_user_entry_event",
        new=AsyncMock(side_effect=RuntimeError("fail")),
    ):
        from handlers.callbacks import start
        # Must not raise — handler swallows sns errors
        await start(update, context)

    context.bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_start_no_sns_event_without_effective_user():
    """If effective_user is None, no sns event should be dispatched."""
    update = _make_update()
    update.effective_user = None
    context = MagicMock()
    context.user_data = {}
    context.bot.delete_message = AsyncMock()
    prompt_message = MagicMock()
    prompt_message.message_id = 999
    context.bot.send_message = AsyncMock(return_value=prompt_message)

    with patch("handlers.callbacks.send_user_entry_event", new=AsyncMock()) as mock_sns:
        from handlers.callbacks import start
        await start(update, context)

    mock_sns.assert_not_called()


@pytest.mark.asyncio
async def test_start_no_message_still_sends_event():
    """Even without a message, the sns event must fire when user is present."""
    update = _make_update(has_message=False)
    context = MagicMock()
    context.user_data = {}
    context.bot.delete_message = AsyncMock()
    prompt_message = MagicMock()
    prompt_message.message_id = 999
    context.bot.send_message = AsyncMock(return_value=prompt_message)

    with patch("handlers.callbacks.send_user_entry_event", new=AsyncMock()) as mock_sns:
        from handlers.callbacks import start
        await start(update, context)

    mock_sns.assert_called_once_with(telegram_user_id=42, username="testuser")
