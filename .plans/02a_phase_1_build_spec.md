# Phase 1 Build Spec

This document turns Phase 1 into an implementation-ready build spec for the current repository.

Research basis for the stack choices was checked on 2026-03-08 against the official docs for Python, FastAPI, Pydantic, SQLAlchemy, psycopg, PostgreSQL, OpenTelemetry, OpenAI, and MinIO.

## Fixed Technology Decisions

- Runtime language: Python `3.13`
- API framework: `FastAPI`
- API server: `Uvicorn`
- Settings and request models: `pydantic` v2 + `pydantic-settings`
- Durable state: PostgreSQL `18`
- Database access: `SQLAlchemy` 2.x + `psycopg` 3
- Schema migration tool: `Alembic`
- Artifact store: `MinIO` via the `minio` Python SDK
- LLM provider path: OpenAI primary only, using the Responses API and strict tool schemas
- Tracing and metrics: OpenTelemetry via OTLP exporter
- Worker execution model: local supervisor + subprocess workers claimed from Postgres queue tables
- Test stack: `pytest` + FastAPI test client / `httpx`

## Explicit Non-Goals For Phase 1

- no Redis
- no Celery
- no Temporal
- no Qdrant
- no MCP
- no browser dashboard
- no multi-agent orchestration
- no broad provider matrix as the default path

These may remain in the repository temporarily, but they are not part of the supported Phase 1 execution path.

## Dependency Plan

### Keep

- `fastapi`
- `uvicorn`
- `pydantic`
- `python-dotenv`
- `rich`

### Add Or Make Explicit

- `pydantic-settings`
- `sqlalchemy`
- `alembic`
- `psycopg[binary]`
- `minio`
- `openai`
- `httpx`
- `opentelemetry-api`
- `opentelemetry-sdk`
- `opentelemetry-exporter-otlp`

### Remove From The Phase 1 Critical Path

- `celery`
- `redis`
- `temporalio`
- `qdrant-client`
- `mcp`
- `slack-sdk`
- `croniter`

If some of these remain installed while the refactor is underway, they should still be removed from the default runtime path, default configuration, and Docker composition.

## Service Topology

Phase 1 should standardize on the following runtime topology:

- `queen-api`
  - admits runs
  - exposes run status, approval, and trace inspection endpoints
  - does not execute long-running worker tasks itself
- `supervisor`
  - claims runnable jobs from Postgres using queue-safe row locking
  - spawns worker subprocesses
  - records attempt lifecycle and heartbeats
- `postgres`
  - authoritative state for runs, jobs, approvals, worker attempts, and trace events
- `minio`
  - artifact payload storage
- `otel-collector` optional but recommended
  - receives OTLP traces and metrics from API and supervisor processes

Worker kinds for Phase 1 are subprocess roles, not long-lived dedicated services:

- `bash`
- `filesystem`
- `github`
- `network`

## Docker Compose Target

The current [`docker-compose.yml`](../docker-compose.yml) should eventually be simplified for the supported Phase 1 path.

The supported Compose stack should be:

- `postgres`
- `minio`
- `queen-api`
- `supervisor`
- `otel-collector` optional

The following current services should be treated as out of scope for the Phase 1 default path:

- `redis`
- `temporal`
- `qdrant`
- `searxng`
- `celery-worker`
- `temporal-worker`
- `pulse`
- `beekeeper-api`

## Repository Layout Target

Use the current package seams and tighten them rather than inventing a second architecture.

- `beekeeper/config`
  - `settings.py`
  - runtime profiles, environment parsing, path resolution
- `beekeeper/data_plane`
  - `models.py`
  - `repositories/`
  - `migrations/`
- `beekeeper/runtime`
  - `coordinator.py`
  - `supervisor.py`
  - `dispatcher.py`
  - `approval_service.py`
- `beekeeper/workers`
  - `base.py`
  - `bash_worker.py`
  - `filesystem_worker.py`
  - `github_worker.py`
  - `network_worker.py`
- `beekeeper/artifacts`
  - `minio_store.py`
  - artifact metadata helpers
- `beekeeper/trace`
  - append-only event writer
  - replay reader
- `beekeeper/cli`
  - `run`, `attach`, `status`, `approve`, `trace`
- `queen_api`
  - thin control-plane API only

## Database Schema Target

### `runs`

- `run_id`
- `workspace_path`
- `goal`
- `status`
- `current_step`
- `result_summary`
- `requires_approval`
- `created_at`
- `updated_at`
- `completed_at`

### `jobs`

- `job_id`
- `run_id`
- `job_type`
- `worker_kind`
- `payload_json`
- `status`
- `lease_owner`
- `lease_expires_at`
- `attempt_count`
- `created_at`
- `scheduled_at`
- `started_at`
- `finished_at`

### `worker_attempts`

- `attempt_id`
- `job_id`
- `run_id`
- `worker_kind`
- `status`
- `pid`
- `started_at`
- `heartbeat_at`
- `finished_at`
- `exit_code`
- `error_code`
- `artifact_prefix`

### `approvals`

- `approval_id`
- `run_id`
- `job_id`
- `action_type`
- `risk_level`
- `request_payload_json`
- `status`
- `requested_at`
- `resolved_at`
- `resolved_by`

### `trace_events`

- `event_id`
- `run_id`
- `job_id`
- `attempt_id`
- `parent_event_id`
- `event_type`
- `actor`
- `payload_json`
- `created_at`

### `artifacts`

- `artifact_id`
- `run_id`
- `job_id`
- `attempt_id`
- `bucket`
- `object_key`
- `content_type`
- `size_bytes`
- `sha256`
- `created_at`

## API Surface For Phase 1

Only build the minimum control API:

- `POST /v1/runs`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/trace`
- `GET /v1/runs/{run_id}/artifacts`
- `POST /v1/approvals/{approval_id}/approve`
- `POST /v1/approvals/{approval_id}/reject`

Everything else is Phase 3 or later.

## CLI Surface For Phase 1

- `beekeeper run`
- `beekeeper attach`
- `beekeeper status`
- `beekeeper approve`
- `beekeeper trace`

These commands should talk to the same Phase 1 runtime path, not alternate schedulers or alternate storage backends.

## Milestone Sequence

### Milestone 1: Runtime Spine

- add typed settings and environment profiles
- add SQLAlchemy models and Alembic migrations
- add Postgres connection layer with health checks
- add MinIO artifact adapter
- keep the API thin and remove long-running execution from request handlers

### Milestone 2: Durable Execution

- add `runs`, `jobs`, `worker_attempts`, `approvals`, `trace_events`, and `artifacts` tables
- build the supervisor claim loop
- use Postgres queue-safe row locking for job claiming
- spawn subprocess workers and persist attempt lifecycle state
- emit append-only trace events for queue, worker, and approval transitions

### Milestone 3: Working Worker Set

- implement the `bash`, `filesystem`, `github`, and `network` workers behind one shared contract
- add approval gating for destructive shell and sensitive network or GitHub actions
- persist artifacts to MinIO and metadata to Postgres
- support foreground run submission and background reattach flow
- prove the dependency-maintenance workflow end to end

## Test Plan

- unit tests for settings, repositories, worker contracts, approval policy, and trace writer
- API tests for run creation, status reads, approval flows, and trace reads
- supervisor tests for queue claiming, lease expiry, retry behavior, and worker result persistence
- end-to-end tests covering:
  - a successful local repo run
  - a run that pauses for approval
  - a run that writes artifacts
  - a run that can be reattached after background execution

## Exit Criteria

Phase 1 is complete only when all of the following are true:

- one supported runtime path exists
- the API does not perform long-running work inline
- workers execute as subprocesses outside the control process
- state survives process restart because Postgres is authoritative
- artifacts are in MinIO and trace is append-only
- approval-gated actions stop and resume correctly
- the CLI and API both use the same durable runtime path

## Research References

- Python versions: <https://www.python.org/doc/versions/>
- FastAPI lifespan guidance: <https://fastapi.tiangolo.com/advanced/events/>
- Pydantic settings: <https://docs.pydantic.dev/latest/concepts/pydantic_settings/>
- SQLAlchemy 2 tutorial: <https://docs.sqlalchemy.org/en/20/tutorial/>
- psycopg 3 usage: <https://www.psycopg.org/psycopg3/docs/basic/usage.html>
- PostgreSQL queue-safe locking: <https://www.postgresql.org/docs/current/sql-select.html>
- OpenTelemetry Python: <https://opentelemetry.io/docs/languages/python/>
- OpenAI Responses guide: <https://developers.openai.com/api/docs/guides/migrate-to-responses>
- OpenAI function calling: <https://developers.openai.com/api/docs/guides/function-calling>
- MinIO server: <https://github.com/minio/minio>
- MinIO Python SDK: <https://github.com/minio/minio-py>
