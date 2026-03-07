from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .store import BeekeeperStore


@dataclass(frozen=True)
class TenancyContext:
    org_id: str | None
    hive_id: str | None
    honeycomb_root: str

    @property
    def org_scope(self) -> str:
        return self.org_id or "__default__"


def resolve_tenancy_context(store: BeekeeperStore, honeycomb_root: str) -> TenancyContext:
    hive_id = store.get_hive_id_for_honeycomb_root(honeycomb_root)
    org_id: str | None = None
    if hive_id:
        hive = store.get_hive(hive_id)
        if hive is not None:
            org_id = hive.org_id
    root = Path(honeycomb_root)
    return TenancyContext(
        org_id=org_id,
        hive_id=hive_id,
        honeycomb_root=str(root),
    )
