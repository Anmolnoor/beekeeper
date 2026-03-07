# Current State (Baseline)

## Runtime Shape

- Core orchestration: `beekeeper/queen.py`
- CLI entry and command surface: `beekeeper/runner.py`
- API surfaces: `beekeeper_api` and `queen_api`
- Local persistence roots: `.honeycomb/` and `.beekeeper_store/`

## Execution and Scheduling

- Scheduler modes exposed: `inline`, `celery`, `temporal`, `auto`
- Execution can run in-process (inline) or through queue-backed workers
- Worker plugins and generated workers can be loaded dynamically

## Storage Usage (Current)

- Honeycomb is used for trace/audit/event timeline data and developer inspection flows
- Store files under `.beekeeper_store/` maintain tenant and settings data
- Vector retrieval can use Qdrant when configured

## Immediate Baseline Truth

- The platform currently blends control-plane and execution responsibilities in a small number of modules.
- Filesystem paths are still part of the default operator experience.
- Production-path constraints now need to be explicitly enforced by runtime mode and support matrix boundaries.
