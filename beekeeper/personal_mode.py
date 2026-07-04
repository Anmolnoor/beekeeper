from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .runtime_env import normalize_ollama_base_url
from .store import BeekeeperStore
from .tenancy import HoneycombRecord, HiveRecord, OrganizationRecord, QueenInstanceRecord

PERSONAL_PROFILE_SETTING = "personal_mode_profile"
PERSONAL_ORG_NAME = "Personal Beekeeper"
PERSONAL_HIVE_NAME = "Personal Workspace"
PERSONAL_QUEEN_NAME = "Personal Queen"
PERSONAL_OWNER_ID = "local-owner"


def run_personal_setup(
    *,
    store: BeekeeperStore,
    honeycomb_root: Path,
    provider: str | None = None,
    model: str | None = None,
    endpoint: str | None = None,
    api_key_env: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ if env is None else env
    honeycomb_root = Path(honeycomb_root)
    _ensure_local_storage(honeycomb_root)

    existing = _read_profile(store)
    org = _ensure_org(store, existing.get("org_id"))
    hive = _ensure_hive(store, org, existing.get("hive_id"))
    honeycomb = _ensure_honeycomb(store, hive, honeycomb_root, existing.get("honeycomb_id"))
    queen = _ensure_queen(store, hive, existing.get("queen_id"))

    provider_profile = _provider_profile(
        provider=provider,
        model=model,
        endpoint=endpoint,
        api_key_env=api_key_env,
        existing=existing.get("provider") if isinstance(existing.get("provider"), dict) else {},
        env=env,
    )
    profile = {
        "mode": "personal",
        "owner_id": PERSONAL_OWNER_ID,
        "org_id": org.org_id,
        "hive_id": hive.hive_id,
        "honeycomb_id": honeycomb.honeycomb_id,
        "queen_id": queen.queen_id,
        "workspace_name": hive.name,
        "queen_name": queen.name,
        "honeycomb_root": str(honeycomb_root),
        "provider": provider_profile,
    }

    created = not bool(existing)
    updated = existing != profile
    store.write_setting(PERSONAL_PROFILE_SETTING, profile)
    return {"created": created, "updated": updated, "profile": profile}


def build_personal_status(
    *,
    store: BeekeeperStore,
    honeycomb_root: Path | None = None,
    env: Mapping[str, str] | None = None,
    provider_timeout: float = 1.0,
) -> dict[str, Any]:
    env = os.environ if env is None else env
    profile = _read_profile(store)
    root = Path(honeycomb_root or profile.get("honeycomb_root") or ".honeycomb")
    required: dict[str, dict[str, Any]] = {}

    if not profile:
        required["profile"] = {
            "status": "blocked",
            "detail": "Personal profile is missing.",
            "next_step": "run beekeeper setup --personal --provider <name> --model <model>",
        }
        return _status_payload(root, profile, required)

    required["profile"] = {
        "status": "ready",
        "detail": "Personal profile loaded.",
    }
    required["storage"] = _storage_check(root)
    required["provider"] = _provider_check(profile, env, provider_timeout)
    return _status_payload(root, profile, required)


def format_personal_status(status: Mapping[str, Any]) -> str:
    lines = [
        f"Beekeeper Personal: {status.get('overall')}",
        "",
        "Required checks:",
    ]
    for name, check in status.get("required", {}).items():
        lines.append(_format_check(name, check))

    lines.extend(["", "Personal surface:"])
    queen = status.get("queen", {})
    if queen:
        lines.append(f"- workspace: {queen.get('workspace_name') or 'personal workspace'}")
        lines.append(f"- queen: {queen.get('queen_name') or queen.get('queen_id') or 'not set'}")

    provider = status.get("provider", {})
    if provider:
        lines.append(
            f"- provider: {provider.get('name') or 'unconfigured'} "
            f"model={provider.get('model') or 'unconfigured'}"
        )

    workers = status.get("workers", {})
    for name, worker in workers.items():
        lines.append(f"- {name}: {worker.get('label')}")

    approvals = status.get("approvals", {})
    lines.append(f"- approvals: {approvals.get('pending', 0)} pending")

    memory = status.get("memory", {})
    if memory:
        lines.append(f"- memory: {memory.get('status')} at {memory.get('path')}")

    optional = status.get("optional", {})
    if optional:
        lines.extend(["", "Optional for V1:"])
        for name, item in optional.items():
            lines.append(f"- {name}: {item.get('detail')}")

    planned = status.get("planned", {})
    if planned:
        lines.extend(["", "Not connected yet:"])
        for name, item in planned.items():
            lines.append(f"- {name}: {item.get('detail')}")

    return "\n".join(lines) + "\n"


def personal_status_json(status: Mapping[str, Any]) -> str:
    return json.dumps(status, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def _read_profile(store: BeekeeperStore) -> dict[str, Any]:
    profile = store.read_setting(PERSONAL_PROFILE_SETTING, default={})
    return profile if isinstance(profile, dict) else {}


def _ensure_local_storage(honeycomb_root: Path) -> None:
    honeycomb_root.mkdir(parents=True, exist_ok=True)
    for name in ("events", "artifacts", "workers", "memory"):
        (honeycomb_root / name).mkdir(parents=True, exist_ok=True)


def _ensure_org(store: BeekeeperStore, org_id: object) -> OrganizationRecord:
    orgs = store.list_orgs()
    existing = _find_by_id(orgs, "org_id", org_id)
    if existing:
        return existing
    named = next((org for org in orgs if org.name == PERSONAL_ORG_NAME), None)
    return named or store.create_org(PERSONAL_ORG_NAME)


def _ensure_hive(store: BeekeeperStore, org: OrganizationRecord, hive_id: object) -> HiveRecord:
    hives = store.list_hives(org.org_id)
    existing = _find_by_id(hives, "hive_id", hive_id)
    if existing:
        return existing
    named = next((hive for hive in hives if hive.name == PERSONAL_HIVE_NAME), None)
    return named or store.create_hive(org.org_id, PERSONAL_HIVE_NAME)


def _ensure_honeycomb(
    store: BeekeeperStore,
    hive: HiveRecord,
    honeycomb_root: Path,
    honeycomb_id: object,
) -> HoneycombRecord:
    honeycombs = store.list_honeycombs(hive.hive_id)
    existing = _find_by_id(honeycombs, "honeycomb_id", honeycomb_id)
    if existing:
        return existing
    root_text = str(honeycomb_root)
    matching_root = next((comb for comb in honeycombs if comb.root_path == root_text), None)
    return matching_root or store.create_honeycomb(hive.hive_id, "Personal Memory", root_text)


def _ensure_queen(store: BeekeeperStore, hive: HiveRecord, queen_id: object) -> QueenInstanceRecord:
    queens = store.list_queens(hive.hive_id)
    existing = _find_by_id(queens, "queen_id", queen_id)
    if existing:
        return existing
    named = next((queen for queen in queens if queen.name == PERSONAL_QUEEN_NAME), None)
    return named or store.create_queen(hive.hive_id, PERSONAL_QUEEN_NAME, "blueprint.queen.default")


def _find_by_id(items: list[Any], attr: str, expected: object) -> Any | None:
    if not expected:
        return None
    for item in items:
        if getattr(item, attr, None) == expected:
            return item
    return None


def _provider_profile(
    *,
    provider: str | None,
    model: str | None,
    endpoint: str | None,
    api_key_env: str | None,
    existing: Mapping[str, Any],
    env: Mapping[str, str],
) -> dict[str, Any]:
    name = _clean(provider) or _clean(env.get("BEEKEEPER_LLM_PROVIDER")) or _first_provider(env) or _clean(existing.get("name")) or "unconfigured"
    resolved_model = _clean(model) or _model_from_env(name, env) or _clean(existing.get("model")) or ""
    resolved_endpoint = _clean(endpoint) or _endpoint_from_env(name, env) or _clean(existing.get("endpoint"))
    resolved_api_key_env = _clean(api_key_env) or _api_key_env_for_provider(name) or _clean(existing.get("api_key_env"))
    return {
        "role": "coding",
        "name": name,
        "model": resolved_model,
        "endpoint": resolved_endpoint,
        "api_key_env": resolved_api_key_env,
    }


def _clean(value: object) -> str:
    return str(value or "").strip()


def _first_provider(env: Mapping[str, str]) -> str:
    raw = _clean(env.get("BEEKEEPER_LLM_PROVIDERS"))
    if not raw:
        return ""
    return next((item.strip().lower() for item in raw.split(",") if item.strip()), "")


def _model_from_env(provider: str, env: Mapping[str, str]) -> str:
    if provider == "ollama":
        return _clean(env.get("BEEKEEPER_OLLAMA_MODEL"))
    if provider == "gemini":
        return _clean(env.get("BEEKEEPER_GEMINI_MODEL"))
    if provider == "openai":
        return _clean(env.get("BEEKEEPER_OPENAI_MODEL"))
    return ""


def _endpoint_from_env(provider: str, env: Mapping[str, str]) -> str:
    if provider == "ollama":
        return _clean(env.get("BEEKEEPER_OLLAMA_BASE_URL"))
    if provider == "openai":
        return _clean(env.get("BEEKEEPER_OPENAI_BASE_URL"))
    return ""


def _api_key_env_for_provider(provider: str) -> str | None:
    if provider == "gemini":
        return "BEEKEEPER_GEMINI_API_KEY"
    if provider == "openai":
        return "BEEKEEPER_OPENAI_API_KEY"
    return None


def _status_payload(
    honeycomb_root: Path,
    profile: Mapping[str, Any],
    required: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    required_ready = all(check.get("status") == "ready" for check in required.values())
    provider = profile.get("provider") if isinstance(profile.get("provider"), dict) else {}
    return {
        "mode": "personal",
        "overall": "ready" if required_ready else "blocked",
        "honeycomb_root": str(honeycomb_root),
        "required": required,
        "optional": {
            "platform_infra": {
                "status": "optional",
                "detail": "Full platform infrastructure and channel setup are optional for V1 personal mode.",
            }
        },
        "provider": {
            "role": provider.get("role"),
            "name": provider.get("name"),
            "model": provider.get("model"),
            "endpoint": provider.get("endpoint"),
            "api_key_env": provider.get("api_key_env"),
        },
        "queen": {
            "owner_id": profile.get("owner_id"),
            "workspace_name": profile.get("workspace_name"),
            "queen_name": profile.get("queen_name"),
            "hive_id": profile.get("hive_id"),
            "queen_id": profile.get("queen_id"),
        },
        "workers": {
            "coding_worker": {
                "status": "planned",
                "label": "planned/not connected",
                "detail": "The FCLI bridge and executable coding worker are intentionally out of scope for V1.",
            }
        },
        "approvals": {"status": "ready", "pending": 0},
        "memory": {
            "status": "ready" if (honeycomb_root / "memory").is_dir() else "blocked",
            "path": str(honeycomb_root / "memory"),
        },
        "planned": {
            "coding_worker": {
                "status": "planned",
                "detail": "Coding-worker supervision arrives with the V2/V3 contract and bridge.",
            }
        },
    }


def _storage_check(honeycomb_root: Path) -> dict[str, Any]:
    missing = [name for name in ("events", "artifacts", "workers", "memory") if not (honeycomb_root / name).is_dir()]
    if missing:
        return {
            "status": "blocked",
            "detail": f"Missing local storage directories: {', '.join(missing)}.",
            "next_step": "run beekeeper setup --personal",
        }
    return {
        "status": "ready",
        "detail": "Local storage is ready.",
        "path": str(honeycomb_root),
    }


def _provider_check(profile: Mapping[str, Any], env: Mapping[str, str], timeout: float) -> dict[str, Any]:
    provider = profile.get("provider") if isinstance(profile.get("provider"), dict) else {}
    name = _clean(provider.get("name"))
    model = _clean(provider.get("model"))
    endpoint = _clean(provider.get("endpoint"))
    api_key_env = _clean(provider.get("api_key_env"))
    if not name or name == "unconfigured":
        return {
            "status": "blocked",
            "detail": "Provider profile is not configured.",
            "next_step": "run beekeeper setup --personal --provider <name> --model <model>",
        }
    if not model:
        return {
            "status": "blocked",
            "detail": "Provider model is missing.",
            "next_step": "run beekeeper setup --personal --provider <name> --model <model>",
        }
    if api_key_env and not _provider_secret_is_set(api_key_env, env):
        return {
            "status": "blocked",
            "detail": f"Provider credential env var {api_key_env} is not set.",
            "next_step": f"export {api_key_env}=<secret>",
        }
    if name == "mock":
        return {
            "status": "ready",
            "detail": "Mock provider is ready for local V1 verification.",
            "provider": name,
            "model": model,
        }
    if name in {"gemini", "openai"} and not endpoint:
        return {
            "status": "ready",
            "detail": f"{name} provider configuration is present.",
            "provider": name,
            "model": model,
        }
    if not endpoint:
        return {
            "status": "blocked",
            "detail": "Provider endpoint is missing.",
            "next_step": "set --endpoint to the provider base URL",
        }

    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "status": "blocked",
            "detail": "Provider endpoint is not a valid URL.",
            "next_step": "set a valid http or https provider endpoint",
        }
    return _probe_provider_endpoint(name, endpoint, api_key_env, env, timeout)


def _provider_secret_is_set(api_key_env: str, env: Mapping[str, str]) -> bool:
    if env.get(api_key_env):
        return True
    if api_key_env == "BEEKEEPER_OLLAMA_API_KEY" and env.get("OLLAMA_API_KEY"):
        return True
    if api_key_env == "OLLAMA_API_KEY" and env.get("BEEKEEPER_OLLAMA_API_KEY"):
        return True
    return False


def _probe_provider_endpoint(
    provider: str,
    endpoint: str,
    api_key_env: str,
    env: Mapping[str, str],
    timeout: float,
) -> dict[str, Any]:
    target = endpoint.rstrip("/")
    if provider == "ollama":
        target = normalize_ollama_base_url(target).rstrip("/") + "/api/tags"
    headers = {"User-Agent": "beekeeper-personal-doctor/1.0"}
    api_key = env.get(api_key_env, "") if api_key_env else ""
    if not api_key and api_key_env == "BEEKEEPER_OLLAMA_API_KEY":
        api_key = env.get("OLLAMA_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(target, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if 200 <= response.status < 300:
                return {
                    "status": "ready",
                    "detail": "Provider endpoint responded successfully.",
                }
            return {
                "status": "blocked",
                "detail": f"Provider endpoint returned HTTP {response.status}.",
                "next_step": "check provider endpoint and model settings",
            }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "status": "blocked",
            "detail": f"Provider endpoint check failed: {exc.__class__.__name__}.",
            "next_step": "check provider endpoint and credentials",
        }


def _format_check(name: str, check: Mapping[str, Any]) -> str:
    line = f"- {name}: {check.get('status')} - {check.get('detail')}"
    if check.get("next_step"):
        line += f" Next step: {check.get('next_step')}"
    return line
