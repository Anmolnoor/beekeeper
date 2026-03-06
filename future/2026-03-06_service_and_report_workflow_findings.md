# Service and Report Workflow Findings (2026-03-06)

## Scope
Validated:
- Full service startup and runtime health
- Queen chat request to generate GitHub report for `anmolnoor`
- Request to save report as local Markdown file
- Verification of file persistence

## What worked
- Docker services are running: `redis`, `temporal`, `qdrant`, `searxng`, `celery-worker`, `temporal-worker`, `beekeeper-api`, `queen-api`, `open-webui`.
- Health checks passed:
  - `beekeeper-api`: `GET /healthz` -> ok
  - `queen-api`: `GET /health` -> ok
  - `open-webui`: `GET /health` -> `200`
  - `qdrant`: `GET /healthz` -> passed
  - `temporal`: `temporal operator cluster health` -> `SERVING`
  - `redis`: `redis-cli ping` -> `PONG`
  - `celery-worker`: `celery inspect ping` -> 1 node online

## Issues found

### 1) Report save claim is unreliable / false-positive in chat output
- Symptom:
  - Queen responds with text claiming file saved at `/home/anmol_noor/hive_terminal/github/anmolnoor_github_report.md`.
  - File does not exist on host workspace.
  - File also does not exist in `queen-api` container at expected paths.
- Evidence:
  - Chat completion returned success narrative with fake shell snippet/path.
  - Filesystem checks returned "No such file or directory".
- Impact:
  - User gets misleading confirmation about persistence.

### 2) Running `queen-api` container is on older code than local workspace
- Symptom:
  - Local `beekeeper/queen.py` contains save-to-file post-processing block (`file_saved` / `file_save_error` events).
  - Container `/app/beekeeper/queen.py` is shorter/older and does not include this logic.
- Impact:
  - Chat/API behavior does not match local source/tests; save flow expected in local code is absent in runtime container.
- Likely fix:
  - Rebuild images from current workspace (`beekeeper rebuild --all` or `docker compose build --no-cache` then `up -d`).

### 3) Save-intent parser misses one natural phrasing
- Symptom:
  - Query phrasing: "save ... as an .md file named ..." does not trigger save intent (`_extract_save_to_file_request` returns false).
- Impact:
  - Request may route/behave as normal chat without any save operation.
- Likely fix:
  - Expand regex in `_extract_save_to_file_request` to support `".md file named <name>.md"` phrasing.

### 4) Save-intent parser can include trailing punctuation in filename
- Symptom:
  - For phrasing that matches, parser currently returns `anmolnoor_github_report.md.` (with trailing `.`).
- Impact:
  - Could produce malformed filename, file lookup confusion, or cross-platform issues.
- Likely fix:
  - Normalize captured filename by stripping trailing punctuation like `. , ; : ! ?`.

### 5) SearXNG inside containers is misconfigured
- Symptom:
  - Trace synthesis includes `SearXNG degraded (unavailable); fallback evidence used.`
  - In-container adapter test shows `BEEKEEPER_SEARXNG_BASE_URL=http://localhost:8080` and connection refused.
- Root cause:
  - `localhost` from inside `queen-api`/worker containers points to the container itself, not `searxng` service.
- Impact:
  - Web search worker silently falls back to synthetic evidence instead of live search results.
- Likely fix:
  - Use container-network address in Docker runtime: `BEEKEEPER_SEARXNG_BASE_URL=http://searxng:8080`.
  - Keep host-local value only for non-container local runs.

### 6) Local CLI run path is unstable with current LLM setup
- Symptom:
  - Local `beekeeper run` returned fallback: "could not reach Gemini".
- Impact:
  - Non-container local execution can fail independently from containerized APIs.
- Likely fix:
  - Validate local provider selection and credentials; ensure intended provider precedence for local CLI.

### 7) Celery worker runs as root in container
- Symptom:
  - Startup warning from Celery about superuser privileges.
- Impact:
  - Security hardening gap in production-like deployment.
- Likely fix:
  - Run worker with non-root user in Docker image/compose.

## Priority suggestion
1. Rebuild container images to align runtime with local source.
2. Fix container SearXNG base URL (`searxng:8080`).
3. Fix save-intent parsing edge cases (`.md file named`, trailing punctuation).
4. Add e2e test: chat request requiring save + assert file exists + assert `file_saved` event.
5. Add response guardrail: forbid "saved" confirmation unless file write event succeeded.

