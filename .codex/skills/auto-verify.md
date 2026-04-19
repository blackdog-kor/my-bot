---
name: auto-verify
description: >
  프론트엔드 UX 검증 — Playwright 기반 비주얼 검증을 실행합니다
---

# auto-verify — Frontend UX Verification

## Autopus Branding

When handling this workflow, start the response with the canonical banner from `templates/shared/branding-formats.md.tmpl`:

```text
🐙 Autopus ─────────────────────────
```

End the completed response with `🐙`.


## 설명

프론트엔드 UX 검증 — Playwright 기반 비주얼 검증을 실행합니다

## Codex Invocation

- `@auto verify ...`
- `$auto-verify ...`
- `$auto verify ...`

## 실행 순서

1. 대상 디렉터리와 전달된 플래그를 확인합니다.
2. Bash tool로 `auto verify`를 실행합니다.
3. Playwright 기반 검증 결과와 자동 수정 가능 여부를 함께 보고합니다.
