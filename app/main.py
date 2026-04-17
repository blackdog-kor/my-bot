import logging
import os
import sys
import threading

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

AFFILIATE_URL = os.getenv("AFFILIATE_URL", "https://t.me")


def _run_bot():
    try:
        from bot.main import main as bot_main
        logger.info("Admin Bot thread started")
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(bot_main())
    except Exception as e:
        logger.warning("Bot thread exited: %s", e)


def _run_subscribe_bot():
    try:
        from bot.subscribe_bot import run_bot as subscribe_run_bot
        logger.info("Subscribe Bot thread started")
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(subscribe_run_bot())
    except Exception as e:
        logger.warning("Subscribe Bot thread exited: %s", e)


def _run_scheduler():
    try:
        from app.scheduler import run_scheduler_forever
        logger.info("Scheduler thread started")
        run_scheduler_forever()
    except Exception as e:
        logger.error("Scheduler thread exited: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB 테이블 초기화
    try:
        from app.pg_broadcast import ensure_pg_table
        ensure_pg_table()
    except Exception as e:
        logger.warning("ensure_pg_table: %s", e)

    try:
        from app.pg_broadcast import ensure_campaign_posts_table
        ensure_campaign_posts_table()
    except Exception as e:
        logger.warning("ensure_campaign_posts_table: %s", e)

    try:
        from app.pg_broadcast import ensure_campaign_config_table
        ensure_campaign_config_table()
    except Exception as e:
        logger.warning("ensure_campaign_config_table: %s", e)

    # Admin Bot 스레드 시작
    try:
        bot_thread = threading.Thread(target=_run_bot, daemon=True)
        bot_thread.start()
    except Exception as e:
        logger.warning("Bot thread start failed: %s", e)

    # Subscribe Bot 스레드 시작 (SUBSCRIBE_BOT_TOKEN이 설정된 경우에만)
    if (os.getenv("SUBSCRIBE_BOT_TOKEN") or "").strip():
        try:
            sub_thread = threading.Thread(target=_run_subscribe_bot, daemon=True)
            sub_thread.start()
        except Exception as e:
            logger.warning("Subscribe Bot thread start failed: %s", e)
    else:
        logger.info("SUBSCRIBE_BOT_TOKEN 미설정 — Subscribe Bot 비활성화")

    # Scheduler 스레드 시작
    try:
        sched_thread = threading.Thread(target=_run_scheduler, daemon=True)
        sched_thread.start()
    except Exception as e:
        logger.warning("Scheduler thread start failed: %s", e)

    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/debug/routes")
def debug_routes():
    """현재 FastAPI에 등록된 모든 라우트 목록 반환 — 엔드포인트 존재 여부 확인용."""
    return {
        "routes": [
            {"path": r.path, "methods": list(r.methods)}
            for r in app.routes
            if hasattr(r, "methods")
        ]
    }


@app.get("/debug/run-group-finder")
async def debug_run_group_finder():
    """group_finder.py 수동 실행 트리거 (테스트용)"""
    import subprocess, sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "group_finder.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-3000:],
        "stderr": result.stderr[-1000:],
    }


@app.get("/debug/run-member-scraper")
async def debug_run_member_scraper():
    """member_scraper.py 수동 실행 트리거 (테스트용)"""
    import subprocess, sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "member_scraper.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-3000:],
        "stderr": result.stderr[-1000:],
    }


@app.get("/track/{ref}")
def track(ref: str):
    try:
        from app.pg_broadcast import mark_clicked
        mark_clicked(ref)
    except Exception as e:
        logger.warning("mark_clicked failed for ref=%s: %s", ref, e)
    return RedirectResponse(url=AFFILIATE_URL, status_code=302)


@app.get("/debug/dm-test")
async def debug_dm_test(username: str = "", user_id: int = 0):
    """
    테스트 DM 발송. username 또는 user_id 중 하나를 지정.
    - /debug/dm-test?username=yourname
    - /debug/dm-test?user_id=123456789
    둘 다 지정 시 user_id 우선 사용.
    """
    if not username and not user_id:
        return {
            "error": "username 또는 user_id 파라미터가 필요합니다.",
            "examples": [
                "/debug/dm-test?username=yourname",
                "/debug/dm-test?user_id=123456789",
            ],
        }

    api_id   = int(os.getenv("API_ID",   "0") or "0")
    api_hash = (os.getenv("API_HASH") or "").strip()
    if not api_id or not api_hash:
        return {"error": "API_ID 또는 API_HASH가 설정되지 않았습니다."}

    # 첫 번째 유효한 세션만 사용
    session_string = ""
    session_label  = ""
    for i in range(1, 11):
        key = f"SESSION_STRING_{i}"
        val = (os.getenv(key) or "").strip()
        if val:
            session_string = val
            session_label  = key
            break
    if not session_string:
        val = (os.getenv("SESSION_STRING") or "").strip()
        if val:
            session_string = val
            session_label  = "SESSION_STRING"
    if not session_string:
        return {"error": "SESSION_STRING 환경변수가 없습니다."}

    # 발송 대상 결정: user_id 우선, 없으면 @username
    if user_id:
        peer   = user_id          # 정수 그대로 사용
        target = str(user_id)
    else:
        target = username.lstrip("@")
        peer   = f"@{target}"    # get_users로 해석 후 .id 사용

    result: dict = {"session": session_label, "target": target, "mode": "user_id" if user_id else "username"}

    try:
        from pyrogram import Client as PyroClient

        async with PyroClient(
            name=f"dmtest_{session_label}",
            api_id=api_id,
            api_hash=api_hash,
            session_string=session_string,
            in_memory=True,
        ) as client:
            # peer 해석: user_id면 바로 사용, username이면 get_users로 정수 ID 획득
            if user_id:
                chat_id = user_id
                # user_id로도 get_users 시도해서 메타데이터 채움 (실패해도 발송은 시도)
                try:
                    user_obj = await client.get_users(user_id)
                    result["resolved_username"] = user_obj.username
                    result["name"] = f"{user_obj.first_name or ''} {user_obj.last_name or ''}".strip()
                except Exception:
                    pass
            else:
                user_obj = await client.get_users(peer)
                chat_id  = user_obj.id
                result["resolved_user_id"] = user_obj.id
                result["resolved_username"] = user_obj.username
                result["name"] = f"{user_obj.first_name or ''} {user_obj.last_name or ''}".strip()

            # 텍스트 메시지 발송
            msg = await client.send_message(
                chat_id,
                "✅ [테스트] UserBot DM 발송 테스트입니다. 이 메시지가 보이면 정상입니다.",
            )
            result["status"]     = "ok"
            result["message_id"] = msg.id
            result["chat_id"]    = chat_id

    except Exception as exc:
        result["status"] = "fail"
        result["error"]  = f"{type(exc).__name__}: {exc}"
        logger.exception("dm-test 실패 [%s → %s]", session_label, target)

    return result


@app.get("/debug/session-test")
async def debug_session_test():
    """각 SESSION_STRING으로 Pyrogram 연결을 시도하고 성공/실패 결과를 반환."""
    import asyncio

    api_id   = int(os.getenv("API_ID",   "0") or "0")
    api_hash = (os.getenv("API_HASH") or "").strip()

    if not api_id or not api_hash:
        return {"error": "API_ID 또는 API_HASH 환경변수가 설정되지 않았습니다."}

    # 세션 목록 수집 (SESSION_STRING_1 ~ SESSION_STRING_10, 없으면 SESSION_STRING)
    sessions: list[tuple[str, str]] = []
    for i in range(1, 11):
        key = f"SESSION_STRING_{i}"
        val = (os.getenv(key) or "").strip()
        if val:
            sessions.append((key, val))
    if not sessions:
        val = (os.getenv("SESSION_STRING") or "").strip()
        if val:
            sessions.append(("SESSION_STRING", val))

    if not sessions:
        return {"error": "SESSION_STRING 환경변수가 설정되지 않았습니다."}

    results: list[dict] = []

    for label, session_string in sessions:
        entry: dict = {"label": label, "session_length": len(session_string)}
        try:
            from pyrogram import Client as PyroClient

            async with PyroClient(
                name=f"test_{label}",
                api_id=api_id,
                api_hash=api_hash,
                session_string=session_string,
                in_memory=True,
            ) as client:
                me = await client.get_me()
                entry["status"]   = "ok"
                entry["user_id"]  = me.id
                entry["username"] = me.username or "(없음)"
                entry["name"]     = f"{me.first_name or ''} {me.last_name or ''}".strip()
        except Exception as exc:
            entry["status"] = "fail"
            entry["error"]  = f"{type(exc).__name__}: {exc}"
            logger.exception("session-test 실패 [%s]", label)

        results.append(entry)

    ok_count   = sum(1 for r in results if r["status"] == "ok")
    fail_count = len(results) - ok_count
    return {
        "api_id":     api_id,
        "api_hash":   api_hash[:6] + "..." if api_hash else "(없음)",
        "total":      len(results),
        "ok":         ok_count,
        "failed":     fail_count,
        "sessions":   results,
    }


@app.get("/debug/status")
async def debug_status():
    # 1. campaign_posts 확인
    try:
        from app.pg_broadcast import list_posts
        posts = list_posts()
        active_posts = sum(1 for p in posts if p.get("is_active"))
        posts_status = f"전체 {len(posts)}개 / 활성 {active_posts}개"
    except Exception as e:
        posts_status = f"오류: {e}"

    # 2. SESSION_STRING 개수 확인
    sessions = []
    for i in range(1, 11):
        k = f"SESSION_STRING_{i}"
        if os.getenv(k):
            sessions.append(k)
    if not sessions and os.getenv("SESSION_STRING"):
        sessions.append("SESSION_STRING")

    # 3. DB 미발송 타겟 수 확인
    try:
        from app.pg_broadcast import count_unsent_with_username
        unsent = count_unsent_with_username()
    except Exception as e:
        unsent = f"오류: {e}"

    # 4. scripts 경로 확인
    script_path = os.path.join(
        os.path.dirname(__file__), "..", "scripts", "dm_campaign_runner.py"
    )
    script_exists = os.path.exists(os.path.abspath(script_path))

    # 5. DB 연결 확인
    try:
        from app.pg_broadcast import count_total
        count_total()
        db_status = "연결됨"
    except Exception as e:
        db_status = f"오류: {e}"

    return {
        "campaign_posts": posts_status,
        "sessions": sessions,
        "session_count": len(sessions),
        "unsent_targets": unsent,
        "script_exists": script_exists,
        "db_status": db_status,
        "python": sys.executable,
        "affiliate_url": AFFILIATE_URL[:30] + "..." if len(AFFILIATE_URL) > 30 else AFFILIATE_URL,
    }
