#!/usr/bin/env python3
"""
매일 오전 9시 관리자 텔레그램 DM으로 전날 기준 KPI 리포트 자동 발송.
스케줄러에서 호출: python scripts/daily_report.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "bot" / ".env")

import httpx

from app.pg_broadcast import (
    get_campaign_stats,
    get_count_added_on_date,
    get_count_clicked_on_date,
    get_retry_sent_count,
)

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID = (os.getenv("ADMIN_ID") or "").strip()
if not BOT_TOKEN or not ADMIN_ID:
    print("BOT_TOKEN 또는 ADMIN_ID 미설정")
    sys.exit(1)

# 오늘/어제 (UTC 기준, DB와 일치)
_today_utc = datetime.now(timezone.utc).date()
_yesterday = _today_utc - timedelta(days=1)
REPORT_DATE_STR = _today_utc.strftime("%Y-%m-%d")


def send_report() -> None:
    stats = get_campaign_stats()
    new_today = get_count_added_on_date(_yesterday)
    new_clicks_today = get_count_clicked_on_date(_yesterday)
    retry_sent = get_retry_sent_count()

    total_targets = stats.get("total_targets", 0)
    total_sent = stats.get("total_sent", 0)
    pending = stats.get("pending", 0)
    total_clicked = stats.get("total_clicked", 0)
    click_rate = stats.get("click_rate", 0.0)

    text = (
        f"📊 일일 KPI 리포트 {REPORT_DATE_STR}\n\n"
        "👥 유저 현황\n"
        f"총 수집: {total_targets}명\n"
        f"발송 완료: {total_sent}명\n"
        f"대기 중: {pending}명\n\n"
        "🎯 전환 현황\n"
        f"링크 클릭: {total_clicked}명\n"
        f"클릭률: {click_rate}%\n"
        f"재발송 완료: {retry_sent}명\n\n"
        "📈 전날 대비\n"
        f"신규 수집: {new_today}명\n"
        f"신규 클릭: {new_clicks_today}명"
    )

    try:
        with httpx.Client(timeout=15) as client:
            r = client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": ADMIN_ID,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
        if r.status_code != 200:
            print(f"Telegram API 오류: {r.status_code} {r.text}")
            sys.exit(1)
        print("일일 KPI 리포트 발송 완료")
    except Exception as e:
        print(f"발송 실패: {e}")
        sys.exit(1)


if __name__ == "__main__":
    send_report()
