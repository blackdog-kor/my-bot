from app.db import get_post, create_post


class VariantEngine:
    @staticmethod
    def create_variants(post_id: int, count: int) -> list[int]:
        row = get_post(post_id)
        if not row:
            return []

        (
            _id,
            source,
            language,
            title,
            body,
            cta_link,
            status,
            created_at,
            media_type,
            media_path,
            thumbnail_path,
            platform_meta_json,
        ) = row

        new_ids = []

        for i in range(count):
            new_title = f"{title} v{i+1}"

            new_id = create_post(
                source=source,
                language=language,
                title=new_title,
                body=body,
                cta_link=cta_link,
                media_type=media_type,
                media_path=media_path,
                thumbnail_path=thumbnail_path,
                platform_meta_json=platform_meta_json,
            )
            new_ids.append(new_id)

        return new_ids
