from pathlib import Path

import pytest

from beekeeper.honeycomb import HoneycombConfig, HoneycombStore
from beekeeper.pulse import PulseConfig, run_pulse_loop, tick


class _FakeQueen:
    def __init__(self, _config: object = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def run_autonomous(self, source: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append((source, payload))
        return {
            "trace_id": "trace_test",
            "blocked": False,
            "results": [{"output": {"summary": "ok"}}],
        }


def test_tick_returns_heartbeat_stats(tmp_path: Path) -> None:
    honeycomb_root = tmp_path / "honeycomb"
    jobs_path = honeycomb_root / "pulse" / "jobs.json"
    honeycomb = HoneycombStore(HoneycombConfig(root_dir=honeycomb_root))
    queen = _FakeQueen()
    config = PulseConfig(honeycomb_root=honeycomb_root, jobs_path=jobs_path)
    jobs = [
        {
            "name": "heartbeat-job",
            "enabled": True,
            "schedule": {"kind": "every", "everyMs": 60000},
            "payload": {"kind": "queen", "query": "hello"},
        }
    ]

    stats = tick(config, queen, honeycomb, jobs)

    assert stats["jobs_total"] == 1
    assert stats["jobs_enabled"] == 1
    assert stats["jobs_due"] == 1
    assert stats["jobs_ran"] == 1
    assert stats["backlog_size"] == 0
    assert stats["ran_job_names"] == ["heartbeat-job"]


def test_run_pulse_loop_writes_heartbeat_each_tick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    honeycomb_root = tmp_path / "honeycomb"
    config = PulseConfig(honeycomb_root=honeycomb_root)

    monkeypatch.setattr("beekeeper.pulse.QueenAgent", _FakeQueen)
    monkeypatch.setattr("beekeeper.pulse._load_jobs", lambda _path: [])
    monkeypatch.setattr("beekeeper.pulse.time.sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        run_pulse_loop(config)

    honeycomb = HoneycombStore(HoneycombConfig(root_dir=honeycomb_root))
    events = honeycomb.read_events("pulse_updates")
    heartbeats = [event for event in events if event.get("kind") == "pulse_heartbeat"]
    assert len(heartbeats) == 1
    heartbeat = heartbeats[0]
    assert heartbeat["interval_seconds"] == 120.0
    assert heartbeat["jobs_total"] == 0
    assert heartbeat["jobs_due"] == 0
    assert heartbeat["jobs_ran"] == 0
    assert "tick_started_at" in heartbeat
    assert "tick_finished_at" in heartbeat
    assert "duration_ms" in heartbeat


def test_run_pulse_loop_keeps_tick_error_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    honeycomb_root = tmp_path / "honeycomb"
    config = PulseConfig(honeycomb_root=honeycomb_root)

    monkeypatch.setattr("beekeeper.pulse.QueenAgent", _FakeQueen)
    monkeypatch.setattr("beekeeper.pulse._load_jobs", lambda _path: [])
    monkeypatch.setattr("beekeeper.pulse.tick", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr("beekeeper.pulse.time.sleep", lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        run_pulse_loop(config)

    honeycomb = HoneycombStore(HoneycombConfig(root_dir=honeycomb_root))
    events = honeycomb.read_events("pulse_updates")
    kinds = [event.get("kind") for event in events]
    assert "tick_error" in kinds
    assert "pulse_heartbeat" in kinds


def test_runner_pulse_default_interval_is_120(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from beekeeper import runner

    captured: dict[str, object] = {}

    def _capture(config: PulseConfig) -> None:
        captured["interval_seconds"] = config.interval_seconds
        captured["honeycomb_root"] = config.honeycomb_root

    monkeypatch.setattr(runner, "run_pulse_loop", _capture)
    monkeypatch.setattr(
        "sys.argv",
        ["beekeeper", "pulse", "--honeycomb-root", str(tmp_path / "honeycomb")],
    )

    runner.main()

    assert captured["interval_seconds"] == 120.0
