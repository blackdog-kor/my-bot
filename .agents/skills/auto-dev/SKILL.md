---
name: auto-dev
description: >
  풀 사이클 개발 — plan → go → sync를 순차 실행합니다
---

# auto-dev — Full Development Cycle

## Autopus Branding

When handling this workflow, start the response with the canonical banner from `templates/shared/branding-formats.md.tmpl`:

```text
🐙 Autopus ─────────────────────────
```

End the completed response with `🐙`.


## 설명

풀 사이클 개발 — plan → go → sync를 순차 실행합니다

## Codex Invocation

- `@auto dev ...`
- `$auto-dev ...`
- `$auto dev ...`

## 실행 규칙

- `dev`는 `plan → go → sync`를 순차 실행하는 orchestration wrapper입니다.
- `--team`은 Codex에서 reserved compatibility flag이며 현재는 기본 subagent pipeline을 유지합니다.
- 각 단계가 실패하면 조용히 건너뛰지 말고 실패 지점과 재개 방법을 명시합니다.
