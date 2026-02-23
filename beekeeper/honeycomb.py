from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .contracts import (
    ArtifactRef,
    HumanReviewRecord,
    PolicyDecision,
    ResultEnvelope,
    RoutingFeedback,
    Status,
    TaskEnvelope,
    WorkerKind,
    WorkerPerformanceRecord,
)
from .vector_store import VectorStore, build_vector_store


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HoneycombConfig:
    root_dir: Path
    vector_backend: str = "memory"
    vector_collection: str = "honeycomb_memory"
    vector_url: str = "http://localhost:6333"


class HoneycombStore:
    """
    Append-only honeycomb data plane:
    - events: telemetry and state transitions
    - artifacts: task reports and files
    - governance: policy decisions
    - graph: simple parent-child task edges
    - memory/vector: in-memory semantic index placeholder
    """

    def __init__(self, config: HoneycombConfig) -> None:
        self.root_dir = config.root_dir
        self.events_dir = self.root_dir / "events"
        self.artifacts_dir = self.root_dir / "artifacts"
        self.governance_dir = self.root_dir / "governance"
        self.graph_dir = self.root_dir / "graph"
        self.performance_dir = self.root_dir / "performance"
        self.optimizer_dir = self.root_dir / "optimizer"
        self.archive_dir = self.root_dir / "archive"
        self.human_review_dir = self.root_dir / "human_review"
        self.backlog_dir = self.root_dir / "backlog"
        self.sessions_dir = self.root_dir / "sessions"
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.governance_dir.mkdir(parents=True, exist_ok=True)
        self.graph_dir.mkdir(parents=True, exist_ok=True)
        self.performance_dir.mkdir(parents=True, exist_ok=True)
        self.optimizer_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.human_review_dir.mkdir(parents=True, exist_ok=True)
        self.backlog_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.vector_store: VectorStore = build_vector_store(
            config.vector_backend,
            collection=config.vector_collection,
            url=config.vector_url,
        )

    def _append_jsonl(self, path: Path, row: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not path.exists():
            return rows
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                row = line.strip()
                if not row:
                    continue
                payload = json.loads(row)
                if isinstance(payload, dict):
                    rows.append(payload)
        return rows

    def list_traces(self, limit: int = 100) -> list[str]:
        """List trace IDs from events dir, most recent first (by file mtime)."""
        if not self.events_dir.exists():
            return []
        files = sorted(
            self.events_dir.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return [f.stem for f in files[:limit]]

    def read_events(self, trace_id: str) -> list[dict[str, Any]]:
        """Read all events for a trace."""
        return self._read_jsonl(self.events_dir / f"{trace_id}.jsonl")

    def read_graph(self, trace_id: str) -> list[dict[str, Any]]:
        """Read graph edges (from_task_id, to_task_id) for a trace."""
        return self._read_jsonl(self.graph_dir / f"{trace_id}.jsonl")

    def write_event(self, trace_id: str, row: dict[str, Any]) -> None:
        payload = {"event_id": str(uuid4()), "at": utcnow_iso(), **row}
        self._append_jsonl(self.events_dir / f"{trace_id}.jsonl", payload)

    def write_task(self, task: TaskEnvelope) -> None:
        self.write_event(
            task.queen_trace_id,
            {
                "kind": "task",
                "stage": "task_state",
                "task_id": task.task_id,
                "status": task.status.value,
                "worker_kind": task.worker_kind.value,
                "task": task.model_dump(mode="json"),
            },
        )
        if task.parent_id:
            self._append_jsonl(
                self.graph_dir / f"{task.queen_trace_id}.jsonl",
                {"from_task_id": task.parent_id, "to_task_id": task.task_id, "at": utcnow_iso()},
            )

    def write_policy_decision(self, decision: PolicyDecision, trace_id: str) -> None:
        self._append_jsonl(self.governance_dir / f"{trace_id}.jsonl", decision.model_dump(mode="json"))
        self.write_event(
            trace_id,
            {
                "kind": "policy_decision",
                "task_id": decision.task_id,
                "status": decision.status,
                "flags": decision.guardrail_flags,
                "requires_human_approval": decision.requires_human_approval,
            },
        )

    def write_artifact(self, trace_id: str, task_id: str, content: str, kind: str = "report") -> ArtifactRef:
        artifact_id = str(uuid4())
        artifact_path = self.artifacts_dir / f"{artifact_id}.txt"
        artifact_path.write_text(content, encoding="utf-8")
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        artifact = ArtifactRef(task_id=task_id, kind=kind, location=str(artifact_path), checksum=checksum)
        self.write_event(
            trace_id,
            {"kind": "artifact", "task_id": task_id, "artifact_id": artifact.artifact_id, "location": artifact.location},
        )
        return artifact

    def write_result(self, trace_id: str, result: ResultEnvelope) -> None:
        self.write_event(
            trace_id,
            {
                "kind": "result",
                "stage": "task_result",
                "task_id": result.task_id,
                "status": result.status.value,
                "worker_kind": result.worker_kind.value,
                "output_schema": result.output_schema,
                "result": result.model_dump(mode="json"),
            },
        )
        searchable = " ".join([str(v) for v in result.output.values()])
        self.vector_store.upsert(result.task_id, searchable)

    def write_worker_performance(self, trace_id: str, record: WorkerPerformanceRecord) -> None:
        self._append_jsonl(self.performance_dir / f"{trace_id}.jsonl", record.model_dump(mode="json"))
        self.write_event(
            trace_id,
            {
                "kind": "worker_performance",
                "task_id": record.task_id,
                "worker_kind": record.worker_kind.value,
                "quality_score": record.quality_score,
                "latency_ms": record.latency_ms,
                "estimated_cost_usd": record.estimated_cost_usd,
                "status": record.status.value,
                "retry_category": record.retry_category.value if record.retry_category else None,
            },
        )

    def _routing_feedback_path(self) -> Path:
        return self.optimizer_dir / "routing_feedback.json"

    def _human_review_path(self, review_id: str) -> Path:
        return self.human_review_dir / f"{review_id}.json"

    def enqueue_review(self, *, task: TaskEnvelope, reason: str) -> HumanReviewRecord:
        existing = self.find_review_for_task(task.task_id, pending_only=True)
        if existing is not None:
            return existing
        review = HumanReviewRecord(
            task_id=task.task_id,
            trace_id=task.queen_trace_id,
            task_type=task.task_type,
            reason=reason,
            payload=task.payload,
            status="pending",
        )
        self._human_review_path(review.review_id).write_text(
            json.dumps(review.model_dump(mode="json"), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        self.write_event(
            task.queen_trace_id,
            {
                "kind": "human_review",
                "action": "enqueued",
                "review_id": review.review_id,
                "task_id": task.task_id,
                "reason": reason,
            },
        )
        try:
            from .notifications import send_approval_notification
            send_approval_notification(review.review_id, task.task_id, reason)
        except Exception:
            pass
        return review

    def get_review(self, review_id: str) -> HumanReviewRecord | None:
        path = self._human_review_path(review_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return HumanReviewRecord.model_validate(payload)

    def list_pending_reviews(self) -> list[HumanReviewRecord]:
        pending: list[HumanReviewRecord] = []
        for item in self.human_review_dir.glob("*.json"):
            payload = json.loads(item.read_text(encoding="utf-8"))
            record = HumanReviewRecord.model_validate(payload)
            if record.status == "pending":
                pending.append(record)
        pending.sort(key=lambda record: record.requested_at)
        return pending

    def find_review_for_task(self, task_id: str, pending_only: bool = False) -> HumanReviewRecord | None:
        for item in self.human_review_dir.glob("*.json"):
            payload = json.loads(item.read_text(encoding="utf-8"))
            record = HumanReviewRecord.model_validate(payload)
            if record.task_id != task_id:
                continue
            if pending_only and record.status != "pending":
                continue
            return record
        return None

    def resolve_review(self, review_id: str, *, approved: bool, approver: str, note: str | None = None) -> HumanReviewRecord:
        review = self.get_review(review_id)
        if review is None:
            raise KeyError(f"unknown_review_id={review_id}")
        if review.status != "pending":
            return review
        review.status = "approved" if approved else "rejected"
        review.resolved_by = approver
        review.resolution_note = note
        review.resolved_at = datetime.now(timezone.utc)
        self._human_review_path(review_id).write_text(
            json.dumps(review.model_dump(mode="json"), ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        self.write_event(
            review.trace_id,
            {
                "kind": "human_review",
                "action": "approved" if approved else "rejected",
                "review_id": review.review_id,
                "task_id": review.task_id,
                "resolved_by": approver,
            },
        )
        return review

    def read_routing_feedback(self) -> dict[str, RoutingFeedback]:
        path = self._routing_feedback_path()
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        feedback: dict[str, RoutingFeedback] = {}
        for key, payload in raw.items():
            feedback[key] = RoutingFeedback.model_validate(payload)
        return feedback

    def write_routing_feedback(self, feedback: dict[str, RoutingFeedback]) -> None:
        serializable = {key: value.model_dump(mode="json") for key, value in feedback.items()}
        self._routing_feedback_path().write_text(json.dumps(serializable, ensure_ascii=True, indent=2), encoding="utf-8")

    def record_routing_outcome(
        self,
        *,
        worker_kind: WorkerKind,
        intent: str | None = None,
        skill_id: str | None = None,
        quality_score: float,
        latency_ms: int,
        cost_usd: float,
        success: bool,
    ) -> RoutingFeedback:
        def _update_bucket(bucket: dict[str, float], quality: float, latency: int, cost: float, was_success: bool) -> dict[str, float]:
            total_runs = int(bucket.get("total_runs", 0)) + 1
            success_runs = int(bucket.get("success_runs", 0)) + (1 if was_success else 0)
            prev_runs = max(0, total_runs - 1)
            avg_quality = ((float(bucket.get("avg_quality", 0.0)) * prev_runs) + quality) / total_runs
            avg_latency_ms = ((float(bucket.get("avg_latency_ms", 0.0)) * prev_runs) + latency) / total_runs
            avg_cost_usd = ((float(bucket.get("avg_cost_usd", 0.0)) * prev_runs) + cost) / total_runs
            return {
                "total_runs": float(total_runs),
                "success_runs": float(success_runs),
                "avg_quality": avg_quality,
                "avg_latency_ms": avg_latency_ms,
                "avg_cost_usd": avg_cost_usd,
            }

        current = self.read_routing_feedback()
        key = worker_kind.value
        existing = current.get(key, RoutingFeedback(worker_kind=worker_kind))
        next_total = existing.total_runs + 1
        next_success = existing.success_runs + (1 if success else 0)
        existing.avg_quality = ((existing.avg_quality * existing.total_runs) + quality_score) / next_total
        existing.avg_latency_ms = ((existing.avg_latency_ms * existing.total_runs) + latency_ms) / next_total
        existing.avg_cost_usd = ((existing.avg_cost_usd * existing.total_runs) + cost_usd) / next_total
        smoothing = 0.3
        if existing.total_runs == 0:
            existing.recent_quality_ema = quality_score
        else:
            existing.recent_quality_ema = (smoothing * quality_score) + ((1.0 - smoothing) * existing.recent_quality_ema)
        if intent:
            existing.by_intent[intent] = _update_bucket(existing.by_intent.get(intent, {}), quality_score, latency_ms, cost_usd, success)
        if skill_id:
            existing.by_skill[skill_id] = _update_bucket(existing.by_skill.get(skill_id, {}), quality_score, latency_ms, cost_usd, success)
        existing.total_runs = next_total
        existing.success_runs = next_success
        existing.updated_at = datetime.now(timezone.utc)
        current[key] = existing
        self.write_routing_feedback(current)
        return existing

    def top_worker_kinds(self) -> list[WorkerKind]:
        feedback = self.read_routing_feedback()
        if not feedback:
            return [WorkerKind.web_search, WorkerKind.heavy_compute, WorkerKind.audit]
        ranked = sorted(
            feedback.values(),
            key=lambda row: (
                (row.success_runs / row.total_runs) if row.total_runs else 0.0,
                row.avg_quality,
                -row.avg_latency_ms,
                -row.avg_cost_usd,
            ),
            reverse=True,
        )
        return [entry.worker_kind for entry in ranked]

    def enforce_retention_lifecycle(self, *, hot_days: int = 30, warm_days: int = 90) -> dict[str, int]:
        """
        Move old artifacts into warm/cold archive tiers and emit retention events.
        """
        now = datetime.now(timezone.utc)
        warm_threshold = now - timedelta(days=hot_days)
        cold_threshold = now - timedelta(days=warm_days)
        warm_dir = self.archive_dir / "warm"
        cold_dir = self.archive_dir / "cold"
        warm_dir.mkdir(parents=True, exist_ok=True)
        cold_dir.mkdir(parents=True, exist_ok=True)
        moved = {"warm": 0, "cold": 0}
        for artifact in self.artifacts_dir.glob("*.txt"):
            modified = datetime.fromtimestamp(artifact.stat().st_mtime, tz=timezone.utc)
            target: Path | None = None
            tier: str | None = None
            if modified <= cold_threshold:
                target = cold_dir / artifact.name
                tier = "cold"
            elif modified <= warm_threshold:
                target = warm_dir / artifact.name
                tier = "warm"
            if target is None or tier is None:
                continue
            artifact.rename(target)
            moved[tier] += 1
            self.write_event(
                "retention_lifecycle",
                {
                    "kind": "retention",
                    "artifact": target.name,
                    "tier": tier,
                    "moved_at": utcnow_iso(),
                },
            )
        return moved

    def semantic_search(self, query: str, limit: int = 5) -> list[str]:
        return self.vector_store.search(query, limit=limit)

    def semantic_search_with_content(self, query: str, limit: int = 5) -> list[tuple[str, str]]:
        """Return [(item_id, text), ...] for context injection into prompts."""
        return self.vector_store.search_with_content(query, limit=limit)

    def _backlog_path(self) -> Path:
        return self.backlog_dir / "tasks.jsonl"

    def push_backlog_task(
        self,
        *,
        intent: str,
        payload: dict[str, Any],
        source: str = "pulse_manual",
        priority: int = 0,
    ) -> str:
        """Append a task to the backlog. Returns task_id."""
        task_id = str(uuid4())
        row = {
            "task_id": task_id,
            "intent": intent,
            "payload": dict(payload),
            "source": source,
            "priority": priority,
            "created_at": utcnow_iso(),
            "status": "pending",
        }
        self._append_jsonl(self._backlog_path(), row)
        return task_id

    def pull_backlog_tasks(self, limit: int = 5) -> list[dict[str, Any]]:
        """Pull up to limit pending tasks from the backlog. Removes them from the queue."""
        path = self._backlog_path()
        if not path.exists():
            return []
        rows = self._read_jsonl(path)
        pending = [r for r in rows if r.get("status") == "pending"]
        pending.sort(key=lambda r: (-r.get("priority", 0), r.get("created_at", "")))
        to_run = pending[:limit]
        to_keep = [r for r in rows if r not in to_run]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for r in to_keep:
                f.write(json.dumps(r, ensure_ascii=True) + "\n")
        return to_run

    def backlog_size(self) -> int:
        """Return count of pending tasks in backlog."""
        path = self._backlog_path()
        if not path.exists():
            return 0
        return sum(1 for r in self._read_jsonl(path) if r.get("status") == "pending")

    # --- Session tree and branching ---

    def _sessions_index_path(self) -> Path:
        return self.sessions_dir / "index.jsonl"

    def create_session(self, parent_session_id: str | None = None) -> str:
        """Create a new session. Returns session_id. Optionally set parent_session_id for branching."""
        session_id = f"sess_{uuid4().hex[:12]}"
        row = {
            "session_id": session_id,
            "created_at": utcnow_iso(),
            "traces": [],
        }
        if parent_session_id:
            row["parent_session_id"] = parent_session_id
        path = self.sessions_dir / f"{session_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row, ensure_ascii=True, indent=2), encoding="utf-8")
        self._append_jsonl(self._sessions_index_path(), {"session_id": session_id, "created_at": utcnow_iso()})
        return session_id

    def link_trace_to_session(
        self,
        session_id: str,
        trace_id: str,
        parent_trace_id: str | None = None,
    ) -> None:
        """Link a trace to a session (and optionally to a parent trace for branching)."""
        path = self.sessions_dir / f"{session_id}.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        traces = list(data.get("traces", []))
        entry = {"trace_id": trace_id, "parent_trace_id": parent_trace_id, "at": utcnow_iso()}
        traces.append(entry)
        data["traces"] = traces
        path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")
        self.write_event(
            trace_id,
            {"kind": "session_link", "session_id": session_id, "parent_trace_id": parent_trace_id},
        )

    def list_sessions(self, limit: int = 50) -> list[str]:
        """List session IDs, most recent first."""
        path = self._sessions_index_path()
        if not path.exists():
            return []
        rows = self._read_jsonl(path)
        return [r["session_id"] for r in reversed(rows[-limit:]) if r.get("session_id")]

    def get_session_traces(self, session_id: str) -> list[dict[str, Any]]:
        """Get trace entries for a session (trace_id, parent_trace_id, at)."""
        path = self.sessions_dir / f"{session_id}.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("traces", []))

    # --- Queen Memories ---

    def _queen_memories_path(self) -> Path:
        return self.root_dir / "queen_memories.jsonl"

    def write_queen_memory(
        self,
        content: str,
        source: str = "queen",
        tags: list[str] | None = None,
    ) -> str:
        """Persist a memory entry to queen_memories.jsonl. Returns memory_id."""
        memory_id = str(uuid4())
        row: dict[str, Any] = {
            "memory_id": memory_id,
            "content": content,
            "source": source,
            "tags": tags or [],
            "created_at": utcnow_iso(),
        }
        self._append_jsonl(self._queen_memories_path(), row)
        # Also index into vector store for semantic recall
        self.vector_store.upsert(memory_id, content)
        return memory_id

    def read_queen_memories(
        self,
        limit: int = 50,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read persisted Queen memories, most recent first. Optionally filter by tag."""
        rows = self._read_jsonl(self._queen_memories_path())
        if tag:
            rows = [r for r in rows if tag in (r.get("tags") or [])]
        return list(reversed(rows[-limit:]))

    def compact_traces(
        self,
        *,
        trace_id: str | None = None,
        all_traces: bool = False,
        min_age_hours: float = 0,
    ) -> dict[str, Any]:
        """Compact trace files. See beekeeper.trace_compaction.compact_traces."""
        from .trace_compaction import compact_traces as _compact
        return _compact(
            self.root_dir,
            trace_id=trace_id,
            all_traces=all_traces,
            min_age_hours=min_age_hours,
        )

    def get_trace_tree(self, trace_id: str) -> dict[str, Any]:
        """Get trace with its children (from session links). Returns {trace_id, parent_trace_id, children: [...]}."""
        events = self.read_events(trace_id)
        parent_trace_id: str | None = None
        session_id: str | None = None
        for ev in events:
            if ev.get("kind") == "session_link":
                parent_trace_id = ev.get("parent_trace_id")
                session_id = ev.get("session_id")
                break
        children: list[dict[str, Any]] = []
        if session_id:
            for entry in self.get_session_traces(session_id):
                if entry.get("parent_trace_id") == trace_id:
                    children.append(self.get_trace_tree(entry["trace_id"]))
        return {
            "trace_id": trace_id,
            "parent_trace_id": parent_trace_id,
            "session_id": session_id,
            "children": children,
        }
