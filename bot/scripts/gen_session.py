#!/usr/bin/env python3
"""
Pyrogram UserBot StringSession 생성기.

사용법:
  pip install pyrogram tgcrypto
  python scripts/gen_session.py

필요한 것:
  1. Telegram API ID & API Hash
     → https://my.telegram.org/apps 에서 앱 생성 후 발급
  2. 유저봇으로 사용할 Telegram 계정 전화번호
  3. Telegram 앱에서 받은 OTP 코드 (+ 2FA 비밀번호가 설정된 경우)

생성된 PYROGRAM_SESSION 문자열을 Railway Variables에 추가하면 됩니다.
⚠️  이 문자열은 계정 전체 접근 권한을 포함하므로 절대 외부에 공개하지 마세요.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Allow running from repo root or scripts/ folder
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main() -> None:
    try:
        from pyrogram import Client
        from pyrogram.errors import SessionPasswordNeeded
    except ImportError:
        print()
        print("❌ pyrogram 패키지가 없습니다.")
        print("   먼저 설치하세요: pip install pyrogram tgcrypto")
        print()
        sys.exit(1)

    print()
    print("=" * 64)
    print("  Pyrogram UserBot StringSession 생성기")
    print("=" * 64)
    print()
    print("📌 API ID / API Hash 발급:")
    print("   https://my.telegram.org/apps  →  'API development tools'")
    print()

    # Read from env or prompt
    api_id_str = (os.getenv("API_ID") or "").strip()
    if api_id_str:
        print(f"  ✅ API_ID 환경변수에서 읽음: {api_id_str}")
        api_id = int(api_id_str)
    else:
        api_id = int(input("  API ID를 입력하세요: ").strip())

    api_hash = (os.getenv("API_HASH") or "").strip()
    if api_hash:
        print(f"  ✅ API_HASH 환경변수에서 읽음: {api_hash[:8]}...")
    else:
        api_hash = input("  API Hash를 입력하세요: ").strip()

    print()
    print("  전화번호 인증을 시작합니다.")
    print("  Telegram이 OTP 코드를 보냅니다. (예: +821012345678)")
    print()

    session_string = ""

    # in_memory=True → no .session file written to disk; interactive login via stdin
    async with Client(
        name="session_gen",
        api_id=api_id,
        api_hash=api_hash,
        in_memory=True,
    ) as client:
        session_string = await client.export_session_string()

    print()
    print("=" * 64)
    print("  ✅ 세션 문자열 생성 완료!")
    print()
    print("  아래 문자열 전체를 복사하여 Railway Variables에 추가하세요.")
    print("  변수명: PYROGRAM_SESSION")
    print()
    print(session_string)
    print()
    print("=" * 64)
    print()
    print("  ⚠️  주의사항:")
    print("   • 이 문자열은 계정 완전 접근 권한이 포함되어 있습니다.")
    print("   • 절대 외부에 공개하거나 git commit 하지 마세요.")
    print("   • Railway Variables > 'Add Variable' 에서만 저장하세요.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
