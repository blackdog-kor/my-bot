---
name: auto-map
description: >
  코드베이스 분석 — 구조, 엔트리포인트, 의존성을 빠르게 요약합니다
---

# auto-map — Codebase Structure Analysis

## Autopus Branding

When handling this workflow, start the response with the canonical banner from `templates/shared/branding-formats.md.tmpl`:

```text
🐙 Autopus ─────────────────────────
```

End the completed response with `🐙`.


## 설명

코드베이스 분석 — 구조, 엔트리포인트, 의존성을 빠르게 요약합니다

## Codex Invocation

- `@auto map ...`
- `$auto-map ...`
- `$auto map ...`

## 실행 순서

1. 분석 범위를 결정합니다.
2. `spawn_agent(...)`로 `explorer`를 호출해 결과를 수집합니다.
3. 주요 findings와 다음 액션을 3개 이내로 정리합니다.
