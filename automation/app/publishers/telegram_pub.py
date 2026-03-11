import os
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _build_text(title: str, body: str, cta_link: str | None = None) -> str:
    text = f"{title}\n\n{body}"
    if cta_link:
        text += f"\n\n{cta_link}"
    return text


def _build_keyboard(cta_link: str | None = None):
    if not cta_link:
        return None

    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔥 Enter Casino", url=cta_link)]]
    )


async def _send_with_media(
    bot,
    channel_id: str,
    title: str,
    body: str,
    cta_link: str | None = None,
    media_type: str = "text",
    media_path: str = "",
):
    text = _build_text(title, body, cta_link)
    keyboard = _build_keyboard(cta_link)

    if media_type == "image" and media_path:
        if media_path.startswith("http://") or media_path.startswith("https://"):
            await bot.send_photo(
                chat_id=channel_id,
                photo=media_path,
                caption=text[:1000],
                reply_markup=keyboard,
            )
            if len(text) > 1000:
                await bot.send_message(chat_id=channel_id, text=text[1000:])
            return

        if os.path.exists(media_path):
            with open(media_path, "rb") as f:
                await bot.send_photo(
                    chat_id=channel_id,
                    photo=f,
                    caption=text[:1000],
                    reply_markup=keyboard,
                )
                if len(text) > 1000:
                    await bot.send_message(chat_id=channel_id, text=text[1000:])
            return

    if media_type == "video" and media_path:
        if media_path.startswith("http://") or media_path.startswith("https://"):
            await bot.send_video(
                chat_id=channel_id,
                video=media_path,
                caption=text[:1000],
                reply_markup=keyboard,
                supports_streaming=True,
            )
            if len(text) > 1000:
                await bot.send_message(chat_id=channel_id, text=text[1000:])
            return

        if os.path.exists(media_path):
            with open(media_path, "rb") as f:
                await bot.send_video(
                    chat_id=channel_id,
                    video=f,
                    caption=text[:1000],
                    reply_markup=keyboard,
                    supports_streaming=True,
                )
                if len(text) > 1000:
                    await bot.send_message(chat_id=channel_id, text=text[1000:])
            return

    await bot.send_message(
        chat_id=channel_id,
        text=text,
        reply_markup=keyboard,
        disable_web_page_preview=False,
    )


async def publish_to_telegram_channel(
    context,
    channel_id: str,
    title: str,
    body: str,
    cta_link: str | None = None,
    media_type: str = "text",
    media_path: str = "",
    thumbnail_path: str = "",
    platform_meta_json: str = "{}",
):
    await _send_with_media(
        bot=context.bot,
        channel_id=channel_id,
        title=title,
        body=body,
        cta_link=cta_link,
        media_type=media_type,
        media_path=media_path,
    )


def scheduled_publish_telegram(
    bot,
    channel_id: str,
    title: str,
    body: str,
    cta_link: str | None = None,
    media_type: str = "text",
    media_path: str = "",
    thumbnail_path: str = "",
    platform_meta_json: str = "{}",
):
    asyncio.run(
        _send_with_media(
            bot=bot,
            channel_id=channel_id,
            title=title,
            body=body,
            cta_link=cta_link,
            media_type=media_type,
            media_path=media_path,
        )
    )
