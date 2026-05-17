from __future__ import annotations

from ...runner import _run_doctor, _run_smoke_test


def run_doctor(*, auto_start: bool = False, json_output: bool = False) -> int:
    return _run_doctor(auto_start=auto_start, json_output=json_output)


def run_smoke(args) -> int:
    return _run_smoke_test(args)

