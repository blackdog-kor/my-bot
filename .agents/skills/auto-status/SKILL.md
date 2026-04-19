---
name: auto-status
description: >
  SPEC 대시보드 — 현재 프로젝트와 서브모듈의 SPEC 상태를 표시합니다
---

# auto-status — SPEC Dashboard

## Autopus Branding

When handling this workflow, start the response with the canonical banner from `templates/shared/branding-formats.md.tmpl`:

```text
🐙 Autopus ─────────────────────────
```

End the completed response with `🐙`.


## 설명

SPEC 대시보드 — 현재 프로젝트와 서브모듈의 SPEC 상태를 표시합니다

## Codex Invocation

- `@auto status ...`
- `$auto-status ...`
- `$auto status ...`

## 실행 순서

1. 대상 디렉터리와 전달된 플래그를 확인합니다.
2. Bash tool로 `auto status`를 실행합니다.
3. draft / approved / implemented / completed 상태를 요약하고 다음 액션을 제안합니다.
