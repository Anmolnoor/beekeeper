from __future__ import annotations

import json
from pathlib import Path

from .queen import QueenAgent, QueenConfig
from .store import BeekeeperStore


def main() -> None:
    queen = QueenAgent(QueenConfig(honeycomb_root=Path(".honeycomb")))
    store = BeekeeperStore(Path(".beekeeper_store"))
    exported = []
    for blueprint in queen.registry.blueprints.values():
        template_id = store.save_template(
            name=blueprint.name,
            blueprint=blueprint,
            profile_refs=blueprint.profile_bundle.model_dump(mode="json"),
        )
        exported.append({"template_id": template_id, "blueprint_id": blueprint.blueprint_id})
    print(json.dumps({"exported": exported}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
