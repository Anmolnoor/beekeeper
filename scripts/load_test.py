from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from beehive.queen import QueenAgent, QueenConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple Beekeeper/Queen load harness.")
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--intent", default="research_topic")
    parser.add_argument("--honeycomb-root", default=".honeycomb")
    args = parser.parse_args()

    queen = QueenAgent(QueenConfig(honeycomb_root=Path(args.honeycomb_root)))
    timings: list[float] = []
    for i in range(args.runs):
        started = time.perf_counter()
        queen.run(intent=args.intent, payload={"query": f"load test run {i}"})
        timings.append((time.perf_counter() - started) * 1000.0)
    summary = {
        "runs": args.runs,
        "latency_ms_avg": round(statistics.mean(timings), 2),
        "latency_ms_p95": round(sorted(timings)[int(len(timings) * 0.95) - 1], 2),
        "latency_ms_max": round(max(timings), 2),
    }
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
