# CLAUDE.md — AI Agent Project Reference & System Architecture

이 문서는 Claude Code가 본 프로젝트(카지노 어필리에이트 자동화 파이프라인)를 조작하고 코드를 수정할 때 반드시 최우선으로 준수해야 하는 시스템 명세서이자 **절대 규칙(Critical Directives)**입니다.

마지막 갱신: 2026-04-18

---

## 1. 🛑 절대 준수 규칙 및 AI 행동 지침 (CRITICAL DIRECTIVES)

### 1.1 AI 사고 및 작업 워크플로우 (Chain of Thought)
- **수정 전 계획 수립:** 코드를 수정하기 전, 반드시 변경 사항이 시스템 전체(특히 비동기 루프 및 DB 트랜잭션)에 미칠 영향을 분석하고 명확한 계획을 먼저 세우십시오.
- **최신 툴링 최우선 적용:** 자체 로직 구현보다 검증된 최신 오픈소스 패키지(예: 재시도 로직에는 `tenacity`, 데이터 검증에는 `pydantic`) 도입을 우선하십시오.
- **Git 자동화:** 모든 작업은 `main` 브랜치에 직접 커밋 및 푸시합니다. `git push origin main` 즉시 Railway가 자동 배포합니다.

### 1.2 코드 품질 및 최신 파이썬 표준 (Modern Python Standards)
- **타입 힌팅 강제:** 모든 새로운 함수와 클래스에는 엄격한 Python Type Hint (예: `-> None`, `List[str]`, `Optional[int]`)를 적용하십시오.
- **비동기 최적화:** `asyncio.sleep()` 등 비동기 블로킹이 발생하지 않도록 주의하고, 스케줄러와 봇 루프 간의 데드락을 방지하십시오.
- **Ruff 호환성:** 코드는 빠르고 현대적인 린터인 `Ruff`의 통과 기준을 충족할 수 있도록 간결하고 표준적으로 작성하십시오.

### 1.3 보안 및 안티 탐지 우회 (Anti-Detection & Resilience)
- **Jitter 및 지수형 백오프 적용:** 텔레그램 API 요청 시 단순 고정 딜레이를 피하십시오. 재시도 및 대기열 로직에는 반드시 **Jitter(무작위 노이즈)**와 **Exponential Backoff** 패턴을 적용하여 패턴 탐지(FloodWait, Ban)를 회피하십시오.
- **구조화된 로깅 (Structured Logging):** 에러 발생 시 단순 문자열이 아닌, 컨텍스트(User ID, Session ID, File ID 등)를 포함한 풍부한 예외 처리(`logger.exception()`)를 수행하고 관리자 DM으로 즉시 알림을 전송하십시오.

### 1.4 금지 사항 (Do NOT)
- `bot/app/userbot_sender.py` 경로 사용 및 수정 금지 (폐기됨). 항상 `app/userbot_sender.py`를 사용.
- **Saved Messages 업로드 방식 재도입을 엄격히 금지합니다.** (현재의 BytesIO + 캐싱 방식 유지).
- Pyrogram 클라이언트 기동 시 `client.start()` 후 반드시 `get_me()`로 계정 유효성을 검증하십시오.
- 스크립트 종료 전 `finally` 블록에서 시작된 모든 클라이언트의 `stop()` 처리를 누락하지 마십시오.

---

## 2. 🏗 시스템 개요 (Architecture)

타겟 그룹 발굴 → 멤버 수집 → DM 발송(Jitter 적용) → 채널 유입 → 봇 가입 유도 파이프라인.

* **Repository:** blackdog-kor/my-bot
* **Infrastructure:** Railway (단일 서비스 배포)
* **Runtime:** Python 3.11 (`runtime.txt`)
* **Web Server:** FastAPI + uvicorn
* **Bot Frameworks:** * `python-telegram-bot` (구독/관리 봇 API)
    * `Pyrogram 2.0.106` (DM 자동 발송)
    * `Telethon` (멤버 스크래핑)
* **Database:** Railway PostgreSQL
* **Scheduler:** APScheduler (`BackgroundScheduler`)

---

## 3. 🤖 봇 역할 및 프로세스 기동 구조

FastAPI 구동 시 모든 스레드는 `daemon=True`로 실행되며, 독립적인 `asyncio` 이벤트 루프를 갖습니다.

| 봇 이름 | 환경변수 | 핸들 | 역할 및 특징 |
|---|---|---|---|
| **구독봇(Main)** | `SUBSCRIBE_BOT_TOKEN` | @blackdog_eve_casino_bot | 유입/환영, 게시물 CRUD, 발송 트리거 |
| **관리봇** | `BOT_TOKEN` | @viP_cAsiNocLub_bot | 캠페인 현황 조회 전용 |

### 주요 활성 디렉토리 맵
- `app/main.py`: FastAPI 진입점, 스레드 기동
- `app/userbot_sender.py`: Pyrogram DM 발송 핵심 로직 (우회 로직 포함)
- `app/pg_broadcast.py`: PostgreSQL CRUD
- `bot/subscribe_bot.py`: 메인 구독봇 로직
- `scripts/`: 로컬 세션 생성 및 스케줄러 배치 스크립트

---

## 4. 🗄 데이터베이스 스키마 (PostgreSQL)

| 테이블명 | 주요 목적 | 핵심 컬럼 |
|---|---|---|
| `broadcast_targets` | 타겟 유저 관리 | `telegram_user_id`(PK), `username`, `is_sent`, `clicked_at` |
| `campaign_posts` | 미디어 캐시 및 순환 발송 | `id`(PK), `file_id`, `file_type`, `caption`, `last_sent_at` |
| `campaign_config` | 시스템 설정값 관리 | `id=1`(단일행), `affiliate_url`, `subscribe_bot_link` |

---

## 5. ⚙️ 핵심 비즈니스 로직 및 워크플로우

### 5.1 DM 발송 흐름 (`broadcast_via_userbot`)
1. `campaign_posts`에서 `last_sent_at` ASC 기준으로 선택.
2. Bot API로 `BytesIO` 메모리 다운로드. (디스크 IO 최소화)
3. `SESSION_STRING_1~10` 로드 및 검증.
4. 타겟 조회 (`is_sent=FALSE`).
5. **업로드 및 캐싱:** 최초 1회 업로드 후 `msg.video.file_id` 캐싱. 이후 발송은 캐시 재사용.
6. **안전장치:** 인간 모사 Jitter 딜레이(15~45초 + alpha), 50명마다 5~10분 휴식.

### 5.2 스케줄러 작업 (UTC 기준)
- `00:00` (KST 09:00): 멤버 수집, 구독봇 푸시
- `03:00` (KST 12:00): 그룹 발굴
- `06:00` (KST 15:00): DM 발송 (*워밍업 전까지 주석 처리됨*)
- `12:00` (KST 21:00): 미클릭 재발송
- `23:00` (KST 08:00): 세션 워밍업 (Ban 방지용 계정 예열)
*(Job 간 `threading.Lock` 직렬화 적용)*

---

## 6. 🛠 트러블슈팅 및 상태 점검 (Observability)

코드 수정 후 반드시 아래 순서로 엔드포인트를 호출하여 상태를 점검하십시오.
1. `GET /health` (서버 생존)
2. `GET /debug/status` (DB 타겟 수, 활성 세션 상태 파악)
3. `GET /debug/session-test` (Pyrogram 세션 검증 - **필수**)
4. `GET /debug/dm-test?username=xxx` (테스트 발송)

**알려진 에러 대응 체계:**
- **AuthKeyUnregistered:** 세션 만료. 로컬 스크립트 재생성 요망.
- **PeerIdInvalid:** 타겟 그룹 미가입 상태. (정상 Skip 처리)
- **FloodWait:** 한도 초과. 쿨다운 설정 및 다음 계정 즉시 전환 (백오프 알고리즘 작동).
