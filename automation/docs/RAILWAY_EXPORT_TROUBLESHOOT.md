# Railway에서 CSV 텔레그램 전송 문제 해결

## 1. 로컬에서 확인한 결과

- **POST /api/export/competitor-users-telegram** 로컬 호출: **200 OK**, `rows_exported: 38881`
- 즉, 코드 경로는 정상 동작함. 로컬에서 호출 시 같은 봇으로 파일이 전송되는지 텔레그램 앱에서 확인 필요.

## 2. Railway 로그 확인 방법

Railway 대시보드에서:

1. **Project** → **automation 서비스** 선택
2. **Deployments** 또는 **Logs** 탭 이동
3. `/api/export/competitor-users-telegram` 호출 시점 또는 **어드민 메뉴에서 "📤 CSV 내보내기"** 클릭 시점의 로그 확인

**찾아볼 에러 예시:**
- `503 telegram app not ready` → BOT_TOKEN 미설정 또는 봇 초기화 실패
- `503 ADMIN_ID not configured` → ADMIN_ID 미설정(아래 3번 참고)
- `Database is empty` → DB에 competitor_users 없음(다른 에러 메시지일 수 있음)
- `Unauthorized` / `403` → 봇이 해당 채팅에 파일 전송 권한 없음
- Telegram API 에러 (파일 크기 제한 50MB 등)

## 3. ADMIN_ID 설정

- **로컬:** `automation/config/settings.json`의 `admin_id` 사용 (현재 `8289740456`)
- **Railway:**  
  - **방법 A:** 동일한 `settings.json`이 배포에 포함되어 있으면 그대로 사용됨.  
  - **방법 B:** Railway **Variables**에 `ADMIN_ID=8289740456` 추가 시, 코드에서 환경변수 값을 우선 사용함(이제 config에서 env 읽도록 수정됨).

Railway Variables에 `ADMIN_ID`가 있으면 그 값이 사용됩니다. 값이 비어 있거나 잘못되면 파일이 다른 곳으로 가거나 전송 실패할 수 있으니 확인하세요.

## 4. 텔레그램에서 CSV 받는 방법 (추가된 기능)

- **어드민 봇**에서 `/admin` 입력 → **"📤 CSV 내보내기"** 버튼 클릭  
- 동일 automation 프로세스에서 청크 단위로 CSV 생성 후, **요청한 어드민 계정(ADMIN_ID)**으로 파일 전송  
- HTTP로 직접 호출하지 않아도 됨.
