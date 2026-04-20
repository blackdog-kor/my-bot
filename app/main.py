import os
import secrets
import sys
import threading

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.logging_config import get_logger

logger = get_logger(__name__)

from app.config import settings

AFFILIATE_URL = settings.affiliate_url or "https://t.me"

# ── Debug endpoint authentication ────────────────────────────────────────────
_DEBUG_SECRET = settings.debug_secret


def _check_debug_auth(request: Request) -> bool:
    """DEBUG_SECRET 미설정 시 전체 차단, 설정 시 헤더 매칭 확인."""
    if not _DEBUG_SECRET:
        return False
    provided = request.headers.get("X-Debug-Secret", "")
    return secrets.compare_digest(provided, _DEBUG_SECRET)


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

    try:
        from app.pg_broadcast import ensure_discovered_groups_table
        ensure_discovered_groups_table()
    except Exception as e:
        logger.warning("ensure_discovered_groups_table: %s", e)

    try:
        from app.group_topic_manager import ensure_forum_topics_table
        ensure_forum_topics_table()
    except Exception as e:
        logger.warning("ensure_forum_topics_table: %s", e)

    try:
        from app.affiliate_tracker import ensure_affiliate_stats_table
        ensure_affiliate_stats_table()
    except Exception as e:
        logger.warning("ensure_affiliate_stats_table: %s", e)

    try:
        from app.token_vault import ensure_vault_table
        from app.api_discovery import register_1win
        ensure_vault_table()
        register_1win()
    except Exception as e:
        logger.warning("token_vault init: %s", e)

    # Admin Bot 스레드 시작
    try:
        bot_thread = threading.Thread(target=_run_bot, daemon=True)
        bot_thread.start()
    except Exception as e:
        logger.warning("Bot thread start failed: %s", e)

    # Subscribe Bot 스레드 시작 (SUBSCRIBE_BOT_TOKEN이 설정된 경우에만)
    if settings.subscribe_bot_token:
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

    # Agent task queue 시작
    try:
        from app.task_queue import queue as agent_queue
        agent_queue.start()
        logger.info("Agent task queue started")
    except Exception as e:
        logger.warning("Agent task queue start failed: %s", e)

    yield

    # Agent task queue 정리
    try:
        from app.task_queue import queue as agent_queue
        agent_queue.stop()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)

from app.affiliate_tracker import router as affiliate_router  # noqa: E402
from app.win1_stats_webhook import router as win1_router      # noqa: E402
app.include_router(affiliate_router)
app.include_router(win1_router)

# ── Railway MCP 프록시 ──────────────────────────────────────────
_RAILWAY_PROXY_SECRET = settings.railway_proxy_secret


def _check_mcp_secret(path_secret: str) -> bool:
    if not _RAILWAY_PROXY_SECRET:
        return True
    return path_secret == _RAILWAY_PROXY_SECRET


@app.get("/health")
def health():
    return {"status": "ok"}


async def _handle_mcp_request(body: dict) -> dict:
    method = body.get("method", "")
    req_id = body.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "Railway Manager", "version": "1.0.0"},
            },
            "id": req_id,
        }

    if method == "notifications/initialized":
        return {"jsonrpc": "2.0", "result": {}, "id": req_id}

    if method == "tools/list":
        from app.railway_mcp_server import TOOLS
        return {"jsonrpc": "2.0", "result": {"tools": TOOLS}, "id": req_id}

    if method == "tools/call":
        from app.railway_mcp_server import call_tool
        params = body.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result_text = await call_tool(tool_name, arguments)
        return {
            "jsonrpc": "2.0",
            "result": {"content": [{"type": "text", "text": result_text}]},
            "id": req_id,
        }

    return {
        "jsonrpc": "2.0",
        "error": {"code": -32601, "message": f"Method not found: {method}"},
        "id": req_id,
    }


@app.post("/railway-mcp/{secret}/mcp")
async def railway_mcp_post(secret: str, request: Request):
    """MCP Streamable HTTP POST 엔드포인트. URL 경로에 비밀값 포함."""
    if not _check_mcp_secret(secret):
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32001, "message": "Unauthorized"}, "id": None}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})
    return JSONResponse(await _handle_mcp_request(body))


@app.get("/railway-mcp/{secret}/mcp")
async def railway_mcp_get(secret: str):
    """MCP Streamable HTTP GET 엔드포인트. 일부 클라이언트 호환용."""
    if not _check_mcp_secret(secret):
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32001, "message": "Unauthorized"}, "id": None}, status_code=401)
    return JSONResponse({"status": "ok", "transport": "streamable-http"})


@app.get("/railway-mcp-info")
def railway_mcp_info(request: Request):
    """Claude.ai Connector에서 Railway MCP 서버 등록 방법을 안내합니다."""
    base = str(request.base_url).rstrip("/")
    secret_in_url = _RAILWAY_PROXY_SECRET or "NO_SECRET_SET"
    mcp_url = f"{base}/railway-mcp/{secret_in_url}/mcp"
    return {
        "mcp_server_url": mcp_url,
        "note": "claude.ai 웹은 Bearer 헤더를 지원하지 않아 URL 경로에 비밀값을 포함합니다.",
        "setup": [
            "1) Railway Account Settings > Tokens 에서 API 토큰 발급",
            "2) Railway 환경변수에 RAILWAY_API_TOKEN 추가",
            f"3) Railway 환경변수에 RAILWAY_PROXY_SECRET 추가 (현재: {'설정됨' if _RAILWAY_PROXY_SECRET else '미설정'})",
            "4) claude.ai > Settings > Connectors > Add custom connector",
            f"5) Remote MCP server URL 칸에만 입력: {mcp_url}",
            "6) Advanced settings는 비워두기 (OAuth 안 씀)",
        ],
    }


@app.get("/debug/routes")
def debug_routes(request: Request):
    """현재 FastAPI에 등록된 모든 라우트 목록 반환 — 엔드포인트 존재 여부 확인용."""
    if not _check_debug_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return {
        "routes": [
            {"path": r.path, "methods": list(r.methods)}
            for r in app.routes
            if hasattr(r, "methods")
        ]
    }


@app.get("/debug/run-group-finder")
async def debug_run_group_finder(request: Request):
    """group_finder.py 수동 실행 트리거 (테스트용)"""
    if not _check_debug_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
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
async def debug_run_member_scraper(request: Request):
    """member_scraper.py 수동 실행 트리거 (테스트용)"""
    if not _check_debug_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
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
async def debug_dm_test(request: Request, username: str = "", user_id: int = 0):
    """
    테스트 DM 발송. username 또는 user_id 중 하나를 지정.
    - /debug/dm-test?username=yourname
    - /debug/dm-test?user_id=123456789
    둘 다 지정 시 user_id 우선 사용.
    """
    if not _check_debug_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if not username and not user_id:
        return {
            "error": "username 또는 user_id 파라미터가 필요합니다.",
            "examples": [
                "/debug/dm-test?username=yourname",
                "/debug/dm-test?user_id=123456789",
            ],
        }

    api_id   = settings.api_id
    api_hash = settings.api_hash
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
async def debug_session_test(request: Request):
    """각 SESSION_STRING으로 Pyrogram 연결을 시도하고 성공/실패 결과를 반환."""
    if not _check_debug_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    import asyncio

    api_id   = settings.api_id
    api_hash = settings.api_hash

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
async def debug_status(request: Request):
    if not _check_debug_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
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
