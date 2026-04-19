# CLAUDE.md — 프로젝트 참조 문서

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

Saved Messages 방식은 완전히 제거됨. 절대로 되돌리지 말 것.

---

## 7. 스케줄러 (UTC 기준)

23:00 UTC (08:00 KST) — 워밍업 — warmup.py — 활성
00:00 UTC (09:00 KST) — 구독봇 푸시 — subscribe_push.py — 활성
00:00 UTC (09:00 KST) — 멤버 수집 — member_scraper.py — 활성
03:00 UTC (12:00 KST) — 그룹 발굴 — group_finder.py — 활성
06:00 UTC (15:00 KST) — DM 발송 — dm_campaign_runner.py — 주석 처리 (워밍업 완료 전)
12:00 UTC (21:00 KST) — 재발송 — retry_sender.py — 활성

Job 간 threading.Lock으로 직렬화 — 동시 실행 없음.

---

## 8. 환경변수 전체 목록

BOT_TOKEN (필수) — 관리봇 토큰
SUBSCRIBE_BOT_TOKEN (필수) — 구독봇 토큰
API_ID (필수) — Telegram App API ID
API_HASH (필수) — Telegram App API Hash
SESSION_STRING_1~10 (최소 1개 필수) — Pyrogram StringSession (DM 발송용)
SESSION_STRING — _1~_10 없을 때 fallback
SESSION_STRING_TELETHON (필수) — Telethon StringSession (멤버 수집용)
BRIGHTDATA_API_TOKEN (필수) — Bright Data SERP API 토큰 (그룹 발굴용)
DATABASE_URL (필수) — PostgreSQL 연결 URL
ADMIN_ID (필수) — 관리자 Telegram user_id (정수)
CHANNEL_ID — 채널 ID (구독봇용)
AFFILIATE_URL — 어필리에이트 링크
VIP_URL — 인라인 버튼 URL
TRACKING_SERVER_URL — 추적 서버 URL
GEMINI_API_KEY — Gemini 캡션 개인화용
USER_DELAY_MIN/MAX — DM 간격 초 (기본 15~45)
LONG_BREAK_EVERY — N명마다 긴 휴식 (기본 50)
LONG_BREAK_MIN/MAX — 긴 휴식 초 (기본 300~600)
BATCH_SIZE — 1회 발송 건수 (기본 50)
DAILY_LIMIT_PER_ACCOUNT — 계정당 일일 한도 (기본 100)

---

## 9. 현재 상태 (2026-04-16)

- SESSION_STRING_1만 활성 → 추가 세션 확보 필요
- 관리봇 계정 제한 중
- DM 발송 스케줄 비활성화 (워밍업 완료 후 활성화)
- 구독봇 정상 작동

---

## 10. 디버그 엔드포인트

GET /health — 생존 확인
GET /debug/status — DB, campaign_posts, 세션 수, 미발송 타겟 수
GET /debug/session-test — SESSION_STRING Pyrogram 연결 테스트
GET /debug/dm-test?username=xxx — 테스트 DM 발송
GET /debug/dm-test?user_id=123 — user_id로 테스트 DM 발송
GET /debug/routes — 등록된 FastAPI 라우트 목록

세션 문제 의심 시 반드시 /debug/session-test 먼저 호출.

---

## 11. 자주 발생하는 에러 패턴

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

## 12. 절대 규칙

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

## 13. SESSION_STRING 생성

Pyrogram (DM 발송용):
  python scripts/generate_session.py  (로컬 실행, 전화번호 입력 필요)
  출력된 문자열을 Railway 환경변수 SESSION_STRING_1~10에 등록.

Telethon (멤버 수집용):
  python scripts/generate_telethon_session.py  (로컬 실행, 전화번호 입력 필요)
  출력된 문자열을 Railway 환경변수 SESSION_STRING_TELETHON에 등록.

주의: Pyrogram StringSession ≠ Telethon StringSession — 포맷이 다르므로 혼용 불가.

---

## 14. 계정 확보 후 발송 재개 체크리스트

1. generate_session.py → SESSION_STRING_2~ 추가
2. Railway 환경변수 추가 후 재배포
3. /debug/session-test 로 전체 세션 검증
4. warmup.py 3~7일 선행 (그룹 가입, 일반 활동)
5. 타겟 그룹에 각 UserBot 계정 가입 (PeerIdInvalid 예방)
6. scheduler.py 에서 _job_dm_campaign 주석 해제
7. /debug/status 로 전체 상태 확인
8. 구독봇에서 테스트 발송 1명 → 정상 확인 후 전체 발송

---

## 15. 개발 워크플로우 (Dual-Agent Collaboration)

개발 환경: GitHub Codespaces + Claude Code + GitHub Copilot Agent
배포: GitHub push → Railway 자동 배포
코드 수정 승인: Claude Code에서 "Yes, and don't ask again"
테스트 순서: /debug/session-test → /debug/dm-test → 구독봇 1명 테스트 → 전체 발송

### 에이전트 역할 분담

| Agent | 작업 방식 | 권한 수준 | 주요 용도 |
|-------|-----------|-----------|-----------|
| **Claude Code** | main 직접 push | Full (bypassPermissions) | 복잡한 리팩토링, MCP 연동, 멀티파일 변경 |
| **Copilot Agent** | PR 기반 작업 | Full (setup-steps로 환경 구성) | 이슈 기반 수정, 코드 리뷰, 단일 기능 구현 |

### 충돌 방지 프로토콜

1. **공유 규칙 파일:** CLAUDE.md가 단일 소스 오브 트루스(SSOT).
2. **Copilot 전용 설정:** `.github/copilot-instructions.md`가 CLAUDE.md를 미러링.
3. **분기 전략:** Copilot은 항상 PR 경유 → Claude Code 복귀 시 충돌 없음.
4. **Autopus 비활성 시:** `.codex/` 설정은 참조용으로만 유지, 실행 의존성 없음.
5. **동기화 규칙:** CLAUDE.md 변경 시 `copilot-instructions.md`도 반드시 갱신할 것.

---

## 16. 개발 방향 원칙

- 작은 수정으로 문제 해결 시도 금지
- 이미 완성된 오픈소스/최신 툴을 먼저 검토하고 도입
- 전세계 개발자들이 만든 마케팅/자동화 툴 적극 통합
- 자체 코드 수정보다 검증된 라이브러리/툴 교체 우선
- 최신 기술 트렌드 반영이 기본 방향

---

## 17. 개발일지 자동 기록 규칙

### 필수 기록 시점
1. **세션 시작:** 오늘의 목표를 DEVLOG.md 상단에 기록
2. **중요 결정:** 기술 선택, 구조 변경 시 즉시 DEVLOG.md에 기록
3. **세션 종료:** 변경 요약 + 다음 할 일을 DEVLOG.md에 추가
4. **TODO 갱신:** 작업 완료 시 TODO.md 체크(`[x]`), 새 작업 발견 시 추가

### 기록 포맷
```
## YYYY-MM-DD | 제목

### 💡 결정 사항 (왜 이 선택을 했는지)
### 🔧 변경 파일 목록
### 📋 다음 할 일
### ⚠️ 주의사항/이슈 (있을 때만)
```

### 파일 역할
| 파일 | 목적 | 갱신 주기 |
|------|------|-----------|
| `DEVLOG.md` | 개발 일지 (결정 근거 보존) | 매 세션 |
| `TODO.md` | 순차 작업 체크리스트 | 작업 완료/추가 시 |
| `ROADMAP.md` | 장기 로드맵 (Phase별) | Phase 전환 시 |

### 워크플로우
```
TODO.md 확인 → 오늘 할 일 선택 → 작업 수행
→ DEVLOG.md 기록 → TODO.md 체크 ✅ → 커밋
```

<!-- AUTOPUS:BEGIN -->
# Autopus-ADK Harness

> 이 섹션은 Autopus-ADK에 의해 자동 생성됩니다. 수동으로 편집하지 마세요.

- **프로젝트**: my-bot
- **모드**: full
- **플랫폼**: claude-code, codex

## 설치된 구성 요소

- Rules: .claude/rules/autopus/
- Skills: .claude/skills/autopus/
- Commands: .claude/skills/auto/SKILL.md
- Agents: .claude/agents/autopus/

## Language Policy

IMPORTANT: Follow these language settings strictly for all work in this project.

- **Code comments**: Write all code comments, docstrings, and inline documentation in English (en)
- **Commit messages**: Write all git commit messages in English (en)
- **AI responses**: Respond to the user in English (en)

## Core Guidelines

### Subagent Delegation

IMPORTANT: Use subagents for complex tasks that modify 3+ files, span multiple domains, or exceed 200 lines of new code. Define clear scope, provide full context, review output before integrating.

### File Size Limit

IMPORTANT: No source code file may exceed 300 lines. Target under 200 lines. Split by type, concern, or layer when approaching the limit. Excluded: generated files (*_generated.go, *.pb.go), documentation (*.md), and config files (*.yaml, *.json).

### Code Review

During review, verify:
- No file exceeds 300 lines (REQUIRED)
- Complex changes use subagent delegation (SUGGESTED)
- See .claude/rules/autopus/ for detailed guidelines

<!-- AUTOPUS:END -->

**알려진 에러 대응 체계:**
- **AuthKeyUnregistered:** 세션 만료. 로컬 스크립트 재생성 요망.
- **PeerIdInvalid:** 타겟 그룹 미가입 상태. (정상 Skip 처리)
- **FloodWait:** 한도 초과. 쿨다운 설정 및 다음 계정 즉시 전환 (백오프 알고리즘 작동).
