from __future__ import annotations

import json
import os
from pathlib import Path

from .queen import QueenAgent, QueenConfig


def main() -> None:
    root = Path(".honeycomb")
    queen = QueenAgent(
        QueenConfig(
            honeycomb_root=root,
            max_reruns=1,
            ollama_base_url=os.getenv("BEEHIVE_OLLAMA_BASE_URL", "http://100.99.106.59:11434"),
        )
    )
    scenarios = [
        (
            "web_search",
            "research_topic",
            {"query": "best AI agent sdk and open source agent patterns", "domains": ["github.com", "openai.com"]},
        ),
        (
            "heavy_compute",
            "heavy_compute",
            {"numbers": [3, 7, 11, 15, 19], "operation": "distribution_summary"},
        ),
        (
            "audit",
            "audit_result",
            {"target_task_id": "demo-task", "target_result": {"confidence": 0.72, "status": "success"}},
        ),
        (
            "hitl_required",
            "research_topic",
            {
                "query": "draft runbook for production change",
                "action": "payment_action",
                "requires_human_approval": True,
            },
        ),
        (
            "hitl_approved",
            "research_topic",
            {
                "query": "draft runbook for production change",
                "action": "payment_action",
                "requires_human_approval": True,
                "human_approved": True,
                "human_approver": "demo-operator",
            },
        ),
    ]
    for label, intent, payload in scenarios:
        output = queen.run(intent=intent, payload=payload)
        print(f"\n=== scenario: {label} ===")
        print(json.dumps(output, indent=2))
    print("\n=== routing_feedback ===")
    print(json.dumps({k: v.model_dump(mode="json") for k, v in queen.honeycomb.read_routing_feedback().items()}, indent=2))


if __name__ == "__main__":
    main()
