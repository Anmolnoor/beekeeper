from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .honeycomb import HoneycombConfig, HoneycombStore
from .ops import compute_ops_metrics, send_alert_webhook
from .queen import QueenAgent, QueenConfig


def _build_config(args: argparse.Namespace) -> QueenConfig:
    return QueenConfig(
        honeycomb_root=Path(args.honeycomb_root),
        max_reruns=args.max_reruns,
        scheduler_backend=args.scheduler,
        celery_broker_url=os.getenv("BEEHIVE_CELERY_BROKER_URL", "redis://localhost:6379/0"),
        celery_backend_url=os.getenv("BEEHIVE_CELERY_BACKEND_URL", "redis://localhost:6379/1"),
        temporal_endpoint=os.getenv("BEEHIVE_TEMPORAL_ENDPOINT", "localhost:7233"),
        temporal_namespace=os.getenv("BEEHIVE_TEMPORAL_NAMESPACE", "default"),
        temporal_task_queue=os.getenv("BEEHIVE_TEMPORAL_TASK_QUEUE", "beehive-queue"),
        vector_backend=args.vector,
        vector_url=os.getenv("BEEHIVE_VECTOR_URL", "http://localhost:6333"),
        vector_collection=os.getenv("BEEHIVE_VECTOR_COLLECTION", "honeycomb_memory"),
        llm_provider=os.getenv("BEEHIVE_LLM_PROVIDER", "ollama"),
        ollama_base_url=os.getenv("BEEHIVE_OLLAMA_BASE_URL", "http://100.99.106.59:11434"),
        ollama_model=os.getenv("BEEHIVE_OLLAMA_MODEL", "catsarethebest/qwen2.5-N2:1.5b"),
        ollama_timeout_seconds=int(os.getenv("BEEHIVE_OLLAMA_TIMEOUT_SECONDS", "120")),
        gemini_api_key=os.getenv("BEEHIVE_GEMINI_API_KEY", ""),
        gemini_model=os.getenv("BEEHIVE_GEMINI_MODEL", "gemini-1.5-flash"),
        gemini_timeout_seconds=int(os.getenv("BEEHIVE_GEMINI_TIMEOUT_SECONDS", "120")),
        searxng_base_url=os.getenv("BEEHIVE_SEARXNG_BASE_URL", "http://localhost:8080"),
    )


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
    cfg = _build_config(args)
    queen = QueenAgent(cfg)
    current_intent = args.intent
    print("Beehive Queen chat")
    print("Type your message. Commands: /help, /intent <name>, /exit")
    while True:
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
            print("  /intent <name>   set the active Queen intent")
            print("  /exit            leave chat")
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

        try:
            output = queen.run(intent=current_intent, payload=payload)
        except Exception as exc:
            print(f"queen> request failed: {exc}")
            continue
        primary = _extract_primary_response(output)
        worker_kind = primary.get("worker_kind", "unknown")
        confidence = primary.get("confidence", 0.0)
        response = primary.get("output", {})
        if isinstance(response, dict) and isinstance(response.get("assistant_reply"), str):
            print(f"queen[{worker_kind}|conf={confidence:.2f}]> {response['assistant_reply']}")
            source = response.get("response_source", "unknown")
            print(f"(source: {source})")
        else:
            print(f"queen[{worker_kind}|conf={confidence:.2f}]> {json.dumps(response, ensure_ascii=True)}")


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
        print("Start Docker Desktop, then rerun `beehive`.")
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
            "User-Agent": "beehive-doctor/1.0",
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


def _collect_doctor_checks() -> list[DoctorCheck]:
    broker_url = os.getenv("BEEHIVE_CELERY_BROKER_URL", "redis://localhost:6379/0")
    temporal_endpoint = os.getenv("BEEHIVE_TEMPORAL_ENDPOINT", "localhost:7233")
    vector_url = os.getenv("BEEHIVE_VECTOR_URL", "http://localhost:6333")
    ollama_url = os.getenv("BEEHIVE_OLLAMA_BASE_URL", "http://100.99.106.59:11434")
    searxng_url = os.getenv("BEEHIVE_SEARXNG_BASE_URL", "http://localhost:8080")

    redis_host, redis_port = _parse_host_port_from_url(broker_url, default_port=6379)
    if ":" in temporal_endpoint:
        temporal_host, temporal_port_text = temporal_endpoint.rsplit(":", 1)
        temporal_port = int(temporal_port_text)
    else:
        temporal_host, temporal_port = temporal_endpoint, 7233

    return [
        _check_tcp("redis", redis_host, redis_port),
        _check_tcp("temporal", temporal_host, temporal_port),
        _check_http("qdrant", vector_url.rstrip("/") + "/readyz"),
        _check_http("ollama", ollama_url.rstrip("/") + "/api/tags"),
        _check_http("searxng", searxng_url.rstrip("/") + "/", tolerated_error_codes=(403,)),
    ]


def _print_doctor_checks(checks: list[DoctorCheck]) -> None:
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        print(f"[{status}] {check.name}: {check.details}")


def _run_doctor(auto_start: bool = False) -> int:
    checks = _collect_doctor_checks()
    _print_doctor_checks(checks)
    failed = [check for check in checks if not check.ok]
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


def _print_command_guide() -> None:
    print("\nBeehive command guide:")
    print(textwrap.dedent("""\
      - beehive
          Checks runtime health and auto-starts required Docker services if needed.
      - beehive doctor [--auto-start]
          Runs health checks for redis, temporal, qdrant, ollama, and searxng.
      - beehive up [--with-workers]
          Starts required infra containers; optionally starts worker containers too.
      - beehive review list|approve|reject
          Lists and resolves human-approval queue entries.
      - beehive metrics [--webhook-url URL]
          Prints honeycomb telemetry metrics and emits alert webhook if requested.
      - beehive down
          Stops Beehive containers from docker-compose.
      - beehive ps
          Shows Beehive container status.
      - beehive run --scheduler <inline|celery|temporal> --vector <memory|qdrant> --query "<text>"
          Runs one Queen request through the selected scheduler/vector backend.
      - beehive chat --scheduler <inline|celery|temporal> --vector <memory|qdrant>
          Starts an interactive Queen chat in your terminal.
      - beehive --help
          Shows all options.
    """).rstrip())


def _print_executed_command(cmd: list[str]) -> None:
    print("$ " + " ".join(shlex.quote(part) for part in cmd))


def _compose_cmd_for_display(args: list[str]) -> list[str]:
    compose_cmd = _detect_compose_command()
    if not compose_cmd:
        return ["docker", "compose", "-f", str(_compose_file()), *args]
    return [*compose_cmd, "-f", str(_compose_file()), *args]


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="beehive", description="Beehive runtime CLI")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run a beehive request")
    run_parser.add_argument("--scheduler", choices=["inline", "celery", "temporal"], default="inline")
    run_parser.add_argument("--vector", choices=["memory", "qdrant"], default="memory")
    run_parser.add_argument("--intent", default="research_topic")
    run_parser.add_argument("--query", default=None)
    run_parser.add_argument("--payload", default=None, help="JSON payload string")
    run_parser.add_argument("--honeycomb-root", default=".honeycomb")
    run_parser.add_argument("--max-reruns", type=int, default=1)

    chat_parser = subparsers.add_parser("chat", help="Interactive Queen chat")
    chat_parser.add_argument("--scheduler", choices=["inline", "celery", "temporal"], default="inline")
    chat_parser.add_argument("--vector", choices=["memory", "qdrant"], default="memory")
    chat_parser.add_argument("--intent", default="research_topic")
    chat_parser.add_argument("--honeycomb-root", default=".honeycomb")
    chat_parser.add_argument("--max-reruns", type=int, default=1)

    doctor_parser = subparsers.add_parser("doctor", help="Check Beehive service connectivity")
    doctor_parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Attempt to start Docker infra (redis/temporal/qdrant) if checks fail.",
    )

    up_parser = subparsers.add_parser("up", help="Start docker compose services")
    up_parser.add_argument(
        "--with-workers",
        action="store_true",
        help="Also start celery-worker and temporal-worker containers.",
    )

    subparsers.add_parser("down", help="Stop docker compose services")
    subparsers.add_parser("ps", help="Show docker compose service status")
    metrics_parser = subparsers.add_parser("metrics", help="Compute telemetry metrics from Honeycomb")
    metrics_parser.add_argument("--honeycomb-root", default=".honeycomb")
    metrics_parser.add_argument("--webhook-url", default=None)

    review_parser = subparsers.add_parser("review", help="Manage human approval queue")
    review_parser.add_argument("--honeycomb-root", default=".honeycomb")
    review_parser.add_argument("--scheduler", choices=["inline", "celery", "temporal"], default="inline")
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

    args = parser.parse_args()
    if args.command is None:
        exit_code = _run_doctor(auto_start=True)
        _print_command_guide()
        raise SystemExit(exit_code)

    if args.command == "run":
        cfg = _build_config(args)
        queen = QueenAgent(cfg)
        payload = _parse_payload(args.payload, args.query)
        output = queen.run(intent=args.intent, payload=payload)
        print(json.dumps(output, indent=2))
        return
    if args.command == "chat":
        raise SystemExit(_run_chat_loop(args))
    if args.command == "doctor":
        raise SystemExit(_run_doctor(auto_start=args.auto_start))
    if args.command == "up":
        display_cmd = _compose_cmd_for_display(
            ["up", "-d", "redis", "temporal", "qdrant", "searxng"]
            + (["celery-worker", "temporal-worker"] if args.with_workers else [])
        )
        _print_executed_command(display_cmd)
        raise SystemExit(_ensure_required_services_running(include_workers=args.with_workers))
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
    if args.command == "review":
        raise SystemExit(_run_review_command(args))
    if args.command == "metrics":
        raise SystemExit(_run_metrics_command(args))


if __name__ == "__main__":
    main()
