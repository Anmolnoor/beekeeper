from __future__ import annotations

import argparse
import time

from ..config.settings import Phase1Settings
from .service import Phase1RuntimeService


def main() -> None:
    parser = argparse.ArgumentParser(prog="beekeeper-supervisor")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    settings = Phase1Settings()
    runtime = Phase1RuntimeService(settings)
    if args.watch:
        while True:
            runtime.drain(run_id=args.run_id)
            time.sleep(settings.supervisor_poll_seconds)
    runtime.drain(run_id=args.run_id)


if __name__ == "__main__":
    main()
