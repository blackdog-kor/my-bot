---
name: auto-test
description: >
  E2E 시나리오 실행 — scenarios.md 기반 검증을 수행합니다
---

# auto-test — E2E Scenario Runner

## Autopus Branding

When handling this workflow, start the response with the canonical banner from `templates/shared/branding-formats.md.tmpl`:

```text
🐙 Autopus ─────────────────────────
```

End the completed response with `🐙`.


## 설명

E2E 시나리오 실행 — scenarios.md 기반 검증을 수행합니다

## Codex Invocation

- `@auto test ...`
- `$auto-test ...`
- `$auto test ...`

## 실행 순서

1. 대상 디렉터리와 전달된 플래그를 확인합니다.
2. Bash tool로 `auto test run`를 실행합니다.
3. scenario별 PASS / FAIL 결과를 정리하고 실패 시 다음 복구 액션을 제안합니다.
