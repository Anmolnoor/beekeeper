from __future__ import annotations

import json
from pathlib import Path

from beehive.channels import ChatHub
from beehive.queen import QueenAgent, QueenConfig
from beehive.security import sign_payload, verify_payload
from beehive.store import BeekeeperStore


def test_blueprint_profiles_seeded(tmp_path: Path) -> None:
    queen = QueenAgent(QueenConfig(honeycomb_root=tmp_path / "honeycomb"))
    assert "blueprint.queen.default" in queen.registry.blueprints
    assert "blueprint.worker.web" in queen.registry.blueprints
    resolved = queen.registry.resolve_profiles("blueprint.worker.web")
    assert resolved.skill.skill_profile_id == "skill.research.web"
    assert resolved.abilities.abilities_profile_id == "abilities.default"


def test_multi_hive_store_and_templates(tmp_path: Path) -> None:
    store = BeekeeperStore(tmp_path / "store")
    org = store.create_org("Acme")
    hive = store.create_hive(org.org_id, "Ops")
    comb = store.create_honeycomb(hive.hive_id, "Ops Comb", str(tmp_path / "comb"))
    queen = QueenAgent(QueenConfig(honeycomb_root=tmp_path / "comb"))
    template_id = store.save_template("Default Queen", queen.registry.get_blueprint("blueprint.queen.default"))
    exported = store.export_template(template_id, tmp_path / "template-export.json")
    imported = store.import_template(exported)
    assert comb.hive_id == hive.hive_id
    assert template_id
    assert imported


def test_channel_hub_dispatch(tmp_path: Path) -> None:
    queen = QueenAgent(QueenConfig(honeycomb_root=tmp_path / "honeycomb"))
    hub = ChatHub(queen)
    payload = hub.dispatch("telegram", {"sender": "u1", "text": "hello queen"})
    assert payload["channel"] == "telegram"
    assert "response" in payload


def test_signed_audit_log(tmp_path: Path) -> None:
    event = {"kind": "policy_change", "value": {"strict": True}}
    signature = sign_payload(event)
    assert verify_payload(event, signature) is True
    assert verify_payload(event, signature + "0") is False
    audit_file = tmp_path / "audit.jsonl"
    audit_file.write_text(json.dumps({"seed": True}) + "\n", encoding="utf-8")
