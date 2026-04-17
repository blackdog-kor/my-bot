# CLAUDE.md — 프로젝트 참조 문서

이 파일은 Claude Code가 이 프로젝트를 작업할 때 반드시 먼저 읽어야 한다.
마지막 갱신: 2026-04-18

---

## 1. 시스템 개요

카지노 어필리에이트 텔레그램 봇 자동화 시스템.
타겟 그룹 발굴 → 멤버 수집 → DM 발송 → 클릭 추적 → 구독봇 유입 순환 구조.

| 항목 | 값 |
|------|-----|
| 레포 | blackdog-kor/my-bot |
| 배포 | Railway (단일 서비스) |
| 런타임 | Python 3.11 (runtime.txt) |
| 웹 서버 | FastAPI + uvicorn |
| 봇 프레임워크 | python-telegram-bot (Bot API) + Pyrogram 2.0.106 (DM 발송) + Telethon (멤버 수집/그룹 발굴) |
| DB | Railway PostgreSQL |
| 스케줄러 | APScheduler (BackgroundScheduler) |
| 디버그 URL | https://web-production-608e6.up.railway.app |

---

## 2. 봇 역할 분리 (중요)

| 봇 | 토큰 환경변수 | 핸들 | 상태 | 역할 |
|----|-------------|-------|------|------|
| 구독봇 | SUBSCRIBE_BOT_TOKEN | @blackdog_eve_casino_bot | 정상 | 메인 봇. 유저 유입, /start 환영, 게시물 CRUD, 설정 관리, 발송 트리거 |
| 관리봇 | BOT_TOKEN | @viP_cAsiNocLub_bot | 계정 제한 중 | /start, /admin 캠페인 현황 조회 전용 (간소화됨) |

구독봇이 메인이다. 게시물 관리·설정·발송 UI는 구독봇(bot/subscribe_bot.py)에 집중.
관리봇(bot/handlers/callbacks.py)은 현황 조회만 담당하며, 과거 있던 장전/발사 기능은 제거됨.

---

## 3. 계정 구조 (전체)

| 계정 | 환경변수 | 용도 | 상태 |
|------|---------|------|------|
| @viP_cAsiNocLub_bot | BOT_TOKEN | 관리봇 | 계정 제한 중 |
| @blackdog_eve_casino_bot | SUBSCRIBE_BOT_TOKEN | 구독봇 (메인) | 정상 |
| @BlackDog_eve | SESSION_STRING_1 | DM 발송 UserBot (Pyrogram) | 활성 |
| @8638661874 (+821059290563) | SESSION_STRING_TELETHON | 멤버 수집/그룹 발굴 (Telethon) | 활성 |
| blackdog.kor | — | 스팸 제한으로 사용 불가 | 사용 불가 |

---

## 4. 프로세스 기동 구조

Procfile: web: uvicorn app.main:app --host 0.0.0.0 --port $PORT

app/main.py (FastAPI lifespan)
 ├── DB 테이블 초기화 (broadcast_targets, campaign_posts, campaign_config)
 ├── Thread: 관리봇        (bot/main.py → polling)          ← BOT_TOKEN
 ├── Thread: 구독봇        (bot/subscribe_bot.py → polling) ← SUBSCRIBE_BOT_TOKEN (토큰 있을 때만)
 └── Thread: 스케줄러      (app/scheduler.py)

모든 스레드는 daemon=True. FastAPI가 죽으면 전부 종료.
각 스레드는 독립 asyncio 이벤트 루프를 생성하므로 루프 충돌 없음.

---

## 5. 파일 맵 (실제 사용 파일만)

my-bot/
├── app/
│   ├── main.py              # FastAPI 진입점 + 디버그 엔드포인트
│   ├── userbot_sender.py    # Pyrogram DM 발송 핵심 로직
│   ├── pg_broadcast.py      # PostgreSQL CRUD (3개 테이블)
│   └── scheduler.py         # APScheduler 자동 Job (cron)
│
├── bot/
│   ├── main.py              # 관리봇 진입점 (polling)
│   ├── handlers/
│   │   └── callbacks.py     # 관리봇 핸들러 (/start, /admin)
│   └── subscribe_bot.py     # 구독봇 전체 (메인 봇)
│
├── scripts/
│   ├── generate_session.py          # Pyrogram SESSION_STRING 생성 (로컬 실행 전용)
│   ├── generate_telethon_session.py # Telethon SESSION_STRING_TELETHON 생성 (로컬 실행 전용)
│   ├── group_finder.py       # 그룹 발굴 (스케줄: 03:00 UTC)
│   ├── member_scraper.py     # 멤버 수집 (스케줄: 00:00 UTC)
│   ├── dm_campaign_runner.py # DM 발송 실행 (스케줄: 비활성화 중)
│   ├── retry_sender.py       # 미클릭 재발송 (스케줄: 12:00 UTC)
│   ├── subscribe_push.py     # 구독봇 자동 푸시 (스케줄: 00:00 UTC)
│   └── warmup.py             # 세션 워밍업 (스케줄: 23:00 UTC)

사용되지 않는 경로 (수정 금지):
- bot/app/userbot_sender.py → 실제는 app/userbot_sender.py
- bot/src/handlers/callbacks.py → 실제는 bot/handlers/callbacks.py

---

## 6. PostgreSQL 테이블 구조 (3개)

broadcast_targets:
  telegram_user_id BIGINT PRIMARY KEY
  username TEXT, source TEXT, added_at TIMESTAMPTZ
  is_sent BOOLEAN DEFAULT FALSE, sent_at TIMESTAMPTZ
  clicked_at TIMESTAMPTZ, click_count INTEGER DEFAULT 0
  unique_ref TEXT, retry_sent BOOLEAN DEFAULT FALSE, retry_sent_at TIMESTAMPTZ

campaign_posts:
  id SERIAL PRIMARY KEY
  file_id TEXT NOT NULL, file_type TEXT NOT NULL DEFAULT 'photo'
  caption TEXT NOT NULL DEFAULT '', is_active BOOLEAN NOT NULL DEFAULT TRUE
  send_order INTEGER NOT NULL DEFAULT 0
  last_sent_at TIMESTAMPTZ (순환 기준: 가장 오래된 것부터 선택)
  created_at TIMESTAMPTZ DEFAULT NOW()

campaign_config (단일 행, id=1):
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id=1)
  affiliate_url TEXT, promo_code TEXT, caption_template TEXT
  subscribe_bot_link TEXT DEFAULT 't.me/blackdog_eve_casino_bot'
  updated_at TIMESTAMPTZ DEFAULT NOW()

### DB 현황 (2026-04-18 기준)
- broadcast_targets 미발송: 9,387명
- discovered_groups: 10개 (브라질 카지노 채널/그룹)
- campaign_posts 활성: 2개

---

## 7. DM 발송 형태 (확정)

- 미디어: 영상 (video)
- 캡션: 이탤릭/스포일러 포맷 + caption_entities 보존 (커스텀이모지 제외)
- 인라인 버튼: [Join Vip Now] → https://1wyucu.life/?p=j7ll
- 발송 계정: @BlackDog_eve (SESSION_STRING_1)

---

## 8. DM 발송 흐름 (broadcast_via_userbot)

dm_campaign_runner.py (또는 구독봇 발송 트리거)
  └─ get_next_post() → campaign_posts에서 순환 선택 (last_sent_at ASC)
  └─ broadcast_via_userbot(bot_token, file_id, file_type, caption, notify_callback)
       1. Bot API getFile → BytesIO 다운로드
       2. SESSION_STRING_1~10 로드 + get_me() 검증 (만료 세션 즉시 제거)
       3. broadcast_targets에서 미발송(is_sent=FALSE, username IS NOT NULL) 조회
       4. 유저별 직접 send_video/send_photo/send_document
          - 계정당 첫 발송: BytesIO 업로드 → msg.video.file_id 캐시
          - 이후 발송: 캐시된 file_id 재사용 (재업로드 없음)
       5. 딜레이: 유저 간 15~45초, 50명마다 5~10분 긴 휴식
       6. 실패 시 admin DM으로 에러 상세 즉시 전송 (logger.exception)
       7. finally: 시작된 모든 Pyrogram 클라이언트 stop()

Saved Messages 방식은 완전히 제거됨. 절대로 되돌리지 말 것.

---

## 9. 스크래퍼 아키텍처

### group_finder.py (03:00 UTC)
1. Bright Data SERP API → Google `site:t.me` 검색 (SEARCH_KEYWORDS 환경변수)
2. 채널/그룹 URL 파싱 → MIN_MEMBER_COUNT 이상 필터
3. Phase 3: Telethon으로 채널 연결 토론그룹 탐색
4. discovered_groups 테이블에 저장 (MAX_GROUPS_PER_RUN 제한)

### member_scraper.py (00:00 UTC)
1. discovered_groups에서 그룹 목록 로드
2. Telethon iter_participants() → broadcast_targets 저장
3. join_groups_for_broadcast_accounts 자동 실행 (PeerIdInvalid 예방)

---

## 10. 스케줄러 (UTC 기준)

| 시간 (UTC) | 시간 (KST) | Job | 파일 | 상태 |
|-----------|-----------|-----|------|------|
| 23:00 | 08:00 | 워밍업 | warmup.py | ✅ 활성 |
| 00:00 | 09:00 | 멤버 수집 | member_scraper.py | ✅ 활성 |
| 00:00 | 09:00 | 구독봇 푸시 | subscribe_push.py | ✅ 활성 |
| 03:00 | 12:00 | 그룹 발굴 | group_finder.py | ✅ 활성 |
| 06:00 | 15:00 | DM 발송 | dm_campaign_runner.py | ❌ 주석 처리 |
| 12:00 | 21:00 | 재발송 | retry_sender.py | ✅ 활성 |

Job 간 threading.Lock으로 직렬화 — 동시 실행 없음.

---

## 11. 환경변수 전체 목록

### Railway 등록 완료
| 변수 | 값/설명 |
|------|--------|
| DATABASE_URL | Railway PostgreSQL 연결 URL |
| ADMIN_ID | 관리자 Telegram user_id (정수) |
| API_ID | 37398454 |
| API_HASH | Telegram App API Hash |
| BOT_TOKEN | 관리봇 토큰 (@viP_cAsiNocLub_bot) |
| SUBSCRIBE_BOT_TOKEN | 구독봇 토큰 (@blackdog_eve_casino_bot) |
| SESSION_STRING_1 | Pyrogram StringSession (@BlackDog_eve) |
| SESSION_STRING_TELETHON | Telethon StringSession (@8638661874) |
| AFFILIATE_URL | 어필리에이트 링크 |
| BRIGHTDATA_API_TOKEN | Bright Data SERP API 토큰 |
| SEARCH_KEYWORDS | 그룹 발굴 검색 키워드 목록 |
| MIN_MEMBER_COUNT | 최소 멤버 수 필터 (기본 5000) |
| MAX_GROUPS_PER_RUN | 1회 발굴 최대 그룹 수 (기본 20) |
| DAILY_LIMIT_PER_ACCOUNT | 계정당 일일 한도 (기본 100) |

### 선택 환경변수 (미등록 시 기본값 사용)
| 변수 | 기본값 | 설명 |
|------|-------|------|
| SESSION_STRING | — | SESSION_STRING_1~10 없을 때 fallback |
| CHANNEL_ID | — | 채널 ID (구독봇용) |
| VIP_URL | — | 인라인 버튼 URL |
| TRACKING_SERVER_URL | — | 클릭 추적 서버 URL |
| GEMINI_API_KEY | — | Gemini 캡션 개인화용 |
| USER_DELAY_MIN/MAX | 15~45 | DM 간격 (초) |
| LONG_BREAK_EVERY | 50 | N명마다 긴 휴식 |
| LONG_BREAK_MIN/MAX | 300~600 | 긴 휴식 (초) |
| BATCH_SIZE | 50 | 1회 발송 건수 |

---

## 12. 현재 상태 (2026-04-18)

- **구독봇** (@blackdog_eve_casino_bot): 정상 작동
- **관리봇** (@viP_cAsiNocLub_bot): 계정 제한 중
- **DM 발송 계정** (@BlackDog_eve): SESSION_STRING_1 단독 활성 → 추가 세션 확보 필요
- **DM 발송 스케줄**: ❌ 비활성 (_job_dm_campaign 주석 처리) — 워밍업 완료 후 활성화 필요
- **미발송 타겟**: 9,387명 대기 중
- **발굴된 그룹**: 10개 (브라질 카지노)
- **캠페인 게시물**: 2개 활성

### 미완료 작업
1. DM 발송 스케줄 활성화 (scheduler.py `_job_dm_campaign` 주석 해제)
2. 1win 채널 운영 검토 (본사 제안)
3. 추가 SESSION_STRING 세션 확보 (SESSION_STRING_2~)

---

## 13. 디버그 엔드포인트

베이스 URL: https://web-production-608e6.up.railway.app

| 경로 | 설명 |
|------|------|
| GET /health | 생존 확인 |
| GET /debug/status | DB, campaign_posts, 세션 수, 미발송 타겟 수 |
| GET /debug/session-test | SESSION_STRING Pyrogram 연결 테스트 |
| GET /debug/dm-test?username=xxx | 테스트 DM 발송 (username) |
| GET /debug/dm-test?user_id=123 | 테스트 DM 발송 (user_id) |
| GET /debug/routes | 등록된 FastAPI 라우트 목록 |
| GET /debug/run-group-finder | group_finder 수동 실행 |
| GET /debug/run-member-scraper | member_scraper 수동 실행 |

세션 문제 의심 시 반드시 /debug/session-test 먼저 호출.

---

## 14. 자주 발생하는 에러 패턴

AuthKeyUnregistered / AuthKeyDuplicated
→ SESSION_STRING 만료. generate_session.py 재실행 후 Railway 환경변수 교체.

PeerIdInvalid
→ UserBot이 해당 그룹에 미가입 상태. 정상 skip 대상.
→ 근본 해결: member_scraper 실행 시 join_groups_for_broadcast_accounts 자동 실행됨.

FloodWait
→ acc["cooldown_until"] 설정 후 다음 계정 자동 전환.
→ 예방: USER_DELAY_MIN/MAX 조정, warmup 선행.

MediaInvalid
→ send_video 실패 시 send_document로 자동 fallback.

SESSION_STRING 체크 실패
→ SESSION_STRING 환경변수도 함께 설정 권장.

---

## 15. 절대 규칙

1. bot/app/userbot_sender.py 수정 금지 — 사용되지 않음. 항상 app/userbot_sender.py 수정.
2. Saved Messages 업로드 방식 재도입 금지.
3. client.start() 후 get_me() 없이 계정 유효 가정 금지.
4. 에러를 logger.warning만으로 처리 금지 — logger.exception() + 관리자 DM.
5. finally에서 모든 클라이언트 stop() 누락 금지.
6. partial diff / 코드 조각 제공 금지 — 항상 통파일 출력.
7. 증분 패치보다 근본 재설계 우선.

Pyrogram BytesIO 발송 패턴:
  bio = io.BytesIO(file_bytes)
  bio.seek(0)
  bio.name = "media.mp4"  # 확장자 필수
  sent = await client.send_video(target, bio, duration=0, width=0, height=0)

file_id 캐싱:
  msg.video.file_id  (Pyrogram — 단일 객체)
  msg.photo[-1].file_id  (python-telegram-bot — 리스트)  혼동 금지.

---

## 16. SESSION_STRING 생성

Pyrogram (DM 발송용):
  python scripts/generate_session.py  (로컬 실행, 전화번호 입력 필요)
  출력된 문자열을 Railway 환경변수 SESSION_STRING_1~10에 등록.

Telethon (멤버 수집용):
  python scripts/generate_telethon_session.py  (로컬 실행, 전화번호 입력 필요)
  출력된 문자열을 Railway 환경변수 SESSION_STRING_TELETHON에 등록.

주의: Pyrogram StringSession ≠ Telethon StringSession — 포맷이 다르므로 혼용 불가.

---

## 17. 발송 재개 체크리스트

1. generate_session.py → SESSION_STRING_2~ 추가
2. Railway 환경변수 추가 후 재배포
3. /debug/session-test 로 전체 세션 검증
4. warmup.py 3~7일 선행 (그룹 가입, 일반 활동)
5. 타겟 그룹에 각 UserBot 계정 가입 (PeerIdInvalid 예방)
6. scheduler.py 에서 `_job_dm_campaign` 주석 해제
7. /debug/status 로 전체 상태 확인
8. 구독봇에서 테스트 발송 1명 → 정상 확인 후 전체 발송

---

## 18. 개발 워크플로우

개발 환경: claude.ai/code (Codespaces 불필요)
배포: GitHub push → Railway 자동 배포
코드 수정 승인: Claude Code에서 "Yes, and don't ask again"
테스트 순서: /debug/session-test → /debug/dm-test → 구독봇 1명 테스트 → 전체 발송

---

## 19. 개발 방향 원칙

- 작은 수정으로 문제 해결 시도 금지
- 이미 완성된 오픈소스/최신 툴을 먼저 검토하고 도입
- 전세계 개발자들이 만든 마케팅/자동화 툴 적극 통합
- 자체 코드 수정보다 검증된 라이브러리/툴 교체 우선
- 최신 기술 트렌드 반영이 기본 방향
