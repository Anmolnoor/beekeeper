from __future__ import annotations


def main() -> None:
    # Transitional shim: keep current CLI behavior while command modules migrate out of runner.py.
    from ..runner import main as legacy_main

    legacy_main()

