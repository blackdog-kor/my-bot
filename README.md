# casino-system

Monorepo for Telegram bot, automation backend, AI development pipeline, and growth systems for casino affiliate operations.

## Structure

- `bot/` — Telegram entry bot
- `automation/` — backend automation service
- `.github/workflows/` — shared GitHub Actions

## Principles

- keep bot lightweight
- keep automation heavy logic separated
- prefer minimal safe changes
- preserve deployment stability

## Automation stability

- CI checks are path-scoped so only impacted areas run (`bot/`, `automation/`, or workflow files).
- Each service is tested from its own working directory to keep monorepo paths consistent.
