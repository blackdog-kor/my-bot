---
name: advisor-strategy
description: Anthropic Advisor Strategy — Opus advises, Sonnet/Haiku executes. Apply when using Claude API or designing agent tasks.
category: methodology
platform: claude-code
---

# Advisor Strategy

IMPORTANT: When building AI agent features or routing tasks between models, apply the Advisor Strategy pattern.

## Core Pattern

- **Executor**: Sonnet or Haiku leads task execution — calls tools, iterates toward solution
- **Advisor**: Opus provides strategic guidance only when executor encounters hard decisions — does NOT call tools
- **Escalation trigger**: Executor decides when to consult Opus, not a fixed schedule

## When to Apply

- Building any feature that calls the Claude Messages API
- Designing multi-step agent workflows in this project
- Choosing model tiers for autopus quality presets
- Replacing Gemini caption personalization with Claude API

## Claude Messages API Usage

```python
# Beta header required
headers = {"anthropic-beta": "advisor-tool-2026-03-01"}

# Declare advisor as a server-side tool in the request
tools = [{"type": "advisor", "name": "opus_advisor", "model": "claude-opus-4-7", "max_uses": 3}]
```

Billing: advisor tokens at Opus rate, executor tokens at Sonnet/Haiku rate.
Advisor generates only 400–700 planning tokens per invocation.

## Autopus Router Mapping

| Autopus tier | Model | Role |
|---|---|---|
| economy | claude-sonnet-4-6 | executor (default) |
| premium | claude-opus-4-6 | advisor (escalation) |
| standard | claude-sonnet-4-6 | executor (standard tasks) |

## Benchmarks (Anthropic, 2026)

- SWE-bench Multilingual: Sonnet + Opus advisor → +2.7pp, -11.9% cost vs Sonnet alone
- BrowseComp: Haiku + Opus advisor → 41.2% vs 19.7% Haiku alone, 85% lower cost than Sonnet configs

## Anti-Patterns

- Do NOT use Opus for all tasks — it eliminates the cost benefit
- Do NOT have the advisor call tools directly
- Do NOT fix the escalation schedule — let the executor decide dynamically
