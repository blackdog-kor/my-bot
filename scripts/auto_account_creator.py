#!/usr/bin/env python3
"""
HeroSMS API를 사용해 텔레그램용 계정을 자동 생성하고 SESSION_STRING 을 수집합니다.

환경변수:
  - HERO_SMS_API_KEY
  - API_ID, API_HASH
  - ACCOUNT_COUNT (기본 10)
  - BOT_TOKEN, ADMIN_ID

동작:
  1) HeroSMS로 인도(22) / 텔레그램(tg) 번호 구매
  2) Pyrogram으로 해당 번호로 코드 전송
  3) HeroSMS에서 60초 동안 3초 간격으로 코드 폴링
  4) 코드로 로그인 후 SESSION_STRING 생성
     - data/sessions.txt 에 SESSION_STRING_N=값 형식으로 저장
  5) 계정마다, 전체 완료 후 관리자 DM 알림
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "bot" / ".env")

import httpx  # noqa: E402


HERO_API_KEY = (os.getenv("HERO_SMS_API_KEY") or "").strip()
API_ID = int(os.getenv("API_ID", "0") or "0")
API_HASH = (os.getenv("API_HASH") or "").strip()
ACCOUNT_COUNT = int(os.getenv("ACCOUNT_COUNT", "10") or "10")
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

DATA_DIR = ROOT / "data"
SESSIONS_PATH = DATA_DIR / "sessions.txt"


def _next_session_index() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SESSIONS_PATH.is_file():
        return 1
    last_idx = 0
    try:
        for line in SESSIONS_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, _ = line.split("=", 1)
            if key.startswith("SESSION_STRING_"):
                try:
                    n = int(key.replace("SESSION_STRING_", ""))
                    if n > last_idx:
                        last_idx = n
                except ValueError:
                    continue
    except Exception:
        return 1
    return last_idx + 1


def _append_session(session_string: str) -> int:
    idx = _next_session_index()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with SESSIONS_PATH.open("a", encoding="utf-8") as f:
        f.write(f"SESSION_STRING_{idx}={session_string}\n")
    return idx


async def _notify(text: str) -> None:
    if not BOT_TOKEN or not ADMIN_ID:
        return
    text = (text or "")[:4000]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": ADMIN_ID,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
    except Exception:
        pass


async def hero_buy_number(client: httpx.AsyncClient) -> Optional[Tuple[str, str]]:
    if not HERO_API_KEY:
        print("HERO_SMS_API_KEY 가 설정되지 않았습니다.")
        return None
    try:
        r = await client.get(
            "https://hero-sms.com/api/v1/",
            params={
                "api_key": HERO_API_KEY,
                "action": "getNumber",
                "service": "tg",
                "country": 22,
            },
            timeout=20,
        )
        data = r.json()
        # 원시 응답을 그대로 로그로 출력 (디버깅용)
        print(f"[HeroSMS] getNumber raw response: {data}")
    except Exception as e:
        print(f"[HeroSMS] 번호 구매 실패: {e}")
        return None
    status = str(data.get("status") or "").lower()
    if status not in ("success", "ok"):
        print(f"[HeroSMS] 번호 구매 실패 응답: {data}")
        return None
    req_id = str(data.get("id") or "")
    number = str(data.get("number") or data.get("phone") or "")
    if not req_id or not number:
        print(f"[HeroSMS] 번호/ID 정보 부족: {data}")
        return None
    return req_id, number


async def hero_cancel_number(client: httpx.AsyncClient, req_id: str) -> None:
    if not HERO_API_KEY or not req_id:
        return
    try:
        await client.get(
            "https://hero-sms.com/api/v1/",
            params={
                "api_key": HERO_API_KEY,
                "action": "cancelNumber",
                "id": req_id,
            },
            timeout=10,
        )
    except Exception:
        pass


async def hero_wait_code(client: httpx.AsyncClient, req_id: str, timeout_sec: int = 60) -> Optional[str]:
    """60초까지 3초 간격으로 getStatus를 호출해 코드 추출."""
    if not HERO_API_KEY or not req_id:
        return None
    deadline = asyncio.get_event_loop().time() + timeout_sec
    pattern = re.compile(r"\b(\d{4,8})\b")
    last_raw = ""
    while asyncio.get_event_loop().time() < deadline:
        try:
            r = await client.get(
                "https://hero-sms.com/api/v1/",
                params={
                    "api_key": HERO_API_KEY,
                    "action": "getStatus",
                    "id": req_id,
                },
                timeout=15,
            )
            data = r.json()
        except Exception as e:
            print(f"[HeroSMS] getStatus 실패: {e}")
            await asyncio.sleep(3)
            continue
        status = str(data.get("status") or "").upper()
        last_raw = str(data)
        if status in ("RECEIVED", "SUCCESS", "OK"):
            sms_text = str(data.get("sms") or data.get("text") or data.get("code") or "")
            m = pattern.search(sms_text)
            if m:
                return m.group(1)
        await asyncio.sleep(3)
    print(f"[HeroSMS] 코드 미수신 (마지막 응답: {last_raw})")
    return None


async def hero_list_countries() -> None:
    """HeroSMS API에서 사용 가능한 국가 목록을 조회해 콘솔에 출력."""
    if not HERO_API_KEY:
        print("HERO_SMS_API_KEY 가 설정되지 않았습니다.")
        return
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://hero-sms.com/api/v1/",
                params={
                    "api_key": HERO_API_KEY,
                    "action": "getCountries",
                    "service": "tg",
                },
            )
            data = r.json()
    except Exception as e:
        print(f"[HeroSMS] getCountries 실패: {e}")
        return
    print("[HeroSMS] getCountries raw response:")
    print(data)


async def create_account(index: int, total: int, client: httpx.AsyncClient) -> bool:
    if not API_ID or not API_HASH:
        print("API_ID 또는 API_HASH가 설정되지 않았습니다.")
        return False
    try:
        from pyrogram import Client  # type: ignore
    except ImportError:
        print("pyrogram 패키지가 없습니다. pip install pyrogram cryptg")
        return False

    for attempt in range(1, 4):
        req = await hero_buy_number(client)
        if not req:
            await asyncio.sleep(3)
            continue
        req_id, number = req
        print(f"[{index}/{total}] 번호 구매 성공: {number} (id={req_id}) 시도 {attempt}/3")
        code = None
        try:
            async with Client(
                name=f"auto_{index}_{attempt}",
                api_id=API_ID,
                api_hash=API_HASH,
                in_memory=True,
            ) as app:
                sent = await app.send_code(number)
                phone_code_hash = getattr(sent, "phone_code_hash", None)
                if not phone_code_hash:
                    print("phone_code_hash 를 얻지 못했습니다.")
                    await hero_cancel_number(client, req_id)
                    continue
                code = await hero_wait_code(client, req_id, timeout_sec=60)
                if not code:
                    print(f"[{index}/{total}] 코드 미수신 → 번호 취소 후 재시도")
                    await hero_cancel_number(client, req_id)
                    continue
                await app.sign_in(number, phone_code_hash, code)
                session_string = await app.export_session_string()
        except Exception as e:
            print(f"[{index}/{total}] Pyrogram 로그인 실패: {e}")
            await hero_cancel_number(client, req_id)
            continue

        if not code:
            # 이미 위에서 처리됨
            continue

        session_idx = _append_session(session_string)
        msg = f"✅ 계정 {index}/{total} 생성 완료: +{number}\nSESSION_STRING_{session_idx} 저장 완료."
        print(msg)
        await _notify(msg)
        return True

    await _notify(f"❌ 계정 {index}/{total} 생성 실패 (최대 재시도 3회 초과)")
    return False


async def main() -> None:
    if not HERO_API_KEY:
        print("HERO_SMS_API_KEY 가 설정되지 않았습니다.")
        return
    if ACCOUNT_COUNT <= 0:
        print("ACCOUNT_COUNT 가 0 이하입니다. 기본값 10으로 진행.")
        account_total = 10
    else:
        account_total = ACCOUNT_COUNT

    success = 0
    fail = 0

    async with httpx.AsyncClient() as client:
        for i in range(1, account_total + 1):
            ok = await create_account(i, account_total, client)
            if ok:
                success += 1
            else:
                fail += 1
            await asyncio.sleep(2)

    summary = (
        "🎉 전체 계정 생성 완료\n"
        f"성공: {success}개\n"
        f"실패: {fail}개\n"
        "data/sessions.txt 파일을 확인하세요."
    )
    print(summary)
    await _notify(summary)


if __name__ == "__main__":
    # 사용법:
    #   python scripts/auto_account_creator.py          → 계정 생성 실행
    #   python scripts/auto_account_creator.py countries → 사용 가능 국가 목록 조회
    if len(sys.argv) > 1 and sys.argv[1].lower() in {"countries", "country"}:
        asyncio.run(hero_list_countries())
    else:
        asyncio.run(main())

