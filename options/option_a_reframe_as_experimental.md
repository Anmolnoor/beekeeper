# Option A — Reframe Beekeeper as an Experimental Orchestrator

**Goal:** Publish the existing repo as-is, but with an honest README that pre-empts the "this is over-engineered / not production-ready" critique by being the first to say it.

**Effort:** ~2 hours. No code changes. README rewrite + a status matrix + a few honest disclaimers.

**Risk:** Low. Worst case the repo gets ignored. Best case people show up curious about the policy/HITL/Honeycomb pieces.

---

## Why this works

Right now Beekeeper reads like a product pitch (multi-tenant, multi-channel, governance, audit, etc.) but the code is a 46-day-old experimental prototype with one user. Anyone landing on the repo will immediately spot the gap and lose trust.

The fix is to flip the framing: lead with "this is a research notebook for ideas about agent orchestration with policy and audit," not "this is your team's agent platform." Honest framing converts skeptics into curious readers.

---

## Concrete steps

### 1. Rewrite the README opening

Replace any "production-grade" / "enterprise-ready" language with research framing:

```markdown
# Beekeeper

An experimental multi-agent orchestrator built around three ideas:

1. A central planner (**Queen**) decomposing a request into typed tasks
2. Ephemeral workers executing those tasks under a per-action policy gate
3. An append-only event log (**Honeycomb**) that traces every decision

Status: research / personal use. Not production-ready. The architecture
is more ambitious than the implementation. Read the status matrix below
before adopting any of this.
```

### 2. Add a status matrix near the top

Be specific about what works, what's stubbed, and what's planned. Concrete, not aspirational.

```markdown
## What's actually shipping

| Subsystem                     | Status         | Notes                                                            |
|-------------------------------|----------------|------------------------------------------------------------------|
| Queen → Worker dispatch       | Working        | 147/153 tests pass. 5 pre-existing scheduler test failures.      |
| Per-action user policy gate   | Working        | `allow` / `ask` / `deny` enforced; HITL review queue.            |
| Honeycomb event log           | Partial        | Append-only events, SSE stream, replay store. NOT authoritative. |
| LLM provider chain (fallback) | Working        | Ollama Cloud → Gemini → OpenAI.                                  |
| HITL approval flow            | Working        | API endpoints + persistence; minimal UI.                         |
| Worker registry / forge       | Experimental   | Auto-spawn on unmatched intent. Sandbox not enforced.            |
| Multi-tenant quotas           | Skeleton       | Models exist; no real enforcement on hot paths.                  |
| Slack channel                 | Working        | Tested manually.                                                 |
| Telegram / Discord / WhatsApp | Skeleton       | Adapters exist; not exercised.                                   |
| Temporal workflow scheduler   | Optional       | Falls back to inline / Celery if not running.                    |
| Production deploy story       | Not implemented| Postgres + Temporal + S3 path is *documented*, not built.        |
| CI                            | Not implemented| Run `pytest` locally.                                            |
```

### 3. Add a "Known limitations" section

Pre-empt the obvious critiques:

```markdown
## Known limitations

- **God objects.** `queen.py` is ~2,200 LOC, `runner.py` is ~2,150, `worker.py` is ~1,100. Splitting these is on the roadmap.
- **Three execution modes.** Legacy worker dispatch, model-driven tool loop, and hybrid mode coexist. The plan is to converge on the hybrid mode and delete the others.
- **Honeycomb is advisory.** It's an event trace, not source-of-truth state. Don't reason about authoritative state from Honeycomb alone.
- **No CI yet.** Tests run locally with `pytest`.
- **Worker forge is unsandboxed.** It can generate and register custom worker code, which is powerful and dangerous. Off by default.
```

### 4. Add a "Why I'm publishing this" section

Honest framing of the goal:

```markdown
## Why this exists

I'm publishing Beekeeper to get feedback on three specific ideas:

1. Is per-action policy gating with `allow` / `ask` / `deny` the right
   primitive for agent governance, or is it too coarse?
2. Is an append-only event log the right shape for agent audit, or do
   we need authoritative state from day one?
3. Is the Queen → Worker decomposition useful in practice, or does it
   collapse into a single agent loop in real use?

If you've thought about any of these, I'd love to hear from you.
Open an issue or PR. I am not promising response times or stability.
```

### 5. Add a "Quick start" that actually works

The current `GETTING_STARTED.md` is good. Pull the no-Docker quick path into the README so a reader can verify the project runs in 30 seconds:

```markdown
## Quick start (no Docker)

    pip install -e .
    cp .env.example .env
    # edit .env to set BEEKEEPER_OLLAMA_API_KEY or BEEKEEPER_GEMINI_API_KEY
    beekeeper run --scheduler inline --vector memory --query "What is 2+2?"
```

### 6. Things to cut from the README

- Any reference to "production-grade", "enterprise-ready", "battle-tested".
- Any feature listed as a bullet that's actually a skeleton. Move to the status matrix.
- Long architectural lectures. Move to `architecture/` (already there).

### 7. Things to add elsewhere (not README)

- `CONTRIBUTING.md` — be explicit that PRs may sit unreviewed; this is personal-time work.
- `LICENSE` — pick MIT or Apache-2.0 and commit it. (Verify if missing.)
- Top-of-file docstrings on `queen.py`, `worker.py`, `honeycomb.py` summarizing role.

---

## What this option does NOT do

- Does not fix the god objects.
- Does not delete the unused execution modes.
- Does not add CI.
- Does not extract the policy/HITL pieces (that's Option B).

It just makes the framing match the reality, which is the cheapest meaningful improvement.

---

## Success criteria

- A reader who has never seen the repo can, in 60 seconds, answer:
  1. What does this do?
  2. Is it production-ready? (No.)
  3. What's the most interesting idea here?
  4. How do I run it?
- Zero "this is over-engineered" hot-takes go un-pre-empted.
- Status matrix is reviewed and updated every time a subsystem changes.

---

## After publishing

Two metrics to watch over the first 4 weeks:

1. **Issue quality.** Are people opening issues about the policy gate, HITL flow, or Honeycomb (the differentiated pieces)? Or are they all "how do I install it"? The former is signal; the latter means the docs are still the bottleneck.
2. **Stars-per-week curve.** Don't worry about absolute numbers. Worry about whether it's flat (interesting only to you) or growing (interesting to others).

If both signals are weak after 4 weeks, fall back to Option B.
