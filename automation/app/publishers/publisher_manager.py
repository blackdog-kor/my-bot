from app.publishers.telegram_pub import publish_to_telegram_channel
from app.publishers.instagram_pub import publish_to_instagram
from app.publishers.tiktok_pub import publish_to_tiktok
from app.publishers.youtube_pub import publish_to_youtube


class PublisherManager:
    def __init__(self, context):
        self.context = context

    async def publish(
        self,
        platform,
        channel_id,
        title,
        body,
        link=None,
        media_type="text",
        media_path="",
        thumbnail_path="",
        platform_meta_json="{}",
    ):
        if platform == "telegram":
            await publish_to_telegram_channel(
                context=self.context,
                channel_id=channel_id,
                title=title,
                body=body,
                cta_link=link,
                media_type=media_type,
                media_path=media_path,
                thumbnail_path=thumbnail_path,
                platform_meta_json=platform_meta_json,
            )
            return

        if platform == "instagram":
            await publish_to_instagram(
                title=title,
                body=body,
                cta_link=link,
                media_type=media_type,
                media_path=media_path,
                thumbnail_path=thumbnail_path,
                platform_meta_json=platform_meta_json,
            )
            return

        if platform == "tiktok":
            await publish_to_tiktok(
                title=title,
                body=body,
                cta_link=link,
                media_type=media_type,
                media_path=media_path,
                thumbnail_path=thumbnail_path,
                platform_meta_json=platform_meta_json,
            )
            return

        if platform == "youtube":
            await publish_to_youtube(
                title=title,
                body=body,
                cta_link=link,
                media_type=media_type,
                media_path=media_path,
                thumbnail_path=thumbnail_path,
                platform_meta_json=platform_meta_json,
            )
            return

        raise ValueError(f"Unsupported platform: {platform}")
