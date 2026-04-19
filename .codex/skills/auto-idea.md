# auto-idea — 아이디어 브레인스토밍 스킬

**프로젝트**: my-bot | **모드**: full

## 설명

멀티 프로바이더 오케스트라를 활용해 아이디어를 구조화하고 발산 후 BS 파일로 저장합니다.
ICE 스코어링으로 아이디어를 평가하고 상위 N개를 선별합니다.
Opportunity-Solution Tree, 다관점 브레인스토밍, 가정 식별을 포함합니다.

## 사용법

```
@auto-idea "아이디어 설명"
@auto-idea "아이디어 설명" --strategy consensus
@auto-idea "아이디어 설명" --auto
```

## 플래그

| Flag | Description |
|------|-------------|
| `--strategy` | 오케스트레이션 전략: debate (기본), consensus, pipeline, fastest |
| `--providers` | 사용할 프로바이더 목록 (기본: 전체) |
| `--auto` | 완료 후 `@auto plan --from-idea BS-{ID}` 자동 체이닝 |

### 공통 플래그

- `--multi`: `idea`에서는 기본적으로 orchestra가 기본 엔진이므로 사실상 항상 활성 상태로 취급합니다.
- `--auto`: 완료 후 plan 체이닝까지 자동 진행합니다.

## Codex 기본 실행 모델

- Codex에서는 `spawn_agent(...)` 기반 subagent-first를 기본 원칙으로 사용합니다.
- `idea`에서는 메인 세션이 오케스트라 실행과 최종 합성을 담당합니다.
- 관련 코드 탐색, 기존 패턴 조사, 리스크 정리처럼 병렬화 가능한 보조 작업은 서브에이전트로 위임합니다.
- 현재 Codex 런타임 정책이 암묵적 `spawn_agent(...)` 호출을 제한하면, 하네스 기본값과 제약을 명시적으로 알린 뒤 사용자에게 서브에이전트 진행 여부 또는 단일 세션 진행을 확인받습니다.
- 아이디어 발산 자체를 불필요하게 잘게 쪼개지는 않습니다.

## 5단계 파이프라인

### Step 1: 입력 파싱

입력에서 아이디어 설명과 플래그를 추출합니다.

### Step 2: What/Why/Who/When 구조화

- **What**: 무엇을 만드는가?
- **Why**: 왜 필요한가? (문제/기회)
- **Who**: 누구를 위한 것인가?
- **When**: 언제 필요한가? (타임라인/맥락)

**Opportunity-Solution Tree** (기존 제품 개선 시):
- Outcome → Opportunity → Solution → Experiment 구조로 정리

**Assumption Identification** (4축):
- Value (사용자가 원하는가?) / Usability (쓸 수 있는가?) / Feasibility (구현 가능한가?) / Viability (지속 가능한가?)

### Step 3: Orchestra 브레인스토밍 (다관점)

PM/Designer/Engineer 3가지 관점에서 다각적 발산을 유도합니다.

IMPORTANT: 이 단계는 반드시 orchestra CLI 호출을 먼저 시도해야 합니다. Step 4로 건너뛰거나, 먼저 자체 생성 아이디어로 대체하면 안 됩니다.

**기본 호출 (권장)**:
```bash
auto orchestra brainstorm "{structured idea}" --strategy {strategy}
```

**서브프로세스 모드 (대체 경로)**:
```bash
auto orchestra run "{structured idea}" --strategy {strategy} --rounds standard
```

`--ultrathink`가 함께 있으면 orchestra 결과를 먼저 수집한 뒤 추가 심화 분석에 사용합니다.

**Fallback rule**: orchestra 호출이 실제 에러로 실패한 경우에만 fallback을 허용합니다.
1. 정확한 에러 메시지를 사용자에게 보여줍니다.
2. 사용자에게 "Orchestra 실행 실패. Sequential Thinking으로 fallback할까요?"를 plain-text로 확인합니다.
3. 사용자가 승인했거나 `--auto` 모드면 Sequential Thinking fallback으로 진행합니다.
4. BS 파일에 `**Providers**: fallback (orchestra unavailable)`를 기록합니다.

### Step 4: ICE 스코어링 + Assumption Risk Overlay

| 항목 | 설명 | 범위 |
|------|------|------|
| Impact | 영향력 | 1-10 |
| Confidence | 확신도 | 1-10 |
| Ease | 실행 용이성 | 1-10 |

`Score = (Impact × Confidence × Ease) / 100`

ICE Top N 아이디어에 핵심 가정의 위험도를 오버레이합니다.
HIGH 위험 가정이 있으면 검증 실험을 권장합니다.

IMPORTANT: ICE 스코어링은 반드시 orchestra 출력 결과를 기반으로 수행합니다. orchestra 출력 없이 자체 생성한 아이디어 목록으로 대체하면 안 됩니다.

### Pre-Completion Verification

BS 파일 저장 전에 아래 항목을 모두 확인합니다.

- [ ] Step 1: 입력 파싱 완료
- [ ] Step 2: What/Why/Who/When 구조화 완료
- [ ] Step 3: orchestra 호출 완료 또는 승인된 fallback 완료
- [ ] Step 4: orchestra 출력 기반 ICE 스코어링 완료

하나라도 비어 있으면 Step 5로 진행하지 않습니다.

### Step 5: BS 파일 저장

`.autopus/brainstorms/BS-{ID}.md`에 결과를 저장합니다.

## 출력

```
🐙 Workflow: BS-{ID}
  ● idea  →  ○ plan  →  ○ go  →  ○ sync
```

`--auto` 설정 시 자동으로 `@auto plan --from-idea BS-{ID}`로 체이닝합니다.
그렇지 않으면 다음 단계로 `@auto plan --from-idea BS-{ID} "feature description"` 를 안내합니다.
