# Pre-Public Removal Review

This file lists every tracked artifact I think should be removed before flipping
the repo public, what's still in question, and what's safe to keep. **I have
NOT executed any `git rm` yet** — this is a review pass for you.

Once you confirm, I'll run the removals on the `launch/open-source-prep` branch.

## Tier 1 — Safe to remove (recommend `git rm`)

These are personal one-off reports / dupes / runtime debris with no project value.

| File | Size | Why remove |
|---|---:|---|
| `anmol_noor_report.md` | 116 B | Stale error message dump from a Queen run. |
| `anmolnoor_github_linkedin_report.md` | 2.4 KB | Old research report about you, generated as test output. |
| `research_anmol_noor_github.md` | 2.4 KB | Duplicate of the file above. |
| `future/2026-03-06_queen_test_anmol_noor_trace_audit_monitoring_report.md` | 4.0 KB | Stale Queen test report with you as the test subject. |

```bash
git rm \
  anmol_noor_report.md \
  anmolnoor_github_linkedin_report.md \
  research_anmol_noor_github.md \
  future/2026-03-06_queen_test_anmol_noor_trace_audit_monitoring_report.md
```

## Tier 2 — Your call

| File | Size | Note |
|---|---:|---|
| `COMPARISON_REPORT.md` | 33 KB | Competitive comparison of Beekeeper vs LangGraph / OpenClaw / etc. Real content, but reads like internal positioning research. **Two options:** (a) `git rm` it, (b) move to `docs/comparisons.md` and link from README. I lean (b) — it's actually useful marketing material if cleaned up, and a public competitive doc is a flex. |
| `anmolnoor_github_linkedin_report.md` (already in Tier 1) | — | If you want to keep any biographical material, put it in `docs/about.md` *intentionally*, not as a leftover scratch file. |

## Tier 3 — Runtime state with PII (separate decision)

| Path | Note |
|---|---|
| `.beekeeper_store/users/user_eb97fe77c4f8.json` | Contains your email (`<redacted-email>`) and a bcrypt password hash. |
| `.beekeeper_store/{hives,honeycombs,orgs,queens,roles}/*.json` (5 more files) | Live runtime state (org/hive/queen IDs from your local instance). Not secret, but not for public consumption. |
| `.queen_core/souls/*` | Local soul data. |

`.gitignore` is already updated to exclude `.beekeeper_store/` and `.queen_core/` going forward. The question is what to do about the **already-committed history**:

- **Option A — `git rm` only.** Removes from main going forward. Email + password hash remain in git history. Bcrypt is expensive to crack and the email is on your public GitHub anyway, so the practical risk is low. This is the simple choice.
- **Option B — `git filter-repo` rewrite.** Scrubs the files from all of git history. Slightly safer, but rewrites history and invalidates any existing clones (no one has any — this is still private, so that cost is zero).

Recommendation: **Option B** before flipping public. The cost is one rewrite and one force-push. The benefit is your email + hash never lived in a public git history. Worth it.

## Tier 4 — Keep (do not remove)

These look "personal" by name but are project-load-bearing:

| File | Why keep |
|---|---|
| `AGREEMENT.md` | Actual Beekeeper usage disclaimer (HITL, verify outputs, etc.). Useful for users. |
| `SOUL.md`, `.soul.json` | Repo-level Queen Crown Soul / persona data. Used at runtime. |
| `beekeeper/souls/queen.soul.json`, `queen.soul.md` | Package data, listed in `pyproject.toml` under `[tool.setuptools.package-data]`. Removing breaks the install. |
| `architecture/10_status_assessment.md` | Internal but historically useful — references "beehive→beekeeper rename" intentionally. |

## Once you've decided

Reply with one of:

- `tier 1 only` — I'll `git rm` the four Tier-1 files.
- `tier 1 + comparison rm` — same, plus drop `COMPARISON_REPORT.md`.
- `tier 1 + comparison move` — same, plus move `COMPARISON_REPORT.md` → `docs/comparisons.md`.
- `tier 3 option A` — also `git rm` `.beekeeper_store/` and `.queen_core/`, leave history intact.
- `tier 3 option B` — also rewrite git history with `git filter-repo` to scrub the email+hash. (I'll need confirmation again before the force push.)

Or override with your own combination.
