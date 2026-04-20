# ROADMAP — 자동화 파이프라인 개발 로드맵

마지막 갱신: 2026-04-20

---

## 개발 철학

> 작은 수정보다 검증된 도구 도입 우선.  
> 필수 인프라를 먼저 완비하고, 그 위에 자동화를 쌓는다.

---

## Phase 1 — 개발환경 구축 (현재 단계)

**목표**: Claude Code + AI 기술 스택이 완전히 연동된 개발환경

| 항목 | 상태 | 설명 |
|------|------|------|
| Autopus-ADK 설치 | ✅ 완료 | `.claude/`, `.codex/`, `.agents/` 구성 |
| GPT-4o 코드 리뷰 Hook | ✅ 완료 | Write/Edit PostToolUse 자동 리뷰 |
| Anthropic SDK 설치 | ✅ 완료 | `requirements.txt`에 `anthropic>=0.40.0` |
| ANTHROPIC_API_KEY 설정 | ✅ 완료 | Railway 환경변수 등록 |
| Claude Advisor 구현 | ✅ 완료 | `app/claude_advisor.py` Sonnet+Opus 패턴 |
| OPENAI_API_KEY 검증 | ✅ 완료 | 환경변수 설정됨 |
| `.playwright-mcp/` 정리 | ⬜ 대기 | gitignore 또는 커밋 결정 필요 |

---

## Phase 2 — AI 기술 스택 완비

**목표**: 모든 AI 모델이 역할에 맞게 분리되고, 비용이 자동 조절되는 구조

| 기능 | 도구 | 역할 |
|------|------|------|
| 코드 실행·판단 | Claude Sonnet 4.6 | Executor — 기본 작업 전담 |
| 전략적 판단 | Claude Opus 4.7 | Advisor — 어려운 결정만 호출 |
| 코드 리뷰 | GPT-4o | 2nd-pass 자동 리뷰 (완료) |
| 캡션 개인화 | Gemini → Claude 교체 예정 | DM 메시지 개인화 |
| 그룹 발굴 | Bright Data SERP | 타겟 그룹 스크래핑 |
| 멤버 수집 | Telethon | 그룹 멤버 추출 |
| DM 발송 | Pyrogram | UserBot 직접 발송 |

---

## Phase 3 — 자동화 파이프라인 구축

**목표**: 사람 개입 없이 타겟 발굴 → DM 발송 → 클릭 추적 → 재발송이 완전 자동화

```
[그룹 발굴 03:00 UTC]
    ↓ Bright Data SERP
[멤버 수집 00:00 UTC]
    ↓ Telethon scraper
[캡션 생성]
    ↓ Claude Sonnet (Advisor 패턴으로 비용 조절)
[DM 발송 06:00 UTC]
    ↓ Pyrogram UserBot (SESSION_STRING_1~10)
[클릭 추적]
    ↓ unique_ref + TRACKING_SERVER_URL
[미클릭 재발송 12:00 UTC]
    ↓ retry_sender.py
[구독봇 유입]
    ↓ @blackdog_eve_casino_bot
```

---

## Phase 2.5 — 채널 콘텐츠 자동화 (신규 🔥)

**목표**: 카지노 채널을 인기 콘텐츠로 자동 성장시켜 유입 퍼널의 입구 확대

```
[소스 채널 스크래핑 05:00 UTC]
    ↓ Telethon (읽기 전용)
    ↓ 인기 콘텐츠 필터 (조회수 500+)
[AI 리라이팅]
    ↓ OpenAI GPT-4o-mini / Gemini Flash
    ↓ 저작권 회피 + 채널 톤 통일 + CTA 삽입
[채널 게시 05:00 + 11:00 UTC]
    ↓ Bot API → CHANNEL_ID
    ↓ 인라인 버튼 (어필리에이트 링크)
[성과 추적]
    ↓ 조회수/반응 모니터링 → 콘텐츠 전략 최적화
```

**핵심 콘텐츠 유형:**
- 🎰 빅윈/잭팟 영상 (바이럴 효과 최고)
- 🃏 게임 팁 & 전략 (교육적 가치)
- 🎁 보너스/프로모 소식 (긴급감)
- 📊 카지노 뉴스 (정보성)
- 🏆 유저 승리 인증 (소셜 프루프)

**일일 게시 스케줄 (UTC):**
- 05:00 (KST 14:00) — 오후 활동 시간 1차 게시
- 11:00 (KST 20:00) — 저녁 피크타임 2차 게시
- 최대 6개/일 (스팸 방지)

---

## Phase 4 — 완전 자동화 운영

**목표**: Railway 배포 후 무인 운영

- 다중 세션(SESSION_STRING_2~10) 확보 및 warmup
- Claude Advisor 기반 캡션 A/B 테스트 자동화
- 클릭률 기반 메시지 자동 최적화
- 관리자 DM으로 일일 리포트 자동 발송

---

## Phase 2.7 — TeraBox 콘텐츠 에이전트 (신규 🔥)

**목표**: TeraBox 공유 링크에서 대용량 비디오 콘텐츠를 자동 수집하여 채널 콘텐츠 소스 확장

**왜 TeraBox?**
- 카지노/슬롯 빅윈 영상의 주요 공유 플랫폼 (대용량 무료 호스팅)
- 공식 API 없음 → browser-use AI 에이전트가 유일한 자동화 방법
- 기존 에이전트 인프라(agent_runner, web_agent) 위에 자연스럽게 확장

**아키텍처:**

```
[TeraBox 공유 URL 목록]
    ↓ TERABOX_SHARE_URLS 환경변수
[browser-use AI 에이전트 (Layer 3)]
    ↓ 메타데이터 추출 (파일명, 크기, 썸네일, 다운로드 링크)
    ↓ 실패 시 → nodriver (Layer 2) 폴백
[중복 필터링]
    ↓ channel_content 테이블 중복 체크
[AI 리라이팅]
    ↓ Claude Sonnet → OpenAI → Gemini 3단 폴백
[DB 저장]
    ↓ channel_content 테이블
[채널 게시]
    ↓ Bot API → CHANNEL_ID
    ↓ 인라인 버튼 (어필리에이트 링크)
```

**파일 구조:**

| 파일 | 역할 |
|------|------|
| `app/terabox_agent.py` | 핵심 에이전트 로직 (수집, 파싱, 다운로드) |
| `scripts/terabox_pipeline.py` | 스케줄러용 파이프라인 오케스트레이션 |
| `app/agent_tools.py` | `terabox_agent` 도구 등록 (agent_runner 통합) |
| `app/agent_planner.py` | 플래너에 TeraBox 도구 추가 |

**스케줄:**
- 07:00 UTC (16:00 KST) — TeraBox 콘텐츠 수집 (기본 비활성화, `TERABOX_ENABLED=true` 시 활성화)

**환경변수:**
- `TERABOX_SHARE_URLS` — 쉼표 구분 공유 링크 목록
- `TERABOX_ENABLED` — 파이프라인 활성화 (기본: false)
- `TERABOX_COOKIES` — (선택) 비공개 파일 접근용 쿠키

---

## 다음 즉시 해야 할 작업

1. `ANTHROPIC_API_KEY` → Codespace Secrets 등록
2. `requirements.txt`에 `anthropic` 추가
3. `AI_STACK.md` 기준으로 Claude Advisor 구현 (`app/claude_advisor.py`)
4. Gemini 캡션 → Claude Sonnet + Advisor 패턴으로 교체

참조: [AI_STACK.md](AI_STACK.md)
