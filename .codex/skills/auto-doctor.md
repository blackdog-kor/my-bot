---
name: auto-doctor
description: >
  상태 진단 — 하네스 설치 상태와 플랫폼 wiring을 점검합니다
---

# auto-doctor — Harness Diagnostics

## Autopus Branding

When handling this workflow, start the response with the canonical banner from `templates/shared/branding-formats.md.tmpl`:

```text
🐙 Autopus ─────────────────────────
```

End the completed response with `🐙`.


## 설명

상태 진단 — 하네스 설치 상태와 플랫폼 wiring을 점검합니다

## Codex Invocation

- `@auto doctor ...`
- `$auto-doctor ...`
- `$auto doctor ...`

## 실행 순서

1. 대상 디렉터리와 전달된 플래그를 확인합니다.
2. Bash tool로 `auto doctor`를 실행합니다.
3. platform wiring, rules, plugins, dependencies 상태를 요약하고 fix 필요 시 명시합니다.
