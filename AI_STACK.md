# AI_STACK.md — AI 기술 스택 및 토큰 비용 관리

마지막 갱신: 2026-04-19

---

## 현재 AI 스택 상태

| 모델 | 환경변수 | 상태 | 용도 |
|------|----------|------|------|
| GPT-4o | `OPENAI_API_KEY` | ✅ 작동 중 | 코드 리뷰 Hook |
| Gemini | `GEMINI_API_KEY` | ✅ 설정됨 | DM 캡션 개인화 |
| Claude Sonnet 4.6 | `ANTHROPIC_API_KEY` | ⬜ 미설정 | Executor (도입 예정) |
| Claude Opus 4.7 | `ANTHROPIC_API_KEY` (동일) | ⬜ 미설정 | Advisor (도입 예정) |

---

## Claude Advisor Strategy — 토큰 비용 자동 조절

### 왜 필요한가

- Opus 단독 사용 시 비용이 Sonnet 대비 ~15배
- Advisor 패턴: Sonnet이 실행, Opus는 어려운 판단에만 호출
- 실측: SWE-bench에서 Sonnet 단독 대비 성능 +2.7pp, 비용 -11.9%
- 캡션 개인화처럼 반복 호출이 많은 작업에서 비용 차이가 극대화됨

### 구조

```
[요청]
  ↓
Claude Sonnet 4.6 (Executor)  ← 기본 실행, 도구 호출
  ↓ (어려운 판단 발생 시만)
Claude Opus 4.7 (Advisor)     ← 전략 판단만, 도구 호출 없음
  ↓
[결과 반환]
```

### API 호출 예시

```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    tools=[
        {
            "type": "advisor",
            "name": "opus_advisor",
            "model": "claude-opus-4-7",
            "max_uses": 3,          # Opus 최대 호출 횟수 제한
        }
    ],
    messages=[{"role": "user", "content": prompt}],
    betas=["advisor-tool-2026-03-01"],
)
```

### 비용 구조

| 항목 | 요금 적용 |
|------|----------|
| Executor 토큰 | Sonnet 요금 |
| Advisor 호출 토큰 | Opus 요금 |
| Advisor 1회 생성 토큰 | 400~700 tokens |
| `max_uses: 3` 설정 시 최대 추가비용 | ~2100 Opus tokens |

---

## 도입 계획

### Step 1 — 환경 설정

```bash
# requirements.txt에 추가
anthropic>=0.40.0

# Codespace Secrets 등록
ANTHROPIC_API_KEY=sk-ant-...
```

### Step 2 — `app/claude_advisor.py` 생성

역할: 캡션 개인화 및 전략적 판단이 필요한 모든 곳에서 호출하는 공통 모듈

```python
# 기본 구조 (구현 시 확장)
async def generate_caption(template: str, user_context: dict) -> str:
    """Sonnet 실행 + Opus 자문으로 DM 캡션 생성."""
    ...

async def evaluate_strategy(proposal: str) -> str:
    """캠페인 전략을 Advisor 패턴으로 평가."""
    ...
```

### Step 3 — Gemini 캡션 교체

`app/userbot_sender.py`의 Gemini 캡션 호출 → `claude_advisor.generate_caption()`으로 교체

---

## GPT-4o 코드 리뷰 Hook (완료)

| 항목 | 값 |
|------|-----|
| 스크립트 | `scripts/gpt4o_hook.py` |
| 트리거 | Write/Edit PostToolUse (`.py` 파일) |
| 대상 경로 | `app/`, `scripts/` |
| 결과 | LGTM → 통과 / 문제 발견 → Claude에 피드백 |
| 설정 위치 | `.claude/settings.json` PostToolUse |

---

## 모델 선택 기준

| 작업 | 모델 | 이유 |
|------|------|------|
| DM 캡션 생성 (반복) | Sonnet | 비용 효율 |
| A/B 테스트 전략 판단 | Sonnet + Opus Advisor | 품질 + 비용 균형 |
| 코드 리뷰 (Hook) | GPT-4o | 외부 2nd-opinion |
| 캠페인 전략 수립 | strategy_debate.py (GPT-4o) | 독립적 비판 시각 |
