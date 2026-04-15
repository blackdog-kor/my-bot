"""
자동 스케줄러: 수집(00:00) → 발송(06:00).

- APScheduler 사용, 한 번에 하나의 Job만 실행 (threading.Lock).
- Job 시작/완료/실패 시 관리자 DM 알림.
- 기동 시 다음 예약 Job 목록 로그 출력.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

# Railway 배포 환경 모듈 경로
sys.path.insert(0, "/app")

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("scheduler")

ROOT = Path(__file__).resolve().parents[1]  # repo root (app/scheduler.py)
_job_lock = threading.Lock()

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None


def _notify(text: str) -> None:
    """관리자에게 DM 전송 (실패 시 무시)."""
    if not BOT_TOKEN or not ADMIN_ID:
        return
    text = (text or "")[:4000]
    try:
        import httpx
        with httpx.Client(timeout=15) as hc:
            hc.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": ADMIN_ID,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
    except Exception as e:
        logger.warning("notify failed: %s", e)


def _run_script(script_name: str, job_label: str) -> bool:
    """scripts/{script_name} 를 subprocess로 실행. 성공 여부 반환."""
    script_path = ROOT / "scripts" / script_name
    if not script_path.is_file():
        logger.error("Script not found: %s", script_path)
        _notify(f"❌ 스케줄 Job 실패: {job_label}\n파일 없음: {script_path}")
        return False
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=3600 * 2,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "")[:1500]
            _notify(f"❌ {job_label} 실패 (exit %s)\n{err}".strip())
            return False
        return True
    except subprocess.TimeoutExpired:
        _notify(f"❌ {job_label} 타임아웃 (2시간)")
        return False
    except Exception as e:
        _notify(f"❌ {job_label} 예외: {e}")
        return False


def _job_group_finder() -> None:
    with _job_lock:
        _notify("🔍 그룹 발굴 Job 시작 (group_finder)")
        ok = _run_script("group_finder.py", "그룹발굴(group_finder)")
        _notify("🔍 그룹 발굴 Job 완료" if ok else "🔍 그룹 발굴 Job 실패")


def _job_member_scraper() -> None:
    with _job_lock:
        _notify("📥 수집 Job 시작 (member_scraper)")
        ok = _run_script("member_scraper.py", "수집(member_scraper)")
        _notify("📥 수집 Job 완료" if ok else "📥 수집 Job 실패")


def _job_dm_campaign() -> None:
    with _job_lock:
        _notify("📤 발송 Job 시작 (dm_campaign_runner)")
        ok = _run_script("dm_campaign_runner.py", "발송(dm_campaign_runner)")
        _notify("📤 발송 Job 완료" if ok else "📤 발송 Job 실패")


def _job_retry_sender() -> None:
    with _job_lock:
        _notify("🔁 재발송 Job 시작 (retry_sender)")
        ok = _run_script("retry_sender.py", "재발송(retry_sender)")
        _notify("🔁 재발송 Job 완료" if ok else "🔁 재발송 Job 실패")


def _job_subscribe_push() -> None:
    with _job_lock:
        _notify("⏰ 구독봇 자동 푸시 Job 시작 (09:00 KST)")
        ok = _run_script("subscribe_push.py", "구독봇 푸시(subscribe_push)")
        _notify("⏰ 구독봇 자동 푸시 Job 완료" if ok else "⏰ 구독봇 자동 푸시 Job 실패")


def _job_warmup() -> None:
    with _job_lock:
        _notify("🏋️ 워밍업 Job 시작 (08:00 KST)")
        ok = _run_script("warmup.py", "워밍업(warmup)")
        _notify("🏋️ 워밍업 Job 완료" if ok else "🏋️ 워밍업 Job 실패")


def run_scheduler_forever() -> None:
    scheduler = BackgroundScheduler()
    # 03:00 — 새 그룹 발굴 (group_finder)
    scheduler.add_job(
        _job_group_finder,
        trigger=CronTrigger(hour=3, minute=0),
        id="group_finder",
    )
    # 00:00 — 멤버 수집 (member_scraper, discovered_groups 포함)
    scheduler.add_job(
        _job_member_scraper,
        trigger=CronTrigger(hour=0, minute=0),
        id="member_scraper",
    )
    # 06:00 — 1차 DM 발송 (dm_campaign_runner) ← 워밍업 완료 전까지 비활성화
    # scheduler.add_job(
    #     _job_dm_campaign,
    #     trigger=CronTrigger(hour=6, minute=0),
    #     id="dm_campaign_runner",
    # )
    # 12:00 — 3일 경과 미클릭 재발송 (retry_sender)
    scheduler.add_job(
        _job_retry_sender,
        trigger=CronTrigger(hour=12, minute=0),
        id="retry_sender",
    )
    # 00:00 UTC (09:00 KST) — 구독봇 자동 푸시 (subscribe_push)
    scheduler.add_job(
        _job_subscribe_push,
        trigger=CronTrigger(hour=0, minute=0),
        id="subscribe_push",
    )
    # 23:00 UTC (08:00 KST) — 세션 계정 워밍업 (warmup)
    scheduler.add_job(
        _job_warmup,
        trigger=CronTrigger(hour=23, minute=0),
        id="warmup",
    )
    scheduler.start()

    # 다음 예약 Job 목록 로그
    jobs = list(scheduler.get_jobs())
    for j in jobs:
        logger.info("다음 예약: %s — %s", j.id, j.next_run_time)
    print(
        "--- 스케줄러 기동: 발굴 03:00 / 수집 00:00 / [발송 비활성화] / 재발송 12:00 / 구독봇 푸시 00:00(UTC=09KST) / 워밍업 23:00(UTC=08KST) ---",
        flush=True,
    )

    try:
        while True:
            import time
            time.sleep(3600)
    except Exception:
        scheduler.shutdown(wait=False)
        raise
