# AGENTS.md — Rules for Coding Agents Working on This Repository

This file is read by coding agents (Claude Code, pi, OpenClaw, Cursor, etc.) when
they run from the repo root. If you are a human contributor, you can skip this —
read `CONTRIBUTING.md` instead.

If you are an agent, read this whole file before making any edit.

## Hard Rules

1. **Do not edit `CHANGELOG.md`.** Changelog entries are added by maintainers at
   release time.
2. **Do not invent new top-level packages** (no new directory at the repo root).
   New code goes inside `beekeeper/`, `beekeeper_api/`, `queen_api/`, or
   `tests/` as appropriate.
3. **Do not edit `LICENSE`, `CODE_OF_CONDUCT.md`, or `SECURITY.md`** unless the
   user is explicitly making a governance change.
4. **Do not add new dependencies** without showing the user the dependency,
   what it's for, and what alternative you considered. Beekeeper's deps are
   curated.
5. **Do not edit files inside `beekeeper/souls/`** unless the user specifically
   asks. Soul files are persona/contract data; editing them silently changes
   runtime behavior.

## Verification Gates

Before declaring a task done:

```bash
ruff check .
pytest tests/
```

Both must pass. If your change touches the policy/guardrails code paths
(`beekeeper/guardrails.py`, `beekeeper/policy_service.py`, `beekeeper/user_policy.py`),
also run the policy test files explicitly:

```bash
pytest tests/test_user_policy.py tests/test_queen_autonomy.py -v
```

## Surgical Change Discipline

- Touch only what the task requires. Do not "improve" adjacent code, comments,
  or formatting.
- Match existing module style. If a file uses `from __future__ import annotations`,
  keep it. If a module uses Pydantic v2 models, do not introduce v1 patterns.
- Do not refactor unless the user asked for a refactor.
- Do not add backward-compatibility shims for unreleased code.
- Do not add error handling, fallbacks, or validation for scenarios that cannot
  happen. Trust internal code.

## Adding a New LLM Provider

If you are adding a provider in `beekeeper/llm_provider.py`:

1. Add the provider class implementing the existing interface.
2. Add a fallback entry in the `BEEKEEPER_LLM_PROVIDERS` parsing.
3. Add at least one unit test in `tests/` — use the existing provider test
   pattern for shape.
4. Document the env vars in `README.md` only if user-visible.

## Adding a New Worker Kind

If you are adding a worker in `beekeeper/`:

1. Implement the worker class extending the existing base.
2. Register it in `beekeeper/worker_registry.py`'s `_workers` map.
3. Map its `WorkerKind` enum value.
4. Add a content-routing test in `tests/`.
5. Do not change the auto-spawn / forge path unless that is the explicit task.

## Internal Routing Reference

The internal routing rules for Queen / Workers / Honeycomb are documented in
`beekeeper/AGENTS.md`. That file is for the runtime; this file is for you,
the contributor agent. They are different files. Do not merge them.

## When in Doubt

Stop and ask the user. Surface the question, do not guess. A wrong PR wastes
maintainer attention; a clarifying question costs one round-trip.
