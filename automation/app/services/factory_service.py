from app.db import create_post, create_video_job
from app.services.ai_service import AIService


class FactoryService:
    def __init__(self):
        self.ai_service = AIService()

    def create_factory_job(
        self,
        keyword: str,
        language: str,
        engine: str = "runway",
    ) -> tuple[int, str]:
        body = self.ai_service.generate_post(
            keyword=keyword,
            language=language,
        )

        title = f"[FACTORY] {keyword}"
        cta_link = "https://example.com"

        post_id = create_post(
            source="factory-ai",
            language=language,
            title=title,
            body=body,
            cta_link=cta_link,
            media_type="text",
            media_path="",
            thumbnail_path="",
            platform_meta_json="{}",
        )

        payload = {
            "post_id": post_id,
            "title": title,
            "body": body,
            "language": language,
            "cta_link": cta_link,
            "auto_publish_platforms": ["telegram"],
            "auto_publish_on_complete": True,
        }

        job_id = create_video_job(
            post_id=post_id,
            engine=engine,
            payload=payload,
        )

        return post_id, job_id
