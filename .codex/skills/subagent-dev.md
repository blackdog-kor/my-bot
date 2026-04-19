# Subagent Development Skill

Guide for designing Codex worker roles and orchestrating them safely.

## Codex Primitives

Codex orchestration uses these primitives:

- `spawn_agent(...)` for new workers
- `send_input(...)` for follow-up instructions
- `wait_agent(...)` for synchronization
- `close_agent(...)` when a worker is no longer needed

Do not design around Claude-only team primitives or assumptions about direct worker-to-worker messaging.

## Agent Definitions

Harness reference agent definitions live under .codex/agents/. They document role scope, review posture, and expected outputs for roles such as `planner`, `executor`, `tester`, and `validator`.

Use those definitions as role contracts. The main session is still responsible for choosing the correct `agent_type` and passing explicit ownership.

## Design Principles

### Single Responsibility

Each worker should own one clear concern:

- implementation
- testing
- validation
- review

Avoid prompts that ask one worker to plan, implement, review, and secure the same slice.

### Ownership First

Every coding worker prompt should state:

- files or modules it owns
- files it must not edit
- completion criteria
- expected return format

### Context Completeness

Workers do not share mutable session state automatically. Include the SPEC id, acceptance criteria, and any relevant constraints in the prompt or via `fork_context`.

## Orchestration Patterns

### Fan-Out / Fan-In

Use for independent slices:

```text
main session -> worker A
             -> worker B
             -> worker C
             -> integrate results
```

### Pipeline

Use when each step depends on the previous result:

```text
planner -> executor -> validator -> reviewer
```

### Supervisor

Use the main session as supervisor:

- detect blockers
- respawn narrower workers
- decide when to fall back to sequential execution

## Practical Prompt Pattern

```python
spawn_agent(
    agent_type="executor",
    fork_context=True,
    message="""
    Own only: pkg/auth/*
    Goal: implement token refresh flow
    Tests: update auth service tests only
    Return: changed files, tests run, unresolved blockers
    """,
)
```

## Completion Checklist

- Role is narrow and concrete
- Ownership is explicit
- Validation path is assigned
- Retry/fallback behavior is defined
- Parallel workers have disjoint write scopes
