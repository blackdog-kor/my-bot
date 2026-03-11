# System Integration Contract (Bot View)

This file intentionally stays short.

Canonical contract lives at:

- `automation/docs/SYSTEM_INTEGRATION_CONTRACT.md`

## Architecture invariant

- `bot/` is entry-only (Telegram `/start`, deep-link normalization, forwarding)
- `automation/` is the central source of truth and automation backend
- The two systems remain separated and event-based

## Why this file is minimal

Historically, the contract existed in both services and drifted over time.
To reduce duplicate docs and broken assumptions, `automation/docs/SYSTEM_INTEGRATION_CONTRACT.md` is now the single source of truth.
