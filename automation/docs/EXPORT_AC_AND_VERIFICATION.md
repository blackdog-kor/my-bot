# 유저 CSV 추출 인수 조건(AC) 및 검증 계획

## 인수 조건 (Acceptance Criteria)

| # | 조건 | 만족 방식 |
|---|------|-----------|
| AC1 | DB(`posts.db`)에서 2만 명 이상 유저 데이터를 CSV로 추출 | `competitor_users` 테이블을 대상으로, `fetchmany(500)` 청크 단위로 읽어 디스크 파일로 기록 |
| AC2 | 한 번에 메모리에 올리지 않고 500개씩 청크 처리 | 커서에서 `fetchmany(500)`만 사용, 전체 `fetchall()` 금지. CSV는 스트리밍으로 파일에 기록 |
| AC3 | 작업 중 서버 메모리 급증/ OOM 없음 | 행 데이터는 최대 500행만 동시에 유지. CSV 본문은 파일에 순차 기록 후 Telegram 전송 시에도 파일 스트림으로 전달 |
| AC4 | 완성된 CSV를 텔레그램 봇으로 내 계정에 전송 | 임시 CSV 파일 생성 → `bot.send_document(chat_id=ADMIN_ID, document=파일)` 호출 → 전송 후 임시 파일 삭제 |

---

## 구현 요약

1. **db.py**
   - **신규:** `export_competitor_users_to_csv_file(filepath: str, *, chunk_size: int = 500) -> int`
     - DB 연결 후 `SELECT ... FROM competitor_users ORDER BY ...` 실행, `fetchmany(chunk_size)` 루프.
     - 파일: UTF-8 BOM + 헤더 1줄 기록 후, 청크마다 행만 추가. 연결은 작업 끝까지 유지하되, 행은 500개씩만 보관 후 파일에 쓰고 버림.
     - 반환: 쓴 총 행 수.
   - **기존:** `export_competitor_users_csv() -> str` (fetchall 사용)는 HTTP 다운로드용으로 유지하거나, 대용량 시 사용 중단 권고. 또는 내부적으로 작은 청크만 사용하는 방식으로 변경 가능(선택).

2. **API + Telegram 전송**
   - **신규:** `POST /api/export/competitor-users-telegram` (또는 동일 역할의 경로)
     - 임시 파일 경로 생성 (예: `tempfile.NamedTemporaryFile(delete=False, suffix='.csv')`).
     - `export_competitor_users_to_csv_file(path, chunk_size=500)` 호출.
     - `telegram_app.bot.send_document(chat_id=ADMIN_ID, document=open(path, 'rb'))` 호출.
     - 전송 후 임시 파일 삭제, 성공/실패 JSON 반환.

3. **메모리 검증**
   - **단위 테스트:** `export_competitor_users_to_csv_file`에 대해:
     - DB를 모킹하거나 작은 SQLite DB로 2,500행 정도 넣고, `chunk_size=500`으로 실행.
     - 생성된 CSV 행 수가 2,500(+헤더 1)인지 검증.
     - 코드/모킹을 통해 `fetchmany(500)`만 호출되고 `fetchall()`이 호출되지 않음을 검증.
   - **통합(선택):** 실제 2만 행급 DB에서 엔드포인트 호출 후, 프로세스 메모리가 일정 임계치 이하인지 확인 (예: `memory_profiler` 또는 CI에서 RSS 체크). 문서화만 하고 CI는 나중에 추가 가능.

---

## 검증 계획 상세

### 1) 코드 수준 검증 (필수)
- `db.py` 내 export 함수에서 `fetchall()` 미사용, `fetchmany(chunk_size)`만 사용하는지 grep/테스트로 확인.
- 테스트에서 `chunk_size=500`으로 호출 시, 모킹 커서가 `fetchmany(500)`만 받고 `fetchall()`은 호출되지 않음을 assert.

### 2) 행 수 / 파일 무결성 검증 (필수)
- 테스트 DB에 2,500행 삽입 후 export → CSV 라인 수 = 1(헤더) + 2,500, 컬럼 수 일치.

### 3) 메모리 동작 검증 (권장)
- **옵션 A:** `tracemalloc`으로 export 전후 할당 크기 차이 확인 (청크 처리 시 증가량이 500행 분량 수준으로 제한되는지).
- **옵션 B:** `memory_profiler`로 해당 엔드포인트 호출 시 peak 메모리 기록 후, 2만 행에서도 OOM 없이 완료되는지 수동 확인.
- **문서화:** “2만 명 이상 추출 시 청크 단위 처리로 메모리 사용을 제한함”을 README 또는 docs에 명시.

### 4) Telegram 전송 검증 (필수)
- 테스트: `ADMIN_ID`를 모킹하거나 테스트 봇으로 실제 전송 후, 채팅에 CSV 파일이 도착하는지 확인.
- 엔드포인트 반환값: 200 + 성공 메시지 또는 파일명/행 수 포함.

---

## 구현 완료 사항 (체크)

- [x] `db.export_competitor_users_to_csv_file(filepath, chunk_size=500)` — fetchmany만 사용, 파일에 순차 기록
- [x] `POST /api/export/competitor-users-telegram` — 임시 CSV 생성 후 `send_document(ADMIN_ID)` 로 전송
- [x] 테스트: `test_export_chunked.py` — AC2(fetchmany만 사용) 및 행 수/컬럼 검증

이 문서는 AC 충족 및 메모리 안전 검증의 기준으로 사용합니다.
