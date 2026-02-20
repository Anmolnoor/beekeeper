from __future__ import annotations

import asyncio
import os

from .temporal_integration import TemporalBeehiveClient, TemporalConfig


async def _main() -> None:
    endpoint = os.getenv("BEEHIVE_TEMPORAL_ENDPOINT", "localhost:7233")
    client = TemporalBeehiveClient(
        TemporalConfig(
            endpoint=endpoint,
            namespace=os.getenv("BEEHIVE_TEMPORAL_NAMESPACE", "default"),
            task_queue=os.getenv("BEEHIVE_TEMPORAL_TASK_QUEUE", "beehive-queue"),
        )
    )
    print(f"temporal worker connecting to {endpoint}")
    await client.run_worker()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
