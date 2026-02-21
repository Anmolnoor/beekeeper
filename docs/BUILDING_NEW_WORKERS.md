# Building New Workers

To support dynamic worker creation, you can either **install a plugin package** or **add workers to the core codebase**.

## Option A: Install a Worker Package (`beehive install`)

The fastest way to add workers is to install a package that declares workers via extension points:

```bash
beehive install <package>           # Install from PyPI
beehive install --list              # List installed plugins
beehive install -l ./local-path     # Install to project-local .beehive/workers/
beehive list-workers                # Show built-in + installed workers
```

Packages register workers via `beehive.workers` entry points in `pyproject.toml` or via `beehive.json`. After install, workers are registered in `.honeycomb/workers/plugins.json`.

**See [EXTENSION_POINTS.md](EXTENSION_POINTS.md)** for the full plugin contract, entry point format, and manual plugin config (`.honeycomb/workers/plugins.json`).

---

## Option B: Add Workers to Core Codebase

If you are contributing to Beehive or need full control, follow these steps. The registry defines **when** workers are used (routing rules); the implementations live in code.

## Checklist

### 1. Extend `WorkerKind` (contracts.py)

Add a new enum value:

```python
class WorkerKind(str, Enum):
    web_search = "web_search"
    heavy_compute = "heavy_compute"
    audit = "audit"
    your_worker = "your_worker"  # snake_case, matches registry
```

### 2. Implement the Worker Class (worker.py)

Subclass `BaseSpecialistWorker`:

```python
class YourWorker(BaseSpecialistWorker):
    worker_kind = WorkerKind.your_worker
    output_model = YourOutput  # Pydantic model from contracts.py

    def execute(self, task: TaskEnvelope, context: WorkerContext) -> dict[str, Any]:
        # task.payload contains the task data
        # Return dict that validates against output_model
        return YourOutput(...).model_dump(mode="json")
```

Define `YourOutput` in `beehive/contracts.py` (Pydantic `BaseModel`) if needed.

### 3. Register in WorkerRuntime (worker.py)

Add to `WorkerRuntime.__init__`:

```python
self._workers: dict[WorkerKind, BaseSpecialistWorker] = {
    WorkerKind.web_search: WebSearchWorker(...),
    WorkerKind.heavy_compute: HeavyComputeWorker(),
    WorkerKind.audit: AuditWorker(),
    WorkerKind.your_worker: YourWorker(),  # Add here
}
```

### 4. Add Registry Entry (worker_registry.py)

Add to `DEFAULT_REGISTRY["workers"]`:

```python
{
    "worker_kind": "your_worker",
    "name": "Your Worker",
    "description": "What it does.",
    "capabilities": ["cap1", "cap2"],
    "intent_patterns": ["intent_a", "intent_b"],
    "payload_triggers": ["payload_key_1"],
    "query_keywords": ["keyword1", "keyword2"],
    "priority": 25,
    "fallback_workers": ["web_search"],
},
```

The registry is also writable to `.honeycomb/workers/registry.json`; ensure `worker_kind` matches the `WorkerKind` enum value exactly.

---

## Optional Integrations

### 5. Capability Check (worker.py)

If the worker requires a skill capability (e.g. `"your_capability"`), add in `execute_task_serialized`:

```python
if task.worker_kind == WorkerKind.your_worker and "your_capability" not in effective_capabilities:
    raise ValueError("context_skill_missing_your_capability")
```

### 6. Queen: Blueprint and Skill (queen.py)

**Blueprint:** Add config and branch in `_build_worker_context`:

```python
# QueenConfig
worker_your_blueprint_id: str = "blueprint.worker.your"

# _build_worker_context
if task.worker_kind == WorkerKind.your_worker:
    blueprint_id = self.config.worker_your_blueprint_id
```

**Required skills:** Update `_plan_tasks`:

```python
if worker_kind == WorkerKind.your_worker:
    required_skills = ["your_capability"]
```

**Skill routing:** Update `_route_skill` if the worker uses a custom skill:

```python
if task.worker_kind == WorkerKind.your_worker:
    return "skill.your.worker"
```

### 7. Guardrails (guardrails.py)

If the worker needs payload or budget checks, add a guardrail and wire it in `GuardrailPolicyEngine`:

```python
@dataclass
class YourWorkerGuardrail:
    def evaluate(self, task: TaskEnvelope, rule_profile: RuleProfile) -> tuple[bool, str | None]:
        if task.worker_kind != WorkerKind.your_worker:
            return True, None
        # Your checks
        return True, None
```

### 8. Monitor (monitor.py)

If the worker needs custom quality scoring or rerun/escalation logic:

```python
# In score_quality()
elif task.worker_kind == WorkerKind.your_worker:
    # Adjust score based on result.output
    pass

# In inspect()
elif task.worker_kind == WorkerKind.your_worker:
    # Rerun/escalate logic
    pass
```

### 9. Routing Feedback (queen.py)

`_route_worker_kind` uses routing feedback for `web_search` and `heavy_compute`. To include your worker in feedback-based routing, add it to the sets in that method.

### 10. Honeycomb (honeycomb.py)

`top_worker_kinds()` returns a default list when there is no feedback. Add your worker there if it should appear in analytics:

```python
return [WorkerKind.web_search, WorkerKind.heavy_compute, WorkerKind.audit, WorkerKind.your_worker]
```

---

## Summary of Required Changes

| Step | File | Required? |
|------|------|-----------|
| 1 | contracts.py (WorkerKind) | Yes |
| 2 | worker.py (Worker class) | Yes |
| 3 | worker.py (WorkerRuntime) | Yes |
| 4 | worker_registry.py (registry) | Yes |
| 5 | worker.py (capability check) | If worker needs a capability |
| 6 | queen.py (blueprint, skills) | If worker has a blueprint/skill |
| 7 | guardrails.py | If worker needs guardrails |
| 8 | monitor.py | If worker needs custom scoring/inspection |
| 9 | queen.py (routing feedback) | If worker should use feedback |
| 10 | honeycomb.py | If worker should appear in defaults |

---

## Pluggable Workers vs Core Workers

- **Pluggable workers** (via `beehive install` or `.honeycomb/workers/plugins.json`): Loaded at runtime from installed packages or JSON config. No core code changes. See [EXTENSION_POINTS.md](EXTENSION_POINTS.md).
- **Core workers** (this guide): Require edits to `contracts.py`, `worker.py`, `worker_registry.py`, etc. Use when you need to modify the Queen routing logic, add built-in guardrails, or contribute to the platform.
