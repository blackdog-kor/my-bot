import os


async def publish_to_youtube(
    title,
    body,
    cta_link=None,
    media_type="text",
    media_path="",
    thumbnail_path="",
    platform_meta_json="{}",
):
    if media_type != "video":
        raise Exception("youtube publish requires media_type=video")

    if not media_path:
        raise Exception("video path is empty")

    if not os.path.exists(media_path):
        raise Exception("video file not found")

    print("===== YouTube Upload Simulation =====")
    print("Title:", title)
    print("Body:", body)
    print("CTA Link:", cta_link)
    print("Media Type:", media_type)
    print("Video:", media_path)
    print("Thumbnail:", thumbnail_path)
    print("Platform Meta:", platform_meta_json)

    return {
        "platform": "youtube",
        "status": "uploaded",
        "video_path": media_path,
    }
