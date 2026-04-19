# Worktree Isolation Skill

Codex parallel work should be isolated by ownership first, and by workspace strategy second.

## Overview

The default isolation model in Codex is the worker's forked workspace created by `spawn_agent(...)`. Do not assume an implicit worktree flag or automatic git worktree creation.

This skill defines when parallel work is safe and how the main session should integrate results.

## Default Isolation Model

- Each parallel worker gets a disjoint file ownership slice
- Each worker edits only its assigned slice in its own forked workspace
- The main session reviews and integrates returned changes

If ownership cannot be separated cleanly, do not parallelize.

## Activation Conditions

Use this guidance when:

- `@auto go` is running in default pipeline or Codex `--team` mode
- planner marks tasks as parallel
- ownership rules are explicit and non-overlapping

Do not use parallel isolation when:

- tasks touch the same file
- migrations or generated outputs must be serialized
- a task depends on a previous task's concrete output

## Ownership Validation

Before spawning parallel workers, compare ownership patterns:

1. Same literal file: conflict
2. Same directory with overlapping globs: conflict
3. Parent/child directory ownership: conflict
4. Different directories with no shared generated output: safe

On conflict, downgrade to sequential execution and log the reason.

## Parallel Worker Contract

Every parallel worker prompt should include:

- exact owned paths
- forbidden paths
- expected tests or checks
- required return format

Example:

```python
spawn_agent(
    agent_type="executor",
    fork_context=True,
    message="""
    Own only: pkg/auth/*, internal/auth/*
    Do not edit: pkg/api/*, migrations/*
    Return changed files and tests run.
    """,
)
```

## Integration Flow

After workers complete:

1. Review returned file lists and assumptions
2. Integrate changes in the main session
3. Run validation after integration, not before
4. If overlap or regressions appear, continue sequentially

## Optional Manual Git Worktree Path

For advanced multi-session workflows, the main session may still create explicit git worktrees with standard git commands. That is an operator choice, not an implicit Codex agent feature.

When using manual git worktrees:

- create them in the main session
- assign one worktree per ownership slice
- merge in a deterministic order
- remove worktrees after successful integration

## Safety Rules

- Prefer ownership separation over git complexity
- Keep validation workers read-only
- Stop parallel execution on merge conflicts or ownership ambiguity
- Never auto-resolve overlapping edits without review

## Multi-Session Guidance

When using multiple terminals or tmux panes:

- one session owns one concern slice
- keep branch names explicit
- merge in a known order after all sessions complete

If these constraints feel heavy for the task, use the default sequential pipeline instead.
