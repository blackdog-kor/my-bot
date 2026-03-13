#!/usr/bin/env python3
"""
수동 SESSION_STRING 생성기 (스크립트, Railway 환경변수 기반).

기능:
  1) PHONE_NUMBER 환경변수로 인증코드 발송
  2) 로그에 \"인증코드를 PHONE_CODE 환경변수에 입력 후 재배포\" 안내
  3) PHONE_CODE 환경변수가 설정되어 있으면 로그인 진행
  4) 로그인 완료 후 SESSION_STRING 콘솔 출력
  5) data/sessions.txt 에 SESSION_STRING_N=값 형식으로 자동 저장

환경변수:
  - API_ID, API_HASH
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "bot" / ".env")

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


async def main() -> None:
    try:
        from pyrogram import Client  # type: ignore
    except ImportError:
        print()
        print("❌ pyrogram 패키지가 없습니다.")
        print("   먼저 설치하세요: pip install pyrogram cryptg")
        print()
        sys.exit(1)

    api_id_raw = (os.getenv("API_ID") or "").strip()
    api_hash = (os.getenv("API_HASH") or "").strip()

    if not api_id_raw or not api_hash:
        print("❌ API_ID 또는 API_HASH 환경변수가 설정되지 않았습니다.")
        sys.exit(1)

    try:
        api_id = int(api_id_raw)
    except ValueError:
        print("❌ API_ID 가 정수가 아닙니다.")
        sys.exit(1)

    print()
    print("=" * 66)
    print("   Pyrogram SESSION_STRING 생성기 (환경변수 기반)")
    print("=" * 66)
    print()
    print(f"  ✅ API_ID  : {api_id}")
    print(f"  ✅ API_HASH: {api_hash[:8]}{'*' * max(0, len(api_hash) - 8)}")
    print()

    phone_number = (os.getenv("PHONE_NUMBER") or "").strip()
    phone_code = (os.getenv("PHONE_CODE") or "").strip()

    if not phone_number:
        print("❌ PHONE_NUMBER 환경변수가 설정되지 않았습니다.")
        print("   예) PHONE_NUMBER=\"+77012345678\"")
        sys.exit(1)
    if not phone_number.startswith("+"):
        print("❌ PHONE_NUMBER 가 국제 형식(+국가코드)이 아닙니다.")
        sys.exit(1)

    # in_memory=True → .session 파일을 디스크에 생성하지 않음
    async with Client(
        name="manual_session_gen",
        api_id=api_id,
        api_hash=api_hash,
        in_memory=True,
    ) as app:
        # 1) 코드 발송
        sent = await app.send_code(phone_number)
        phone_code_hash = getattr(sent, "phone_code_hash", None)
        if not phone_code_hash:
            print("❌ phone_code_hash 를 얻지 못했습니다.")
            sys.exit(1)

        if not phone_code:
            # 첫 실행: 코드만 발송하고 종료, PHONE_CODE 설정을 안내
            print()
            print("✅ 인증코드를 전송했습니다.")
            print("👉 받은 인증코드를 PHONE_CODE 환경변수에 입력한 뒤 다시 배포/실행하세요.")
            print("   예) PHONE_CODE=\"12345\"")
            return

        # 2) 코드로 로그인
        await app.sign_in(phone_number, phone_code_hash, phone_code.strip())

        # 3) SESSION_STRING 추출
        session_string = await app.export_session_string()

    # 콘솔 출력
    print()
    print("=" * 66)
    print("  ✅ SESSION_STRING 생성 완료!")
    print()
    print("  ▼ 아래 문자열 전체를 복사해 Railway Variables 에 등록하세요.")
    print()
    print(session_string)
    print()

    # 파일 저장
    idx = _append_session(session_string)
    print(f"  data/sessions.txt 에 SESSION_STRING_{idx} 으로 저장했습니다.")
    print("=" * 66)
    print()


if __name__ == "__main__":
    asyncio.run(main())

