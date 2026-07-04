# Third Project: Beekeeper Personal — Detailed Plan, Decision Menus, and Remaining Gaps

Date: 2026-06-10

## Source

- Vision statement written 2026-06-10 (this doc formalizes it).
- Builds on: `future/2026-06-08_beekeeper_fcli_inventory_and_v1_roadmap.md` (source of truth),
  `beekeeper_fcli_roadmap/plans/` (v1–vn), `future/2026-06-07_beekeeper_fcli_worker_template_plan.md`.
- Review inputs: Beekeeper project audit (2026-06-10) and fcli codebase assessment (2026-06-10).

---

## 1. The Thing Itself

A governed agent runtime where a persistent Queen delegates real work to disposable, verified
workers.

- **Beekeeper supplies the brain-stem**: memory, policy, scheduling, approvals, audit.
- **fcli supplies the hands**: shell, files, git, verification.
- **The contract is the nervous system**: JSON task in, NDJSON events out, verified result +
  evidence at the end.

> In one line: Claude Code's capability with Beekeeper's accountability — an agent system you can
> trust precisely because you never have to trust it.

### What the combination can do, concretely

| Capability | Shape |
|---|---|
| Delegated coding tasks | "Fix the failing tests in repo X" → Queen spawns a worker, it edits, runs pytest, returns proof, dies. You review evidence, not promises. |
| Verified automation | Any shell-doable task (refactors, dependency bumps, log analysis, batch file ops) executed with ground truth, never hallucinated. |
| Parallel work | Three repos, three workers, three isolated worktrees, one audit trail. |
| Safe autonomy | Workers cannot exceed their grant: workspace-scoped, network-off, budget-capped. Risky actions queue as HITL approvals in Beekeeper. |
| Recurring jobs | Queen schedules "run the test suite nightly, file a summary," dispatches a worker each time, accumulates outcomes in Honeycomb. |
| Curated memory | Raw thoughts → curator worker extracts candidates → Queen approves what becomes durable. Memory is curated, not polluted. |
| Full forensics | Every task → trace_id → event log → result evidence. "What did the system do and why" is answerable for anything it ever did. |

### Phases

| Phase | Name | Delivers |
|---|---|---|
| v1 | The spine | One worker, one lifecycle: contract in → verified result + event log out. Includes the death path (timeouts, crash, teardown). |
| v2 | The trust boundary | Approval escalation to Queen, live event streaming, runtime-enforced sandboxing, contract-granted budgets, teardown guarantees. |
| v3 | The supervisor | Parallel workers, scheduling/retries, recurring tasks, memory curation flow. The "second brain" promise comes alive here. |
| v4 | The growth loop | Skill promotion pipeline (draft → sandboxed → tested → approved → active) and worker forge with provenance. The system extends itself — under governance. |

**Phase discipline rule:** do not start v3 (parallel autonomy) before v2 (enforced boundaries) is
real. Parallelism before enforcement multiplies blast radius, not capability.

---

## 2. Keep List — Decided, Do Not Reopen

1. **Brain-stem / hands split.** Beekeeper owns state, policy, memory, approvals; fcli owns side
   effects. (Kubernetes control-plane/kubelet pattern.)
2. **NDJSON events as the bridge; never parse terminal prose.**
3. **Subprocess bridge first, package import later.** The process boundary is the cheapest
   isolation available and keeps the contract honest.
4. **Disposable workers that return proof and die.**
5. **fcli's verification taxonomy** (`passed / failed / unavailable / not_attempted`).
6. **Phase ordering** spine → trust boundary → supervisor → growth loop; Worker Forge last.
7. **Explicit non-goals and acceptance bars per phase.**
8. **Memory curation flow** (dump → curator extracts → Queen approves durable memory).
9. **No auto-commit / auto-push without approval; worker is named `coding_worker`, not
   `fcli_worker`** (name the role, not the implementation).

---

## 3. The 10 Improvements — Decision Menus

Each improvement below is a decision to make. Options are mutually exclusive unless noted.
Recommended option listed first and marked.

### Q1. Sandbox enforcement — how does "cannot exceed grant" become true?

The vision claims workers *physically* can't exceed their grant. Today fcli's guardrails are
in-process policy checks (advisory). Pick the v2 enforcement mechanism:

- [ ] **A (Recommended for v2):** `sandbox-exec` (Seatbelt) profile around the worker subprocess —
  filesystem scoped to the worktree, network denied by default. Lightest weight; macOS-only;
  Apple-deprecated API but still functional and used by Claude Code itself.
- [ ] **B:** Container per worker (Docker/OCI) — portable to Linux, strongest isolation; heavier
  startup (~seconds), requires Docker running; better fit for v3 parallel fleets.
- [ ] **C:** Dedicated low-privilege OS user + filesystem ACLs — no dependencies; coarse-grained,
  no per-run network control, painful cleanup.
- [ ] **D:** Keep policy-only enforcement and reword the vision to "policy-gated" — zero work,
  honest, but abandons the strongest differentiator.

Suggested path: **A in v2, B in v3** when parallel workers and Linux portability matter. If neither
A nor B lands in v2, the vision text must be reworded (D) — do not ship the claim without the
mechanism.

### Q2. Contract ownership — where does the schema live?

- [ ] **A (Recommended):** A third tiny package/repo (`agent-task-contract` or similar): Pydantic
  models + JSON Schema export + golden NDJSON fixtures. Both Beekeeper and fcli depend on it and
  run its compatibility tests in CI.
- [ ] **B:** Schema lives in Beekeeper (supervisor owns the contract); fcli vendors a copy and a
  drift-check test compares them.
- [ ] **C:** Schema lives in fcli (producer owns the events); Beekeeper vendors.
- [ ] **D:** Versioned JSON Schema files only (no shared code), each side hand-writes models.

Non-negotiable regardless of option: `contract_version` field in every envelope from message one,
plus golden fixture files tested from both repos.

### Q3. Worker death path — who detects and what happens?

- [ ] **A (Recommended):** Heartbeat events in the contract (worker emits `heartbeat` every N
  seconds) + supervisor-side wall-clock deadline per task + kill-and-teardown on breach, recorded
  as a `worker_timeout` terminal event.
- [ ] **B:** Supervisor-side deadline only (no heartbeats) — simpler; cannot distinguish "hung" from
  "slow but alive."
- [ ] **C:** Worker self-enforces its own deadline — simplest, but a crashed worker can't
  self-report; supervisor still needs a backstop.

A includes C's self-deadline as defense-in-depth. Orphan cleanup (stale worktrees, zombie
processes) runs at supervisor startup and after every terminal event.

### Q4. Budget granting — where do limits live?

- [ ] **A (Recommended):** Budgets are fields in `CodingWorkerTask` (max_iterations, max_actions,
  wall_clock_seconds, max_provider_calls or token/cost cap). Worker enforces them; supervisor
  verifies from the event stream and enforces the wall-clock backstop.
- [ ] **B:** Keep budgets as fcli config defaults; supervisor only sets wall-clock — less contract
  churn, but "budget-capped" stays a worker default, not a governance feature.
- [ ] **C:** Supervisor-side only enforcement — workers stay simple, but the supervisor can only
  kill, not gracefully stop at a boundary.

### Q5. Repo mutation model

- [ ] **A (Recommended):** Temporary git worktree + patch artifact. The result IS a diff + test
  evidence; applying the patch is the approval action. Smallest v1 policy surface; makes v3
  parallelism nearly free.
- [ ] **B:** Direct mutation of the selected repo with git-stash safety net — simpler plumbing,
  larger blast radius, complicates parallel work later.
- [ ] **C:** Copy-the-repo sandbox (no git plumbing) — works for non-git folders, expensive for
  large repos, loses git context.

### Q6. Beekeeper inheritance — how much of the frozen MVP does the third project take?

- [ ] **A (Recommended):** Carve-out: only the modules the bridge touches (run store, approval
  queue, audit writer, personal-mode status) are imported, and that slice is brought to fcli's
  quality bar (hermetic tests, strict typing, the JWT/CORS fixes on any exposed endpoint).
- [ ] **B:** Import Beekeeper wholesale as a dependency and fix issues opportunistically — fastest
  start, inherits the full 26k-LOC surface and its known security gaps.
- [ ] **C:** Rewrite the needed control-plane pieces fresh in the third project, porting concepts
  only — cleanest, slowest; risks re-learning solved problems.

(Note: `~/Developer/beekeeper-personal/` already exists — whichever option is chosen should be
recorded there as an ADR so the carve-out boundary is explicit.)

### Q7. Trace identity across the boundary

- [ ] **A (Recommended):** Supervisor mints `trace_id` and `task_id`; passes both in the task
  envelope; worker stamps them on every NDJSON event and on its internal session/step records.
  One ID namespace end-to-end.
- [ ] **B:** Each side keeps its own IDs; a mapping table in Beekeeper joins them — works, but
  forensics requires a join and breaks if the mapping write fails.
- [ ] **C:** Worker mints IDs and reports them back — supervisor can't correlate until the worker
  responds; orphaned tasks become unsearchable.

### Q8. Approval-resume contract shape (built in v1, used in v2)

- [ ] **A (Recommended):** Tasks are resumable by ID: `pending_approval` is a suspended task state;
  the resume call carries the approval verdict; all events are idempotent (event_id +
  monotonic sequence number) so re-delivery is safe.
- [ ] **B:** v1 ships stop-and-rerun (fresh task referencing the old one); design resume later —
  risks the first breaking contract change exactly when v2 needs stability.
- [ ] **C:** Worker blocks in-process waiting for approval over the event channel — no contract
  change needed, but a worker holding a worktree open for hours fights the "disposable" principle.

### Q9. Failure-path acceptance tests in the golden smoke

- [ ] **A (Recommended):** Golden smoke = happy path + four mandatory failure scenarios: blocked
  commit, workspace-escape attempt, worker timeout/hang, worker crash mid-run. Each must produce
  the correct terminal event, approval record (where applicable), and clean teardown.
- [ ] **B:** Happy path in the smoke; failure paths as ordinary unit tests — cheaper to run, but
  failure handling is exactly what the product claims, so it belongs in the acceptance bar.
- [ ] **C:** Add a chaos/fault-injection harness from the start — valuable, premature before v2.

### Q10. v1 provider strategy

- [ ] **A (Recommended):** Mock/stub provider as a first-class provider implementation (used by the
  golden smoke and CI — deterministic, free) + exactly one real provider for daily use. Real-LLM
  runs are a manual/nightly check, never the acceptance gate.
- [ ] **B:** One real provider only — simplest, but the acceptance bar then depends on a live LLM
  (the exact mistake that made Beekeeper's test suite unrunnable).
- [ ] **C:** Multiple real providers in v1 — breadth before the spine is proven; defer to v2+.

Which real provider: Ollama Cloud (already wired into both projects, cheap) or Codex (already a
fcli provider, strongest at coding). Decide on cost + observed plan quality; this choice is
reversible and low-stakes compared to the mock-provider decision.

---

## 4. Remaining Gaps — Not Yet in Any Plan Doc

Things discovered during review that no existing roadmap covers. Each needs an owner-decision
before or during v1/v2.

### G1. License compatibility (decide before the third repo takes shape)

Beekeeper is **AGPL-3.0-or-later**; fcli is **MIT**. The third project combines them.

- If the third project imports Beekeeper code (Q6 options A/B), the third project is effectively
  AGPL — fine if intended, but it must be a conscious choice, and AGPL §13 network-service terms
  apply if it's ever hosted.
- The subprocess bridge keeps fcli's MIT licensing untangled (process boundary, not linking).
- The contract package (Q2-A) should be permissively licensed (MIT/Apache-2.0) so both sides and
  any future worker implementation can depend on it freely.

### G2. Secret handling for workers

How does a worker get its provider API key? Today both projects read ambient env vars. A worker
that inherits the parent environment can exfiltrate every secret in it (and "network-off" makes
this moot only after Q1 lands).

- Minimum v1 posture: supervisor passes an explicit, minimal env allowlist to the worker
  subprocess (provider key only, nothing else); never inherit the full parent env.
- v3 posture (already roadmapped as "secret references"): short-lived scoped credentials resolved
  at spawn time from Beekeeper's secret_manager abstraction.

### G3. Platform portability

fcli is macOS-first (PTY handling), `sandbox-exec` is macOS-only, and the dev machine is a Mac.
Acceptable for v1–v2; becomes a real constraint the moment recurring jobs should run on an
always-on box (typically Linux). Flag it as a v3 decision tied to Q1-B (containers), not something
to solve now.

### G4. Supervisor state under concurrency

Beekeeper's store is JSONL/SQLite-file based. One worker (v1) is fine. Three workers (v3)
emitting events + run-state updates concurrently will hit write contention and partial-write
corruption risks. Decision point at v3 entry: SQLite-WAL with a single writer process, or the
already-roadmapped Postgres move. Do not let v3 start on naive concurrent JSONL appends.

### G5. Contract version skew

After v1 ships, Queen and installed workers will upgrade at different times. Policy needed (can be
one paragraph in the contract spec): supervisor rejects task dispatch when
`worker.contract_version` is outside its supported range, with a clear doctor-style error.
Cheap to define now; expensive to retrofit.

### G6. v1 primary surface (open question 3 from the June 8 doc — still undecided)

Recommendation: **CLI-first for v1** (`beekeeper run`, `status --personal`, `review`), dashboard as
read-only viewer. Rationale: the dashboard is prototype-grade (single 963-line HTML file), and the
golden smoke + failure paths are scriptable against a CLI but not against a DOM. Dashboard becomes
a first-class surface in v2 alongside live event streaming.

### G7. Worker regression harness as a release gate

fcli's `manual_playbook/` scenario suite should graduate into the third project's CI: every
`coding_worker` release must pass the playbook against the mock provider before the supervisor
will dispatch to it (record worker version + manifest fingerprint in the run record — fcli already
computes SHA-256 manifest fingerprints; surface them in Beekeeper's audit trail).

### G8. Cost accounting across runs

Budgets (Q4) cap a single task. Nothing yet accumulates spend per day/repo/schedule. Honeycomb
should record per-task provider usage from worker events so "what did the nightly job cost this
month" is answerable. Small contract addition (usage block in the result envelope); v2.

### G9. Product naming

"Beekeeper Personal" describes the mode, not the product. Low stakes, but the third repo needs a
name before its first commit. (`beekeeper-personal` exists as a folder already — fine as a working
name; revisit before any public release.)

---

## 5. Suggested Decision Order

1. **Q5** (worktree+patch) and **Q7** (ID namespace) — they shape the contract.
2. **Q2** (contract ownership) + **G1** (licensing) + **G5** (version skew) — then write the
   contract spec.
3. **Q3/Q4/Q8** (death path, budgets, resume shape) — fields in that same spec.
4. **Q10** (mock provider) + **Q9** (failure-path smoke) — the v1 test strategy.
5. **Q6** (Beekeeper carve-out) + **G2** (worker env allowlist) + **G6** (CLI-first) — v1 build scope.
6. **Q1** (sandbox mechanism) — v2's make-or-break milestone; until it lands, all docs say
   "policy-gated," not "physically can't."

## 6. Acceptance Bar for This Doc

This plan is "decided" when every checkbox in section 3 has exactly one selection, each gap in
section 4 has a one-line decision recorded, and the contract spec draft exists reflecting
Q2/Q3/Q4/Q5/Q7/Q8/G5.
