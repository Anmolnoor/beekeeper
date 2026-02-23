# Beekeeper Agent Platform — Architecture Index

This folder documents the full architecture of the **Beekeeper Agent Platform**, a production-grade multi-agent system built in Python.

## Documents

| File | Description |
|------|-------------|
| [01_overview.md](./01_overview.md) | High-level system overview and design philosophy |
| [02_system_diagram.md](./02_system_diagram.md) | Mermaid diagrams: component map, request lifecycle, data flows |
| [03_core_modules.md](./03_core_modules.md) | Deep-dive into every Python module in `beekeeper/` |
| [04_apis.md](./04_apis.md) | REST APIs: Beekeeper API and Queen API |
| [05_data_layer.md](./05_data_layer.md) | Storage, data models, and persistence |
| [06_infrastructure.md](./06_infrastructure.md) | Docker services, scheduler backends, LLM providers |
| [07_extension_guide.md](./07_extension_guide.md) | How to extend: custom workers, guardrails, skills, LLM providers |
| [08_env_reference.md](./08_env_reference.md) | All environment variables and configuration reference |
| [09_docker_webui_guide.md](./09_docker_webui_guide.md) | **Start here to chat** — Docker Compose + Open WebUI + Queen API step-by-step guide |

## Quick Orientation

```
beekeeper/          ← Core agent runtime (Queen, Workers, Honeycomb, etc.)
beekeeper_api/    ← REST API for tenant/hive/channel management (FastAPI)
queen_api/        ← OpenAI-compatible API adapter for Queen agent (FastAPI)
docs/             ← Operational docs (onboarding, channels, decision tree)
tests/            ← Pytest test suite (regression, integration)
scripts/          ← Load test and utility scripts
architecture/     ← THIS FOLDER: full architecture documentation
```
