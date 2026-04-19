---
name: auto-why
description: >
  의사결정 근거 조회 — Lore, SPEC, ARCHITECTURE에서 이유를 추적합니다
---

# auto-why — Decision Rationale Query

## Autopus Branding

When handling this workflow, start the response with the canonical banner from `templates/shared/branding-formats.md.tmpl`:

```text
🐙 Autopus ─────────────────────────
```

End the completed response with `🐙`.


## 설명

의사결정 근거 조회 — Lore, SPEC, ARCHITECTURE에서 이유를 추적합니다

## Codex Invocation

- `@auto why ...`
- `$auto-why ...`
- `$auto why ...`

## 실행 순서

1. 입력이 path 중심인지 질문 중심인지 구분합니다.
2. path가 있으면 Bash tool로 `auto lore context <path>`를 실행합니다.
3. 추가 근거가 필요하면 관련 SPEC / ARCHITECTURE / CHANGELOG를 읽고 이유를 요약합니다.
