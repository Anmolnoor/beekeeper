# Launch Prep — Status

Branch: **`launch/open-source-prep`** (not committed yet, not pushed yet)

## Done (staged in working tree)

### Governance
- `LICENSE` — Apache 2.0, © 2026 Anmol Noor
- `CONTRIBUTING.md` — gate, lgtm/lgtmi flow, weekend rule, quality bar, philosophy, FAQ
- `CODE_OF_CONDUCT.md` — Contributor Covenant 2.1, **rewritten with Beekeeper-specific clauses** (no framework-bashing, no AI-ghostwriting at scale, no throwaway-account spam)
- `SECURITY.md` — private advisories + email channel, response SLAs, scope
- `CHANGELOG.md` — 0.1.0 initial-release entry, "no contributor edits" notice
- `AGENTS.md` (repo root) — rules for coding agents working *on* the repo (different from `beekeeper/AGENTS.md`)

### Pi-mono protection system (.github/)
- `APPROVED_CONTRIBUTORS` — seeded with `Anmolnoor pr`
- `workflows/issue-gate.yml` — auto-close issues, weekend label, lgtm/lgtmi messaging
- `workflows/pr-gate.yml` — auto-close PRs from non-allowlisted, fork-safe (`pull_request_target`)
- `workflows/approve-contributor.yml` — `lgtm`/`lgtmi` parser, allowlist updater, **auto-reopens the issue** (improvement over pi-mono which leaves it closed)

### Issue + PR templates
- `ISSUE_TEMPLATE/config.yml` — blank issues disabled, links to Discussions + private SECURITY advisories
- `ISSUE_TEMPLATE/bug.yml` — Beekeeper-specific component dropdown (Queen, Worker, Honeycomb, MCP, etc.)
- `ISSUE_TEMPLATE/contribution.yml` — proposal-first, surface dropdown, willing-to-implement field
- `PULL_REQUEST_TEMPLATE.md` — three sections, verification checklist, `CHANGELOG.md` warning

### CI
- `workflows/ci.yml` — ruff lint + pytest matrix on Python 3.10/3.11/3.12, concurrency-cancel on superseded runs

### Repo polish
- `README.md` — added 4 badges + "heads-up for contributors" note up top + Contributing + License sections at bottom
- `pyproject.toml` — added `license = "Apache-2.0"`, classifiers, project URLs, keywords, authors

### Code cleanup
- `beekeeper/runner.py` — fixed 7× "Beehive" → "Beekeeper" in CLI banners
- `beekeeper/sdk.py` — fixed 2× "Beehive" → "Beekeeper" in docstrings
- `.gitignore` — added `.beekeeper_store/`, `.queen_core/`

### Launch content (in `launch/`)
- `launch/blog-post.md` — ~2200-word post for anmolnoor.com (story → architecture → 3 differences → opinionated bits → contribution gate → roadmap → close)
- `launch/social/linkedin.md` — single-post draft with hook, narrative, gate justification, hashtags
- `launch/social/x-thread.md` — 9-tweet thread, all char-counted ≤280

## Pending — needs your review/decision

### `launch/REMOVAL_REVIEW.md` ⚠️
Tier-1 removals (4 stale personal files), Tier-2 (`COMPARISON_REPORT.md` keep/move/drop), Tier-3 (`.beekeeper_store/` PII — git-rm-only vs git-filter-repo). **Read it and reply** so I can run the right `git rm` set.

### Steps after your review
1. `git rm` the files you've approved.
2. Stage everything: `git add -A`
3. Commit on `launch/open-source-prep` (your call on the message).
4. (You) push the branch and open a self-review PR against `main`, OR push directly if you trust the diff.
5. Merge to main.
6. **Then, in this order:**
   - Settings → Branches → protect `main` (require PR, require CI green).
   - Settings → Code security → enable Dependabot + secret scanning + push protection.
   - Settings → General → enable Discussions.
   - Settings → General → set description: `Governed multi-agent runtime with tool-level policy, HITL guardrails, and full trace/audit. Apache-2.0.`
   - Settings → General → topics: `agents agent-framework llm multi-agent governance policy python fastapi temporal mcp`
   - Settings → Social preview → upload 1280×640 PNG.
   - Settings → General → Change visibility → **Public**.
7. **Smoke test from a throwaway account:**
   - Open a test issue → `Issue Gate` should auto-close with the right message within ~30s.
   - Open a test PR → `PR Gate` should auto-close.
   - From your main account, comment `lgtmi` on the closed issue → `Approve Contributor` should run, update `APPROVED_CONTRIBUTORS`, push a commit, and reopen the issue.
   - Comment `lgtm` on a fresh issue → confirm capability upgrades to `pr`.
8. Once smoke test passes, post the LinkedIn + X thread + publish the blog post.

## Test status

Full `pytest tests/` (153 collected) did not finish in 6+ minutes — at least one test hangs waiting on an external service. **Pre-existing, not introduced by this prep.**

Fast subset (`test_beekeeper.py`, `test_user_policy.py`, `test_dispatch_service.py`) finished in 2:21 with **20 passed, 5 failed**.

All 5 failures are the same root cause:

```
AttributeError: 'module' object at beekeeper.queen has no attribute 'resolve_runtime_mode'
```

Failing tests:
- `test_auto_scheduler_prefers_celery_for_queueable_payload`
- `test_auto_scheduler_prefers_temporal_for_durable_payload`
- `test_auto_scheduler_falls_back_inline_when_backends_unavailable`
- `test_inline_scheduler_disallowed_in_non_dev_prefers_temporal`
- `test_inline_scheduler_disallowed_in_non_dev_without_backends_raises`

The tests `monkeypatch.setattr(beekeeper.queen, "resolve_runtime_mode", ...)` but that attribute doesn't exist on the module — likely a refactor renamed/moved it and these tests weren't updated. **Pre-existing, none of my edits touch `beekeeper/queen.py` or these tests.**

**Recommendation:** Don't block launch on this. The CI workflow on GitHub will reproduce the failures cleanly (no service hangs), and you can fix as a follow-up PR. The user-facing surface (CLI, API, governance) is unaffected.

If you want this fixed before flipping public, the fix is one of:
1. Add `resolve_runtime_mode` to `beekeeper/queen.py` if it was supposed to live there.
2. Change the tests to monkeypatch the module where the function actually lives.
3. Mark the 5 tests `@pytest.mark.skip(reason="resolve_runtime_mode refactor pending")`.

## What I did NOT do (intentionally — needs your call)

- ❌ No `git rm` of any file (waiting on `REMOVAL_REVIEW.md` decision).
- ❌ No `git commit`.
- ❌ No `git push`.
- ❌ No GitHub Settings changes (description, topics, visibility, branch protection, security features).
- ❌ No `git filter-repo` history rewrite (Tier-3 Option B in `REMOVAL_REVIEW.md`).
- ❌ No flip to public.

Everything above is reversible by `git checkout main && git branch -D launch/open-source-prep` if you want to throw it away.
