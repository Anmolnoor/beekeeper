from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TraceSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    started_at: datetime
    ended_at: datetime | None = None


class Tracer:
    def __init__(self) -> None:
        self._events: list[dict] = []

    @property
    def events(self) -> list[dict]:
        return self._events

    @contextmanager
    def span(
        self,
        trace_id: str,
        name: str,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        span_id = str(uuid4())
        start = utcnow()
        attrs = attributes or {}
        self._events.append(
            {
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "name": name,
                "phase": "start",
                "at": start.isoformat(),
                "attributes": attrs,
            }
        )
        try:
            yield span_id
        finally:
            self._events.append(
                {
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "parent_span_id": parent_span_id,
                    "name": name,
                    "phase": "end",
                    "at": utcnow().isoformat(),
                    "attributes": attrs,
                }
            )
