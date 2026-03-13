#!/usr/bin/env python3
"""
HeroSMS API를 이용한 완전 자동화 SESSION_STRING 생성기.

환경변수:
  - API_ID, API_HASH
  - HERO_SMS_API_KEY
  - ACCOUNT_COUNT (생성할 계정 수, 기본 10)
  - COUNTRY      (번호 국가코드, 기본 77)

동작 흐름 (1개 계정 기준):
  1) HeroSMS API로 번호 구매
     GET handler_api.php?action=getNumber&service=tg&country={COUNTRY}
     응답: ACCESS_NUMBER:{id}:{phone}
  2) Pyrogram으로 해당 번호에 인증코드 발송
     app.send_code("+{phone}")
  3) HeroSMS API로 인증코드 자동 수신 (최대 2분 폴링)
     GET handler_api.php?action=getStatus&id={id}
     응답: STATUS_OK:{code} 올 때까지 10초마다 폴링
  4) 자동 로그인
     app.sign_in(full_phone, phone_code_hash, code)
  5) SESSION_STRING 생성 후 data/sessions.txt 저장
     형식: SESSION_STRING_N=값
  6) 번호 사용완료 처리
     GET handler_api.php?action=setStatus&status=6&id={id}
  7) ACCOUNT_COUNT 만큼 반복

에러 처리:
  - NO_NUMBERS: 10초 대기 후 재시도 (최대 3회)
  - STATUS_WAIT_CODE 2분 초과: 번호 취소(status=8) 후 다음 번호
  - PhoneCodeExpired: 번호 취소(status=8) 후 다음 번호
  - 기타: 로그 출력 후 다음 계정으로 진행
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import cloudscraper
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


def hero_request(scraper, params: dict) -> str:
    base = "https://hero-sms.com/stubs/handler_api.php"
    try:
        resp = scraper.get(base, params=params, timeout=30)
        return resp.text.strip()
    except Exception as e:
        print(f"[HeroSMS] 요청 실패 ({params.get('action')}): {e}")
        return ""


def hero_buy_number(scraper, api_key: str, country: int) -> Optional[Tuple[str, str]]:
    """번호 구매. 성공 시 (id, phone) 반환. NO_NUMBERS 등은 None."""
    text = hero_request(
        scraper,
        {
            "api_key": api_key,
            "action": "getNumber",
            "service": "tg",
            "country": country,
        },
    )
    if not text:
        return None
    print(f"[HeroSMS] getNumber 응답: {text}")
    if text.startswith("NO_NUMBERS"):
        return None
    if not text.startswith("ACCESS_NUMBER:"):
        print(f"[HeroSMS] 예상치 못한 응답: {text}")
        return None
    try:
        _, id_part, phone_part = text.split(":", 2)
        return id_part, phone_part
    except ValueError:
        print(f"[HeroSMS] 파싱 실패: {text}")
        return None


def hero_get_status(scraper, api_key: str, req_id: str) -> str:
    """상태 조회. 원본 텍스트 반환."""
    return hero_request(
        scraper,
        {
            "api_key": api_key,
            "action": "getStatus",
            "id": req_id,
        },
    )


def hero_set_status(scraper, api_key: str, req_id: str, status: int) -> None:
    """상태 변경 (6=완료, 8=취소 등). 오류는 로그만."""
    text = hero_request(
        scraper,
        {
            "api_key": api_key,
            "action": "setStatus",
            "status": status,
            "id": req_id,
        },
    )
    if text:
        print(f"[HeroSMS] setStatus({status}) 응답: {text}")


def main() -> None:
    try:
        from pyrogram import Client
        from pyrogram.errors import PhoneCodeExpired
    except ImportError:
        print("❌ pyrogram 패키지가 없습니다. 먼저 설치하세요: pip install pyrogram cryptg")
        sys.exit(1)

    api_id_raw = (os.getenv("API_ID") or "").strip()
    api_hash = (os.getenv("API_HASH") or "").strip()
    hero_key = (os.getenv("HERO_SMS_API_KEY") or "").strip()
    account_count = int(os.getenv("ACCOUNT_COUNT", "10") or "10")
    country = int(os.getenv("COUNTRY", "77") or "77")

    if not api_id_raw or not api_hash or not hero_key:
        print("❌ API_ID / API_HASH / HERO_SMS_API_KEY 환경변수를 확인하세요.")
        sys.exit(1)

    try:
        api_id = int(api_id_raw)
    except ValueError:
        print("❌ API_ID 가 정수가 아닙니다.")
        sys.exit(1)

    if account_count <= 0:
        account_count = 10

    print("=" * 66)
    print(" HeroSMS 완전 자동 SESSION_STRING 생성기")
    print("=" * 66)
    print(f"API_ID      : {api_id}")
    print(f"COUNTRY     : {country}")
    print(f"계정 생성 수: {account_count}")
    print("=" * 66)

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )

    success = 0
    fail = 0

    for idx in range(1, account_count + 1):
        print("\n" + "-" * 40)
        print(f"[계정 {idx}/{account_count}] 번호 구매 시도")

        # 번호 구매 (NO_NUMBERS 재시도 최대 3회)
        attempt = 0
        number_info: Optional[Tuple[str, str]] = None
        while attempt < 3 and number_info is None:
            attempt += 1
            number_info = hero_buy_number(scraper, hero_key, country)
            if number_info is None:
                print(f"NO_NUMBERS 또는 실패, 10초 대기 후 재시도 ({attempt}/3)")
                time.sleep(10)
        if number_info is None:
            print(f"❌ 계정 {idx}: 번호를 얻지 못했습니다. 다음 계정으로.")
            fail += 1
            continue

        req_id, raw_phone = number_info
        full_phone = f"+{raw_phone.lstrip('+')}"
        print(f"[계정 {idx}] 번호 확보: id={req_id}, phone={full_phone}")

        # Pyrogram Client: connect() → send_code() → sign_in() → export() → disconnect()
        app = Client(
            name=f"session_{raw_phone}",
            api_id=api_id,
            api_hash=api_hash,
            in_memory=True,
        )
        try:
            app.connect()

            # 2) 인증 코드 발송
            sent = app.send_code(full_phone)
            phone_code_hash = getattr(sent, "phone_code_hash", None)
            if not phone_code_hash:
                print("❌ phone_code_hash 를 얻지 못했습니다. 번호 취소 후 다음 계정으로.")
                hero_set_status(scraper, hero_key, req_id, status=8)
                fail += 1
                app.disconnect()
                continue
            print(f"[계정 {idx}] 코드 발송 완료, hash={phone_code_hash}")

            # 3) 코드 수신 (최대 2분, 10초 간격)
            code = None
            deadline = time.time() + 120
            while time.time() < deadline:
                status_text = hero_get_status(scraper, hero_key, req_id)
                print(f"[계정 {idx}] getStatus 응답: {status_text}")
                if status_text.startswith("STATUS_OK:"):
                    try:
                        _, code_part = status_text.split(":", 1)
                        code = code_part.strip()
                        break
                    except ValueError:
                        pass
                elif status_text.startswith("STATUS_CANCEL"):
                    print(f"[계정 {idx}] 번호가 취소됨. 다음 계정으로.")
                    break
                # STATUS_WAIT_CODE 또는 기타: 잠시 대기 후 재시도
                time.sleep(10)

            if not code:
                print(f"[계정 {idx}] 2분 내 코드 미수신. 번호 취소 후 다음 계정으로.")
                hero_set_status(scraper, hero_key, req_id, status=8)
                fail += 1
                app.disconnect()
                continue

            # 4) 자동 로그인
            try:
                app.sign_in(full_phone, phone_code_hash, code)
            except PhoneCodeExpired:
                print(f"[계정 {idx}] PhoneCodeExpired: 번호 취소 후 다음 계정으로.")
                hero_set_status(scraper, hero_key, req_id, status=8)
                fail += 1
                app.disconnect()
                continue
            except Exception as e:
                print(f"[계정 {idx}] 로그인 오류: {e}")
                hero_set_status(scraper, hero_key, req_id, status=8)
                fail += 1
                app.disconnect()
                continue

            # 5) SESSION_STRING 생성 및 저장
            session_string = app.export_session_string()
            session_idx = _append_session(session_string)
            print(f"[계정 {idx}] SESSION_STRING_{session_idx} 저장 완료")

            # 6) 번호 사용 완료 처리 (status=6)
            hero_set_status(scraper, hero_key, req_id, status=6)
            success += 1

            app.disconnect()

        except Exception as e:
            print(f"[계정 {idx}] 예외 발생: {e}")
            # 안전하게 번호 취소 시도
            try:
                hero_set_status(scraper, hero_key, req_id, status=8)
            except Exception:
                pass
            try:
                app.disconnect()
            except Exception:
                pass
            fail += 1
            continue

    print("\n" + "=" * 66)
    print(f"전체 {success + fail}개 중 성공: {success}개, 실패: {fail}개")
    print("data/sessions.txt 파일을 확인하세요.")
    print("=" * 66)


if __name__ == "__main__":
    main()

