from __future__ import annotations

import argparse
import json
import os
import select
import shlex
import shutil
import socket
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown as RichMarkdown

_console = Console()

def _project_root_for_env() -> Path | None:
    """Find project root (dir with .env or pyproject.toml) by walking up from cwd or package root."""
    candidates: list[Path] = []
    # From package root (works for editable install)
    pkg_root = Path(__file__).resolve().parent.parent
    candidates.append(pkg_root)
    # Walk up from cwd (works when running from subdir or non-editable install)
    cwd = Path.cwd()
    for _ in range(20):
        if (cwd / ".env").exists() or (cwd / "pyproject.toml").exists():
            candidates.append(cwd)
            break
        parent = cwd.parent
        if parent == cwd:
            break
        cwd = parent
    for d in candidates:
        env_path = d / ".env"
        if env_path.exists():
            return d
    return None


def _load_env_early() -> None:
    """Load .env from project root before any other config reads."""
    try:
        from dotenv import load_dotenv
        root = _project_root_for_env()
        if root is not None:
            load_dotenv(root / ".env")
        # Also load from cwd so local overrides work (e.g. running from project subdir)
        cwd_env = Path.cwd() / ".env"
        if cwd_env.exists():
            load_dotenv(cwd_env, override=True)
        if root is None and not cwd_env.exists():
            load_dotenv()
    except ImportError:
        pass

from .honeycomb import HoneycombConfig, HoneycombStore
from .ops import compute_ops_metrics, send_alert_webhook
from .package_installer import install_package, list_installed_plugins, uninstall_plugin
from .worker_registry import WorkerRegistry
from .trace_compaction import compact_traces
from .pulse import PulseConfig, run_pulse_loop
from .queen import QueenAgent, QueenConfig
from .store import BeekeeperStore


def _build_config(
    args: argparse.Namespace,
    *,
    scheduler_override: str | None = None,
) -> QueenConfig:
    scheduler = scheduler_override if scheduler_override is not None else getattr(args, "scheduler", "inline")
    cfg = QueenConfig(
        honeycomb_root=Path(args.honeycomb_root),
        max_reruns=args.max_reruns,
        scheduler_backend=scheduler,
        celery_broker_url=os.getenv("BEEKEEPER_CELERY_BROKER_URL", "redis://localhost:6379/0"),
        celery_backend_url=os.getenv("BEEKEEPER_CELERY_BACKEND_URL", "redis://localhost:6379/1"),
        temporal_endpoint=os.getenv("BEEKEEPER_TEMPORAL_ENDPOINT", "localhost:7233"),
        temporal_namespace=os.getenv("BEEKEEPER_TEMPORAL_NAMESPACE", "default"),
        temporal_task_queue=os.getenv("BEEKEEPER_TEMPORAL_TASK_QUEUE", "beekeeper-queue"),
        vector_backend=args.vector,
        vector_url=os.getenv("BEEKEEPER_VECTOR_URL", "http://localhost:6333"),
        vector_collection=os.getenv("BEEKEEPER_VECTOR_COLLECTION", "honeycomb_memory"),
        llm_provider=os.getenv("BEEKEEPER_LLM_PROVIDER", "ollama"),
        ollama_base_url=os.getenv("BEEKEEPER_OLLAMA_BASE_URL", "http://100.99.106.59:11434"),
        ollama_model=os.getenv("BEEKEEPER_OLLAMA_MODEL", "catsarethebest/qwen2.5-N2:1.5b"),
        ollama_timeout_seconds=int(os.getenv("BEEKEEPER_OLLAMA_TIMEOUT_SECONDS", "120")),
        gemini_api_key=os.getenv("BEEKEEPER_GEMINI_API_KEY", ""),
        gemini_model=os.getenv("BEEKEEPER_GEMINI_MODEL", "gemini-1.5-flash"),
        gemini_timeout_seconds=int(os.getenv("BEEKEEPER_GEMINI_TIMEOUT_SECONDS", "120")),
        searxng_base_url=os.getenv("BEEKEEPER_SEARXNG_BASE_URL", "http://localhost:8080"),
    )
    return cfg


def _parse_payload(payload_text: str | None, query: str | None) -> dict[str, Any]:
    if payload_text:
        return json.loads(payload_text)
    if query:
        return {"query": query}
    return {}


def _extract_primary_response(run_output: dict[str, Any]) -> dict[str, Any]:
    results = run_output.get("results", [])
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict):
            return first
    return {}


def _run_chat_loop(args: argparse.Namespace) -> int:
    import getpass
    current_scheduler = getattr(args, "scheduler", "inline")
    model_override: str | None = None
    cfg = _build_config(args, scheduler_override=current_scheduler)
    queen = QueenAgent(cfg)
    current_intent = args.intent
    honeycomb_root = Path(args.honeycomb_root)
    honeycomb_store = HoneycombStore(HoneycombConfig(root_dir=honeycomb_root))
    verbose = getattr(args, "verbose", False)

    # User ID and memory store
    user_id = getattr(args, "user_id", None) or os.getenv("BEEKEEPER_USER_ID", "") or getpass.getuser()
    store_root = Path(os.getenv("BEEKEEPER_STORE_ROOT", ".beekeeper_store"))
    try:
        _mem_store: BeekeeperStore | None = BeekeeperStore(store_root)
    except Exception:
        _mem_store = None

    _pending_spawns: set[str] = set()

    print("Beekeeper Queen chat")
    print(f"User: {user_id}  |  Commands: /help, /intent, /model, /scheduler, /tree, /trace, /exit")
    while True:
        # Notify about completed background spawns
        if _pending_spawns:
            try:
                registry = WorkerRegistry(honeycomb_root)
                current_kinds = {w.get("worker_kind", "") for w in registry.list_workers()}
                completed = _pending_spawns & current_kinds
                for wk in completed:
                    print(f"\n  ✓ Worker '{wk}' is ready — it will handle similar tasks from now on.")
                _pending_spawns -= completed
            except Exception:
                pass

        print()  # blank line before prompt for readability
        try:
            raw = input("you> ").strip()
        except EOFError:
            print("\nbye")
            return 0
        except KeyboardInterrupt:
            print("\nbye")
            return 0
        if not raw:
            continue
        if raw in {"/exit", "/quit"}:
            print("bye")
            return 0
        if raw == "/help":
            print("Commands:")
            print("  /intent <name>      set the active Queen intent")
            print("  /model [name]       set or show LLM model override")
            print("  /scheduler [be]     set scheduler (auto|inline|celery|temporal)")
            print("  /tree [trace_id]    show trace tree")
            print("  /trace [trace_id]   show trace events and details")
            print("  /exit               leave chat")
            print("  Start chat with --quiet to suppress step-by-step progress.")
            print("  Start chat with --verbose to show worker kind and confidence.")
            print("Input mode:")
            print("  plain text       -> sent as payload {'query': <text>}")
            print("  JSON object      -> sent as raw payload")
            continue
        if raw.startswith("/intent "):
            next_intent = raw.replace("/intent ", "", 1).strip()
            if not next_intent:
                print("queen> intent cannot be empty")
                continue
            current_intent = next_intent
            print(f"queen> active intent set to '{current_intent}'")
            continue
        if raw.startswith("/model"):
            rest = raw.replace("/model", "", 1).strip()
            if rest:
                model_override = rest
                print(f"queen> model override set to '{model_override}'")
            else:
                print(f"queen> model override: {model_override or '(none)'}")
            continue
        if raw.startswith("/scheduler"):
            rest = raw.replace("/scheduler", "", 1).strip()
            if rest and rest in ("auto", "inline", "celery", "temporal"):
                current_scheduler = rest
                cfg = _build_config(args, scheduler_override=current_scheduler)
                queen = QueenAgent(cfg)
                print(f"queen> scheduler set to '{current_scheduler}'")
            elif rest:
                print("queen> scheduler must be auto, inline, celery, or temporal")
            else:
                print(f"queen> scheduler: {current_scheduler}")
            continue
        if raw.startswith("/tree"):
            rest = raw.replace("/tree", "", 1).strip()
            trace_id = rest
            if not trace_id:
                traces = honeycomb_store.list_traces(limit=1)
                trace_id = traces[0] if traces else ""
            if not trace_id:
                print("queen> no trace_id and no recent traces")
                continue
            try:
                tree = honeycomb_store.get_trace_tree(trace_id)
                print(json.dumps(tree, ensure_ascii=True, indent=2))
            except Exception as exc:
                print(f"queen> tree failed: {exc}")
            continue
        if raw.startswith("/trace"):
            rest = raw.replace("/trace", "", 1).strip()
            trace_id = rest
            if not trace_id:
                traces = honeycomb_store.list_traces(limit=1)
                trace_id = traces[0] if traces else ""
            if not trace_id:
                print("queen> no trace_id and no recent traces")
                continue
            try:
                events = honeycomb_store.read_events(trace_id)
                gov_path = honeycomb_store.governance_dir / f"{trace_id}.jsonl"
                gov_events = honeycomb_store._read_jsonl(gov_path) if gov_path.exists() else []
                out = {"trace_id": trace_id, "events": events, "governance": gov_events}
                print(json.dumps(out, ensure_ascii=True, indent=2))
            except Exception as exc:
                print(f"queen> trace failed: {exc}")
            continue

        payload: dict[str, Any]
        if raw.startswith("{") and raw.endswith("}"):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"queen> invalid JSON payload: {exc}")
                continue
            if not isinstance(parsed, dict):
                print("queen> JSON payload must be an object")
                continue
            payload = parsed
        else:
            payload = {"query": raw}
        if model_override:
            payload["model_override"] = model_override

        # Attach user identity and memories
        payload["user_id"] = user_id
        if _mem_store is not None:
            try:
                user_memories = [
                    {"content": m["content"]}
                    for m in _mem_store.search_user_memories(user_id, query=raw, limit=12)
                ]
                if user_memories:
                    payload["user_memories"] = user_memories
            except Exception:
                pass

        def _on_status(msg: str) -> None:
            print(f"  → {msg}", flush=True, file=sys.stderr)

        try:
            output = queen.run(
                intent=current_intent,
                payload=payload,
                source="cli",
                status_callback=None if getattr(args, "quiet", False) else _on_status,
            )
        except Exception as exc:
            print(f"queen> request failed: {exc}")
            continue
        primary = _extract_primary_response(output)
        worker_kind = primary.get("worker_kind", "unknown")
        confidence = primary.get("confidence", 0.0)
        response = primary.get("output", {})

        # Check trace for auto-spawn events
        trace_id = output.get("trace_id", "")
        if trace_id:
            try:
                trace_events = honeycomb_store.read_events(trace_id)
                spawn_events = [e for e in trace_events if e.get("kind") == "auto_spawn_started"]
                for ev in spawn_events:
                    wk = ev.get("worker_kind", "custom")
                    print(f"\n  ⚡ New task type detected — building a custom worker ({wk}) in the background.")
                    print(f"     This request was handled immediately. Future requests of this type will be faster.")
                    _pending_spawns.add(wk)
            except Exception:
                pass

        # Display reply
        if isinstance(response, dict) and isinstance(response.get("assistant_reply"), str):
            reply_text = response["assistant_reply"]
            prefix = f"queen[{worker_kind}|conf={confidence:.2f}]" if verbose else "queen"
            _console.print(f"[bold green]{prefix}>[/bold green]")
            _console.print(RichMarkdown(reply_text))
            if verbose:
                _console.print(f"[dim](source: {response.get('response_source', 'unknown')})[/dim]")
        else:
            reply_text = ""
            raw_json = json.dumps(response, ensure_ascii=True)
            prefix = f"queen[{worker_kind}|conf={confidence:.2f}]" if verbose else "queen"
            _console.print(f"[bold green]{prefix}>[/bold green] {raw_json}")

        # Background context curation
        def _curate(text: str = raw, reply: str = reply_text, uid: str = user_id) -> None:
            try:
                queen.run(
                    intent="context_curation",
                    payload={
                        "user_msg": text[:1200],
                        "assistant_reply": reply[:3000],
                        "user_id": uid,
                        "delegate_to_worker": True,
                    },
                    source="cli:context_curator",
                )
            except Exception:
                pass
        threading.Thread(target=_curate, daemon=True).start()


@dataclass
class DoctorCheck:
    name: str
    ok: bool
    details: str


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _compose_file() -> Path:
    return _project_root() / "docker-compose.yml"


def _detect_compose_command() -> list[str] | None:
    docker = shutil.which("docker")
    if docker:
        result = subprocess.run([docker, "compose", "version"], capture_output=True, text=True)
        if result.returncode == 0:
            return [docker, "compose"]
    docker_compose = shutil.which("docker-compose")
    if docker_compose:
        result = subprocess.run([docker_compose, "version"], capture_output=True, text=True)
        if result.returncode == 0:
            return [docker_compose]
    return None


def _docker_daemon_is_reachable(docker_binary: str = "docker") -> bool:
    result = subprocess.run([docker_binary, "info"], capture_output=True, text=True)
    return result.returncode == 0


def _run_compose(args: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    compose_cmd = _detect_compose_command()
    compose_file = _compose_file()
    if not compose_cmd:
        raise RuntimeError("Docker Compose is not installed.")
    if not compose_file.exists():
        raise RuntimeError(f"Missing compose file: {compose_file}")
    cmd = compose_cmd + ["-f", str(compose_file)] + args
    return subprocess.run(cmd, capture_output=capture_output, text=True)


def _ensure_required_services_running(include_workers: bool = False) -> int:
    compose_cmd = _detect_compose_command()
    if not compose_cmd:
        print("[FAIL] docker: Docker Compose not found.")
        print("Install Docker Desktop (or docker + compose plugin), then rerun.")
        return 1

    docker_binary = compose_cmd[0]
    if Path(docker_binary).name == "docker-compose":
        docker_binary = shutil.which("docker") or "docker"

    if not _docker_daemon_is_reachable(docker_binary=docker_binary):
        print("[FAIL] docker: Docker daemon is not running.")
        print("Start Docker Desktop, then rerun `beekeeper`.")
        return 1

    services = ["redis", "temporal", "qdrant", "searxng"]
    if include_workers:
        services.extend(["celery-worker", "temporal-worker"])
    print(f"[INFO] starting services: {', '.join(services)}")
    try:
        result = _run_compose(["up", "-d", *services], capture_output=True)
    except RuntimeError as exc:
        print(f"[FAIL] compose: {exc}")
        return 1
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        print("[FAIL] compose: could not start services.")
        if stderr:
            print(stderr)
        return 1
    print("[OK] compose: required services are running")
    return 0


def _parse_host_port_from_url(url: str, default_port: int) -> tuple[str, int]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or default_port
    return host, port


def _check_tcp(name: str, host: str, port: int, timeout: float = 2.0) -> DoctorCheck:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return DoctorCheck(name=name, ok=True, details=f"reachable {host}:{port}")
    except Exception as exc:
        return DoctorCheck(name=name, ok=False, details=f"unreachable {host}:{port} ({exc})")


def _check_http(
    name: str,
    url: str,
    timeout: float = 3.0,
    tolerated_error_codes: tuple[int, ...] = (),
) -> DoctorCheck:
    req = urllib.request.Request(
        url=url,
        method="GET",
        headers={
            "User-Agent": "beekeeper-doctor/1.0",
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", 200)
            if 200 <= code < 300:
                return DoctorCheck(name=name, ok=True, details=f"http {code} {url}")
            return DoctorCheck(name=name, ok=False, details=f"http {code} {url}")
    except urllib.error.HTTPError as exc:
        if exc.code in tolerated_error_codes:
            return DoctorCheck(name=name, ok=True, details=f"http {exc.code} {url} (reachable)")
        return DoctorCheck(name=name, ok=False, details=f"http {exc.code} {url}")
    except urllib.error.URLError as exc:
        return DoctorCheck(name=name, ok=False, details=f"error {url} ({exc})")


def _check_llm_provider_env() -> DoctorCheck:
    """Verify LLM provider(s) have required env vars. Considers BEEKEEPER_LLM_PROVIDERS and BEEKEEPER_LLM_PROVIDER."""
    providers_str = (os.getenv("BEEKEEPER_LLM_PROVIDERS") or "").strip()
    if not providers_str:
        providers_str = (os.getenv("BEEKEEPER_LLM_PROVIDER") or "ollama").strip()
    provider_names = [p.strip().lower() for p in providers_str.split(",") if p.strip()]
    if not provider_names:
        provider_names = ["ollama"]

    missing: list[str] = []
    warn_unused: list[str] = []
    for name in provider_names:
        if name == "gemini":
            key = (os.getenv("BEEKEEPER_GEMINI_API_KEY") or "").strip()
            if not key:
                missing.append("BEEKEEPER_GEMINI_API_KEY (required when gemini in providers)")
            else:
                pass  # ok
        elif name == "openai":
            key = (os.getenv("BEEKEEPER_OPENAI_API_KEY") or "").strip()
            if not key:
                missing.append("BEEKEEPER_OPENAI_API_KEY (required when openai in providers)")
            else:
                pass  # ok
        elif name == "ollama":
            pass  # no key required
        else:
            missing.append(f"unknown provider '{name}'")

    gemini_key = (os.getenv("BEEKEEPER_GEMINI_API_KEY") or "").strip()
    if gemini_key and "gemini" not in provider_names:
        warn_unused.append("BEEKEEPER_GEMINI_API_KEY set but gemini not in providers")
    openai_key = (os.getenv("BEEKEEPER_OPENAI_API_KEY") or "").strip()
    if openai_key and "openai" not in provider_names:
        warn_unused.append("BEEKEEPER_OPENAI_API_KEY set but openai not in providers")

    if missing:
        return DoctorCheck(
            name="llm_provider",
            ok=False,
            details="; ".join(missing),
        )
    details = f"{','.join(provider_names)} configured"
    if warn_unused:
        details += f" (warn: {'; '.join(warn_unused)})"
    return DoctorCheck(name="llm_provider", ok=True, details=details)


def _check_audit_signing_key() -> DoctorCheck:
    """Flag risky prod setting: missing or default audit signing key."""
    key = (os.getenv("BEEKEEPER_AUDIT_SIGNING_KEY") or "").strip()
    if not key:
        return DoctorCheck(
            name="audit_signing",
            ok=False,
            details="BEEKEEPER_AUDIT_SIGNING_KEY not set; audit logs unsigned (risky for production)",
        )
    if "dev" in key.lower() or key == "beekeeper-dev-signing-key":
        return DoctorCheck(
            name="audit_signing",
            ok=True,
            details="audit signing key set (dev default; consider changing for production)",
        )
    return DoctorCheck(name="audit_signing", ok=True, details="audit signing key set")


def _check_risky_settings() -> DoctorCheck:
    """Summarize risky settings (dev defaults that should change for production)."""
    risks: list[str] = []
    key = (os.getenv("BEEKEEPER_AUDIT_SIGNING_KEY") or "").strip()
    if key and ("dev" in key.lower() or key == "beekeeper-dev-signing-key"):
        risks.append("BEEKEEPER_AUDIT_SIGNING_KEY uses dev default")
    if not risks:
        return DoctorCheck(name="risky_settings", ok=True, details="no risky dev defaults detected")
    return DoctorCheck(
        name="risky_settings",
        ok=True,
        details="; ".join(risks) + " (consider changing for production)",
    )


def _check_celery_broker() -> DoctorCheck:
    """Optional: verify Celery can connect to broker (same as redis check for default)."""
    broker_url = os.getenv("BEEKEEPER_CELERY_BROKER_URL", "redis://localhost:6379/0")
    redis_host, redis_port = _parse_host_port_from_url(broker_url, default_port=6379)
    return _check_tcp("celery_broker", redis_host, redis_port)


_CHANNEL_REQUIRED_FIELDS: dict[str, list[str]] = {
    "whatsapp": ["whatsapp_access_token", "whatsapp_phone_number_id"],
    "slack": ["slack_bot_token"],
    "telegram": ["telegram_bot_token"],
    "discord": ["discord_bot_token"],
}


def _validate_channel_config(channel: str, config: dict[str, Any]) -> list[str]:
    """Return list of missing required field names for this channel config."""
    required = _CHANNEL_REQUIRED_FIELDS.get(channel, [])
    missing = [f for f in required if not (config.get(f) or "").strip()]
    return missing


def _check_channel_configs() -> DoctorCheck:
    """Validate channel configs: verify store is reachable, list channels, and validate required fields."""
    try:
        store = _get_beekeeper_store()
        configs = store.list_channel_configs()
        channel_names = [c.get("channel", "?") for c in configs]
        invalid: list[str] = []
        for c in configs:
            ch = c.get("channel", "")
            if not ch:
                continue
            decrypted = store.get_channel_config_decrypted(ch) or {}
            missing = _validate_channel_config(ch, decrypted)
            if missing:
                invalid.append(f"{ch}(missing: {','.join(missing)})")
        if invalid:
            return DoctorCheck(
                name="channels",
                ok=False,
                details=f"channel(s) with invalid config: {'; '.join(invalid)}",
            )
        if channel_names:
            return DoctorCheck(
                name="channels",
                ok=True,
                details=f"{len(configs)} channel(s): {', '.join(channel_names)}",
            )
        return DoctorCheck(name="channels", ok=True, details="no channels configured (optional)")
    except Exception as exc:
        return DoctorCheck(name="channels", ok=False, details=f"store error: {exc}")


def _collect_doctor_checks() -> list[DoctorCheck]:
    broker_url = os.getenv("BEEKEEPER_CELERY_BROKER_URL", "redis://localhost:6379/0")
    temporal_endpoint = os.getenv("BEEKEEPER_TEMPORAL_ENDPOINT", "localhost:7233")
    vector_url = os.getenv("BEEKEEPER_VECTOR_URL", "http://localhost:6333")
    ollama_url = os.getenv("BEEKEEPER_OLLAMA_BASE_URL", "http://100.99.106.59:11434")
    searxng_url = os.getenv("BEEKEEPER_SEARXNG_BASE_URL", "http://localhost:8080")

    redis_host, redis_port = _parse_host_port_from_url(broker_url, default_port=6379)
    if ":" in temporal_endpoint:
        temporal_host, temporal_port_text = temporal_endpoint.rsplit(":", 1)
        temporal_port = int(temporal_port_text)
    else:
        temporal_host, temporal_port = temporal_endpoint, 7233

    checks = [
        _check_tcp("redis", redis_host, redis_port),
        _check_tcp("temporal", temporal_host, temporal_port),
        _check_http("qdrant", vector_url.rstrip("/") + "/readyz"),
        _check_http("ollama", ollama_url.rstrip("/") + "/api/tags"),
        _check_http("searxng", searxng_url.rstrip("/") + "/", tolerated_error_codes=(403,)),
        _check_llm_provider_env(),
        _check_audit_signing_key(),
        _check_risky_settings(),
        _check_celery_broker(),
        _check_channel_configs(),
    ]
    return checks


def _print_doctor_checks(checks: list[DoctorCheck]) -> None:
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        print(f"[{status}] {check.name}: {check.details}")


def _doctor_checks_to_json(checks: list[DoctorCheck]) -> dict[str, Any]:
    """Serialize doctor checks for --json output."""
    return {
        "checks": [{"name": c.name, "ok": c.ok, "details": c.details} for c in checks],
        "passed": sum(1 for c in checks if c.ok),
        "failed": sum(1 for c in checks if not c.ok),
        "all_passed": all(c.ok for c in checks),
    }


def _run_doctor(auto_start: bool = False, json_output: bool = False) -> int:
    checks = _collect_doctor_checks()
    failed = [check for check in checks if not check.ok]

    if json_output:
        payload = _doctor_checks_to_json(checks)
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 0 if not failed else 1

    _print_doctor_checks(checks)
    if not failed:
        print(f"doctor summary: all {len(checks)} checks passed")
        return 0

    if auto_start:
        print(f"doctor summary: {len(failed)} failed, {len(checks) - len(failed)} passed")
        print("[INFO] trying Docker startup for required services...")
        if _ensure_required_services_running(include_workers=False) != 0:
            return 1
        checks = _collect_doctor_checks()
        _print_doctor_checks(checks)
        failed = [check for check in checks if not check.ok]

    if failed:
        print(f"doctor summary: {len(failed)} failed, {len(checks) - len(failed)} passed")
        return 1
    print(f"doctor summary: all {len(checks)} checks passed")
    return 0


def _update_env_key(project_root: Path, key: str, value: str) -> None:
    """Update or append KEY=value in .env file."""
    env_path = project_root / ".env"
    if not env_path.exists():
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    new_line = f"{key}={value}"
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}=") or (line.strip().startswith(f"{key}=")):
            lines[i] = new_line
            updated = True
            break
    if not updated:
        lines.append(new_line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ensure_env_file(project_root: Path, non_interactive: bool) -> bool:
    """Copy .env.example to .env if .env does not exist. Returns True if .env exists or was created."""
    env_path = project_root / ".env"
    example_path = project_root / ".env.example"
    if env_path.exists():
        return True
    if not example_path.exists():
        return False
    shutil.copy2(example_path, env_path)
    print(f"[OK] Created .env from .env.example. Edit {env_path} to add API keys (BEEKEEPER_GEMINI_API_KEY, BEEKEEPER_OPENAI_API_KEY, etc.).")
    if not non_interactive:
        input("Press Enter to continue...")
    return True


def _run_quickstart(non_interactive: bool = False) -> int:
    """Short 5-minute path: .env, doctor, init-tenant with defaults."""
    print("Beehive Quickstart")
    print("=" * 40)
    project_root = _project_root()
    _ensure_env_file(project_root, non_interactive=True)
    _load_env_early()
    print("\nStep 1: Checking runtime health...")
    exit_code = _run_doctor(auto_start=not non_interactive, json_output=False)
    if exit_code != 0 and non_interactive:
        print("[WARN] Some health checks failed. Continuing with quickstart.")
    elif exit_code != 0:
        print("\n[FAIL] Fix the issues above and run `beekeeper quickstart` again.")
        return 1
    else:
        print("[OK] Health checks passed.\n")

    store = _get_beekeeper_store()
    orgs = store.list_orgs()
    if orgs:
        print("[OK] Tenant already initialized.")
    else:
        print("Step 2: Initializing tenant...")
        org = store.create_org("Default Organization")
        hive = store.create_hive(org.org_id, "Main Hive")
        comb = store.create_honeycomb(hive.hive_id, "Main Hive-comb", ".honeycomb")
        store.create_queen(hive.hive_id, "Main Queen", "blueprint.queen.default")
        print(json.dumps({
            "org": org.model_dump(mode="json"),
            "hive": hive.model_dump(mode="json"),
            "honeycomb": comb.model_dump(mode="json"),
        }, ensure_ascii=True, indent=2))
        print("[OK] Tenant initialized.\n")

    print("Quickstart complete. Run `beekeeper chat` to start, or `beekeeper run --query \"hello\"` to try.")
    return 0


def _run_setup_wizard(non_interactive: bool = False) -> int:
    """Interactive first-time setup: .env copy, doctor, init-tenant, LLM provider, optional channels, admin."""
    print("Beehive Setup Wizard")
    print("=" * 40)
    project_root = _project_root()
    _ensure_env_file(project_root, non_interactive)
    _load_env_early()
    print("\nStep 1: Checking runtime health...")
    exit_code = _run_doctor(auto_start=True, json_output=False)
    if exit_code != 0:
        print("\n[FAIL] Some health checks failed. Fix the issues above and run `beekeeper setup` again.")
        return 1
    print("\n[OK] All health checks passed.\n")

    store = _get_beekeeper_store()
    orgs = store.list_orgs()
    if orgs and non_interactive:
        print("Org/hive already initialized. Use `beekeeper onboard` to add a Queen to an existing hive.")
        return 0

    if orgs:
        print("Existing org(s) found. You can:")
        print("  - Run `beekeeper onboard` to add a Queen to an existing hive")
        print("  - Run `beekeeper init-tenant --org X --hive Y` to create another org/hive")
        return 0

    if non_interactive:
        org_name = "Default Organization"
        hive_name = "Main Hive"
        honeycomb_root = ".honeycomb"
        llm_provider = "ollama"
    else:
        print("Step 2: First-time tenant setup")
        org_name = input("Organization name [Default Organization]: ").strip() or "Default Organization"
        hive_name = input("Hive name [Main Hive]: ").strip() or "Main Hive"
        honeycomb_root = input("Honeycomb root path [.honeycomb]: ").strip() or ".honeycomb"
        print("LLM provider: ollama (local), gemini, openai, or comma-separated for fallback (e.g. ollama,gemini)")
        llm_choice = input("LLM provider(s) [ollama]: ").strip().lower() or "ollama"
        llm_provider = llm_choice
        _update_env_key(project_root, "BEEKEEPER_LLM_PROVIDERS", llm_provider)
        if "gemini" in llm_provider or "openai" in llm_provider:
            print("  Ensure BEEKEEPER_GEMINI_API_KEY and/or BEEKEEPER_OPENAI_API_KEY are set in .env")
        channel_choice = input("Configure channels now? [y/N]: ").strip().lower()
        if channel_choice in ("y", "yes"):
            print("  Run `beekeeper channels set <channel> <json>` after setup. See .env.example for WhatsApp/Slack vars.")

    org = store.create_org(org_name)
    hive = store.create_hive(org.org_id, hive_name)
    comb = store.create_honeycomb(hive.hive_id, f"{hive_name}-comb", honeycomb_root)
    store.create_queen(hive.hive_id, "Main Queen", "blueprint.queen.default")

    print("\n[OK] Tenant initialized:")
    print(json.dumps({
        "org": org.model_dump(mode="json"),
        "hive": hive.model_dump(mode="json"),
        "honeycomb": comb.model_dump(mode="json"),
    }, ensure_ascii=True, indent=2))

    if not non_interactive:
        create_admin = input("\nCreate admin user? [y/N]: ").strip().lower()
        if create_admin in ("y", "yes"):
            try:
                from beekeeper_api.auth import hash_password
            except ImportError:
                hash_password = None
            if hash_password:
                email = input("Admin email: ").strip()
                password = input("Admin password: ").strip()
                if email and password:
                    existing = store.get_user_by_email(email)
                    if existing:
                        print("[WARN] Email already registered. Skipping admin creation.")
                    else:
                        user = store.create_user(email, hash_password(password))
                        store.assign_org_role(user.user_id, org.org_id, "admin")
                        print(f"[OK] Admin user created: {email}")
                else:
                    print("[WARN] Email/password empty. Skipping admin creation.")
            else:
                print("[WARN] beekeeper_api not installed. Skipping admin creation.")

    print("\nSetup complete. Run `beekeeper run --query \"your question\"` to try the Queen.")
    return 0


def _run_onboard_wizard(non_interactive: bool = False) -> int:
    """Onboard a Queen into an existing hive (or create org/hive if none exist)."""
    print("Beehive Onboard")
    print("=" * 40)
    store = _get_beekeeper_store()
    orgs = store.list_orgs()
    if not orgs:
        print("No orgs found. Run `beekeeper setup` first for first-time setup.")
        return 1

    if non_interactive:
        org = orgs[0]
        hives = store.list_hives(org.org_id)
        hive = hives[0] if hives else None
        if not hive:
            hive = store.create_hive(org.org_id, "Main Hive")
        queen_name = "Main Queen"
        blueprint_id = "blueprint.queen.default"
    else:
        print("Select organization:")
        for i, o in enumerate(orgs, 1):
            print(f"  {i}. {o.name} ({o.org_id})")
        idx = input("Number [1]: ").strip() or "1"
        try:
            org = orgs[int(idx) - 1]
        except (ValueError, IndexError):
            org = orgs[0]
        hives = store.list_hives(org.org_id)
        if not hives:
            hive_name = input("No hives. Create hive name [Main Hive]: ").strip() or "Main Hive"
            hive = store.create_hive(org.org_id, hive_name)
        else:
            print("Select hive:")
            for i, h in enumerate(hives, 1):
                print(f"  {i}. {h.name} ({h.hive_id})")
            hidx = input(f"Number [1]: ").strip() or "1"
            try:
                hive = hives[int(hidx) - 1]
            except (ValueError, IndexError):
                hive = hives[0]
        queen_name = input("Queen name [Main Queen]: ").strip() or "Main Queen"
        blueprint_id = input("Blueprint ID [blueprint.queen.default]: ").strip() or "blueprint.queen.default"

    queen = store.create_queen(hive.hive_id, queen_name, blueprint_id)
    print("\n[OK] Queen onboarded:")
    print(json.dumps({"queen": queen.model_dump(mode="json")}, ensure_ascii=True, indent=2))
    return 0


def _run_shell(honeycomb_root: str = ".honeycomb") -> int:
    """Interactive shell with command discovery."""
    print("Beehive Shell")
    print("=" * 40)
    print("Type a command or 'help' for options. 'exit' to quit.")
    print()
    while True:
        try:
            raw = input("beekeeper> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return 0
        if not raw:
            continue
        if raw in {"exit", "quit", "q"}:
            print("bye")
            return 0
        if raw in {"help", "?"}:
            _print_command_guide()
            continue
        if raw == "commands":
            _run_commands_list()
            continue
        # Run as subprocess for full arg support
        cmd = [sys.executable, "-m", "beekeeper.runner"] + shlex.split(raw)
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"[exit code {result.returncode}]")
        print()
    return 0


def _run_commands_list() -> None:
    """List all commands with short descriptions."""
    cmds = [
        ("run", "Run a Queen request (--query, --payload)"),
        ("chat", "Interactive Queen chat"),
        ("doctor", "Health checks (--auto-start)"),
        ("up", "Start Docker services (--with-workers, --with-open-webui)"),
        ("down", "Stop Docker services"),
        ("ps", "Show container status"),
        ("restart", "Restart all services"),
        ("reload", "Reload queen-api"),
        ("rebuild", "Rebuild images (--core, --api, --all)"),
        ("setup", "First-time setup wizard"),
        ("onboard", "Onboard Queen to hive"),
        ("init-tenant", "Create org/hive"),
        ("install", "Install worker/guardrail package"),
        ("traces compact", "Compact trace files"),
        ("sessions", "Session tree (list, create, traces, tree)"),
        ("review", "Human approval (list, approve, reject)"),
        ("metrics", "Telemetry metrics"),
        ("settings", "Manage settings"),
        ("channels", "Channel configs"),
        ("templates", "Agent templates"),
        ("version", "Show version"),
        ("update", "Upgrade beekeeper package"),
    ]
    print("Commands:")
    for name, desc in cmds:
        print(f"  beekeeper {name:<20} {desc}")


def _print_command_guide() -> None:
    print("\nBeehive command guide:")
    print(textwrap.dedent("""\
      - beekeeper
          Checks runtime health and auto-starts required Docker services if needed.
      - beekeeper doctor [--auto-start]
          Runs health checks for redis, temporal, qdrant, ollama, and searxng.
      - beekeeper up [--with-workers]
          Starts required infra containers; optionally starts worker containers too.
      - beekeeper up --with-open-webui
          Starts infra plus beekeeper-api, queen-api and Open WebUI for dashboard and chat.
      - beekeeper review list|approve|reject
          Lists and resolves human-approval queue entries.
      - beekeeper metrics [--webhook-url URL]
          Prints honeycomb telemetry metrics and emits alert webhook if requested.
      - beekeeper down
          Stops Beehive containers from docker-compose.
      - beekeeper restart
          Restarts all containers (core, workers, beekeeper-api).
      - beekeeper reload
          Restarts beekeeper-api and queen-api to pick up config changes.
      - beekeeper rebuild [--core] [--api] [--all]
          Rebuilds images with latest code and restarts. --core=workers, --api=beekeeper-api and queen-api.
      - beekeeper reset [--core] [--api] [--all]
          Same as rebuild.
      - beekeeper ps
          Shows Beehive container status.
      - beekeeper run --scheduler <auto|inline|celery|temporal> --vector <memory|qdrant> --query "<text>"
          Runs one Queen request through the selected scheduler/vector backend.
      - beekeeper chat --scheduler <auto|inline|celery|temporal> --vector <memory|qdrant>
          Starts an interactive Queen chat in your terminal.
      - beekeeper pulse [--interval 2] [--honeycomb-root .honeycomb]
          Runs Pulse tick loop for Queen autonomy (cron jobs, backlog, analyzers).
      - beekeeper --help
          Shows all options.
      - beekeeper setup [--non-interactive]
          First-time setup wizard: doctor, init tenant, optional admin user.
      - beekeeper onboard [--non-interactive]
          Onboard a Queen into an existing hive (or create org/hive if none).
      - beekeeper init-tenant --org "Acme" --hive "Ops"
          Initializes a first org/hive/honeycomb for Beekeeper.
      - beekeeper settings list|get|set
          Manage settings via CLI.
      - beekeeper channels list|set
          Manage channel configs (Slack, Telegram, Discord).
      - beekeeper templates list|instantiate
          List or instantiate agent templates.
      - beekeeper sessions list|create|traces|tree
          Session tree and branching (list sessions, create, traces in session, trace tree).
      - beekeeper install <package> [--editable] [--no-registry]
          Install worker/guardrail package from PyPI; registers in .honeycomb/workers|guardrails.
      - beekeeper traces compact [--trace-id X] [--all] [--min-age-hours N]
          Compact trace files to reduce size.
      - beekeeper shell
          Interactive shell with command discovery.
      - beekeeper commands
          List all commands.
      - beekeeper version
          Show version.
      - beekeeper update
          Upgrade beekeeper package (pip install --upgrade).
    """).rstrip())


def _print_executed_command(cmd: list[str]) -> None:
    print("$ " + " ".join(shlex.quote(part) for part in cmd))


def _compose_cmd_for_display(args: list[str]) -> list[str]:
    compose_cmd = _detect_compose_command()
    if not compose_cmd:
        return ["docker", "compose", "-f", str(_compose_file()), *args]
    return [*compose_cmd, "-f", str(_compose_file()), *args]


def _run_rebuild(args: argparse.Namespace) -> int:
    core = args.core or args.all
    api = args.api or args.dashboard or args.all
    if not core and not api:
        core = api = True
    services: list[str] = []
    if core:
        services.extend(["celery-worker", "temporal-worker"])
    if api:
        services.extend(["beekeeper-api", "queen-api"])
    build_cmd = _compose_cmd_for_display(["build", "--no-cache", *services])
    up_cmd = _compose_cmd_for_display(["up", "-d", "--force-recreate", *services])
    print("$ " + " ".join(shlex.quote(p) for p in build_cmd))
    try:
        result = _run_compose(["build", "--no-cache", *services])
        if result.returncode != 0:
            return result.returncode
    except RuntimeError as exc:
        print(f"[FAIL] compose: {exc}")
        return 1
    print("$ " + " ".join(shlex.quote(p) for p in up_cmd))
    try:
        result = _run_compose(["up", "-d", "--force-recreate", *services])
    except RuntimeError as exc:
        print(f"[FAIL] compose: {exc}")
        return 1
    return result.returncode


def _build_store(honeycomb_root: str) -> HoneycombStore:
    return HoneycombStore(HoneycombConfig(root_dir=Path(honeycomb_root)))


def _run_review_command(args: argparse.Namespace) -> int:
    store = _build_store(args.honeycomb_root)
    if args.review_command == "list":
        pending = store.list_pending_reviews()
        payload = {
            "pending_count": len(pending),
            "reviews": [item.model_dump(mode="json") for item in pending],
        }
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 0
    if args.review_command in {"approve", "reject"}:
        approved = args.review_command == "approve"
        if args.resume:
            queen = QueenAgent(_build_config(args))
            output = queen.resume_human_review(
                args.review_id,
                approver=args.approver,
                approved=approved,
                note=args.note,
            )
            print(json.dumps(output, ensure_ascii=True, indent=2))
            return 0
        review = store.resolve_review(
            args.review_id,
            approved=approved,
            approver=args.approver,
            note=args.note or None,
        )
        print(json.dumps(review.model_dump(mode="json"), ensure_ascii=True, indent=2))
        return 0
    return 1


def _run_metrics_command(args: argparse.Namespace) -> int:
    metrics = compute_ops_metrics(Path(args.honeycomb_root))
    print(json.dumps(metrics, ensure_ascii=True, indent=2))
    if args.webhook_url and metrics.get("alerts"):
        payload = {
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "alerts": metrics["alerts"],
        }
        send_alert_webhook(args.webhook_url, payload)
    return 0


def _get_beekeeper_store() -> BeekeeperStore:
    root = Path(os.getenv("BEEKEEPER_STORE_ROOT", ".beekeeper_store"))
    return BeekeeperStore(root)


def _run_list_workers(args: argparse.Namespace) -> None:
    """List built-in and installed workers."""
    honeycomb_root = Path(getattr(args, "honeycomb_root", ".honeycomb"))
    registry = WorkerRegistry(honeycomb_root)
    builtin = {w.get("worker_kind"): w for w in registry.list_workers()}
    plugins_data = list_installed_plugins(honeycomb_root)
    plugin_workers = plugins_data.get("workers", [])
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for w in plugin_workers:
        kind = w.get("worker_kind", "custom")
        if kind in seen:
            continue
        seen.add(kind)
        reg = builtin.get(kind, {})
        rows.append({
            "worker_kind": kind,
            "name": w.get("name") or reg.get("name", kind),
            "source": "plugin",
            "module_path": f"{w.get('module_path', '')}:{w.get('class_name', '')}",
        })
    for kind, w in builtin.items():
        if kind in seen:
            continue
        seen.add(kind)
        rows.append({
            "worker_kind": kind,
            "name": w.get("name", kind),
            "source": "built-in",
            "module_path": None,
        })
    if getattr(args, "json", False):
        print(json.dumps({"workers": rows}, ensure_ascii=True, indent=2))
        return
    if not rows:
        print("No workers found.")
        return
    col1 = max(len(r["worker_kind"]) for r in rows)
    col2 = max(len(r["name"]) for r in rows)
    col4 = max(len(str(r["module_path"]) or "-") for r in rows)
    fmt = f"{{:<{col1}}} {{:<{col2}}} {{:<9}} {{}}"
    print(fmt.format("worker_kind", "name", "source", "module_path"))
    print("-" * (col1 + col2 + 9 + col4 + 4))
    for r in rows:
        print(fmt.format(r["worker_kind"], r["name"], r["source"], (r["module_path"] or "-")))


def _run_settings_command(args: argparse.Namespace) -> int:
    store = _get_beekeeper_store()
    if args.settings_command == "list":
        settings = store.list_settings()
        print(json.dumps({"settings": settings}, ensure_ascii=True, indent=2))
        return 0
    if args.settings_command == "get":
        val = store.read_setting(args.key)
        print(json.dumps({"key": args.key, "value": val}, ensure_ascii=True, indent=2))
        return 0
    if args.settings_command == "set":
        raw = (args.json_value or "").strip()
        if args.key == "llm_model" and raw and not raw.startswith(("{", "[", '"')):
            value = raw
        else:
            try:
                value = json.loads(args.json_value)
            except json.JSONDecodeError as exc:
                print(f"[FAIL] invalid JSON: {exc}", file=sys.stderr)
                return 1
        hive_id = getattr(args, "hive_id", None)
        if hive_id:
            store.write_hive_setting(hive_id, args.key, value)
            print(json.dumps({"ok": True, "key": args.key, "hive_id": hive_id}, ensure_ascii=True, indent=2))
        else:
            store.write_setting(args.key, value)
            print(json.dumps({"ok": True, "key": args.key}, ensure_ascii=True, indent=2))
        return 0
    return 1


def _run_channels_command(args: argparse.Namespace) -> int:
    store = _get_beekeeper_store()
    if args.channels_command == "list":
        configs = store.list_channel_configs()
        print(json.dumps({"channels": configs}, ensure_ascii=True, indent=2))
        return 0
    if args.channels_command == "set":
        try:
            payload = json.loads(args.json_value)
        except json.JSONDecodeError as exc:
            print(f"[FAIL] invalid JSON: {exc}", file=sys.stderr)
            return 1
        store.write_channel_config(args.channel, payload)
        print(json.dumps({"ok": True, "channel": args.channel}, ensure_ascii=True, indent=2))
        return 0
    return 1


def _run_sessions_command(args: argparse.Namespace) -> int:
    store = _build_store(getattr(args, "honeycomb_root", ".honeycomb"))
    cmd = getattr(args, "sessions_command", None)
    if cmd == "list":
        sessions = store.list_sessions(limit=50)
        print(json.dumps({"sessions": sessions}, ensure_ascii=True, indent=2))
        return 0
    if cmd == "create":
        session_id = store.create_session()
        print(json.dumps({"session_id": session_id}, ensure_ascii=True, indent=2))
        return 0
    if cmd == "traces":
        session_id = getattr(args, "session_id", None)
        if not session_id:
            print("[FAIL] session_id required", file=sys.stderr)
            return 1
        traces = store.get_session_traces(session_id)
        print(json.dumps({"session_id": session_id, "traces": traces}, ensure_ascii=True, indent=2))
        return 0
    if cmd == "tree":
        trace_id = getattr(args, "trace_id", None)
        if not trace_id:
            print("[FAIL] trace_id required", file=sys.stderr)
            return 1
        tree = store.get_trace_tree(trace_id)
        print(json.dumps(tree, ensure_ascii=True, indent=2))
        return 0
    return 1


def _run_templates_command(args: argparse.Namespace) -> int:
    store = _get_beekeeper_store()
    if args.templates_command == "list":
        templates = store.list_templates()
        print(json.dumps({"templates": templates}, ensure_ascii=True, indent=2))
        return 0
    if args.templates_command == "instantiate":
        templates = {row.get("template_id"): row for row in store.list_templates()}
        template = templates.get(args.template_id)
        if template is None:
            print(f"[FAIL] template not found: {args.template_id}", file=sys.stderr)
            return 1
        blueprint_payload = template.get("blueprint", {})
        blueprint_id = str(blueprint_payload.get("blueprint_id", "blueprint.queen.default"))
        queen = store.create_queen(args.hive_id, args.name, blueprint_id)
        print(json.dumps({"queen": queen.model_dump(mode="json"), "template_id": args.template_id}, ensure_ascii=True, indent=2))
        return 0
    return 1


def _check_docker_available() -> tuple[bool, str]:
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        if r.returncode == 0:
            return True, "Docker daemon running"
        return False, "Docker daemon not responding (is Docker Desktop running?)"
    except FileNotFoundError:
        return False, "docker not found — install Docker Desktop from https://docker.com"
    except subprocess.TimeoutExpired:
        return False, "docker info timed out — Docker daemon may be starting"


def _check_env_warnings() -> None:
    providers_str = (os.getenv("BEEKEEPER_LLM_PROVIDERS") or os.getenv("BEEKEEPER_LLM_PROVIDER") or "").strip()
    if "gemini" in providers_str and not os.getenv("BEEKEEPER_GEMINI_API_KEY", "").strip():
        print("  [WARN] BEEKEEPER_GEMINI_API_KEY not set (required for gemini provider)")
    if "openai" in providers_str and not os.getenv("BEEKEEPER_OPENAI_API_KEY", "").strip():
        print("  [WARN] BEEKEEPER_OPENAI_API_KEY not set (required for openai provider)")


def _wait_for_service(
    name: str,
    *,
    url: str | None = None,
    tcp_host: str | None = None,
    tcp_port: int | None = None,
    timeout: float = 60.0,
) -> bool:
    """Poll an HTTP URL or TCP port until it becomes available. Returns True on success."""
    start = time.monotonic()
    spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spin_idx = 0
    while True:
        elapsed = time.monotonic() - start
        if elapsed >= timeout:
            print(f"\r  ✗ {name:<20} (timeout after {timeout:.0f}s)")
            return False
        ok = False
        if url:
            try:
                req = urllib.request.Request(url, method="GET", headers={"User-Agent": "beekeeper-start/1.0"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    ok = 200 <= getattr(resp, "status", 200) < 400
            except urllib.error.HTTPError as e:
                ok = e.code < 500
            except Exception:
                ok = False
        elif tcp_host and tcp_port:
            try:
                with socket.create_connection((tcp_host, tcp_port), timeout=2):
                    ok = True
            except Exception:
                ok = False
        if ok:
            print(f"\r  ✓ {name}")
            return True
        char = spinner[spin_idx % len(spinner)]
        print(f"\r  {char} waiting for {name}...", end="", flush=True)
        spin_idx += 1
        time.sleep(2.0)


def _print_start_success_panel() -> None:
    width = 60
    lines = [
        "  ✓  Beekeeper is running",
        "",
        "  Web UI:      http://localhost:3000",
        "  Dashboard:   http://localhost:8787",
        "  Queen API:   http://localhost:8788",
        "",
        "  Quick commands:",
        "    beekeeper chat     →  talk to Queen in terminal",
        "    beekeeper status   →  live stats (workers, storage)",
        "    beekeeper ps       →  container status",
        "    beekeeper doctor   →  health checks",
        "    beekeeper down     →  stop all services",
    ]
    border = "─" * (width - 2)
    print(f"┌{border}┐")
    for line in lines:
        padded = line.ljust(width - 2)
        print(f"│{padded}│")
    print(f"└{border}┘")


def _run_start(args: argparse.Namespace) -> int:
    # Step 1: Docker pre-flight
    print("Checking dependencies...")
    ok, msg = _check_docker_available()
    if not ok:
        print(f"  ✗ {msg}")
        return 1
    print(f"  ✓ {msg}")

    # Step 2: Check compose file
    compose_file = _compose_file()
    if not compose_file.exists():
        print("  ✗ docker-compose.yml not found — run from the beekeeper project root")
        return 1
    print("  ✓ docker-compose.yml found")

    # Step 3: Warn about missing env vars
    _check_env_warnings()

    # Step 4: Start all services
    print("\nStarting services...")
    services = [
        "redis", "qdrant", "temporal", "searxng",
        "celery-worker", "pulse", "beekeeper-api", "queen-api", "open-webui",
    ]
    try:
        result = _run_compose(["up", "-d"] + services, capture_output=True)
    except RuntimeError as exc:
        print(f"[FAIL] compose: {exc}")
        return 1
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        print("[FAIL] Could not start services. Run `beekeeper doctor` for details.")
        if stderr:
            print(stderr[:500])
        return 1
    print("  ✓ services launched")

    # Step 5: Write queen start time (for status uptime display)
    honeycomb_root = Path(getattr(args, "honeycomb_root", ".honeycomb"))
    honeycomb_root.mkdir(parents=True, exist_ok=True)
    start_file = honeycomb_root / "queen_start.txt"
    if not start_file.exists():
        start_file.write_text(datetime.now(timezone.utc).isoformat())

    # Step 6: Wait for each service to become healthy
    print("\nWaiting for services to be ready...")
    health_targets = [
        ("redis",         None,                           "localhost", 6379),
        ("qdrant",        "http://localhost:6333/readyz",  None,        None),
        ("temporal",      None,                           "localhost", 7233),
        ("searxng",       "http://localhost:8080/",        None,        None),
        ("beekeeper-api", "http://localhost:8787/health",  None,        None),
        ("queen-api",     "http://localhost:8788/health",  None,        None),
        ("open-webui",    "http://localhost:3000/",        None,        None),
    ]
    all_ready = True
    for name, url, tcp_host, tcp_port in health_targets:
        ready = _wait_for_service(name, url=url, tcp_host=tcp_host, tcp_port=tcp_port)
        if not ready:
            all_ready = False

    if not all_ready:
        print("\n[WARN] Some services may still be starting. Run `beekeeper doctor` to check.")

    print()
    _print_start_success_panel()
    return 0


# ── beekeeper status ──────────────────────────────────────────────────────────

def _dir_size_mb(path: Path) -> float:
    total = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total / (1024 * 1024)


def _gather_status_data(honeycomb_root: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}

    # Containers via compose ps --format json
    containers: list[dict[str, Any]] = []
    try:
        r = _run_compose(["ps", "--format", "json"], capture_output=True)
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, list):
                        containers.extend(obj)
                    elif isinstance(obj, dict):
                        containers.append(obj)
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass
    data["containers"] = containers

    # Workers
    try:
        registry = WorkerRegistry(honeycomb_root)
        workers = registry.list_workers()
    except Exception:
        workers = []
    data["workers"] = workers

    # Generated workers
    gen_dir = honeycomb_root / "workers" / "generated"
    try:
        data["generated_workers"] = len(list(gen_dir.glob("*.py"))) if gen_dir.exists() else 0
    except Exception:
        data["generated_workers"] = 0

    # Storage size
    data["storage_mb"] = _dir_size_mb(honeycomb_root)

    # Trace count
    events_dir = honeycomb_root / "events"
    try:
        data["traces"] = len(list(events_dir.glob("*.jsonl"))) if events_dir.exists() else 0
    except Exception:
        data["traces"] = 0

    # Memory count
    mem_file = honeycomb_root / "queen_memories.jsonl"
    try:
        data["memories"] = sum(1 for _ in mem_file.open()) if mem_file.exists() else 0
    except Exception:
        data["memories"] = 0

    # Queen uptime
    start_file = honeycomb_root / "queen_start.txt"
    try:
        if start_file.exists():
            started = datetime.fromisoformat(start_file.read_text().strip())
            elapsed = datetime.now(timezone.utc) - started
            hours, rem = divmod(int(elapsed.total_seconds()), 3600)
            mins = rem // 60
            data["uptime"] = f"{hours}h {mins}m"
        else:
            data["uptime"] = "unknown"
    except Exception:
        data["uptime"] = "unknown"

    return data


def _print_status_screen(data: dict[str, Any], now_str: str) -> None:
    print(f"Beekeeper Status  [{now_str}]  (q to quit)")
    print("─" * 54)

    print(f"\nQueen")
    print(f"  Uptime:   {data.get('uptime', 'unknown')}")

    workers: list[dict[str, Any]] = data.get("workers", [])
    gen_count = data.get("generated_workers", 0)
    print(f"\nWorkers ({len(workers)} registered)")
    for w in workers[:8]:
        kind = w.get("worker_kind", "?")
        mp = str(w.get("module_path", ""))
        source = "generated" if "generated" in mp else "built-in"
        print(f"  {kind:<30} {source:<12} ✓ active")
    if len(workers) > 8:
        print(f"  ... and {len(workers) - 8} more")

    containers: list[dict[str, Any]] = data.get("containers", [])
    print(f"\nContainers")
    if containers:
        col = 0
        for c in containers:
            name = c.get("Name", c.get("Service", "?"))
            state = c.get("State", c.get("Status", "?"))
            sym = "✓" if "running" in str(state).lower() else "✗"
            print(f"  {name:<20} {sym}", end="")
            col += 1
            if col % 3 == 0:
                print()
        if col % 3 != 0:
            print()
    else:
        print("  (no container info — is Docker running?)")

    print(f"\nStorage")
    print(
        f"  Honeycomb:  {data.get('storage_mb', 0):.1f} MB   "
        f"Traces: {data.get('traces', 0)}   "
        f"Memories: {data.get('memories', 0)}"
    )
    print(f"  Workers:    {len(workers)} registered  ({gen_count} generated)")


def _run_status(args: argparse.Namespace) -> int:
    honeycomb_root = Path(getattr(args, "honeycomb_root", ".honeycomb"))
    interval = getattr(args, "interval", 3.0)
    once = getattr(args, "once", False)

    def render() -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = _gather_status_data(honeycomb_root)
        if not once:
            print("\033[2J\033[H", end="")
        _print_status_screen(data, now_str)

    if once:
        render()
        return 0

    try:
        while True:
            render()
            deadline = time.monotonic() + interval
            while time.monotonic() < deadline:
                try:
                    rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
                    if rlist:
                        ch = sys.stdin.read(1)
                        if ch in ("q", "Q"):
                            print("\nbye")
                            return 0
                except Exception:
                    time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nbye")
        return 0


def main() -> None:
    _load_env_early()
    parser = argparse.ArgumentParser(prog="beekeeper", description="Beekeeper runtime CLI")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run a beekeeper request")
    run_parser.add_argument("--scheduler", choices=["auto", "inline", "celery", "temporal"], default="auto")
    run_parser.add_argument("--vector", choices=["memory", "qdrant"], default="memory")
    run_parser.add_argument("--intent", default="research_topic")
    run_parser.add_argument("--query", default=None)
    run_parser.add_argument("--payload", default=None, help="JSON payload string")
    run_parser.add_argument("--honeycomb-root", default=".honeycomb")
    run_parser.add_argument("--max-reruns", type=int, default=1)

    chat_parser = subparsers.add_parser("chat", help="Interactive Queen chat")
    chat_parser.add_argument("--scheduler", choices=["auto", "inline", "celery", "temporal"], default="auto")
    chat_parser.add_argument("--vector", choices=["memory", "qdrant"], default="memory")
    chat_parser.add_argument("--intent", default="research_topic")
    chat_parser.add_argument("--honeycomb-root", default=".honeycomb")
    chat_parser.add_argument("--max-reruns", type=int, default=1)
    chat_parser.add_argument("--quiet", action="store_true", help="Suppress step-by-step progress; show only final reply")
    chat_parser.add_argument("--verbose", action="store_true", help="Show worker kind and confidence in replies")
    chat_parser.add_argument("--user-id", dest="user_id", default=None, help="User ID for memory scoping (default: system username)")

    doctor_parser = subparsers.add_parser("doctor", help="Check Beekeeper service connectivity")
    doctor_parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Attempt to start Docker infra (redis/temporal/qdrant) if checks fail.",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        dest="doctor_json",
        help="Output checks as JSON for scripting.",
    )

    up_parser = subparsers.add_parser("up", help="Start docker compose services")
    up_parser.add_argument(
        "--with-workers",
        action="store_true",
        help="Also start celery-worker and temporal-worker containers.",
    )
    up_parser.add_argument(
        "--with-open-webui",
        action="store_true",
        help="Also start beekeeper-api, queen-api and open-webui for dashboard and chat.",
    )

    subparsers.add_parser("down", help="Stop docker compose services")
    subparsers.add_parser("ps", help="Show docker compose service status")
    restart_parser = subparsers.add_parser(
        "restart",
        help="Restart all docker compose services (core, workers, beekeeper-api, queen-api, open-webui).",
    )
    reload_parser = subparsers.add_parser(
        "reload",
        help="Reload beekeeper: restart beekeeper-api and queen-api (picks up config changes). Use 'restart' for full reset.",
    )
    rebuild_parser = subparsers.add_parser(
        "rebuild",
        help="Rebuild Docker images with latest code and restart. Use flags to select what to rebuild.",
    )
    rebuild_parser.add_argument("--core", action="store_true", help="Rebuild workers (celery-worker, temporal-worker).")
    rebuild_parser.add_argument("--api", action="store_true", help="Rebuild beekeeper-api and queen-api.")
    rebuild_parser.add_argument("--dashboard", action="store_true", help="Same as --api.")
    rebuild_parser.add_argument("--all", action="store_true", help="Rebuild everything (default).")
    reset_parser = subparsers.add_parser(
        "reset",
        help="Alias for rebuild: rebuild images with latest code and restart.",
    )
    reset_parser.add_argument("--core", action="store_true", help="Rebuild workers only.")
    reset_parser.add_argument("--api", action="store_true", help="Rebuild beekeeper-api and queen-api only.")
    reset_parser.add_argument("--dashboard", action="store_true", help="Same as --api.")
    reset_parser.add_argument("--all", action="store_true", help="Rebuild everything (default).")
    setup_parser = subparsers.add_parser("setup", help="First-time setup wizard (doctor, tenant, optional admin)")
    setup_parser.add_argument("--non-interactive", action="store_true", help="Use defaults, no prompts")
    quickstart_parser = subparsers.add_parser("quickstart", help="5-minute quickstart (doctor, tenant, minimal prompts)")
    quickstart_parser.add_argument("--non-interactive", action="store_true", help="Use defaults, no prompts")
    onboard_parser = subparsers.add_parser("onboard", help="Onboard a Queen into an existing hive")
    onboard_parser.add_argument("--non-interactive", action="store_true", help="Use defaults, no prompts")
    init_tenant_parser = subparsers.add_parser("init-tenant", help="Initialize Beekeeper org/hive")
    init_tenant_parser.add_argument("--org", default="Default Organization")
    init_tenant_parser.add_argument("--hive", default="Main Hive")
    init_tenant_parser.add_argument("--honeycomb-root", default=".honeycomb")
    metrics_parser = subparsers.add_parser("metrics", help="Compute telemetry metrics from Honeycomb")
    metrics_parser.add_argument("--honeycomb-root", default=".honeycomb")
    metrics_parser.add_argument("--webhook-url", default=None)

    pulse_parser = subparsers.add_parser("pulse", help="Run Pulse tick loop (Queen autonomy)")
    pulse_parser.add_argument("--honeycomb-root", default=".honeycomb")
    pulse_parser.add_argument("--interval", type=float, default=120.0, help="Tick interval in seconds")

    review_parser = subparsers.add_parser("review", help="Manage human approval queue")
    review_parser.add_argument("--honeycomb-root", default=".honeycomb")
    review_parser.add_argument("--scheduler", choices=["auto", "inline", "celery", "temporal"], default="auto")
    review_parser.add_argument("--vector", choices=["memory", "qdrant"], default="memory")
    review_parser.add_argument("--max-reruns", type=int, default=1)
    review_sub = review_parser.add_subparsers(dest="review_command", required=True)
    review_sub.add_parser("list", help="List pending approvals")
    approve_parser = review_sub.add_parser("approve", help="Approve a queued review")
    approve_parser.add_argument("review_id")
    approve_parser.add_argument("--approver", default="operator")
    approve_parser.add_argument("--note", default="")
    approve_parser.add_argument("--resume", action="store_true")
    reject_parser = review_sub.add_parser("reject", help="Reject a queued review")
    reject_parser.add_argument("review_id")
    reject_parser.add_argument("--approver", default="operator")
    reject_parser.add_argument("--note", default="")
    reject_parser.add_argument("--resume", action="store_true")

    settings_parser = subparsers.add_parser("settings", help="Manage Beekeeper settings (CLI)")
    settings_sub = settings_parser.add_subparsers(dest="settings_command", required=True)
    settings_sub.add_parser("list", help="List all settings")
    get_parser = settings_sub.add_parser("get", help="Get a setting by key")
    get_parser.add_argument("key", help="Setting key")
    set_parser = settings_sub.add_parser("set", help="Set a setting")
    set_parser.add_argument("key", help="Setting key")
    set_parser.add_argument("json_value", help="JSON value (e.g. '\"value\"' or '{\"a\":1}')")
    set_parser.add_argument("--hive", dest="hive_id", help="Scope to hive (hive-level setting)")

    channels_parser = subparsers.add_parser("channels", help="Manage channel configs (Slack, Telegram, Discord)")
    channels_sub = channels_parser.add_subparsers(dest="channels_command", required=True)
    channels_sub.add_parser("list", help="List channel configs (secrets redacted)")
    channels_set_parser = channels_sub.add_parser("set", help="Set channel config")
    channels_set_parser.add_argument("channel", help="Channel name: slack, telegram, discord")
    channels_set_parser.add_argument("json_value", help="JSON config (e.g. '{\"slack_bot_token\":\"xoxb-...\"}')")

    templates_parser = subparsers.add_parser("templates", help="Manage agent templates")
    templates_sub = templates_parser.add_subparsers(dest="templates_command", required=True)
    templates_sub.add_parser("list", help="List templates")
    templates_inst_parser = templates_sub.add_parser("instantiate", help="Instantiate a template as a Queen")
    templates_inst_parser.add_argument("template_id", help="Template ID from list")
    templates_inst_parser.add_argument("--hive", "--hive-id", dest="hive_id", required=True, help="Hive ID")
    templates_inst_parser.add_argument("--name", required=True, help="Queen name")

    sessions_parser = subparsers.add_parser("sessions", help="Session tree and branching")
    sessions_parser.add_argument("--honeycomb-root", default=".honeycomb")
    sessions_sub = sessions_parser.add_subparsers(dest="sessions_command", required=True)
    sessions_sub.add_parser("list", help="List sessions")
    sessions_create = sessions_sub.add_parser("create", help="Create a new session")
    sessions_traces = sessions_sub.add_parser("traces", help="List traces in a session")
    sessions_traces.add_argument("session_id", help="Session ID")
    sessions_tree = sessions_sub.add_parser("tree", help="Show trace tree (branching)")
    sessions_tree.add_argument("trace_id", help="Trace ID")

    install_parser = subparsers.add_parser("install", help="Install worker/guardrail package (beekeeper install <pkg>)")
    install_parser.add_argument("package", nargs="?", help="Package name (PyPI) or path; omit with --list")
    install_parser.add_argument("--list", action="store_true", dest="install_list", help="List installed plugins")
    install_parser.add_argument("--honeycomb-root", default=".honeycomb")
    install_parser.add_argument("--local", "-l", action="store_true", dest="install_local", help="Install to project-local .beekeeper/workers/")
    install_parser.add_argument("--editable", "-e", action="store_true", help="Install in editable mode")
    install_parser.add_argument("--no-registry", action="store_true", help="Do not add worker to registry")

    list_workers_parser = subparsers.add_parser("list-workers", help="List built-in and installed workers")
    list_workers_parser.add_argument("--honeycomb-root", default=".honeycomb")
    list_workers_parser.add_argument("--json", action="store_true", help="Output as JSON")

    traces_parser = subparsers.add_parser("traces", help="Trace operations")
    traces_parser.add_argument("--honeycomb-root", default=".honeycomb")
    traces_sub = traces_parser.add_subparsers(dest="traces_command", required=True)
    traces_compact = traces_sub.add_parser("compact", help="Compact trace files to reduce size")
    traces_compact.add_argument("--trace-id", help="Compact only this trace")
    traces_compact.add_argument("--all", action="store_true", help="Compact all traces")
    traces_compact.add_argument("--min-age-hours", type=float, default=0, help="Only compact traces older than N hours")
    traces_tree = traces_sub.add_parser("tree", help="Show trace tree (session branching)")
    traces_tree.add_argument("trace_id", help="Trace ID")
    traces_fork = traces_sub.add_parser("fork", help="Fork a trace (create new branch)")
    traces_fork.add_argument("trace_id", help="Parent trace ID")
    traces_fork.add_argument("--session-id", help="Session to attach to; creates new session if omitted")

    shell_parser = subparsers.add_parser("shell", help="Interactive shell with command discovery")
    shell_parser.add_argument("--honeycomb-root", default=".honeycomb")
    subparsers.add_parser("commands", help="List all commands")
    subparsers.add_parser("version", help="Show version")
    update_parser = subparsers.add_parser("update", help="Upgrade beekeeper package")
    update_parser.add_argument("--channel", "-c", choices=["stable", "beta", "dev"], default="stable", help="Release channel: stable (default), beta, dev")

    start_parser = subparsers.add_parser("start", help="Start all Beekeeper services and print ready panel")
    start_parser.add_argument("--honeycomb-root", default=".honeycomb")

    status_parser = subparsers.add_parser("status", help="Live Beekeeper stats (Ctrl+C or q to quit)")
    status_parser.add_argument("--honeycomb-root", default=".honeycomb")
    status_parser.add_argument("--interval", type=float, default=3.0, help="Refresh interval in seconds")
    status_parser.add_argument("--once", action="store_true", help="Print once and exit (no live refresh)")

    args = parser.parse_args()
    if args.command is None:
        exit_code = _run_doctor(auto_start=True)
        _print_command_guide()
        raise SystemExit(exit_code)

    if args.command == "run":
        cfg = _build_config(args)
        queen = QueenAgent(cfg)
        payload = _parse_payload(args.payload, args.query)
        output = queen.run(intent=args.intent, payload=payload, source="cli")
        print(json.dumps(output, indent=2))
        return
    if args.command == "chat":
        raise SystemExit(_run_chat_loop(args))
    if args.command == "doctor":
        raise SystemExit(_run_doctor(auto_start=args.auto_start, json_output=getattr(args, "doctor_json", False)))
    if args.command == "up":
        display_cmd = _compose_cmd_for_display(
            ["up", "-d", "redis", "temporal", "qdrant", "searxng"]
            + (["celery-worker", "temporal-worker"] if args.with_workers else [])
            + (["beekeeper-api", "queen-api", "open-webui"] if args.with_open_webui else [])
        )
        _print_executed_command(display_cmd)
        exit_code = _ensure_required_services_running(include_workers=args.with_workers)
        if exit_code != 0:
            raise SystemExit(exit_code)
        if args.with_open_webui:
            result = _run_compose(["up", "-d", "beekeeper-api", "queen-api", "open-webui"], capture_output=True)
            if result.returncode != 0:
                print("[FAIL] compose: could not start beekeeper-api / queen-api / open-webui")
                print((result.stderr or "").strip())
                raise SystemExit(1)
        raise SystemExit(0)
    if args.command == "down":
        cmd = _compose_cmd_for_display(["down"])
        _print_executed_command(cmd)
        try:
            result = _run_compose(["down"])
        except RuntimeError as exc:
            print(f"[FAIL] compose: {exc}")
            raise SystemExit(1)
        raise SystemExit(result.returncode)
    if args.command == "ps":
        cmd = _compose_cmd_for_display(["ps"])
        _print_executed_command(cmd)
        try:
            result = _run_compose(["ps"])
        except RuntimeError as exc:
            print(f"[FAIL] compose: {exc}")
            raise SystemExit(1)
        raise SystemExit(result.returncode)
    if args.command == "restart":
        cmd = _compose_cmd_for_display(["restart"])
        _print_executed_command(cmd)
        try:
            result = _run_compose(["restart"])
        except RuntimeError as exc:
            print(f"[FAIL] compose: {exc}")
            raise SystemExit(1)
        raise SystemExit(result.returncode)
    if args.command == "reload":
        cmd = _compose_cmd_for_display(["restart", "beekeeper-api", "queen-api"])
        _print_executed_command(cmd)
        try:
            result = _run_compose(["restart", "beekeeper-api", "queen-api"])
        except RuntimeError as exc:
            print(f"[FAIL] compose: {exc}")
            raise SystemExit(1)
        raise SystemExit(result.returncode)
    if args.command in ("rebuild", "reset"):
        raise SystemExit(_run_rebuild(args))
    if args.command == "review":
        raise SystemExit(_run_review_command(args))
    if args.command == "metrics":
        raise SystemExit(_run_metrics_command(args))
    if args.command == "pulse":
        config = PulseConfig(
            honeycomb_root=Path(args.honeycomb_root),
            interval_seconds=args.interval,
        )
        run_pulse_loop(config)
        return
    if args.command == "settings":
        raise SystemExit(_run_settings_command(args))
    if args.command == "channels":
        raise SystemExit(_run_channels_command(args))
    if args.command == "templates":
        raise SystemExit(_run_templates_command(args))
    if args.command == "setup":
        raise SystemExit(_run_setup_wizard(non_interactive=getattr(args, "non_interactive", False)))
    if args.command == "quickstart":
        raise SystemExit(_run_quickstart(non_interactive=getattr(args, "non_interactive", False)))
    if args.command == "onboard":
        raise SystemExit(_run_onboard_wizard(non_interactive=getattr(args, "non_interactive", False)))
    if args.command == "sessions":
        raise SystemExit(_run_sessions_command(args))
    if args.command == "init-tenant":
        store = _get_beekeeper_store()
        org = store.create_org(args.org)
        hive = store.create_hive(org.org_id, args.hive)
        comb = store.create_honeycomb(hive.hive_id, f"{args.hive}-comb", args.honeycomb_root)
        payload = {
            "org": org.model_dump(mode="json"),
            "hive": hive.model_dump(mode="json"),
            "honeycomb": comb.model_dump(mode="json"),
        }
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        raise SystemExit(0)

    if args.command == "list-workers":
        _run_list_workers(args)
        raise SystemExit(0)

    if args.command == "install":
        if getattr(args, "install_list", False):
            root = Path.cwd() / ".beekeeper" if getattr(args, "install_local", False) else Path(args.honeycomb_root)
            plugins = list_installed_plugins(root)
            print(json.dumps(plugins, ensure_ascii=True, indent=2))
            raise SystemExit(0)
        if not args.package:
            print("[FAIL] Package name required. Use 'beekeeper install <package>' or 'beekeeper install --list'", file=sys.stderr)
            raise SystemExit(1)
        install_root = Path.cwd() / ".beekeeper" if getattr(args, "install_local", False) else Path(args.honeycomb_root)
        ok, msg = install_package(
            args.package,
            install_root,
            editable=getattr(args, "editable", False),
            registry=not getattr(args, "no_registry", False),
        )
        if ok:
            print(f"[OK] {msg}")
            raise SystemExit(0)
        print(f"[FAIL] {msg}", file=sys.stderr)
        raise SystemExit(1)

    if args.command == "traces":
        traces_cmd = getattr(args, "traces_command", None)
        if traces_cmd == "compact":
            result = compact_traces(
                Path(args.honeycomb_root),
                trace_id=getattr(args, "trace_id", None),
                all_traces=getattr(args, "all", False),
                min_age_hours=getattr(args, "min_age_hours", 0),
            )
            print(json.dumps(result, ensure_ascii=True, indent=2))
            if result.get("error"):
                raise SystemExit(1)
            raise SystemExit(0)
        if traces_cmd == "tree":
            store = _build_store(getattr(args, "honeycomb_root", ".honeycomb"))
            trace_id = getattr(args, "trace_id", None)
            if not trace_id:
                print("[FAIL] trace_id required", file=sys.stderr)
                raise SystemExit(1)
            tree = store.get_trace_tree(trace_id)
            print(json.dumps(tree, ensure_ascii=True, indent=2))
            raise SystemExit(0)
        if traces_cmd == "fork":
            from .sdk import BeekeeperClient
            honeycomb_root = getattr(args, "honeycomb_root", ".honeycomb")
            client = BeekeeperClient(honeycomb_root=honeycomb_root)
            trace_id = getattr(args, "trace_id", None)
            session_id = getattr(args, "session_id", None)
            if not trace_id:
                print("[FAIL] trace_id required", file=sys.stderr)
                raise SystemExit(1)
            new_trace_id = client.fork_trace(trace_id, session_id=session_id)
            print(json.dumps({"trace_id": new_trace_id, "parent_trace_id": trace_id}, ensure_ascii=True, indent=2))
            raise SystemExit(0)
        raise SystemExit(1)

    if args.command == "shell":
        raise SystemExit(_run_shell(honeycomb_root=args.honeycomb_root))

    if args.command == "commands":
        _run_commands_list()
        raise SystemExit(0)

    if args.command == "version":
        try:
            import importlib.metadata
            v = importlib.metadata.version("beekeeper-agent-platform")
            print(f"beekeeper-agent-platform {v}")
        except Exception:
            print("beekeeper-agent-platform (version unknown)")
        raise SystemExit(0)

    if args.command == "start":
        raise SystemExit(_run_start(args))

    if args.command == "status":
        raise SystemExit(_run_status(args))

    if args.command == "update":
        channel = getattr(args, "channel", "stable")
        if channel == "stable":
            cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "beekeeper-agent-platform"]
        elif channel == "beta":
            index = os.getenv("BEEKEEPER_UPDATE_BETA_INDEX", "")
            cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--pre", "beekeeper-agent-platform"]
            if index:
                cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--pre", "-i", index, "beekeeper-agent-platform"]
        else:
            proj = _project_root()
            cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "-e", str(proj)]
        result = subprocess.run(cmd, capture_output=False)
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
