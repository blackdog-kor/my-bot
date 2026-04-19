# TODO — 순차 작업 목록

> 위에서 아래로 순서대로 진행합니다.
> 완료된 항목은 `[x]`로 체크합니다.
> GitHub에서 이 파일을 보면 체크박스가 시각적으로 렌더링됩니다.

---

## ✅ 완료

- [x] Autopus-ADK 설치 (`.claude/`, `.codex/`, `.agents/`)
- [x] GPT-4o 코드 리뷰 Hook 설정
- [x] OPENAI_API_KEY 환경변수 설정
- [x] ROADMAP.md 작성
- [x] AI_STACK.md 작성
- [x] DEVLOG.md + TODO.md 자동 기록 시스템 도입
- [x] `structlog` 실적용 — main, userbot_sender, scheduler, pg_broadcast, retry_utils 전환
- [x] `pydantic-settings` 실적용 — userbot_sender, main에서 os.getenv → settings 교체
- [x] `tenacity` 실적용 — `_download_via_bot_api`에 재시도 데코레이터 적용
- [x] PostgreSQL MCP 추가 (`.mcp.json`에 `@anthropic/mcp-server-postgres`)

---

## 🔴 즉시 (이번 주)

- [ ] `ANTHROPIC_API_KEY` → Codespace Secrets 등록
- [ ] `requirements.txt`에 `anthropic>=0.40.0` 추가
- [ ] `app/claude_advisor.py` 기본 구현 (Sonnet + Opus Advisor 패턴)
- [ ] Gemini 캡션 → Claude Sonnet 교체 (`app/userbot_sender.py`)
- [ ] `.playwright-mcp/` 정리 (gitignore 또는 커밋 결정)
- [ ] 콘텐츠 소스 채널 목록 확정 (`CONTENT_SCRAPE_SOURCES` 환경변수)
- [ ] 콘텐츠 자동화 파이프라인 테스트 (`/debug/content-test` 추가)
- [ ] `CHANNEL_ID` 환경변수 설정 (게시 대상 채널)

---

## 🟡 곧 (다음 주)

- [ ] `SESSION_STRING_2~3` 추가 확보 (`scripts/generate_session.py`)
- [ ] `warmup.py` 7일 실행 (Ban 방지용 계정 예열)
- [ ] 타겟 그룹에 UserBot 계정 가입 (PeerIdInvalid 예방)
- [ ] DM 발송 스케줄 활성화 (`scheduler.py` 주석 해제)
- [ ] GitHub Projects Kanban 보드 설정
- [ ] 콘텐츠 자동화 A/B 테스트 (리라이팅 변형별 조회수 비교)
- [ ] VIP 세분화 — `broadcast_targets`에 tier 컬럼 추가
- [ ] 리텐션 자동 푸시 시퀀스 (가입 후 3일/7일/14일)

---

## 🟢 나중에 (Phase 3~4)

- [ ] A/B 테스트 자동화 (캡션 변형별 클릭률 비교)
- [ ] 클릭률 기반 메시지 자동 최적화
- [ ] 관리자 일일 리포트 자동 DM 발송
- [ ] 다중 세션 (SESSION_STRING_4~10) 확보
- [ ] 완전 무인 운영 모드 구축
- [ ] Sentry/Logfire 도입 (에러 추적 + 성능 모니터링)
- [ ] LangGraph 에이전트 오케스트레이션 (agent_runner.py 연계)
- [ ] Temporal.io/Prefect 분산 워크플로우 검토 (APScheduler 대체)
- [ ] 링크 클로킹 서버 구축 (어필리에이트 링크 보호)
- [ ] WhatsApp Business API 채널 추가 (다채널 확장)
- [ ] 프록시 로테이션 통합 (계정 안전성 강화)
- [ ] Gemini AI 메시지 스피닝 고도화 (DM 전환율 극대화)

---

## 📝 메모

- 작업 완료 시 이 파일의 체크박스를 `[x]`로 변경
- 새로운 작업 발견 시 적절한 우선순위 섹션에 추가
- 상세 내용은 `DEVLOG.md`에 기록
- 전체 로드맵은 `ROADMAP.md` 참조
