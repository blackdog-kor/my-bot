async def publish_to_instagram(
    title: str,
    body: str,
    cta_link: str,
    media_type: str = "text",
    media_path: str = "",
    thumbnail_path: str = "",
    platform_meta_json: str = "{}",
) -> None:
    raise NotImplementedError(
        "Instagram publisher is not connected yet. "
        "Media-ready payload shape is already prepared."
    )
