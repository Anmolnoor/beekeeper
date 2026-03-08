from __future__ import annotations

from typing import Any

from ..data_plane.models import TraceEventRecord, new_id
from ..data_plane.repositories.runtime_state import RuntimeStateRepository


class TraceEventStore:
    def __init__(self, repository: RuntimeStateRepository) -> None:
        self.repository = repository

    def append(
        self,
        *,
        run_id: str,
        event_type: str,
        actor: str,
        payload: dict[str, Any],
        job_id: str | None = None,
        attempt_id: str | None = None,
        parent_event_id: str | None = None,
    ) -> dict[str, Any]:
        event = TraceEventRecord(
            event_id=new_id("evt"),
            run_id=run_id,
            job_id=job_id,
            attempt_id=attempt_id,
            parent_event_id=parent_event_id,
            event_type=event_type,
            actor=actor,
            payload_json=payload,
        )
        return self.repository.append_trace_event(event)

    def replay(self, run_id: str) -> list[dict[str, Any]]:
        return self.repository.list_trace_events(run_id)
