# DEVLOG — 개발 일지

> AI 에이전트가 작업할 때마다 자동으로 기록합니다.
> 대화가 사라져도 이 파일에서 모든 결정과 변경 내용을 확인할 수 있습니다.

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
