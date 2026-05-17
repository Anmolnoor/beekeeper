# Beekeeper Package Ecosystem

`beekeeper install <package>` installs worker and guardrail packages from PyPI and registers them in your honeycomb.

## Creating an Installable Package

### 1. Entry Points (Recommended)

In your package's `pyproject.toml`:

```toml
[project.entry-points."beekeeper.workers"]
my_worker = "my_package.workers:MyWorker"

[project.entry-points."beekeeper.guardrails"]
my_guardrail = "my_package.guardrails:MyGuardrail"
```

Your worker must subclass `beekeeper.worker.BaseSpecialistWorker` and set `worker_kind` and `output_model`.

### 2. beekeeper.json

Include a `beekeeper.json` file in your package:

```json
{
  "workers": [
    {
      "module_path": "my_package.workers",
      "class_name": "MyWorker",
      "worker_kind": "custom",
      "name": "My Worker",
      "description": "Does something useful"
    }
  ],
  "guardrails": [
    {
      "module_path": "my_package.guardrails",
      "class_name": "MyGuardrail"
    }
  ]
}
```

### 3. [tool.beekeeper] in pyproject.toml (Python 3.11+)

```toml
[tool.beekeeper]
workers = [
  { module_path = "my_package.workers", class_name = "MyWorker", worker_kind = "custom" }
]
guardrails = [
  { module_path = "my_package.guardrails", class_name = "MyGuardrail" }
]
```

## CLI Commands

- `beekeeper install <package>` — Install and register
- `beekeeper install --list` — List installed plugins
- `beekeeper install --no-registry` — Install without adding to worker registry
- `beekeeper install -e ./local-path` — Install from local path (editable)

## Registry

Workers are added to `.honeycomb/workers/registry.json` so the Queen can route to them. Use `--no-registry` if you want to manage routing manually.
