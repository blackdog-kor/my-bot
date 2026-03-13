#!/usr/bin/env python3
"""
HeroSMS API 엔드포인트 테스트 스크립트 (Cloudflare 우회용 cloudscraper 사용).

환경변수:
  - HERO_SMS_API_KEY

테스트할 URL:
1. https://hero-sms.com/api?api_key={key}&action=getBalance
2. https://hero-sms.com/api?api_key={key}&action=getNumbersStatus&service=tg&country=0
"""

import os
import sys

import cloudscraper


def main() -> None:
    api_key = (os.getenv("HERO_SMS_API_KEY") or "").strip()
    if not api_key:
        print("❌ HERO_SMS_API_KEY 환경변수가 설정되지 않았습니다.")
        sys.exit(1)

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )

    urls = [
        f"https://hero-sms.com/api?api_key={api_key}&action=getBalance",
        f"https://hero-sms.com/api?api_key={api_key}&action=getNumbersStatus&service=tg&country=0",
    ]

    for i, url in enumerate(urls, start=1):
        print("=" * 80)
        print(f"[{i}] 요청 URL:")
        print(url)
        print("-" * 80)
        try:
            resp = scraper.get(url, timeout=20)
            print(f"status_code: {resp.status_code}")
            print("응답 텍스트:")
            print(resp.text)
        except Exception as e:
            print(f"요청 중 예외 발생: {e}")
        print()


if __name__ == "__main__":
    main()

