#!/usr/bin/env python3
"""
Pyrogram UserBot SESSION_STRING 생성기 (일회용).

사용법:
  1) 의존 패키지 설치 (최초 1회):
       pip install pyrogram tgcrypto

  2) 이 스크립트 실행:
       python scripts/generate_session.py

  3) 전화번호 입력 → Telegram 앱 OTP 입력 → (2FA 설정 시) 클라우드 비밀번호 입력

  4) 출력된 SESSION_STRING 문자열을 Railway Variables에 추가:
       변수명: SESSION_STRING

⚠️  이 문자열은 계정 전체 접근 권한을 포함합니다.
    절대 외부에 공개하거나 git commit 하지 마세요.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── 사전 발급된 API 자격증명 ─────────────────────────────────────────────────
# my.telegram.org/apps 에서 발급받은 값 (환경변수 우선, 없으면 아래 기본값 사용)
DEFAULT_API_ID   = "37398454"
DEFAULT_API_HASH = "a73350e09f51f516d8eac08498967750"


async def main() -> None:
    try:
        from pyrogram import Client
    except ImportError:
        print()
        print("❌ pyrogram 패키지가 없습니다.")
        print("   먼저 설치하세요: pip install pyrogram tgcrypto")
        print()
        sys.exit(1)

    print()
    print("=" * 66)
    print("   Pyrogram UserBot  SESSION_STRING  생성기")
    print("=" * 66)
    print()

    # API_ID
    api_id_str = (os.getenv("API_ID") or DEFAULT_API_ID).strip()
    print(f"  ✅ API_ID  : {api_id_str}")
    api_id = int(api_id_str)

    # API_HASH
    api_hash = (os.getenv("API_HASH") or DEFAULT_API_HASH).strip()
    print(f"  ✅ API_HASH: {api_hash[:8]}{'*' * (len(api_hash) - 8)}")

    print()
    print("  전화번호 인증을 시작합니다.")
    print("  국가 코드 포함 전화번호를 입력하세요.  예) +821012345678")
    print()

    session_string = ""

    # in_memory=True → 디스크에 .session 파일을 생성하지 않음
    async with Client(
        name="session_gen",
        api_id=api_id,
        api_hash=api_hash,
        in_memory=True,
    ) as client:
        session_string = await client.export_session_string()

    print()
    print("=" * 66)
    print("  ✅ SESSION_STRING 생성 완료!")
    print()
    print("  ▼ 아래 문자열 전체를 복사 → Railway Variables > SESSION_STRING 에 붙여넣기")
    print()
    print(session_string)
    print()
    print("=" * 66)
    print()
    print("  ⚠️  보안 주의사항:")
    print("   • 이 문자열은 텔레그램 계정 완전 접근 권한을 포함합니다.")
    print("   • .env 파일이나 git 저장소에 절대 저장하지 마세요.")
    print("   • Railway Variables 에만 저장하세요.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
