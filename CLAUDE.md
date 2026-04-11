# CLAUDE.md — 프로젝트 참조 문서

이 파일은 Claude Code가 이 프로젝트를 작업할 때 반드시 먼저 읽어야 하는 문서입니다.
과거에 반복된 실수와 핵심 구조를 정리합니다.

---

## 프로젝트 구조

```
my-bot/
├── app/
│   ├── main.py              # FastAPI 진입점 (Railway 배포)
│   │                        #   /health, /track/{ref}, /debug/status, /debug/session-test
│   ├── userbot_sender.py    # Pyrogram UserBot DM 브로드캐스트 핵심 로직
│   ├── pg_broadcast.py      # PostgreSQL broadcast_targets 테이블 CRUD
│   ├── scheduler.py         # APScheduler 채널 자동 발송
│   └── services/
│       └── premium_formatter.py
│
├── bot/
│   ├── main.py              # python-telegram-bot 폴링 진입점 (app/main.py에서 thread로 시작)
│   ├── handlers/
│   │   └── callbacks.py     # 실제 사용되는 봇 핸들러 (admin, 장전, 발사, 메뉴)
│   └── app/
│       └── userbot_sender.py  # ⚠️ 사용 안 함 (bot/app/userbot_sender.py는 무시)
│
├── scripts/
│   ├── generate_session.py  # Pyrogram SESSION_STRING 생성
│   ├── dm_campaign_runner.py
│   └── retry_sender.py
│
├── bot/src/handlers/callbacks.py  # ⚠️ 사용 안 함 (bot/handlers/callbacks.py가 실제 사용됨)
└── CLAUDE.md                # 이 파일
```

### 어떤 파일이 실제로 실행되는가

| 역할 | 실제 파일 | 주의 |
|------|-----------|------|
| FastAPI 서버 | `app/main.py` | Railway 시작점 |
| 봇 핸들러 | `bot/handlers/callbacks.py` | `bot/main.py`가 import |
| UserBot 발송 | `app/userbot_sender.py` | `bot/handlers/callbacks.py`가 `from app.userbot_sender import broadcast_via_userbot` |
| DB | `app/pg_broadcast.py` | PostgreSQL (Railway) |

`bot/app/userbot_sender.py`와 `bot/src/handlers/callbacks.py`는 **사용되지 않는 파일**이다.
수정 시 항상 `app/userbot_sender.py`와 `bot/handlers/callbacks.py`를 수정할 것.

---

## DM 브로드캐스트 전체 흐름

```
관리자가 미디어 전송 (봇에게)
  └─ bot/handlers/callbacks.py :: admin_load_message_handler()
       1. Bot API file_id → SQLite loaded_message 저장
       2. Pyrogram으로 Saved Messages 업로드 시도 (SESSION_STRING_1)
          → 성공 시 userbot_message_id → PostgreSQL loaded_message 저장

관리자가 [🚀 발사] 클릭
  └─ bot/handlers/callbacks.py :: _broadcast_loaded_message()
       └─ app/userbot_sender.py :: broadcast_via_userbot()
            1. Bot API getFile → BytesIO 다운로드
            2. SESSION_STRING_1~10 로드 + get_me() 검증 (만료 세션 즉시 제거)
            3. 유저별 직접 send_video/send_photo/send_document
               - 계정당 첫 발송: BytesIO 업로드 → file_id 캐시
               - 이후 발송: 캐시된 file_id 재사용
            4. 실패 시 admin DM으로 에러 상세 즉시 전송
            5. finally: 모든 Pyrogram 클라이언트 stop()
```

### ⚠️ Saved Messages 방식은 제거됨

과거에 "Saved Messages에 업로드 → copy_message" 방식을 사용했으나
업로드 실패가 계속 발생해 **직접 발송 방식으로 교체**했다.
절대로 Saved Messages 업로드 방식으로 되돌리지 말 것.

---

## 환경변수 목록

| 변수 | 필수 | 설명 |
|------|------|------|
| `BOT_TOKEN` | ✅ | Telegram Bot API 토큰 |
| `API_ID` | ✅ | Telegram App API ID (my.telegram.org) |
| `API_HASH` | ✅ | Telegram App API Hash |
| `SESSION_STRING_1` ~ `SESSION_STRING_10` | ✅ | Pyrogram StringSession (최소 1개) |
| `SESSION_STRING` | 대체 | _1~_10 없을 때 fallback |
| `DATABASE_URL` | ✅ | PostgreSQL 연결 URL |
| `ADMIN_ID` | ✅ | 관리자 Telegram user_id (정수) |
| `VIP_URL` | | 인라인 버튼 URL (기본값 있음) |
| `AFFILIATE_URL` | | 제휴 링크 (캡션 치환용) |
| `TRACKING_SERVER_URL` | | 추적 서버 URL |
| `USER_DELAY_MIN/MAX` | | DM 간격 (기본 3~7초) |
| `LONG_BREAK_EVERY` | | N명마다 긴 휴식 (기본 50) |
| `LONG_BREAK_MIN/MAX` | | 긴 휴식 시간 초 단위 (기본 300~600) |

---

## 자주 발생하는 에러 패턴과 해결법

### 1. `AuthKeyUnregistered` / `AuthKeyDuplicated`
- **원인**: SESSION_STRING이 만료되었거나 다른 기기에서 로그아웃됨
- **해결**: `python scripts/generate_session.py`로 새 세션 생성 후 Railway 환경변수 교체
- **확인**: `GET /debug/session-test` 엔드포인트로 각 세션 상태 확인

### 2. `미디어 업로드에 성공한 계정이 없습니다`
- **원인**: 과거 Saved Messages 방식 사용 시 발생하던 에러 — 현재 코드에서는 직접 발송으로 변경됨
- **현재 코드에서**: 이 메시지가 나오면 `broadcast_via_userbot` 내 세션 검증 단계에서 모든 계정이 실패한 것
- **해결**: `/debug/session-test`로 세션 상태 확인

### 3. `MediaInvalid` (Pyrogram RPCError)
- **원인**: BytesIO의 `bio.name` 확장자가 실제 파일 형식과 맞지 않거나, 파일이 손상됨
- **현재 코드**: `send_video` 실패 시 `send_document`로 자동 fallback 처리됨

### 4. `PeerIdInvalid` / `UsernameNotOccupied`
- **원인**: username이 존재하지 않거나 변경됨 — 정상적인 skip 대상
- **처리**: `skipped` 카운트 증가 후 계속 진행 (에러가 아님)

### 5. `FloodWait`
- **원인**: Telegram 스팸 방지 — 해당 계정에 쿨다운 설정
- **처리**: `acc["cooldown_until"]` 설정 후 다음 계정으로 자동 전환
- **예방**: `USER_DELAY_MIN/MAX` 환경변수로 딜레이 조정

### 6. `bot/handlers/callbacks.py`의 `_broadcast_loaded_message`에서 SESSION_STRING 체크 실패
- **원인**: `if not (os.getenv("API_ID") and os.getenv("API_HASH") and os.getenv("SESSION_STRING"))` 에서
  `SESSION_STRING_1`만 있고 `SESSION_STRING`이 없으면 차단됨
- **해결**: `SESSION_STRING` 환경변수도 함께 설정하거나, 해당 체크 로직 수정

---

## PostgreSQL 테이블 구조

### `broadcast_targets`
```sql
telegram_user_id  BIGINT PRIMARY KEY
username          TEXT              -- @username (없으면 발송 불가)
source            TEXT              -- 'bot' | 'scraper'
is_sent           BOOLEAN DEFAULT FALSE
sent_at           TIMESTAMPTZ
unique_ref        TEXT              -- 추적 링크용 UUID
retry_sent        BOOLEAN DEFAULT FALSE
```

### `loaded_message` (PostgreSQL)
```sql
userbot_message_id  BIGINT   -- Pyrogram Saved Messages message_id (현재 미사용)
file_type           TEXT
caption             TEXT
```

SQLite `loaded_message` (bot/data/users.db):
```sql
file_id    TEXT   -- Bot API file_id (이것이 실제 발송에 사용됨)
file_type  TEXT
caption    TEXT
```

---

## 수정 시 주의사항

### 절대 하지 말 것

1. **`bot/app/userbot_sender.py` 수정 금지** — 이 파일은 사용되지 않음. 항상 `app/userbot_sender.py` 수정.
2. **Saved Messages 업로드 방식 재도입 금지** — 업로드 실패 문제로 완전히 제거됨.
3. **`client.start()` 후 `get_me()` 없이 계정을 유효하다고 가정 금지** — in_memory 세션은 만료된 세션도 start() 성공처럼 보임. 반드시 `get_me()` 호출로 검증.
4. **에러를 `logger.warning`만으로 처리 금지** — `logger.exception()` 사용해 트레이스백 포함. 관리자 DM에도 에러 내용 전송.
5. **`all_started` 리스트 없이 클라이언트 정리 금지** — `finally`에서 업로드 실패한 클라이언트도 반드시 `stop()` 호출.

### Pyrogram BytesIO 발송 패턴

```python
# ✅ 올바른 방법
bio = io.BytesIO(file_bytes)
bio.seek(0)
bio.name = "media.mp4"   # 확장자가 MIME 타입 결정에 사용됨
sent = await client.send_video("me", bio, duration=0, width=0, height=0)

# ❌ 잘못된 방법 (name 없으면 Pyrogram이 MIME 타입 추론 실패)
bio = io.BytesIO(file_bytes)
sent = await client.send_video("me", bio)
```

### file_id 캐싱 패턴 (재업로드 방지)

```python
if acc["cached_file_id"] is None:
    msg = await client.send_video(target, _make_bio(), ...)
    acc["cached_file_id"] = msg.video.file_id   # Pyrogram: msg.video.file_id
else:
    msg = await client.send_video(target, acc["cached_file_id"], ...)
```

> **주의**: Pyrogram의 `msg.photo`는 `Photo` 객체이므로 `msg.photo.file_id`.
> python-telegram-bot은 `msg.photo[-1].file_id` (리스트). 혼동 금지.

---

## 디버그 엔드포인트

| URL | 설명 |
|-----|------|
| `/health` | 서비스 생존 확인 |
| `/debug/status` | DB 연결, 장전 상태, 세션 개수 확인 |
| `/debug/session-test` | 각 SESSION_STRING으로 Pyrogram 연결 시도 후 결과 반환 |

세션 문제 의심 시 **반드시 `/debug/session-test` 먼저 호출**.

---

## SESSION_STRING 생성 방법

```bash
# 로컬에서 실행 (Railway 아님 — 전화번호 입력 필요)
python scripts/generate_session.py
```

출력된 SESSION_STRING을 Railway 환경변수 `SESSION_STRING_1` ~ `SESSION_STRING_10`에 등록.
