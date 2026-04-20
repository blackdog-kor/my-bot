# DEVLOG — 개발 일지

> AI 에이전트가 작업할 때마다 자동으로 기록합니다.
> 대화가 사라져도 이 파일에서 모든 결정과 변경 내용을 확인할 수 있습니다.

---

## 2026-04-20 | TeraBox 디버그 엔드포인트 + channel_content 테이블 초기화

### 💡 결정 사항
- `/debug/terabox-test` 엔드포인트 추가 — 단일 URL 및 전체 수집 두 가지 모드 지원
- `channel_content` 테이블 초기화를 FastAPI lifespan에 추가 (TeraBox 파이프라인 선행 조건)
- 디버그 인증 (`X-Debug-Secret`) 일관 적용

### 🔧 변경 파일 목록
- `app/main.py` — `/debug/terabox-test` 엔드포인트 추가, lifespan에 channel_content 테이블 초기화
- `DEVLOG.md` — 세션 기록
- `TODO.md` — `/debug/terabox-test` 완료 체크

### 📋 다음 할 일
- Railway에 `TERABOX_SHARE_URLS` 환경변수 설정
- Railway 배포 후 `/debug/terabox-test` 엔드포인트 호출하여 browser-use headless 작동 확인
- 정상 작동 확인 후 `scheduler.py`에서 `terabox_pipeline` Job 주석 해제
- TeraBox 다운로드 → BytesIO → 채널 직접 비디오 업로드 연동 (file_id 캐싱)

---

## 2026-04-20 | TeraBox 콘텐츠 에이전트 모듈 구축

### 💡 결정 사항
- TeraBox는 공식 API 없음 → browser-use AI 에이전트가 유일한 자동화 방법
- 기존 에이전트 인프라(agent_runner, web_agent, agent_planner, agent_tools) 위에 확장
- 3-Layer 폴백 구조: browser-use (Layer 3) → nodriver (Layer 2) → curl_cffi (Layer 1, 다운로드)
- 기본 비활성화 상태로 배포 (`TERABOX_ENABLED=false`) — URL 설정 후 활성화
- 스케줄: 07:00 UTC (16:00 KST) — 오후 시간대 수집

### 🔧 변경 파일 목록
- `app/terabox_agent.py` (신규) — TeraBox browser-use 에이전트 핵심 모듈
  - `extract_terabox_info()` — AI 에이전트로 메타데이터 추출
  - `extract_terabox_info_nodriver()` — nodriver 폴백
  - `collect_terabox_content()` — 전체 URL 순회 수집
  - `download_terabox_file()` — BytesIO 다운로드
- `scripts/terabox_pipeline.py` (신규) — 스케줄러용 파이프라인 스크립트
- `app/config.py` — `terabox_share_urls`, `terabox_enabled`, `terabox_cookies` 필드 추가
- `app/agent_tools.py` — `run_terabox_agent()` 도구 실행기 + TOOL_DISPATCH 등록
- `app/agent_planner.py` — 플래너 시스템 프롬프트에 `terabox_agent` 도구 추가
- `app/scheduler.py` — `_job_terabox_pipeline()` Job + 07:00 UTC 스케줄 (비활성화 상태)
- `TODO.md` — TeraBox 관련 작업 추가 및 완료 체크
- `ROADMAP.md` — Phase 2.7 (TeraBox 콘텐츠 에이전트) 추가
- `DEVLOG.md` — 세션 기록

### 📋 다음 할 일
- `TERABOX_SHARE_URLS` 환경변수에 실제 공유 링크 설정
- `/debug/terabox-test` 엔드포인트 추가 (수동 테스트)
- Railway 배포 후 browser-use 에이전트 실행 테스트
- `TERABOX_ENABLED=true` 설정으로 스케줄 활성화
- TeraBox 다운로드 → BytesIO → 채널 직접 업로드 연동 (video file_id 캐싱)

### ⚠️ 주의사항
- browser-use는 OPENAI_API_KEY 필수 (GPT-4o가 에이전트 브레인)
- TeraBox UI가 자주 변경될 수 있음 → 에이전트 프롬프트 유지보수 필요
- 비공개 파일은 TERABOX_COOKIES 설정 필요
- Railway headless 환경에서 browser-use 작동 여부 사전 검증 필요

---

## 2026-04-20 | Claude Advisor 패턴 구현 완료

### 💡 결정 사항
- ANTHROPIC_API_KEY Railway 등록 완료 → Claude Advisor 패턴 본격 구현
- Sonnet (Executor) + Opus (Advisor) 2단 구조 확정
- 캡션 개인화: Claude Sonnet 우선 → Gemini Flash 폴백 (기존 Gemini 전용에서 전환)
- 콘텐츠 리라이팅: Claude → OpenAI → Gemini 3단 폴백 체인 구축
- 전략 평가: Opus 우선 → Sonnet 폴백 (고급 분석에만 Opus 사용)
- 모델명: claude-sonnet-4-5-20250514 (Executor), claude-opus-4-0-20250514 (Advisor)

### 🔧 변경 파일 목록
- `app/config.py` — `anthropic_api_key` 필드 추가
- `app/claude_advisor.py` (신규) — 핵심 Claude Advisor 모듈
  - `generate_caption()` — DM 캡션 개인화 (Sonnet + Gemini 폴백)
  - `rewrite_content()` — 채널 콘텐츠 리라이팅
  - `evaluate_strategy()` — 캠페인 전략 평가 (Opus + Sonnet 폴백)
- `app/userbot_sender.py` — Gemini 직접 호출 → `claude_advisor.generate_caption()` 위임
- `app/content_rewriter.py` — Claude를 최우선 AI로 추가 (3단 폴백 체인)
- `AI_STACK.md` — Claude 상태 ✅ 활성으로 갱신
- `TODO.md` — 완료 항목 체크
- `DEVLOG.md` — 세션 기록

### 📋 다음 할 일
- `/debug/session-test` → `/debug/dm-test` 로 실 발송 테스트
- Claude API 비용 모니터링 대시보드 확인
- 콘텐츠 파이프라인 Claude 리라이팅 실전 테스트
- DM 발송 스케줄 활성화 준비 (warmup 완료 후)

### ⚠️ 주의사항
- Claude API 키 미설정 시 자동으로 Gemini 폴백 — 서비스 중단 없음
- Opus는 전략 평가(`evaluate_strategy`)에서만 사용 — 비용 절감
- content_rewriter.py의 `_generate_with_claude`는 `_call_sonnet`을 직접 import — 순환참조 주의

---

## 2026-04-19 | 채널 콘텐츠 자동화 시스템 구축

### 💡 결정 사항
- 채널 성장이 DM 파이프라인보다 선행되어야 함 (유입 퍼널 입구 확대)
- 콘텐츠 자동화 = 스크래핑 → AI 리라이팅 → 자동 게시 3단계 파이프라인
- AI: OpenAI GPT-4o-mini 우선 (비용 효율), Gemini Flash 폴백
- 하루 최대 6개 게시, 피크타임 2회 실행 (14:00 KST, 20:00 KST)
- 콘텐츠 유형: 빅윈 영상, 게임 팁, 보너스 소식, 카지노 뉴스, 유저 인증

### 🔧 변경 파일 목록
- `app/content_scraper.py` (신규) — Telethon 기반 소스 채널 콘텐츠 스크래핑
- `app/content_rewriter.py` (신규) — AI 리라이팅 (OpenAI/Gemini dual)
- `app/channel_poster.py` (신규) — 채널 자동 게시 + 인라인 버튼
- `scripts/content_pipeline.py` (신규) — 전체 파이프라인 스크립트
- `app/pg_broadcast.py` — channel_content 테이블 CRUD 추가
- `app/scheduler.py` — 콘텐츠 자동화 Job 등록 (05:00, 11:00 UTC)
- `app/config.py` — 콘텐츠 자동화 설정 추가
- `TODO.md` — 콘텐츠 자동화 작업 추가
- `ROADMAP.md` — Phase 2.5 (채널 콘텐츠 자동화) 추가

### 📋 다음 할 일
- CONTENT_SCRAPE_SOURCES 환경변수에 실제 소스 채널 설정
- CHANNEL_ID 환경변수 설정
- /debug/content-test 엔드포인트 추가
- 콘텐츠 파이프라인 수동 테스트 실행
- 게시 성과 추적 (조회수 모니터링) 기능 추가

### ⚠️ 주의사항
- Telethon 세션(SESSION_STRING_TELETHON)이 소스 채널에 접근 가능해야 함
- 소스 채널이 비공개면 해당 계정으로 먼저 가입 필요
- 일일 게시 한도(6개) 초과 방지 로직 내장됨
- AI API 키 없으면 기본 포맷팅만 적용 (graceful degradation)

---

## 2026-04-19 | 시니어 기술 스택 실제 적용 (structlog + pydantic-settings + tenacity + PostgreSQL MCP)

### 💡 결정 사항
- 제미나이 추천 5개 중 Context7만 유효, 나머지 4개(v0, Bolt.new, Cline, Smithery)는 프론트엔드용으로 부적합 판정
- 이미 설치만 되어 있던 `structlog`, `pydantic-settings`, `tenacity`를 실제 코드에 적용하기로 결정
- PostgreSQL MCP 서버 추가로 Claude Code의 DB 직접 쿼리 기능 활성화

### 🔧 변경 내용
- `.mcp.json` — `@anthropic/mcp-server-postgres` 추가 (Railway PostgreSQL 직접 조회)
- `app/main.py` — `logging.basicConfig()` → `structlog` 전환 + `os.getenv` → `settings` 전환
- `app/userbot_sender.py` — `os.getenv` 17개 → `settings` 전환, `logging` → `structlog`, `_download_via_bot_api`에 tenacity 재시도 적용
- `app/scheduler.py` — `logging` → `structlog` 전환
- `app/pg_broadcast.py` — `logging` → `structlog` 전환
- `app/retry_utils.py` — `logging` → `structlog` 전환

### 📋 다음 할 일
- ANTHROPIC_API_KEY 설정 후 Claude Advisor 패턴 구현
- Sentry/Logfire 도입 검토 (Railway 로그 한계 극복)
- LangGraph 점진적 도입 검토 (agent_runner.py 연계)

### ⚠️ 주의사항
- PostgreSQL MCP는 DATABASE_URL 환경변수 필요 — Railway에서 자동 설정됨
- structlog JSON 출력으로 Railway 로그 필터링 용이해짐

---

## 2026-04-19 | 개발일지 자동화 시스템 도입

### 💡 결정 사항
- Notion 대신 GitHub 네이티브 3단 시스템 채택 (DEVLOG.md + TODO.md + GitHub Projects)
- 이유: AI 에이전트 직접 편집 가능, 버전 관리 자동, 외부 의존성 없음
- CLAUDE.md에 자동 기록 규칙 추가로 재발방지

### 🔧 변경 내용
- `DEVLOG.md` 생성 (본 파일)
- `TODO.md` 생성 (순차 작업 체크리스트)
- `CLAUDE.md` 섹션 17 추가 (개발일지 자동 기록 규칙)

### 📋 다음 할 일
- GitHub Projects 보드 설정 (수동, 브라우저에서)
- ANTHROPIC_API_KEY 설정
- claude_advisor.py 구현

---

## 2026-04-19 | 시스템 검토 및 AI 기술 스택 설계

### 💡 결정 사항
- Claude Advisor 패턴 도입 결정 (Sonnet 실행 + Opus 자문)
- Gemini 캡션 → Claude Sonnet 교체 방향 확정
- GPT-4o 코드 리뷰 Hook 설치 완료
- Autopus-ADK 설치로 개발 자동화 프레임워크 구축

### 🔧 변경 내용
- `ROADMAP.md` 작성 — 4단계 개발 로드맵
- `AI_STACK.md` 작성 — AI 모델별 역할 정의 + 비용 관리 전략
- `.claude/`, `.codex/`, `.agents/` 디렉토리 구성 (Autopus-ADK)
- `scripts/gpt4o_hook.py` — GPT-4o 코드 리뷰 자동화
- `.claude/settings.json` PostToolUse Hook 설정

### 📋 다음 할 일
- ANTHROPIC_API_KEY → Codespace Secrets 등록
- requirements.txt에 anthropic 추가
- app/claude_advisor.py 기본 구현

### ⚠️ 주의사항
- SESSION_STRING_1만 활성 → 추가 세션 확보 필요
- DM 발송 스케줄 비활성화 중 (워밍업 완료 후 활성화)

---

## 2026-04-18 | 프로젝트 초기 구축

### 💡 결정 사항
- Railway 단일 서비스 배포 구조 확정
- Pyrogram + Telethon + python-telegram-bot 3중 프레임워크 채택
- BytesIO + file_id 캐싱 방식 확정 (Saved Messages 방식 폐기)

### 🔧 변경 내용
- `app/main.py` — FastAPI 진입점
- `app/userbot_sender.py` — Pyrogram DM 발송 핵심 로직
- `app/pg_broadcast.py` — PostgreSQL CRUD
- `bot/subscribe_bot.py` — 구독봇 로직
- `CLAUDE.md` — 프로젝트 규칙 문서 초판

### 📋 다음 할 일
- 스케줄러 구현 (APScheduler)
- 멤버 스크래핑 자동화
- DM 발송 Jitter 패턴 적용

---
