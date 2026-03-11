from app.db import create_post, create_video_job
from app.services.ai_service import AIService


class PipelineService:
    def __init__(self):
        self.ai_service = AIService()

    def create_pipeline(self, keyword: str, language: str, engine: str = "runway") -> tuple[int, str]:
        body = self.ai_service.generate_post(
            keyword=keyword,
            language=language,
        )

        title = f"[AUTO] {keyword}"

        post_id = create_post(
            source="auto-pipeline",
            language=language,
            title=title,
            body=body,
            cta_link="https://example.com",
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
            "cta_link": "https://example.com",
        }

        job_id = create_video_job(
            post_id=post_id,
            engine=engine,
            payload=payload,
        )

        return post_id, job_id
