# Option B — Extract the Policy / HITL / Audit Layer as a Standalone Library

**Goal:** Carve out the genuinely novel piece of Beekeeper — per-action policy gating with HITL queue and append-only audit trail — into a small, focused, reusable Python library that any agent can drop in.

**Effort:** 1–2 weekends.

**Risk:** Medium. The carve-out has to be clean (no leaking Beekeeper concepts) or nobody will adopt it. Done well, this is the most likely path to traction because *orchestrators are saturated; policy primitives are not.*

---

## Why this is the right move

The orchestrator space is crowded — LangGraph, CrewAI, AutoGen, Semantic Kernel, Bedrock Agents, plus pi-mono, hermes-agent, opencode. None of them have a clean answer to "how do I gate every tool call against a user-defined policy, queue the ones that need approval, and persist an audit trail I can replay later."

That's a small library, not a platform. Small libraries get adopted. Platforms compete with VC-funded teams.

---

## Proposed package

**Name:** `beekeeper-policy` or `agent-policy-gate` (pick one — the latter is more SEO-friendly).

**Lines of code:** ~2,300 LOC of source today (see breakdown below), targeting ~1,200 LOC after extraction (drop the Beekeeper-specific glue).

**Public API surface:** small. Three classes and one decorator, ideally.

### Sketch of the public API

```python
from agent_policy_gate import PolicyGate, ReviewQueue, AuditLog, gated

policy = PolicyGate.from_dict({
    "default": "allow",
    "actions": {
        "send_email": "ask",
        "delete_file": "deny",
        "spawn_subprocess": "ask",
    },
})

reviews = ReviewQueue(backend="sqlite:///reviews.db")
audit = AuditLog(backend="jsonl:///audit.log")

@gated(policy=policy, reviews=reviews, audit=audit, action="send_email")
def send_email(to: str, subject: str, body: str): ...

# In your agent loop:
result = send_email(to="alice@example.com", subject="hi", body="hello")
# - policy=allow → runs immediately, audited
# - policy=ask   → enqueued in reviews, raises PendingApproval
# - policy=deny  → raises PolicyDenied, audited
```

Plus a simple FastAPI router for `GET /reviews`, `POST /reviews/{id}/approve|deny`.

That's it. No Queen, no Workers, no Celery, no Temporal, no SSE, no Honeycomb metaphor. Just a decorator and three storage-backed primitives.

---

## What to extract from Beekeeper

Source files that contain the policy / HITL / audit logic today:

| File                                       | LOC  | Goes into lib?                     |
|--------------------------------------------|------|------------------------------------|
| `beekeeper/user_policy.py`                 | 113  | Yes — core policy model            |
| `beekeeper/policy_service.py`              |  90  | Yes — load / save / merge          |
| `beekeeper/governance/policy_adapter.py`   | 221  | Yes — decision logic               |
| `beekeeper/governance/capability_manifests.py` | 164 | Maybe — depends on scope cut    |
| `beekeeper/governance/tool_broker.py`      |  41  | Yes — gate-call wrapper            |
| `beekeeper/audit_logger.py`                | 379  | Yes — append-only audit            |
| `beekeeper/audit_compliance.py`            | 272  | No — too coupled to compliance     |
| `beekeeper/honeycomb.py`                   | 825  | **No** — too big, too coupled      |
| `beekeeper/guardrails.py`                  | 217  | Maybe — PII filter is reusable     |

**Total in scope: ~1,000–1,200 LOC after deduping and cutting Beekeeper-specific code.**

The big subtraction: `honeycomb.py` is 825 LOC of Beekeeper-specific event store with embedded SSE bus and queen-context replay. Don't ship that. Re-implement a *small* AuditLog with one storage backend (JSONL) and one optional adapter (SQLite). 100 LOC max.

---

## Step-by-step carve-out plan

### Step 1: New repo skeleton (~30 min)

```
agent-policy-gate/
├── pyproject.toml
├── README.md
├── LICENSE                # Apache 2.0
├── src/
│   └── agent_policy_gate/
│       ├── __init__.py    # public API exports only
│       ├── policy.py      # PolicyGate
│       ├── reviews.py     # ReviewQueue (sqlite backend)
│       ├── audit.py       # AuditLog (jsonl backend)
│       ├── decorator.py   # @gated
│       ├── api.py         # optional FastAPI router
│       └── exceptions.py  # PolicyDenied, PendingApproval
├── tests/
└── examples/
    ├── basic_usage.py
    ├── with_langchain.py
    └── with_openai_tools.py
```

### Step 2: Port code without Beekeeper assumptions (~1 day)

Copy → strip → minimize:

- Drop `tracer`, `honeycomb`, `worker_registry`, `queen_context` imports.
- Drop tenant-id plumbing (or make it an optional kwarg).
- Drop the `actor`/`channel` distinctions if they don't generalize.
- Replace JSON-file-on-disk persistence with pluggable backends (start with two: in-memory + sqlite). One adapter per backend, ~50 LOC each.
- Replace per-action allowlists with a single typed `PolicyGate` model.

### Step 3: Public API ergonomics (~half day)

The decorator is the user's first impression. Make it perfect:

- Sync and async support.
- Auto-derive the action name from the function name if not given.
- Inject the policy decision into the function as an optional kwarg (so callers can branch on `ask` if they want).
- Pleasant exceptions (`PendingApproval` carries `review_id` so the caller knows where to point the user).

### Step 4: Two reference integrations (~half day each)

The lib is only as compelling as its examples:

1. **OpenAI tool-calling integration.** A 50-line example showing how to wrap each tool definition with `@gated` and how to surface `PendingApproval` back to the model.
2. **LangChain integration.** Same idea, but as a `BaseTool` subclass.

### Step 5: Tests (~half day)

Port the relevant tests from `tests/test_user_policy.py` (14 tests already exist). Add:

- Roundtrip: deny → exception, ask → queued, allow → ran.
- Concurrent approve/deny races (one win, one no-op).
- Audit log replay.
- The two reference integrations.

Target: 25–30 tests, full coverage of the public API.

### Step 6: README + example GIF (~half day)

The README is the marketing. Structure:

1. **30-second pitch** — "Agent calling tools? Gate every call against a user policy, queue the risky ones for human approval, persist an audit log. Drop-in, ~5 lines.".
2. **Why** — one paragraph: orchestrators are crowded; policy primitives aren't.
3. **Quick start** — the 5-line example from above.
4. **Pluggable backends** — one paragraph + a table.
5. **Integrations** — link to the two examples.
6. **Comparison** — short table vs. doing it yourself, vs. LangChain's callbacks, vs. doing nothing.
7. **Status** — be honest: "alpha, API may change before 1.0".

GIF showing: agent tries to send email → terminal pauses with "approval required" → reviewer approves in another shell → agent continues.

### Step 7: Publish (~1 hour)

- `pip install -e .` works.
- Push to PyPI as `agent-policy-gate==0.1.0`.
- Push to GitHub. Public.
- Post once to one place (Hacker News *or* r/LocalLLaMA *or* Twitter — pick one, make it good). Don't multi-post.

---

## What stays in Beekeeper

The lib is a clean carve-out, not a fork. Beekeeper continues to use the same code, just imported from the package:

```python
# beekeeper/queen.py (after extraction)
from agent_policy_gate import PolicyGate, ReviewQueue, AuditLog
```

Beekeeper keeps: Queen, Workers, scheduler, vector store, channels, runner CLI, Honeycomb (which becomes a thicker Beekeeper-specific layer on top of `AuditLog`).

This means:
- The lib has one real user from day one (Beekeeper itself), which is a strong dogfooding signal.
- Beekeeper gets smaller (deletes ~1,000 LOC) and more focused.
- Both repos win.

---

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| The carve-out leaks Beekeeper concepts and feels weird to outside users | Validate by having one outside example (LangChain) work end-to-end before publishing. If it's awkward, the API is wrong. |
| Adoption depends on the README, not the code | Spend a full day on the README. Read it cold the next day. Rewrite. |
| Someone else has already done this | Search PyPI + HN before naming. The closest existing thing is LangChain's callback handlers, which aren't policy-gates. |
| The audit log re-implementation is half-baked | Ship one backend (JSONL) only at v0.1. SQLite at v0.2. Anything more is YAGNI. |
| You lose interest mid-carve-out | Time-box it: 2 weekends. If not done, ship what you have and write a "lessons learned" post. |

---

## Success criteria

- 50+ stars in 4 weeks **and** at least one external user opens an issue about the API. Star count alone doesn't mean adoption.
- Beekeeper's own code reads more cleanly after the extraction (fewer imports, smaller files, clearer ownership).
- API doesn't need to break for v0.2.

---

## Decision after publishing

**If the lib gets traction:** double down. Beekeeper becomes the reference implementation / kitchen-sink demo. The lib is the product.

**If the lib does not get traction:** you've still extracted the cleanest piece of code in your stack. Beekeeper is smaller and more focused. The work is not wasted.

**Either way:** publishing the lib is a strict improvement on the current "private 26K-LOC repo with one user" state.
