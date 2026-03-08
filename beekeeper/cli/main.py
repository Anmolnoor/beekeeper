from __future__ import annotations

import argparse
import json
import time

from ..config.settings import Phase1Settings
from ..runtime import Phase1RuntimeService
from ..runtime.stack import (
    init_runtime,
    service_urls,
    stack_settings,
    stack_down,
    stack_logs,
    stack_ps,
    stack_restart,
    stack_up,
)


def _json_payload(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("payload_must_be_json_object")
    return loaded


def _print(payload: object, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return
    if isinstance(payload, dict):
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return
    print(str(payload))


def _build_run_request(args: argparse.Namespace) -> dict[str, object]:
    payload = _json_payload(args.payload)
    if args.shell_command:
        payload["command"] = args.shell_command
    if args.path:
        payload["path"] = args.path
    if args.url:
        payload["url"] = args.url
    return {
        "goal": args.goal,
        "workspace_path": args.workspace_path,
        "worker_kind": args.worker_kind,
        "job_type": args.job_type,
        "payload": payload,
    }


def _print_urls() -> None:
    urls = service_urls()
    print("Beekeeper stack is ready")
    print(json.dumps(urls, ensure_ascii=True, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(prog="beekeeper", description="Beekeeper Phase 1 runtime CLI")
    subparsers = parser.add_subparsers(dest="action", required=True)

    start_parser = subparsers.add_parser("start", help="One command to build, start, and initialize the full Phase 1 stack")
    start_parser.add_argument("--build", action="store_true")
    start_parser.add_argument("--json", action="store_true")

    init_parser = subparsers.add_parser("init", help="Initialize the configured state schema and artifact bucket")
    init_parser.add_argument("--json", action="store_true")

    run_parser = subparsers.add_parser("run", help="Create a Phase 1 run")
    run_parser.add_argument("goal")
    run_parser.add_argument("--workspace-path", default=None)
    run_parser.add_argument("--worker-kind", default="bash", choices=["bash", "filesystem", "github", "network"])
    run_parser.add_argument("--job-type", default="task")
    run_parser.add_argument("--payload", default=None)
    run_parser.add_argument("--command", dest="shell_command", default=None)
    run_parser.add_argument("--path", default=None)
    run_parser.add_argument("--url", default=None)
    run_parser.add_argument("--background", action="store_true")
    run_parser.add_argument("--json", action="store_true")

    attach_parser = subparsers.add_parser("attach", help="Attach to a run and optionally wait")
    attach_parser.add_argument("run_id")
    attach_parser.add_argument("--wait", action="store_true")
    attach_parser.add_argument("--poll-seconds", type=float, default=0.5)
    attach_parser.add_argument("--drain", action="store_true")
    attach_parser.add_argument("--json", action="store_true")

    status_parser = subparsers.add_parser("status", help="Show run status")
    status_parser.add_argument("run_id")
    status_parser.add_argument("--json", action="store_true")

    approve_parser = subparsers.add_parser("approve", help="Approve or reject a pending approval")
    approve_parser.add_argument("approval_id")
    approve_parser.add_argument("--by", required=True)
    approve_parser.add_argument("--reject", action="store_true")
    approve_parser.add_argument("--json", action="store_true")

    trace_parser = subparsers.add_parser("trace", help="Show append-only trace for a run")
    trace_parser.add_argument("run_id")
    trace_parser.add_argument("--json", action="store_true")

    stack_parser = subparsers.add_parser("stack", help="Manage the Phase 1 docker compose stack")
    stack_sub = stack_parser.add_subparsers(dest="stack_command", required=True)

    stack_up_parser = stack_sub.add_parser("up", help="Start the stack")
    stack_up_parser.add_argument("--build", action="store_true")
    stack_up_parser.add_argument("--json", action="store_true")

    stack_init_parser = stack_sub.add_parser("init", help="Initialize state schema and MinIO bucket")
    stack_init_parser.add_argument("--json", action="store_true")

    stack_down_parser = stack_sub.add_parser("down", help="Stop the stack")
    stack_down_parser.add_argument("--volumes", action="store_true")
    stack_down_parser.add_argument("--json", action="store_true")

    stack_ps_parser = stack_sub.add_parser("ps", help="Show stack service status")
    stack_ps_parser.add_argument("--json", action="store_true")

    stack_logs_parser = stack_sub.add_parser("logs", help="Show stack logs")
    stack_logs_parser.add_argument("service", nargs="?")
    stack_logs_parser.add_argument("--follow", action="store_true")
    stack_logs_parser.add_argument("--tail", type=int, default=200)
    stack_logs_parser.add_argument("--json", action="store_true")

    stack_restart_parser = stack_sub.add_parser("restart", help="Restart the full stack or a single service")
    stack_restart_parser.add_argument("service", nargs="?")
    stack_restart_parser.add_argument("--json", action="store_true")

    supervisor_parser = subparsers.add_parser("supervisor", help=argparse.SUPPRESS)
    supervisor_parser.add_argument("--run-id", default=None)

    args = parser.parse_args()

    if args.action == "start":
        result = stack_up(build=args.build, detach=True)
        if args.json:
            _print(result, as_json=True)
        else:
            _print_urls()
        return

    if args.action == "init":
        result = init_runtime(Phase1Settings())
        _print(result, as_json=args.json)
        return

    if args.action == "stack":
        if args.stack_command == "up":
            result = stack_up(build=args.build, detach=True)
            _print(result, as_json=args.json)
            return
        if args.stack_command == "init":
            result = init_runtime(stack_settings())
            _print(result, as_json=args.json)
            return
        if args.stack_command == "down":
            result = stack_down(volumes=args.volumes)
            _print(result, as_json=args.json)
            return
        if args.stack_command == "ps":
            result = stack_ps()
            _print(result, as_json=args.json)
            return
        if args.stack_command == "logs":
            result = stack_logs(service=args.service, follow=args.follow, tail=args.tail)
            _print(result, as_json=args.json)
            return
        if args.stack_command == "restart":
            result = stack_restart(service=args.service)
            _print(result, as_json=args.json)
            return
        raise SystemExit(2)

    runtime = Phase1RuntimeService(Phase1Settings())

    if args.action == "run":
        run = runtime.submit_run(_build_run_request(args), background=args.background)
        _print(run, as_json=args.json)
        return

    if args.action == "attach":
        if args.drain:
            runtime.drain(run_id=args.run_id)
        while True:
            run = runtime.get_run(args.run_id)
            if run is None:
                raise SystemExit(f"run_not_found:{args.run_id}")
            if not args.wait or run["status"] in {"completed", "failed", "awaiting_approval"}:
                _print(run, as_json=args.json)
                return
            time.sleep(args.poll_seconds)
        return

    if args.action == "status":
        run = runtime.get_run(args.run_id)
        if run is None:
            raise SystemExit(f"run_not_found:{args.run_id}")
        _print(run, as_json=args.json)
        return

    if args.action == "approve":
        approval = runtime.resolve_approval(args.approval_id, approved=not args.reject, resolved_by=args.by)
        _print(approval, as_json=args.json)
        return

    if args.action == "trace":
        _print({"run_id": args.run_id, "events": runtime.get_trace(args.run_id)}, as_json=args.json)
        return

    if args.action == "supervisor":
        runtime.drain(run_id=args.run_id)
        return

    raise SystemExit(2)
