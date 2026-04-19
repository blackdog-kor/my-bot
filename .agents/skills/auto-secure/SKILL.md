---
name: auto-secure
description: >
  보안 감사 — OWASP Top 10 관점에서 변경 범위를 점검합니다
---

# auto-secure — Security Audit

## Autopus Branding

When handling this workflow, start the response with the canonical banner from `templates/shared/branding-formats.md.tmpl`:

```text
🐙 Autopus ─────────────────────────
```

End the completed response with `🐙`.


## 설명

보안 감사 — OWASP Top 10 관점에서 변경 범위를 점검합니다

## Codex Invocation

- `@auto secure ...`
- `$auto-secure ...`
- `$auto secure ...`

## 실행 순서

1. 분석 범위를 결정합니다.
2. `spawn_agent(...)`로 `security-auditor`를 호출해 결과를 수집합니다.
3. 주요 findings와 다음 액션을 3개 이내로 정리합니다.
