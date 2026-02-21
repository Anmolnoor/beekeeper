# Extension Points: Pluggable Workers and Guardrails

Beehive supports pluggable workers and guardrails via JSON config and dynamic class loading.

## Package Ecosystem: `beehive install`

Install worker/guardrail packages from PyPI:

```bash
beehive install <package>
beehive install --list   # List installed plugins
```

Packages declare workers/guardrails via:
1. **Entry points** in `pyproject.toml`: `[project.entry-points."beehive.workers"]`, `[project.entry-points."beehive.guardrails"]`
2. **beehive.json** in the package
3. **`[tool.beehive]`** in `pyproject.toml` (Python 3.11+)

After install, workers are registered in `.honeycomb/workers/plugins.json` and optionally in `.honeycomb/workers/registry.json`.

## Worker Plugins (Manual)

Add workers by creating `.honeycomb/workers/plugins.json`:

```json
{
  "workers": [
    {
      "module_path": "my_workers.custom",
      "class_name": "CustomWorker",
      "worker_kind": "custom"
    }
  ]
}
```

- `module_path`: Python module (must be importable)
- `class_name`: Class name in that module
- `worker_kind`: One of `web_search`, `heavy_compute`, `audit`, `monitor`, `logger`, `custom`

Your worker must:
- Subclass `beehive.worker.BaseSpecialistWorker`
- Set `worker_kind` and `output_model` (Pydantic model)
- Implement `execute(task, context) -> dict`

Also add an entry to `.honeycomb/workers/registry.json` so the Queen can route to it.

## Guardrail Plugins

Add guardrails by creating `.honeycomb/guardrails/plugins.json`:

```json
{
  "guardrails": [
    {
      "module_path": "my_guardrails.rate_limit",
      "class_name": "RateLimitGuardrail"
    }
  ]
}
```

Your guardrail must implement `evaluate(task: TaskEnvelope, rule_profile: RuleProfile) -> tuple[bool, str | None]`:
- Return `(True, None)` to allow
- Return `(False, "reason_code")` to block

## Example Worker

```python
# my_workers/custom.py
from beehive.worker import BaseSpecialistWorker
from beehive.contracts import WorkerKind, TaskEnvelope, WorkerContext
from pydantic import BaseModel

class CustomOutput(BaseModel):
    result: str

class CustomWorker(BaseSpecialistWorker):
    worker_kind = WorkerKind.custom
    output_model = CustomOutput

    def execute(self, task: TaskEnvelope, context: WorkerContext) -> dict:
        return {"result": f"Processed: {task.payload}"}
```
