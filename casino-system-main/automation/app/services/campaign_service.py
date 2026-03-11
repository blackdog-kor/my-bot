from app.config import DEFAULT_LANGUAGE
from app.db import (
    create_campaign,
    get_campaign,
    list_campaign_posts,
    link_campaign_post,
    update_campaign_status,
)
from app.services.pipeline_service import PipelineService

pipeline_service = PipelineService()


class CampaignService:
    def create_campaign_shell(
        self,
        name: str,
        keyword: str,
        engine: str,
        post_count: int,
        language: str = DEFAULT_LANGUAGE,
    ) -> int:
        return create_campaign(
            name=name,
            keyword=keyword,
            engine=engine,
            post_count=post_count,
            language=language,
            meta={},
        )

    def run_campaign(self, campaign_id: int) -> list[tuple[int, str]]:
        row = get_campaign(campaign_id)
        if not row:
            return []

        (
            _id,
            name,
            keyword,
            engine,
            post_count,
            status,
            language,
            created_at,
            meta_json,
        ) = row

        results: list[tuple[int, str]] = []

        for i in range(post_count):
            variant_keyword = f"{keyword} v{i+1}"
            post_id, job_id = pipeline_service.create_pipeline(
                keyword=variant_keyword,
                language=language,
                engine=engine,
            )
            link_campaign_post(campaign_id, post_id, job_id)
            results.append((post_id, job_id))

        update_campaign_status(campaign_id, "running")
        return results

    def get_campaign_links(self, campaign_id: int) -> list[tuple]:
        return list_campaign_posts(campaign_id)
