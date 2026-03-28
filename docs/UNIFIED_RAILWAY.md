# 통합 서비스 Railway 배포 (단일 서비스)

## 구조

- **단일 Railway 서비스** 하나에서 수집 → 발송 → 재발송 자동 로테이션
- 수집과 발송이 **동시에 실행되지 않음** (스케줄러가 `threading.Lock`으로 한 번에 하나의 Job만 실행)

## 폴더 구조

```
my-bot/
├── app/
│   ├── main.py            # FastAPI: /health, /track/{ref}
│   ├── pg_broadcast.py    # DB 공용
│   ├── userbot_sender.py  # UserBot 발송
│   ├── scheduler.py       # APScheduler (00:00 수집, 06:00 발송, 12:00 재발송)
│   └── services/
│       └── premium_formatter.py
├── bot/
│   ├── main.py            # Admin Bot (폴링)
│   └── handlers/
│       └── callbacks.py   # /admin, 장전, 알림
├── scripts/
│   ├── member_scraper.py
│   ├── dm_campaign_runner.py
│   └── retry_sender.py
├── data/
│   └── users.db           # SQLite (loaded_message)
├── Procfile
└── requirements.txt
```

## Procfile (단일 웹 프로세스)

```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- `app.main` lifespan에서 **Admin Bot**과 **스케줄러**를 각각 스레드로 기동
- 별도 Worker 불필요

## 환경변수 (Railway Variables)

통합해서 한 서비스에 모두 설정:

- `BOT_TOKEN`, `ADMIN_ID`
- `API_ID`, `API_HASH`, `SESSION_STRING`
- `DATABASE_URL` (PostgreSQL)
- `AFFILIATE_URL`, `TRACKING_SERVER_URL`, `RETRY_CAPTION`
- (선택) `CHANNEL_ID`, `USER_DELAY_MIN`, `USER_DELAY_MAX`, `LONG_BREAK_*` 등

## 스케줄

| 시각 (로컬) | Job |
|------------|-----|
| 00:00 | 수집 (`scripts/member_scraper.py`) |
| 06:00 | 발송 (`scripts/dm_campaign_runner.py`) |
| 12:00 | 재발송 (`scripts/retry_sender.py`) |

- Job 시작/완료/실패 시 관리자(`ADMIN_ID`)에게 DM 알림

## 검증

1. **GET /track/test** → `AFFILIATE_URL`로 302 리다이렉트
2. **봇 /admin** → 정상 응답 (장전/발사 안내)
3. **앱 기동 시** 스케줄러 로그에 다음 예약 Job 목록 출력 (수집 00:00, 발송 06:00, 재발송 12:00)

## 데이터 보존

- 기존 **broadcast_targets** (PostgreSQL) 100% 유지
- 기존 **loaded_message** (SQLite) 유지: 기존에 `bot/data/users.db`를 쓰던 경우, 한 번만 `data/users.db`로 복사하면 됨 (또는 `data/`에 새로 생성되면 봇에서 장전 시 저장됨)
- Railway 배포 시 `ensure_pg_table()`로 필요한 컬럼 자동 추가
