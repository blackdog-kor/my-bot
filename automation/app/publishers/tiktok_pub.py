async def publish_to_tiktok(
    title: str,
    body: str,
    cta_link: str,
    media_type: str = "text",
    media_path: str = "",
    thumbnail_path: str = "",
    platform_meta_json: str = "{}",
) -> None:
    if media_type != "video" or not media_path:
        raise ValueError("TikTok publish requires media_type='video' and media_path.")

    raise NotImplementedError(
        "TikTok publisher is not connected yet. "
        "Media-ready payload shape is already prepared."
    )
