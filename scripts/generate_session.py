#!/usr/bin/env python3
"""
대화형 다중 계정 SESSION_STRING 생성기 (로컬 전용).

기능:
  1) 실행 시 생성할 계정 수 입력
  2) 각 계정마다:
     - 전화번호 입력 → Pyrogram으로 인증코드 발송
     - PHONE_CODE_HASH 내부적으로 저장
     - 인증코드 입력 즉시 sign_in
     - SESSION_STRING 생성 후 data/sessions.txt 에 SESSION_STRING_N=값 저장
     - "✅ 계정 N 생성 완료" 출력
  3) 전체 완료 후 "전체 N개 완료. data/sessions.txt 확인하세요." 출력

환경변수(.env 또는 직접 설정):
  - API_ID
  - API_HASH
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
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
        from pyrogram import Client
        from pyrogram.errors import PhoneCodeExpired, PhoneCodeInvalid
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
    print("   Pyrogram 다중 계정 SESSION_STRING 생성기")
    print("=" * 66)
    print()
    print(f"  ✅ API_ID  : {api_id}")
    print(f"  ✅ API_HASH: {api_hash[:8]}{'*' * max(0, len(api_hash) - 8)}")
    print()

    try:
        count_raw = input("생성할 계정 수를 입력하세요 (예: 10): ").strip()
        account_count = int(count_raw) if count_raw else 1
        if account_count <= 0:
            account_count = 1
    except Exception:
        account_count = 1

    print(f"\n→ 총 {account_count}개 계정을 순서대로 생성합니다.\n")

    success = 0
    fail = 0

    for idx in range(1, account_count + 1):
        print("-" * 40)
        print(f"[계정 {idx}/{account_count}]")
        phone_number = input("전화번호 입력 (예: +77012345678, 빈 값이면 종료): ").strip()
        if not phone_number:
            print("입력이 비어 있어 생성 루프를 종료합니다.")
            break
        if not phone_number.startswith("+"):
            print("❌ 국제 형식(+국가코드)이 아닙니다. 이 계정을 건너뜁니다.")
            fail += 1
            continue

        try:
            # in_memory=True → 디스크에 .session 파일을 생성하지 않음
            async with Client(
                name=f"session_gen_{idx}",
                api_id=api_id,
                api_hash=api_hash,
                in_memory=True,
            ) as app:
                # 코드 발송 및 로그인 루프
                while True:
                    sent = await app.send_code(phone_number)
                    phone_code_hash = getattr(sent, "phone_code_hash", None)
                    if not phone_code_hash:
                        print("❌ phone_code_hash 를 얻지 못했습니다. 이 계정을 건너뜁니다.")
                        fail += 1
                        break

                    print("인증코드가 텔레그램 앱으로 발송되었습니다.")

                    # 코드 입력 및 sign_in 루프
                    while True:
                        code = input("인증코드 입력: ").strip()
                        if not code:
                            print("❌ 인증코드가 비어 있습니다. 이 계정을 건너뜁니다.")
                            fail += 1
                            break
                        try:
                            await app.sign_in(phone_number, phone_code_hash, code)
                            # 로그인 성공
                            session_string = await app.export_session_string()
                            session_idx = _append_session(session_string)
                            print(f"SESSION_STRING_{session_idx}={session_string}")
                            print(f"✅ 계정 {idx}/{account_count} 생성 완료 (SESSION_STRING_{session_idx} 저장)")
                            success += 1
                            break
                        except PhoneCodeInvalid:
                            print("❌ 잘못된 코드입니다. 다시 입력하세요.")
                            continue
                        except PhoneCodeExpired:
                            print("⚠️ 코드 만료. 새 코드를 재발송합니다.")
                            # 바깥 while(True) 로 돌아가 새 코드 발송
                            break
                        except Exception as e:
                            print(f"❌ 로그인 중 오류 발생: {e}")
                            fail += 1
                            break

                    else:
                        # 내부 while 이 정상 종료된 경우 (break 없이) — 이 케이스는 사실상 없음
                        pass

                    # PhoneCodeExpired 로 인해 inner loop에서 break 되었을 경우, outer while 이 계속 돌면서 새 코드 발송
                    # 기타 이유(성공/실패)로 break 한 경우에는 outer while 도 종료
                    if success + fail >= idx:
                        # 이 계정에 대한 처리가 끝난 상태 → outer while 탈출
                        break

        except Exception as e:
            print(f"❌ 계정 {idx}/{account_count} 처리 중 예외 발생: {e}")
            fail += 1
            continue

    print("\n" + "=" * 66)
    print(f"전체 {success + fail}개 중 성공: {success}개, 실패: {fail}개")
    print("data/sessions.txt 파일을 확인하세요.")
    print("=" * 66)


if __name__ == "__main__":
    asyncio.run(main())

