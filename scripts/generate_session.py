#!/usr/bin/env python3
"""
비대화식(non-interactive) Pyrogram SESSION_STRING 생성기.

환경변수:
  - API_ID, API_HASH
  - PHONE_NUMBER          (예: +77012345678)
  - PHONE_CODE            (2단계에서 설정)
  - PHONE_CODE_HASH       (2단계에서 설정)

동작:
  1단계:
    - PHONE_CODE, PHONE_CODE_HASH 미설정 상태로 실행
    - PHONE_NUMBER 로 인증코드 발송
    - PHONE_CODE_HASH 를 로그에 출력
    - "PHONE_CODE / PHONE_CODE_HASH 환경변수 설정 후 재배포" 안내

  2단계:
    - PHONE_CODE, PHONE_CODE_HASH 환경변수 설정 후 다시 실행
    - sign_in → SESSION_STRING 생성
    - 콘솔 출력 + data/sessions.txt 에 SESSION_STRING_N=값 형식으로 저장
"""

import asyncio
import os

from pyrogram import Client

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
PHONE_NUMBER = os.environ["PHONE_NUMBER"]
PHONE_CODE = os.environ.get("PHONE_CODE", "")
PHONE_CODE_HASH_ENV = os.environ.get("PHONE_CODE_HASH", "")


async def main():
    app = Client(
        name="session_gen",
        api_id=API_ID,
        api_hash=API_HASH,
        in_memory=True,
    )

    await app.connect()

    if not PHONE_CODE:
        # 1단계: 인증코드 발송
        sent = await app.send_code(PHONE_NUMBER)
        phone_code_hash = getattr(sent, "phone_code_hash", None)
        print(f"PHONE_CODE_HASH={phone_code_hash}")
        print("인증코드가 발송됐습니다.")
        print("PHONE_CODE 및 PHONE_CODE_HASH 환경변수에 값을 설정한 뒤 재배포/재실행하세요.")
        await app.disconnect()
        return

    # 2단계: 로그인 완료
    if not PHONE_CODE_HASH_ENV:
        print("PHONE_CODE_HASH 환경변수가 필요합니다. 1단계 로그의 값을 설정하세요.")
        await app.disconnect()
        return

    await app.sign_in(PHONE_NUMBER, PHONE_CODE_HASH_ENV, PHONE_CODE)
    session_string = await app.export_session_string()
    print(f"SESSION_STRING={session_string}")

    # data/sessions.txt 저장
    os.makedirs("data", exist_ok=True)
    sessions_path = os.path.join("data", "sessions.txt")

    try:
        with open(sessions_path, "r", encoding="utf-8") as rf:
            lines = rf.readlines()
        idx = len([l for l in lines if l.startswith("SESSION_STRING_")]) + 1
    except FileNotFoundError:
        idx = 1
    except Exception:
        idx = 1

    with open(sessions_path, "a", encoding="utf-8") as f:
        f.write(f"SESSION_STRING_{idx}={session_string}\n")

    print(f"SESSION_STRING_{idx} 저장 완료 (data/sessions.txt)")
    await app.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

