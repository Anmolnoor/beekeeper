from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .contracts import AgentBlueprint
from .security import append_signed_audit_log
from .secret_manager import build_secret_provider, is_secret_reference
from .tenancy import HoneycombRecord, HiveRecord, OrganizationRecord, QueenInstanceRecord, UserOrgRole, UserRecord
from .vector_store import VectorStore, build_vector_store


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BeekeeperStore:
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for scope in ("orgs", "hives", "honeycombs", "queens", "templates", "profiles", "settings", "channels", "channel_pairings", "pairing_pending", "audit", "users", "roles", "chats", "user_memories"):
            (self.root / scope).mkdir(parents=True, exist_ok=True)
        self.vector_store: VectorStore = build_vector_store(
            os.getenv("BEEKEEPER_VECTOR_BACKEND", "memory"),
            collection=os.getenv("BEEKEEPER_VECTOR_COLLECTION", "beekeeper_user_memory"),
            url=os.getenv("BEEKEEPER_VECTOR_URL", "http://localhost:6333"),
        )

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _list_json(self, folder: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for file in sorted((self.root / folder).glob("*.json")):
            out.append(self._read_json(file))
        return out

    def create_org(self, name: str) -> OrganizationRecord:
        rec = OrganizationRecord(name=name)
        self._write_json(self.root / "orgs" / f"{rec.org_id}.json", rec.model_dump(mode="json"))
        return rec

    def list_orgs(self) -> list[OrganizationRecord]:
        return [OrganizationRecord.model_validate(row) for row in self._list_json("orgs")]

    def create_hive(self, org_id: str, name: str) -> HiveRecord:
        rec = HiveRecord(org_id=org_id, name=name)
        self._write_json(self.root / "hives" / f"{rec.hive_id}.json", rec.model_dump(mode="json"))
        return rec

    def list_hives(self, org_id: str | None = None) -> list[HiveRecord]:
        rows = [HiveRecord.model_validate(row) for row in self._list_json("hives")]
        if org_id:
            rows = [row for row in rows if row.org_id == org_id]
        return rows

    def get_hive(self, hive_id: str) -> HiveRecord | None:
        path = self.root / "hives" / f"{hive_id}.json"
        if not path.exists():
            return None
        return HiveRecord.model_validate(self._read_json(path))

    def create_honeycomb(self, hive_id: str, name: str, root_path: str) -> HoneycombRecord:
        rec = HoneycombRecord(hive_id=hive_id, name=name, root_path=root_path)
        self._write_json(self.root / "honeycombs" / f"{rec.honeycomb_id}.json", rec.model_dump(mode="json"))
        return rec

    def list_honeycombs(self, hive_id: str | None = None) -> list[HoneycombRecord]:
        rows = [HoneycombRecord.model_validate(row) for row in self._list_json("honeycombs")]
        if hive_id:
            rows = [row for row in rows if row.hive_id == hive_id]
        return rows

    def create_queen(self, hive_id: str, name: str, blueprint_id: str) -> QueenInstanceRecord:
        rec = QueenInstanceRecord(hive_id=hive_id, name=name, blueprint_id=blueprint_id)
        self._write_json(self.root / "queens" / f"{rec.queen_id}.json", rec.model_dump(mode="json"))
        return rec

    def list_queens(self, hive_id: str | None = None) -> list[QueenInstanceRecord]:
        rows = [QueenInstanceRecord.model_validate(row) for row in self._list_json("queens")]
        if hive_id:
            rows = [row for row in rows if row.hive_id == hive_id]
        return rows

    def save_template(self, name: str, blueprint: AgentBlueprint, profile_refs: dict[str, str] | None = None) -> str:
        template_id = f"tpl_{uuid4().hex[:12]}"
        payload = {
            "template_id": template_id,
            "name": name,
            "blueprint": blueprint.model_dump(mode="json"),
            "profile_refs": profile_refs or {},
            "created_at": _utcnow_iso(),
        }
        self._write_json(self.root / "templates" / f"{template_id}.json", payload)
        return template_id

    def list_templates(self) -> list[dict[str, Any]]:
        return self._list_json("templates")

    def export_template(self, template_id: str, destination: Path) -> Path:
        src = self.root / "templates" / f"{template_id}.json"
        payload = self._read_json(src)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        return destination

    def import_template(self, source: Path) -> str:
        payload = json.loads(source.read_text(encoding="utf-8"))
        template_id = str(payload.get("template_id") or f"tpl_{uuid4().hex[:12]}")
        payload["template_id"] = template_id
        self._write_json(self.root / "templates" / f"{template_id}.json", payload)
        return template_id

    def write_setting(self, key: str, value: Any) -> None:
        self._write_json(self.root / "settings" / f"{key}.json", {"key": key, "value": value, "updated_at": _utcnow_iso()})

    def read_setting(self, key: str, default: Any = None) -> Any:
        file = self.root / "settings" / f"{key}.json"
        if not file.exists():
            return default
        return self._read_json(file).get("value", default)

    def write_hive_setting(self, hive_id: str, key: str, value: Any) -> None:
        path = self.root / "hives" / hive_id / "settings" / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json(path, {"key": key, "value": value, "updated_at": _utcnow_iso()})

    def read_hive_setting(self, hive_id: str, key: str, default: Any = None) -> Any:
        path = self.root / "hives" / hive_id / "settings" / f"{key}.json"
        if not path.exists():
            return default
        return self._read_json(path).get("value", default)

    def get_hive_id_for_honeycomb_root(self, honeycomb_root: str) -> str | None:
        """Resolve hive_id from honeycomb root path by matching HoneycombRecord.root_path."""
        root_resolved = str(Path(honeycomb_root).resolve())
        for row in self._list_json("honeycombs"):
            rec = HoneycombRecord.model_validate(row)
            if str(Path(rec.root_path).resolve()) == root_resolved:
                return rec.hive_id
        return None

    def resolve_llm_model(self, hive_id: str | None = None, honeycomb_root: str | None = None) -> str | None:
        """Resolve llm_model: hive-level first (if hive_id or honeycomb_root), then global."""
        h_id = hive_id
        if not h_id and honeycomb_root:
            h_id = self.get_hive_id_for_honeycomb_root(honeycomb_root)
        if h_id:
            val = self.read_hive_setting(h_id, "llm_model")
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict) and val.get("value"):
                return str(val["value"]).strip() or None
        val = self.read_setting("llm_model")
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict) and val.get("value"):
            return str(val["value"]).strip() or None
        return None

    def list_settings(self) -> list[dict[str, Any]]:
        return self._list_json("settings")

    def create_pairing_code(self, channel: str, expires_minutes: int = 10) -> str:
        """Generate a 6-digit pairing code for DM pairing. User enters this in DM to pair. Returns the code."""
        import random
        code = "".join(str(random.randint(0, 9)) for _ in range(6))
        from datetime import timedelta
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)).isoformat()
        (self.root / "pairing_pending").mkdir(parents=True, exist_ok=True)
        path = self.root / "pairing_pending" / f"{channel}_{code}.json"
        self._write_json(path, {"channel": channel, "code": code, "expires_at": expires_at, "created_at": _utcnow_iso()})
        return code

    def validate_pairing_code(self, channel: str, user_id: str, code: str) -> bool:
        """Validate pairing code and mark user as paired. Returns True if valid."""
        path = self.root / "pairing_pending" / f"{channel}_{code}.json"
        if not path.exists():
            return False
        try:
            data = self._read_json(path)
        except Exception:
            return False
        if data.get("channel") != channel or data.get("code") != code:
            return False
        from datetime import datetime as dt
        try:
            exp = dt.fromisoformat(data.get("expires_at", "2000-01-01"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                path.unlink(missing_ok=True)
                return False
        except Exception:
            return False
        path.unlink(missing_ok=True)
        key = f"{channel}_{user_id}"
        pair_path = self.root / "channel_pairings" / f"{key}.json"
        self._write_json(pair_path, {"channel": channel, "user_id": user_id, "paired_at": _utcnow_iso(), "paired": True})
        return True

    def is_dm_paired(self, channel: str, user_id: str) -> bool:
        """Check if user is paired for DM."""
        key = f"{channel}_{user_id}"
        path = self.root / "channel_pairings" / f"{key}.json"
        if not path.exists():
            return False
        try:
            data = self._read_json(path)
            return bool(data.get("paired"))
        except Exception:
            return False

    _CHANNEL_SECRET_KEYS = frozenset({
        "slack_bot_token", "slack_signing_secret", "slack_client_secret",
        "telegram_bot_token", "telegram_secret_token",
        "discord_bot_token", "discord_public_key",
        "whatsapp_access_token", "whatsapp_app_secret", "whatsapp_verify_token",
    })

    def write_channel_config(self, channel: str, payload: dict[str, Any]) -> None:
        from .channel_auth import encrypt_secret
        encrypted = dict(payload)
        for key in self._CHANNEL_SECRET_KEYS:
            if key in encrypted and encrypted[key]:
                raw_value = str(encrypted[key])
                if is_secret_reference(raw_value):
                    encrypted[key] = raw_value
                else:
                    encrypted[key] = encrypt_secret(raw_value)
        body = {"channel": channel, "payload": encrypted, "updated_at": _utcnow_iso()}
        self._write_json(self.root / "channels" / f"{channel}.json", body)

    def list_channel_configs(self) -> list[dict[str, Any]]:
        configs = self._list_json("channels")
        for c in configs:
            payload = c.get("payload", {})
            for key in self._CHANNEL_SECRET_KEYS:
                if key in payload and payload[key]:
                    payload = dict(payload)
                    payload[key] = "***"
                    c["payload"] = payload
                    break
        return configs

    def get_channel_config_decrypted(self, channel: str) -> dict[str, Any] | None:
        path = self.root / "channels" / f"{channel}.json"
        if not path.exists():
            return None
        from .channel_auth import decrypt_secret
        body = self._read_json(path)
        payload = body.get("payload", {})
        decrypted = dict(payload)
        secret_provider = None
        for key in self._CHANNEL_SECRET_KEYS:
            if key in decrypted and decrypted[key] and decrypted[key] != "***":
                raw_value = str(decrypted[key])
                if is_secret_reference(raw_value):
                    try:
                        secret_provider = secret_provider or build_secret_provider()
                        decrypted[key] = secret_provider.resolve(raw_value)
                    except Exception:
                        decrypted[key] = raw_value
                else:
                    decrypted[key] = decrypt_secret(raw_value)
        return decrypted

    def append_audit_event(self, kind: str, payload: dict[str, Any]) -> None:
        path = self.root / "audit" / f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
        append_signed_audit_log(path, {"kind": kind, "payload": payload})

    def create_user(self, email: str, password_hash: str) -> UserRecord:
        rec = UserRecord(email=email, password_hash=password_hash)
        self._write_json(self.root / "users" / f"{rec.user_id}.json", rec.model_dump(mode="json"))
        return rec

    def get_user_by_id(self, user_id: str) -> UserRecord | None:
        path = self.root / "users" / f"{user_id}.json"
        if not path.exists():
            return None
        return UserRecord.model_validate(self._read_json(path))

    def get_user_by_email(self, email: str) -> UserRecord | None:
        for row in self._list_json("users"):
            if row.get("email", "").lower() == email.lower():
                return UserRecord.model_validate(row)
        return None

    def list_users(self) -> list[UserRecord]:
        return [UserRecord.model_validate(row) for row in self._list_json("users")]

    def assign_org_role(self, user_id: str, org_id: str, role: str = "admin") -> UserOrgRole:
        key = f"{user_id}_{org_id}"
        rec = UserOrgRole(user_id=user_id, org_id=org_id, role=role)
        self._write_json(self.root / "roles" / f"{key}.json", rec.model_dump(mode="json"))
        return rec

    def get_user_org_roles(self, user_id: str) -> list[UserOrgRole]:
        roles: list[UserOrgRole] = []
        for file in (self.root / "roles").glob("*.json"):
            row = self._read_json(file)
            if row.get("user_id") == user_id:
                roles.append(UserOrgRole.model_validate(row))
        return roles

    def has_org_access(self, user_id: str, org_id: str, min_role: str = "viewer") -> bool:
        role_order = {"admin": 3, "member": 2, "viewer": 1}
        min_level = role_order.get(min_role, 0)
        for r in self.get_user_org_roles(user_id):
            if r.org_id == org_id and role_order.get(r.role, 0) >= min_level:
                return True
        return False

    def list_org_ids_for_user(self, user_id: str) -> list[str]:
        return [r.org_id for r in self.get_user_org_roles(user_id)]

    # --- Chat (OpenAI ChatGPT-style) ---

    def create_chat(self, user_id: str, title: str = "New Chat") -> dict[str, Any]:
        chat_id = f"chat_{uuid4().hex[:12]}"
        rec = {
            "chat_id": chat_id,
            "user_id": user_id,
            "title": title,
            "messages": [],
            "created_at": _utcnow_iso(),
            "updated_at": _utcnow_iso(),
        }
        self._write_json(self.root / "chats" / f"{chat_id}.json", rec)
        return rec

    def list_chats(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for file in (self.root / "chats").glob("*.json"):
            row = self._read_json(file)
            # Include user's chats and channel chats (source=whatsapp etc.)
            is_channel = row.get("source") and row.get("user_id") == "__channel__"
            if row.get("user_id") == user_id or is_channel:
                row.setdefault("pinned", False)
                out.append(row)
        # Sort: pinned first, then by updated_at (newest first)
        pinned = sorted([r for r in out if r.get("pinned")], key=lambda r: r.get("updated_at", "") or "", reverse=True)
        unpinned = sorted([r for r in out if not r.get("pinned")], key=lambda r: r.get("updated_at", "") or "", reverse=True)
        return (pinned + unpinned)[:limit]

    def get_or_create_channel_chat(self, source: str, title: str) -> dict[str, Any]:
        """Get or create a channel chat (e.g. WhatsApp). Visible to all users."""
        chat_id = f"chat_{source}"
        path = self.root / "chats" / f"{chat_id}.json"
        if path.exists():
            return self._read_json(path)
        rec = {
            "chat_id": chat_id,
            "user_id": "__channel__",
            "source": source,
            "title": title,
            "messages": [],
            "created_at": _utcnow_iso(),
            "updated_at": _utcnow_iso(),
        }
        self._write_json(path, rec)
        return rec

    def get_chat(self, chat_id: str) -> dict[str, Any] | None:
        path = self.root / "chats" / f"{chat_id}.json"
        if not path.exists():
            return None
        return self._read_json(path)

    def append_chat_message(
        self, chat_id: str, role: str, content: str, source: str | None = None
    ) -> dict[str, Any] | None:
        chat = self.get_chat(chat_id)
        if not chat:
            return None
        msg: dict[str, Any] = {"role": role, "content": content, "created_at": _utcnow_iso()}
        if source:
            msg["source"] = source
        chat.setdefault("messages", []).append(msg)
        chat["updated_at"] = _utcnow_iso()
        if role == "user" and (not chat.get("title") or chat.get("title") == "New Chat"):
            chat["title"] = (content[:60] + "…") if len(content) > 60 else content
        self._write_json(self.root / "chats" / f"{chat_id}.json", chat)
        return chat

    def update_chat_title(self, chat_id: str, title: str) -> dict[str, Any] | None:
        chat = self.get_chat(chat_id)
        if not chat:
            return None
        chat["title"] = title
        chat["updated_at"] = _utcnow_iso()
        self._write_json(self.root / "chats" / f"{chat_id}.json", chat)
        return chat

    def update_chat_pinned(self, chat_id: str, pinned: bool) -> dict[str, Any] | None:
        chat = self.get_chat(chat_id)
        if not chat:
            return None
        chat["pinned"] = bool(pinned)
        chat["updated_at"] = _utcnow_iso()
        self._write_json(self.root / "chats" / f"{chat_id}.json", chat)
        return chat

    def delete_chat(self, chat_id: str) -> bool:
        path = self.root / "chats" / f"{chat_id}.json"
        if not path.exists():
            return False
        path.unlink()
        return True

    # --- User memory (persistent context for better answers over time) ---

    def append_user_memory(self, user_id: str, content: str, chat_id: str | None = None) -> None:
        """Append a memory about the user. Used to personalize responses."""
        self._append_user_memory_internal(user_id, content, chat_id=chat_id)

    def _memory_ttl_days(self, tier: str | None, score: float | None) -> int:
        if tier == "profile_fact":
            ttl = 365
        elif tier == "project_preference":
            ttl = 180
        else:
            ttl = 30
        s = float(score or 0.0)
        if s < 0.75:
            ttl = min(ttl, 30)
        if tier == "ephemeral_note":
            ttl = min(ttl, 14)
        return max(1, ttl)

    def _parse_iso_dt(self, raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    def _is_memory_expired(self, row: dict[str, Any], now: datetime) -> bool:
        exp = self._parse_iso_dt(str(row.get("expires_at", "")) or None)
        if exp is None:
            return False
        return exp <= now

    def _cleanup_user_memories_file(self, user_id: str) -> None:
        path = self.root / "user_memories" / f"{user_id}.jsonl"
        if not path.exists():
            return
        now = datetime.now(timezone.utc)
        kept: list[dict[str, Any]] = []
        changed = False
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    changed = True
                    continue
                if self._is_memory_expired(row, now):
                    changed = True
                    continue
                kept.append(row)
        if not changed:
            return
        with path.open("w", encoding="utf-8") as f:
            for row in kept:
                f.write(json.dumps(row, ensure_ascii=True) + "\n")

    def _append_user_memory_internal(
        self,
        user_id: str,
        content: str,
        *,
        chat_id: str | None = None,
        tier: str | None = None,
        score: float | None = None,
    ) -> None:
        """Append a memory about the user. Used to personalize responses."""
        clean = content.strip()
        if not clean:
            return
        self._cleanup_user_memories_file(user_id)
        path = self.root / "user_memories" / f"{user_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        memory_id = f"mem_{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        ttl_days = self._memory_ttl_days(tier=tier, score=score)
        row = {
            "memory_id": memory_id,
            "content": clean,
            "chat_id": chat_id,
            "tier": tier or "project_preference",
            "score": float(score) if score is not None else None,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(days=ttl_days)).isoformat(),
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")
        self.vector_store.upsert(f"user:{user_id}:{memory_id}", clean)

    def list_user_memories(self, user_id: str, limit: int = 25) -> list[dict[str, Any]]:
        """List recent memories for a user, most recent first."""
        self._cleanup_user_memories_file(user_id)
        path = self.root / "user_memories" / f"{user_id}.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        with path.open("r", encoding="utf-8") as f:
            for line in reversed(f.readlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if self._is_memory_expired(row, now):
                    continue
                rows.append(row)
                if len(rows) >= limit:
                    break
        return rows

    def append_user_memory_with_metadata(
        self,
        user_id: str,
        content: str,
        *,
        chat_id: str | None = None,
        tier: str | None = None,
        score: float | None = None,
    ) -> None:
        self._append_user_memory_internal(
            user_id,
            content,
            chat_id=chat_id,
            tier=tier,
            score=score,
        )

    def search_user_memories(self, user_id: str, query: str, limit: int = 15) -> list[dict[str, Any]]:
        """Hybrid-ish retrieval over user memories with keyword and semantic signal."""
        recent = self.list_user_memories(user_id, limit=max(limit * 3, 40))
        if not query.strip() or not recent:
            return recent[:limit]
        query_l = query.lower()
        tokens = [t for t in query_l.replace("/", " ").replace("_", " ").split() if len(t) > 2]
        semantic_hits = self.vector_store.search_with_content(query, limit=max(limit * 2, 12))
        semantic_texts = {text for _, text in semantic_hits if text}
        scored: list[tuple[float, dict[str, Any]]] = []
        for idx, row in enumerate(recent):
            content = str(row.get("content", "")).strip()
            if not content:
                continue
            lower = content.lower()
            keyword = float(sum(1 for t in tokens if t in lower))
            semantic = 1.5 if content in semantic_texts else 0.0
            recency = max(0.05, 1.0 - (idx * 0.06))
            score = keyword + semantic + recency
            if score <= 0:
                continue
            scored.append((score, row))
        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _, row in scored:
            key = str(row.get("memory_id", ""))
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
            if len(out) >= limit:
                break
        return out
