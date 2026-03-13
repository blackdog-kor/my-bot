#!/usr/bin/env python3
"""
data/sessions.txt 에 저장된 SESSION_STRING_N 값들을
Railway 환경변수(Variables)에 자동 등록하는 스크립트.

환경변수:
  - RAILWAY_TOKEN        (필수, Railway API 토큰)
  - RAILWAY_PROJECT_ID   (필수)
  - RAILWAY_SERVICE_ID   (필수)
  - RAILWAY_ENVIRONMENT_ID (선택, 기본 'production')

세션 파일 형식 예:
  SESSION_STRING_1=xxxxx
  SESSION_STRING_2=yyyyy

이 스크립트는 위 키들을 그대로 Railway Variables에 올립니다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SESSIONS_PATH = DATA_DIR / "sessions.txt"


def load_sessions() -> dict[str, str]:
    if not SESSIONS_PATH.is_file():
        print(f"❌ 세션 파일이 존재하지 않습니다: {SESSIONS_PATH}")
        sys.exit(1)

    variables: dict[str, str] = {}
    for line in SESSIONS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key.startswith("SESSION_STRING_"):
            continue
        if not value:
            continue
        variables[key] = value
    if not variables:
        print("❌ SESSION_STRING_* 항목을 찾지 못했습니다.")
        sys.exit(1)
    return variables


def main() -> None:
    token = (os.getenv("RAILWAY_TOKEN") or "").strip()
    project_id = (os.getenv("RAILWAY_PROJECT_ID") or "").strip()
    service_id = (os.getenv("RAILWAY_SERVICE_ID") or "").strip()
    environment_id = (os.getenv("RAILWAY_ENVIRONMENT_ID") or "production").strip()

    if not token or not project_id or not service_id:
        print("❌ RAILWAY_TOKEN / RAILWAY_PROJECT_ID / RAILWAY_SERVICE_ID 환경변수를 확인하세요.")
        sys.exit(1)

    variables = load_sessions()

    print("다음 세션들이 Railway에 업로드됩니다:")
    for k in sorted(variables.keys()):
        print(f"  {k}=(길이 {len(variables[k])})")

    url = "https://backboard.railway.app/graphql/v2"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    query = """
mutation VariableCollectionUpsert($input: VariableCollectionUpsertInput!) {
  variableCollectionUpsert(input: $input)
}
""".strip()

    payload = {
        "query": query,
        "variables": {
            "input": {
                "projectId": project_id,
                "serviceId": service_id,
                "environmentId": environment_id,
                "variables": variables,
            }
        },
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)

    print(f"\nHTTP status: {resp.status_code}")
    try:
        data = resp.json()
    except Exception:
        print("응답 JSON 파싱 실패:")
        print(resp.text)
        sys.exit(1)

    if "errors" in data:
        print("❌ GraphQL 오류 발생:")
        print(json.dumps(data["errors"], ensure_ascii=False, indent=2))
        sys.exit(1)

    print("✅ Railway 환경변수 등록 완료")


if __name__ == "__main__":
    main()

