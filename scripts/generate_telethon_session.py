"""
Telethon StringSession 생성 스크립트 (로컬 실행 전용).
생성된 세션 문자열을 Railway 환경변수 SESSION_STRING_TELETHON에 등록.

실행: python scripts/generate_telethon_session.py
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "bot" / ".env")

API_ID_RAW = (os.getenv("API_ID") or "").strip()
API_HASH = (os.getenv("API_HASH") or "").strip()


async def main() -> None:
    if not API_ID_RAW or not API_HASH:
        print("❌ .env 에 API_ID / API_HASH 를 먼저 설정하세요.")
        sys.exit(1)

    api_id = int(API_ID_RAW)
    print("=" * 60)
    print("  Telethon StringSession 생성")
    print("=" * 60)
    print("전화번호, 인증 코드, 2FA 비밀번호(설정된 경우)를 입력하세요.\n")

    async with TelegramClient(StringSession(), api_id, API_HASH) as client:
        me = await client.get_me()
        session_str = client.session.save()

    print("\n" + "=" * 60)
    print(f"✅ 로그인 성공: @{me.username or me.id}")
    print("=" * 60)
    print("\n아래 문자열을 Railway 환경변수 SESSION_STRING_TELETHON 에 등록하세요:\n")
    print(session_str)
    print()


if __name__ == "__main__":
    asyncio.run(main())
