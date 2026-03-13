#!/usr/bin/env python3
"""
HeroSMS API 엔드포인트 테스트 스크립트.

환경변수:
  - HERO_SMS_API_KEY

아래 URL들을 모두 호출하고 요청 URL, status_code, 응답 텍스트를 출력합니다.

1. https://hero-sms.com/stubs/handler.php?api_key={key}&action=getBalance
2. https://hero-sms.com/api/v1/getBalance?api_key={key}
3. https://hero-sms.com/api?api_key={key}&action=getBalance
4. https://api.hero-sms.com/v1/?api_key={key}&action=getBalance
"""

import os
import sys

import requests


def main() -> None:
    api_key = (os.getenv("HERO_SMS_API_KEY") or "").strip()
    if not api_key:
        print("❌ HERO_SMS_API_KEY 환경변수가 설정되지 않았습니다.")
        sys.exit(1)

    urls = [
        f"https://hero-sms.com/stubs/handler.php?api_key={api_key}&action=getBalance",
        f"https://hero-sms.com/api/v1/getBalance?api_key={api_key}",
        f"https://hero-sms.com/api?api_key={api_key}&action=getBalance",
        f"https://api.hero-sms.com/v1/?api_key={api_key}&action=getBalance",
    ]

    for i, url in enumerate(urls, start=1):
        print("=" * 80)
        print(f"[{i}] 요청 URL:")
        print(url)
        print("-" * 80)
        try:
            resp = requests.get(url, timeout=20)
            print(f"status_code: {resp.status_code}")
            print("응답 텍스트:")
            print(resp.text)
        except Exception as e:
            print(f"요청 중 예외 발생: {e}")
        print()


if __name__ == "__main__":
    main()

