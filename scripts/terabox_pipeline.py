#!/usr/bin/env python
"""
TeraBox 콘텐츠 파이프라인: 수집 → 리라이팅 → DB 저장 → 채널 게시.

실행 흐름:
1. TeraBox 공유 링크에서 콘텐츠 메타데이터 수집 (browser-use AI 에이전트)
2. 중복 필터링 (이미 수집된 콘텐츠 제외)
3. AI 리라이팅 (캡션 생성)
4. channel_content 테이블에 저장
5. 대기 콘텐츠 채널 게시

scheduler.py에서 subprocess로 실행됨.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("terabox_pipeline")


async def run_terabox_collect() -> int:
    """TeraBox 콘텐츠 수집 + 리라이팅 + DB 저장. 저장된 수 반환."""
    from app.terabox_agent import collect_terabox_content, TeraBoxItem
    from app.content_rewriter import rewrite_content
    from app.pg_broadcast import (
        ensure_channel_content_table,
        is_content_duplicate,
        save_channel_content,
    )
    from app.config import settings

    ensure_channel_content_table()

    # ── TeraBox 수집 ──
    logger.info("=== TeraBox 콘텐츠 수집 시작 ===")
    result = await collect_terabox_content()

    if not result.items:
        logger.warning("TeraBox 수집 결과 없음 (errors=%d)", len(result.errors))
        for err in result.errors:
            logger.warning("  → %s", err)
        return 0

    logger.info(
        "TeraBox 수집 완료: %d/%d 성공",
        result.success_count, result.total_processed,
    )

    # ── 중복 필터 + 리라이팅 + 저장 ──
    saved_count = 0
    max_save = settings.batch_size

    for item in result.items:
        if saved_count >= max_save:
            break

        # 중복 체크 (share_url 기반)
        source = f"terabox:{item.share_url}"
        if is_content_duplicate(source, 0):
            logger.info("중복 스킵: %s", item.file_name or item.title)
            continue

        # 캡션 텍스트 구성
        caption_parts: list[str] = []
        if item.title:
            caption_parts.append(item.title)
        if item.file_name:
            caption_parts.append(f"📁 {item.file_name}")
        if item.file_size:
            caption_parts.append(f"💾 {item.file_size}")

        original_text = "\n".join(caption_parts) if caption_parts else item.file_name

        if not original_text.strip():
            continue

        # AI 리라이팅
        rewritten = None
        if settings.content_rewrite_enabled:
            try:
                rewritten = await rewrite_content(
                    original_text=original_text,
                    media_type=item.media_type,
                )
            except Exception as e:
                logger.warning("리라이팅 실패: %s", e)

        # DB 저장
        content_id = save_channel_content(
            original_text=original_text,
            rewritten_text=rewritten,
            media_type=item.media_type,
            source_channel=source,
            source_msg_id=0,
            source_views=0,
        )

        if content_id:
            saved_count += 1
            logger.info(
                "TeraBox 콘텐츠 #%d 저장 (file=%s, type=%s)",
                content_id, item.file_name, item.media_type,
            )

        # Rate limit 방지
        await asyncio.sleep(2.0)

    logger.info("=== TeraBox 저장 완료: %d개 ===", saved_count)
    return saved_count


async def run_channel_post() -> int:
    """대기 콘텐츠 채널 게시. 게시된 수 반환."""
    from app.channel_poster import check_and_post

    logger.info("=== 채널 게시 시작 ===")
    posted = await check_and_post()
    logger.info("=== 채널 게시 완료: %d개 ===", posted)
    return posted


async def main() -> None:
    """TeraBox 전체 파이프라인 실행."""
    import httpx

    bot_token = os.getenv("BOT_TOKEN", "")
    admin_id = os.getenv("ADMIN_ID", "")

    def notify(text: str) -> None:
        if not bot_token or not admin_id:
            return
        try:
            httpx.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": admin_id, "text": text[:4000]},
                timeout=10,
            )
        except Exception:
            pass

    try:
        # Phase 1: TeraBox 수집 + 리라이팅
        saved = await run_terabox_collect()

        # Phase 2: 채널 게시
        posted = await run_channel_post()

        result_msg = (
            f"📦 [TeraBox 파이프라인] 완료!\n"
            f"• 새 콘텐츠 수집: {saved}개\n"
            f"• 채널 게시: {posted}개"
        )
        logger.info(result_msg)
        notify(result_msg)

    except Exception as e:
        error_msg = f"❌ [TeraBox 파이프라인] 실패: {e}"
        logger.exception(error_msg)
        notify(error_msg)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
