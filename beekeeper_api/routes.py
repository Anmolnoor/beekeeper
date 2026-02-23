from __future__ import annotations

import asyncio
import fnmatch
import hmac
import json
import queue
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from beekeeper.audit_logger import log_service_call
from beekeeper.channels import ChatHub
from beekeeper.ops import compute_ops_metrics
from beekeeper.queen import QueenAgent, QueenConfig
from beekeeper.queen_updates import list_queen_updates
from beekeeper.store import BeekeeperStore
from beekeeper.tenancy import UserRecord

from .auth import create_access_token, get_current_user, hash_password, verify_password
from .deps import get_honeycomb, get_store, get_worker_registry
from .setup import is_fresh_install, is_setup_done, mark_setup_done, read_env_from_file, write_env_from_config

router = APIRouter()


def _get_whatsapp_config() -> dict[str, Any] | None:
    """WhatsApp config from store + env (env overrides). Allows full config via .env."""
    import os

    store = get_store()
    config = dict(store.get_channel_config_decrypted("whatsapp") or {})
    env_keys = [
        ("WHATSAPP_ACCESS_TOKEN", "whatsapp_access_token"),
        ("WHATSAPP_PHONE_NUMBER_ID", "whatsapp_phone_number_id"),
        ("WHATSAPP_APP_SECRET", "whatsapp_app_secret"),
        ("WHATSAPP_VERIFY_TOKEN", "whatsapp_verify_token"),
    ]
    for env_name, config_key in env_keys:
        val = os.getenv(env_name)
        if val:
            config[config_key] = val
    return config if (config.get("whatsapp_access_token") or config.get("whatsapp_verify_token")) else None


def _can_access_chat(chat: dict[str, Any], user_id: str) -> bool:
    """Allow access if user owns the chat or it's a channel chat (WhatsApp, etc.)."""
    return chat.get("user_id") == user_id or chat.get("user_id") == "__channel__"


def _parse_iso_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _activity_window(window: str) -> tuple[datetime, datetime, int, int]:
    now = datetime.now(timezone.utc)
    if window == "24h":
        step_seconds = 3600
        bucket_count = 24
    else:
        step_seconds = 300
        bucket_count = 12
    start = now - timedelta(seconds=step_seconds * bucket_count)
    aligned_epoch = int(start.timestamp())
    aligned_epoch -= aligned_epoch % step_seconds
    start = datetime.fromtimestamp(aligned_epoch, tz=timezone.utc)
    return now, start, step_seconds, bucket_count


def _bucket_index(at: datetime, start: datetime, step_seconds: int, bucket_count: int) -> int | None:
    pos = int((at - start).total_seconds() // step_seconds)
    if 0 <= pos < bucket_count:
        return pos
    return None


def _enqueue_context_curation(
    *,
    body: "SendMessageRequest",
    user_id: str,
    chat_id: str,
    user_msg: str,
    assistant_reply: str,
) -> None:
    if not user_msg.strip() or not assistant_reply.strip():
        return

    def _run() -> None:
        try:
            queen = QueenAgent(
                QueenConfig(
                    honeycomb_root=Path(body.honeycomb_root),
                    scheduler_backend=body.scheduler,
                    vector_backend=body.vector,
                )
            )
            queen.run(
                intent="context_curation",
                payload={
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "user_msg": user_msg[:1200],
                    "assistant_reply": assistant_reply[:3000],
                    "honeycomb_root": body.honeycomb_root,
                    "delegate_to_worker": True,
                },
                source="web_ui:context_curator",
            )
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


class CreateOrgRequest(BaseModel):
    name: str


class CreateHiveRequest(BaseModel):
    org_id: str
    name: str


class CreateHoneycombRequest(BaseModel):
    hive_id: str
    name: str
    root_path: str


class CreateQueenRequest(BaseModel):
    hive_id: str
    name: str
    blueprint_id: str = "blueprint.queen.default"


class InstantiateTemplateRequest(BaseModel):
    template_id: str
    hive_id: str
    name: str


class OnboardingRequest(BaseModel):
    org_name: str
    hive_name: str
    honeycomb_root: str = ".honeycomb"
    queen_name: str = "Main Queen"
    queen_blueprint_id: str = "blueprint.queen.default"
    admin_email: str | None = None
    admin_password: str | None = None


class SetupCompleteRequest(BaseModel):
    """First-run wizard completion payload."""
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "catsarethebest/qwen2.5-N2:1.5b"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    telegram_bot_token: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""
    org_name: str = "Default Organization"
    hive_name: str = "Main Hive"
    admin_email: str = ""
    admin_password: str = ""
    create_linux_user: bool = False


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str


class RunChatRequest(BaseModel):
    intent: str = "research_topic"
    payload: dict[str, Any] = Field(default_factory=dict)
    honeycomb_root: str = ".honeycomb"
    scheduler: str = "auto"
    vector: str = "memory"


class ChannelRunRequest(BaseModel):
    channel: str
    intent: str = "research_topic"
    payload: dict[str, Any] = Field(default_factory=dict)
    honeycomb_root: str = ".honeycomb"


class CreateChatRequest(BaseModel):
    title: str = "New Chat"


class SendMessageRequest(BaseModel):
    content: str
    honeycomb_root: str = ".honeycomb"
    intent: str = "research_topic"
    scheduler: str = "auto"
    vector: str = "memory"


class UpdateChatRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class SettingsValidationRequest(BaseModel):
    config: dict[str, Any]


class PermissionSimulationRequest(BaseModel):
    rules: list[dict[str, Any]] = Field(default_factory=list)
    tool: str = "read"
    target: str = ""
    sample_targets: list[str] = Field(default_factory=list)


class AnalyticsEventRequest(BaseModel):
    event: str = Field(min_length=1, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StaffingUpdateRequest(BaseModel):
    staffing: dict[str, Any]


class ContractReadinessUpdateRequest(BaseModel):
    contracts: list[dict[str, Any]]


class UsabilitySessionRequest(BaseModel):
    sprint: str
    participant_count: int = Field(ge=1, le=1000)
    task_success_rate: float = Field(ge=0.0, le=1.0)
    notes: str = ""


def _settings_scopes() -> list[dict[str, str]]:
    return [
        {"scope": "managed", "priority": "highest", "description": "Org-enforced configuration policy."},
        {"scope": "cli", "priority": "high", "description": "Runtime override via CLI flags."},
        {"scope": "local", "priority": "high", "description": "Machine-local non-committed settings."},
        {"scope": "project", "priority": "medium", "description": "Project-level shared settings."},
        {"scope": "user", "priority": "low", "description": "Personal defaults."},
    ]


def _settings_catalog() -> list[dict[str, Any]]:
    return [
        {
            "category": "model_runtime",
            "title": "Model and Runtime",
            "fields": [
                {"key": "llm_provider", "type": "enum", "options": ["ollama", "gemini", "openai"], "required": True},
                {"key": "ollama_base_url", "type": "string", "required": False},
                {"key": "ollama_model", "type": "string", "required": False},
                {"key": "llm_model", "type": "string", "required": False},
            ],
        },
        {
            "category": "api_keys",
            "title": "Provider and Channel Secrets",
            "fields": [
                {"key": "gemini_api_key", "type": "secret", "required": False},
                {"key": "openai_api_key", "type": "secret", "required": False},
                {"key": "telegram_bot_token", "type": "secret", "required": False},
                {"key": "whatsapp_access_token", "type": "secret", "required": False},
                {"key": "whatsapp_phone_number_id", "type": "string", "required": False},
            ],
        },
        {
            "category": "policy",
            "title": "Policy and Permissions",
            "fields": [
                {"key": "permission_rules", "type": "json", "required": False},
                {"key": "sandbox_mode", "type": "enum", "options": ["standard", "strict"], "required": False},
            ],
        },
        {
            "category": "governance",
            "title": "Governance and Rollout",
            "fields": [
                {"key": "dashboard_staffing", "type": "json", "required": False},
                {"key": "dashboard_api_contracts", "type": "json", "required": False},
                {"key": "dashboard_usability_sessions", "type": "json", "required": False},
            ],
        },
    ]


def _settings_templates() -> list[dict[str, Any]]:
    return [
        {
            "template_id": "secure-enterprise",
            "name": "Secure Enterprise",
            "description": "OpenAI + strict policy posture with explicit channel setup.",
            "config": {
                "llm_provider": "openai",
                "ollama_base_url": "http://localhost:11434",
                "ollama_model": "catsarethebest/qwen2.5-N2:1.5b",
                "gemini_api_key": "",
                "openai_api_key": "",
                "telegram_bot_token": "",
                "whatsapp_access_token": "",
                "whatsapp_phone_number_id": "",
            },
        },
        {
            "template_id": "team-collaboration",
            "name": "Team Collaboration",
            "description": "Gemini defaults with channel-first onboarding.",
            "config": {
                "llm_provider": "gemini",
                "ollama_base_url": "http://localhost:11434",
                "ollama_model": "catsarethebest/qwen2.5-N2:1.5b",
                "gemini_api_key": "",
                "openai_api_key": "",
                "telegram_bot_token": "",
                "whatsapp_access_token": "",
                "whatsapp_phone_number_id": "",
            },
        },
        {
            "template_id": "solo-fast",
            "name": "Solo Fast Local",
            "description": "Ollama-first local defaults for quick setup.",
            "config": {
                "llm_provider": "ollama",
                "ollama_base_url": "http://localhost:11434",
                "ollama_model": "catsarethebest/qwen2.5-N2:1.5b",
                "gemini_api_key": "",
                "openai_api_key": "",
                "telegram_bot_token": "",
                "whatsapp_access_token": "",
                "whatsapp_phone_number_id": "",
            },
        },
    ]


def _validate_settings_payload(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    provider = str(config.get("llm_provider", "")).strip().lower()
    if provider not in {"ollama", "gemini", "openai"}:
        errors.append("llm_provider must be one of: ollama, gemini, openai.")

    if provider == "ollama":
        if not str(config.get("ollama_base_url", "")).strip():
            errors.append("ollama_base_url is required when llm_provider=ollama.")
        if not str(config.get("ollama_model", "")).strip():
            errors.append("ollama_model is required when llm_provider=ollama.")
    if provider == "gemini" and not str(config.get("gemini_api_key", "")).strip():
        warnings.append("gemini_api_key is empty; Gemini requests will fail until set.")
    if provider == "openai" and not str(config.get("openai_api_key", "")).strip():
        warnings.append("openai_api_key is empty; OpenAI requests will fail until set.")

    wa_token = str(config.get("whatsapp_access_token", "")).strip()
    wa_phone = str(config.get("whatsapp_phone_number_id", "")).strip()
    if wa_token and not wa_phone:
        warnings.append("whatsapp_phone_number_id should be set when whatsapp_access_token is configured.")

    for secret_key in ("gemini_api_key", "openai_api_key", "telegram_bot_token", "whatsapp_access_token"):
        if str(config.get(secret_key, "")).strip().lower() in {"todo", "changeme", "replace-me"}:
            errors.append(f"{secret_key} uses a placeholder value; provide a real secret.")

    return errors, warnings


def _effective_settings(honeycomb_root: str = ".honeycomb") -> dict[str, Any]:
    store = get_store()
    env_cfg = _get_setup_config(mask_secrets=True)
    global_llm_model = store.resolve_llm_model(honeycomb_root=honeycomb_root)
    settings_list = store.list_settings()
    settings_map = {row.get("key"): row.get("value") for row in settings_list if row.get("key")}
    effective_fields = {
        "llm_provider": {"value": env_cfg.get("llm_provider", "ollama"), "source": "env"},
        "ollama_base_url": {"value": env_cfg.get("ollama_base_url", "http://localhost:11434"), "source": "env"},
        "ollama_model": {"value": env_cfg.get("ollama_model", ""), "source": "env"},
        "gemini_api_key": {"value": env_cfg.get("gemini_api_key", ""), "source": "env"},
        "openai_api_key": {"value": env_cfg.get("openai_api_key", ""), "source": "env"},
        "telegram_bot_token": {"value": env_cfg.get("telegram_bot_token", ""), "source": "channel_store"},
        "whatsapp_access_token": {"value": env_cfg.get("whatsapp_access_token", ""), "source": "env/channel_store"},
        "whatsapp_phone_number_id": {"value": env_cfg.get("whatsapp_phone_number_id", ""), "source": "env/channel_store"},
        "llm_model": {"value": global_llm_model or "", "source": "hive_or_global_setting"},
    }
    if "permission_rules" in settings_map:
        effective_fields["permission_rules"] = {"value": settings_map.get("permission_rules"), "source": "global_setting"}
    return {
        "scopes": _settings_scopes(),
        "fields": effective_fields,
        "last_updated_at": max((str(s.get("updated_at", "")) for s in settings_list), default=""),
    }


def _permission_rule_match(rule: dict[str, Any], tool: str, target: str) -> bool:
    tools = rule.get("tools", ["*"])
    if isinstance(tools, str):
        tools = [tools]
    if not any(fnmatch.fnmatch(tool, str(pat)) for pat in tools):
        return False
    pattern = str(rule.get("pattern", "*"))
    if not target:
        return True
    return fnmatch.fnmatch(target, pattern)


def _permission_simulate(
    rules: list[dict[str, Any]],
    tool: str,
    targets: list[str],
) -> dict[str, Any]:
    lint: list[str] = []
    for idx, rule in enumerate(rules):
        action = str(rule.get("action", "")).lower()
        if action not in {"allow", "deny"}:
            lint.append(f"Rule {idx + 1}: action must be allow|deny.")
        if "pattern" not in rule:
            lint.append(f"Rule {idx + 1}: missing pattern.")
    results: list[dict[str, Any]] = []
    for target in targets:
        decision = "deny"
        matched_rule: dict[str, Any] | None = None
        for rule in rules:
            if _permission_rule_match(rule, tool=tool, target=target):
                matched_rule = rule
                decision = str(rule.get("action", "deny")).lower()
                break
        results.append({"target": target, "decision": decision, "matched_rule": matched_rule})
    return {"lint": lint, "results": results}


def _queen_from_request(body: RunChatRequest) -> QueenAgent:
    cfg = QueenConfig(
        honeycomb_root=Path(body.honeycomb_root),
        scheduler_backend=body.scheduler,
        vector_backend=body.vector,
    )
    return QueenAgent(cfg)


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/auth/login")
def auth_login(body: LoginRequest) -> dict[str, Any]:
    store = get_store()
    user = store.get_user_by_email(body.email)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user.user_id, user.email)
    return {"access_token": token, "token_type": "bearer", "user_id": user.user_id, "email": user.email}


@router.post("/api/auth/register")
def auth_register(body: RegisterRequest) -> dict[str, Any]:
    store = get_store()
    if store.get_user_by_email(body.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    user = store.create_user(body.email, hash_password(body.password))
    token = create_access_token(user.user_id, user.email)
    return {"access_token": token, "token_type": "bearer", "user_id": user.user_id, "email": user.email}


@router.get("/api/auth/me")
def auth_me(user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    return {"user_id": user.user_id, "email": user.email}


@router.get("/api/setup/status")
def setup_status() -> dict[str, Any]:
    """Returns whether first-run wizard is needed. No auth required."""
    return {
        "needs_setup": is_fresh_install(),
        "setup_done": is_setup_done(),
    }


def _get_setup_config(mask_secrets: bool = False) -> dict[str, Any]:
    """Build config dict for setup form. Used by GET /api/setup/config and GET /api/env."""
    import os

    env = read_env_from_file()
    tg: dict[str, Any] = {}
    wa: dict[str, Any] = {}
    first_org = None
    first_hive = None
    try:
        store = get_store()
        tg = store.get_channel_config_decrypted("telegram") or {}
        wa = store.get_channel_config_decrypted("whatsapp") or {}
        orgs = store.list_orgs()
        first_org = orgs[0] if orgs else None
        if first_org:
            hives = store.list_hives(first_org.org_id)
            first_hive = hives[0] if hives else None
    except Exception:
        pass

    def _mask(val: str) -> str:
        return "***" if (mask_secrets and val) else (val or "")

    return {
        "llm_provider": env.get("BEEKEEPER_LLM_PROVIDER") or os.environ.get("BEEKEEPER_LLM_PROVIDER", "ollama"),
        "ollama_base_url": env.get("BEEKEEPER_OLLAMA_BASE_URL") or os.environ.get("BEEKEEPER_OLLAMA_BASE_URL", "http://localhost:11434"),
        "ollama_model": env.get("BEEKEEPER_OLLAMA_MODEL") or os.environ.get("BEEKEEPER_OLLAMA_MODEL", "catsarethebest/qwen2.5-N2:1.5b"),
        "gemini_api_key": _mask(env.get("BEEKEEPER_GEMINI_API_KEY") or os.environ.get("BEEKEEPER_GEMINI_API_KEY", "")),
        "openai_api_key": _mask(env.get("BEEKEEPER_OPENAI_API_KEY") or os.environ.get("BEEKEEPER_OPENAI_API_KEY", "")),
        "telegram_bot_token": _mask(str(tg.get("telegram_bot_token", ""))),
        "whatsapp_access_token": _mask(env.get("WHATSAPP_ACCESS_TOKEN") or wa.get("whatsapp_access_token", "") or os.environ.get("WHATSAPP_ACCESS_TOKEN", "")),
        "whatsapp_phone_number_id": env.get("WHATSAPP_PHONE_NUMBER_ID") or wa.get("whatsapp_phone_number_id", "") or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        "org_name": first_org.name if first_org else "Default Organization",
        "hive_name": first_hive.name if first_hive else "Main Hive",
    }


@router.get("/api/setup/config")
def setup_config() -> dict[str, Any]:
    """Returns current env/config values for setup form pre-population. No auth required."""
    return _get_setup_config(mask_secrets=False)


@router.post("/api/setup/complete")
def setup_complete(body: SetupCompleteRequest) -> dict[str, Any]:
    """Complete first-run wizard: write .env, bootstrap tenant, mark done. No auth required."""
    if is_setup_done():
        raise HTTPException(status_code=400, detail="setup_already_done")
    if not is_fresh_install():
        raise HTTPException(status_code=400, detail="not_fresh_install")

    env_config: dict[str, str] = {
        "BEEKEEPER_LLM_PROVIDER": body.llm_provider,
        "BEEKEEPER_OLLAMA_BASE_URL": body.ollama_base_url,
        "BEEKEEPER_OLLAMA_MODEL": body.ollama_model,
        "BEEKEEPER_STORE_ROOT": ".beekeeper_store",
    }
    import os
    for k, v in env_config.items():
        os.environ[k] = v
    if body.gemini_api_key:
        env_config["BEEKEEPER_GEMINI_API_KEY"] = body.gemini_api_key
    if body.openai_api_key:
        env_config["BEEKEEPER_OPENAI_API_KEY"] = body.openai_api_key
    if body.whatsapp_access_token:
        env_config["WHATSAPP_ACCESS_TOKEN"] = body.whatsapp_access_token
    if body.whatsapp_phone_number_id:
        env_config["WHATSAPP_PHONE_NUMBER_ID"] = body.whatsapp_phone_number_id
    if body.whatsapp_app_secret:
        env_config["WHATSAPP_APP_SECRET"] = body.whatsapp_app_secret
    if body.whatsapp_verify_token:
        env_config["WHATSAPP_VERIFY_TOKEN"] = body.whatsapp_verify_token

    write_env_from_config(env_config)

    if body.create_linux_user:
        _try_create_beekeeper_user()

    store = get_store()
    if body.telegram_bot_token:
        store.write_channel_config("telegram", {"telegram_bot_token": body.telegram_bot_token})
    if body.whatsapp_access_token or body.whatsapp_verify_token:
        wa = store.get_channel_config_decrypted("whatsapp") or {}
        if body.whatsapp_access_token:
            wa["whatsapp_access_token"] = body.whatsapp_access_token
        if body.whatsapp_phone_number_id:
            wa["whatsapp_phone_number_id"] = body.whatsapp_phone_number_id
        if body.whatsapp_app_secret:
            wa["whatsapp_app_secret"] = body.whatsapp_app_secret
        if body.whatsapp_verify_token:
            wa["whatsapp_verify_token"] = body.whatsapp_verify_token
        store.write_channel_config("whatsapp", wa)

    bootstrap = OnboardingRequest(
        org_name=body.org_name,
        hive_name=body.hive_name,
        admin_email=body.admin_email or None,
        admin_password=body.admin_password or None,
    )
    result = onboarding_bootstrap(bootstrap)
    mark_setup_done()
    result["setup_done"] = True
    return result


def _try_create_beekeeper_user() -> None:
    """Create sandboxed beekeeper-agent user on Linux. Skips on macOS/Docker."""
    import platform
    import subprocess
    if platform.system() != "Linux":
        return
    try:
        subprocess.run(
            ["useradd", "-r", "-m", "-s", "/bin/bash", "beekeeper-agent"],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


_SKIP_SECRET = "***"  # When user submits this, do not overwrite existing secret


@router.get("/api/env")
def get_env(user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    """Returns current env/config values for dashboard. Auth required. Masks secrets."""
    return _get_setup_config(mask_secrets=True)


@router.post("/api/env")
def update_env(
    body: SetupCompleteRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> dict[str, Any]:
    """Update .env from dashboard. Auth required. Does not run onboarding."""
    import os

    env_config: dict[str, str] = {
        "BEEKEEPER_LLM_PROVIDER": body.llm_provider,
        "BEEKEEPER_OLLAMA_BASE_URL": body.ollama_base_url,
        "BEEKEEPER_OLLAMA_MODEL": body.ollama_model,
    }
    if body.gemini_api_key and body.gemini_api_key != _SKIP_SECRET:
        env_config["BEEKEEPER_GEMINI_API_KEY"] = body.gemini_api_key
    if body.openai_api_key and body.openai_api_key != _SKIP_SECRET:
        env_config["BEEKEEPER_OPENAI_API_KEY"] = body.openai_api_key
    if body.whatsapp_access_token != _SKIP_SECRET:
        env_config["WHATSAPP_ACCESS_TOKEN"] = body.whatsapp_access_token or ""
    env_config["WHATSAPP_PHONE_NUMBER_ID"] = body.whatsapp_phone_number_id or ""
    if getattr(body, "whatsapp_app_secret", "") and getattr(body, "whatsapp_app_secret", "") != _SKIP_SECRET:
        env_config["WHATSAPP_APP_SECRET"] = body.whatsapp_app_secret
    if getattr(body, "whatsapp_verify_token", "") and getattr(body, "whatsapp_verify_token", "") != _SKIP_SECRET:
        env_config["WHATSAPP_VERIFY_TOKEN"] = body.whatsapp_verify_token

    write_env_from_config(env_config)

    store = get_store()
    if body.telegram_bot_token and body.telegram_bot_token != _SKIP_SECRET:
        store.write_channel_config("telegram", {"telegram_bot_token": body.telegram_bot_token})
    wa = store.get_channel_config_decrypted("whatsapp") or {}
    if body.whatsapp_access_token != _SKIP_SECRET:
        wa["whatsapp_access_token"] = body.whatsapp_access_token or ""
    wa["whatsapp_phone_number_id"] = body.whatsapp_phone_number_id or ""
    if getattr(body, "whatsapp_app_secret", "") and getattr(body, "whatsapp_app_secret", "") != _SKIP_SECRET:
        wa["whatsapp_app_secret"] = body.whatsapp_app_secret
    if getattr(body, "whatsapp_verify_token", "") and getattr(body, "whatsapp_verify_token", "") != _SKIP_SECRET:
        wa["whatsapp_verify_token"] = body.whatsapp_verify_token
    store.write_channel_config("whatsapp", wa)

    for k, v in env_config.items():
        os.environ[k] = v

    return {"ok": True, "message": "Environment updated. Restart beekeeper-api and queen-api for changes to take effect."}


class ApprovalActionRequest(BaseModel):
    approver: str = "operator"
    note: str | None = None


@router.get("/api/approvals")
def list_approvals(
    honeycomb_root: str = Query(".honeycomb"),
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """List pending HITL approval requests."""
    honeycomb = get_honeycomb(honeycomb_root)
    pending = honeycomb.list_pending_reviews()
    return {
        "pending_count": len(pending),
        "approvals": [r.model_dump(mode="json") for r in pending],
    }


@router.get("/api/approvals/{review_id}")
def get_approval(
    review_id: str,
    honeycomb_root: str = Query(".honeycomb"),
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """Get a single approval/review by ID."""
    honeycomb = get_honeycomb(honeycomb_root)
    review = honeycomb.get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="approval_not_found")
    return review.model_dump(mode="json")


@router.post("/api/approvals/{review_id}/approve")
def approve_review(
    review_id: str,
    body: ApprovalActionRequest = ApprovalActionRequest(),
    honeycomb_root: str = Query(".honeycomb"),
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """Approve a pending HITL request and optionally resume the task."""
    honeycomb = get_honeycomb(honeycomb_root)
    review = honeycomb.get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="approval_not_found")
    if review.status != "pending":
        return {"review": review.model_dump(mode="json"), "resumed": False}
    root = Path(honeycomb_root)
    if not root.is_absolute():
        root = Path.cwd() / root
    queen = QueenAgent(QueenConfig(honeycomb_root=root))
    result = queen.resume_human_review(
        review_id,
        approver=body.approver or user.email or "operator",
        approved=True,
        note=body.note or "",
    )
    resolved = honeycomb.get_review(review_id)
    return {
        "review": resolved.model_dump(mode="json") if resolved else {},
        "resumed": result.get("resumed", False),
        "run": result.get("run"),
    }


@router.post("/api/approvals/{review_id}/reject")
def reject_review(
    review_id: str,
    body: ApprovalActionRequest = ApprovalActionRequest(),
    honeycomb_root: str = Query(".honeycomb"),
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """Reject a pending HITL request."""
    honeycomb = get_honeycomb(honeycomb_root)
    review = honeycomb.get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="approval_not_found")
    if review.status != "pending":
        return {"review": review.model_dump(mode="json")}
    resolved = honeycomb.resolve_review(
        review_id,
        approved=False,
        approver=body.approver or user.email or "operator",
        note=body.note,
    )
    return {"review": resolved.model_dump(mode="json")}


@router.get("/api/init/status")
def init_status() -> dict[str, Any]:
    store = get_store()
    orgs = store.list_orgs()
    users = store.list_users()
    return {"needs_setup": len(orgs) == 0, "has_users": len(users) > 0}


@router.get("/api/orgs")
def list_orgs(user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    orgs = store.list_orgs()
    org_ids = set(store.list_org_ids_for_user(user.user_id))
    if org_ids:
        orgs = [o for o in orgs if o.org_id in org_ids]
    return {"orgs": [item.model_dump(mode="json") for item in orgs]}


@router.post("/api/orgs")
def create_org(body: CreateOrgRequest, user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    org = store.create_org(body.name)
    store.assign_org_role(user.user_id, org.org_id, "admin")
    return org.model_dump(mode="json")


@router.get("/api/hives")
def list_hives(
    org_id: str | None = None,
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    store = get_store()
    from .auth import require_org_access
    hives = store.list_hives(org_id)
    if org_id:
        require_org_access(user, org_id, store, "viewer")
    else:
        org_ids = set(store.list_org_ids_for_user(user.user_id))
        hives = [h for h in hives if h.org_id in org_ids]
    return {"hives": [item.model_dump(mode="json") for item in hives]}


@router.post("/api/hives")
def create_hive(body: CreateHiveRequest, user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    from .auth import require_org_access
    require_org_access(user, body.org_id, store, "admin")
    return store.create_hive(body.org_id, body.name).model_dump(mode="json")


@router.get("/api/honeycombs")
def list_honeycombs(
    hive_id: str | None = None,
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    store = get_store()
    from .auth import require_org_access
    combs = store.list_honeycombs(hive_id)
    if hive_id:
        hive = store.get_hive(hive_id)
        if hive:
            require_org_access(user, hive.org_id, store, "viewer")
    else:
        org_ids = set(store.list_org_ids_for_user(user.user_id))
        hives = {h.hive_id: h for h in store.list_hives() if h.org_id in org_ids}
        combs = [c for c in combs if c.hive_id in hives]
    return {"honeycombs": [item.model_dump(mode="json") for item in combs]}


@router.post("/api/honeycombs")
def create_honeycomb(body: CreateHoneycombRequest, user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    from .auth import require_org_access
    hive = store.get_hive(body.hive_id)
    if hive:
        require_org_access(user, hive.org_id, store, "admin")
    return store.create_honeycomb(body.hive_id, body.name, body.root_path).model_dump(mode="json")


@router.get("/api/queens")
def list_queens(
    hive_id: str | None = None,
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    store = get_store()
    from .auth import require_org_access
    queens = store.list_queens(hive_id)
    if hive_id:
        hive = store.get_hive(hive_id)
        if hive:
            require_org_access(user, hive.org_id, store, "viewer")
    else:
        org_ids = set(store.list_org_ids_for_user(user.user_id))
        hives = {h.hive_id: h for h in store.list_hives() if h.org_id in org_ids}
        queens = [q for q in queens if q.hive_id in hives]
    return {"queens": [item.model_dump(mode="json") for item in queens]}


@router.post("/api/queens")
def create_queen(body: CreateQueenRequest, user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    from .auth import require_org_access
    hive = store.get_hive(body.hive_id)
    if hive:
        require_org_access(user, hive.org_id, store, "admin")
    return store.create_queen(body.hive_id, body.name, body.blueprint_id).model_dump(mode="json")


@router.get("/api/templates")
def list_templates(user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    return {"templates": store.list_templates()}


@router.post("/api/templates")
def create_template(payload: dict[str, Any], user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    try:
        from beekeeper.contracts import AgentBlueprint

        blueprint = AgentBlueprint.model_validate(payload["blueprint"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid_template_blueprint: {exc}") from exc
    template_id = store.save_template(payload.get("name", blueprint.name), blueprint, payload.get("profile_refs"))
    return {"template_id": template_id}


@router.post("/api/templates/instantiate")
def instantiate_template(body: InstantiateTemplateRequest, user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    from .auth import require_org_access
    hive = store.get_hive(body.hive_id)
    if hive:
        require_org_access(user, hive.org_id, store, "admin")
    templates = {row.get("template_id"): row for row in store.list_templates()}
    template = templates.get(body.template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="template_not_found")
    blueprint_payload = template.get("blueprint", {})
    blueprint_id = str(blueprint_payload.get("blueprint_id", "blueprint.queen.default"))
    queen = store.create_queen(body.hive_id, body.name, blueprint_id)
    return {"queen": queen.model_dump(mode="json"), "template_id": body.template_id}


@router.post("/api/onboarding/bootstrap")
def onboarding_bootstrap(body: OnboardingRequest) -> dict[str, Any]:
    store = get_store()
    org = store.create_org(body.org_name)
    hive = store.create_hive(org.org_id, body.hive_name)
    comb = store.create_honeycomb(hive.hive_id, f"{body.hive_name}-comb", body.honeycomb_root)
    queen = store.create_queen(hive.hive_id, body.queen_name, body.queen_blueprint_id)
    result = {
        "org": org.model_dump(mode="json"),
        "hive": hive.model_dump(mode="json"),
        "honeycomb": comb.model_dump(mode="json"),
        "queen": queen.model_dump(mode="json"),
    }
    if body.admin_email and body.admin_password:
        existing = store.get_user_by_email(body.admin_email)
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        user = store.create_user(body.admin_email, hash_password(body.admin_password))
        store.assign_org_role(user.user_id, org.org_id, "admin")
        token = create_access_token(user.user_id, user.email)
        result["access_token"] = token
        result["user_id"] = user.user_id
        result["email"] = user.email
    return result


@router.get("/api/settings")
def list_settings(user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    return {"settings": store.list_settings()}


@router.get("/api/settings/catalog")
def settings_catalog(user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    return {"catalog": _settings_catalog(), "scopes": _settings_scopes()}


@router.get("/api/settings/templates")
def settings_templates(user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    return {"templates": _settings_templates()}


@router.post("/api/settings/validate")
def settings_validate(
    body: SettingsValidationRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> dict[str, Any]:
    errors, warnings = _validate_settings_payload(body.config)
    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


@router.get("/api/settings/effective")
def settings_effective(
    honeycomb_root: str = Query(".honeycomb"),
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    return _effective_settings(honeycomb_root=honeycomb_root)


@router.post("/api/settings/permissions/simulate")
def settings_permissions_simulate(
    body: PermissionSimulationRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> dict[str, Any]:
    targets = body.sample_targets or [body.target or ""]
    return _permission_simulate(body.rules, tool=body.tool, targets=targets)


@router.post("/api/settings/{key}")
def write_setting(key: str, payload: dict[str, Any], user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    store.write_setting(key, payload.get("value"))
    return {"ok": True, "key": key}


class PairingGenerateRequest(BaseModel):
    channel: str
    expires_minutes: int = 10


@router.post("/api/pairing/generate")
def generate_pairing_code(
    body: PairingGenerateRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> dict[str, Any]:
    """Generate a DM pairing code. User enters this code in a DM to the bot to complete pairing."""
    store = get_store()
    code = store.create_pairing_code(body.channel, expires_minutes=body.expires_minutes)
    base = __import__("os").environ.get("BEEKEEPER_BASE_URL", "http://localhost:8788")
    return {
        "code": code,
        "channel": body.channel,
        "expires_minutes": body.expires_minutes,
        "instructions": f"Send the code '{code}' in a DM to the bot to complete pairing.",
        "dashboard_url": f"{base}/",
    }


@router.get("/api/channels")
def list_channels(user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    return {"channels": store.list_channel_configs()}


@router.post("/api/channels/{channel}")
def upsert_channel(channel: str, payload: dict[str, Any], user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    store.write_channel_config(channel, payload)
    return {"ok": True, "channel": channel}


@router.get("/api/channels/{channel}/webhook")
async def channel_webhook_get(
    channel: str,
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """WhatsApp webhook verification (GET). Meta sends hub.mode, hub.verify_token, hub.challenge."""
    if channel != "whatsapp":
        raise HTTPException(status_code=404, detail="not_found")
    if hub_mode != "subscribe" or not hub_verify_token or not hub_challenge:
        raise HTTPException(status_code=400, detail="invalid_verification_request")
    store = get_store()
    config = store.get_channel_config_decrypted("whatsapp")
    if not config or config.get("whatsapp_verify_token") != hub_verify_token:
        raise HTTPException(status_code=403, detail="invalid_verify_token")
    return PlainTextResponse(hub_challenge)


@router.post("/api/channels/{channel}/webhook")
async def channel_webhook(channel: str, request: Request):
    from beekeeper.channel_auth import verify_slack_signature
    from beekeeper.channels import ChatHub
    from beekeeper.queen import QueenAgent, QueenConfig

    body = await request.body()
    store = get_store()
    if channel == "whatsapp":
        config = _get_whatsapp_config()
    else:
        config = store.get_channel_config_decrypted(channel)
    if not config:
        raise HTTPException(status_code=404, detail="channel_not_configured")

    if channel == "slack":
        signing_secret = config.get("slack_signing_secret")
        sig = request.headers.get("x-slack-signature", "")
        if signing_secret and not verify_slack_signature(body, sig, signing_secret):
            raise HTTPException(status_code=401, detail="invalid_slack_signature")
        import json as _json
        payload = _json.loads(body)
        if payload.get("type") == "url_verification":
            return JSONResponse(content={"challenge": payload.get("challenge", "")})
        if payload.get("type") == "event_callback":
            ev = payload.get("event", {})
            if ev.get("type") == "message" and not ev.get("bot_id"):
                text = ev.get("text", "")
                user_id = ev.get("user", "unknown")
                channel_id = ev.get("channel", "")
                from beekeeper.channel_allowlist import check_channel_allowlist
                from beekeeper.channel_mention import check_mention_required, _get_slack_bot_user_id
                allowed, reason = check_channel_allowlist(config, channel_id, user_id)
                if not allowed:
                    return JSONResponse(content={"ok": True})  # Silently ignore; avoid leaking allowlist
                bot_user_id = config.get("slack_bot_user_id") or (config.get("slack_bot_token") and _get_slack_bot_user_id(config["slack_bot_token"]))
                mention_ok, _ = check_mention_required(config, "slack", text, bot_user_id=bot_user_id)
                if not mention_ok:
                    return JSONResponse(content={"ok": True})  # Silently ignore when require_mention and no @mention
                is_dm = ev.get("channel_type") == "im"
                if config.get("require_dm_pairing") and is_dm:
                    from beekeeper.channel_pairing import looks_like_pairing_code
                    if store.is_dm_paired("slack", user_id):
                        pass
                    elif looks_like_pairing_code(text):
                        if store.validate_pairing_code("slack", user_id, text.strip()):
                            reply_msg = "Paired! You can now send messages."
                        else:
                            reply_msg = "Invalid or expired code. Get a new code from the dashboard."
                        if config.get("slack_bot_token"):
                            try:
                                from slack_sdk import WebClient
                                WebClient(token=config["slack_bot_token"]).chat_postMessage(channel=channel_id, text=reply_msg)
                            except Exception:
                                pass
                        return JSONResponse(content={"ok": True})
                    else:
                        base = __import__("os").environ.get("BEEKEEPER_BASE_URL", "http://localhost:8788")
                        reply_msg = f"DM pairing required. Get a code from the dashboard ({base}/) and send it here."
                        if config.get("slack_bot_token"):
                            try:
                                from slack_sdk import WebClient
                                WebClient(token=config["slack_bot_token"]).chat_postMessage(channel=channel_id, text=reply_msg)
                            except Exception:
                                pass
                        return JSONResponse(content={"ok": True})
                honeycomb_root = config.get("honeycomb_root", ".honeycomb")
                dispatch_payload: dict = {"sender": user_id, "text": text, "channel_id": channel_id, "event": ev}
                model_override = store.resolve_llm_model(honeycomb_root=honeycomb_root)
                if model_override:
                    dispatch_payload["model_override"] = model_override
                log_service_call("beekeeper_api", "called", source="channel:slack")
                queen = QueenAgent(QueenConfig(honeycomb_root=Path(honeycomb_root)))
                hub = ChatHub(queen)
                result = hub.dispatch(
                    "slack",
                    dispatch_payload,
                    intent="research_topic",
                    source="channel:slack",
                )
                bot_token = config.get("slack_bot_token")
                if bot_token:
                    resp = result.get("response", {})
                    results = resp.get("results", [])
                    reply = ""
                    if results and results[0].get("output"):
                        reply = str(results[0]["output"])
                    if not reply:
                        reply = "Request processed."
                    try:
                        from slack_sdk import WebClient
                        client = WebClient(token=bot_token)
                        client.chat_postMessage(channel=channel_id, text=reply[:4000])
                    except Exception:
                        pass
                return JSONResponse(content={"ok": True})
        return JSONResponse(content={"ok": True})

    if channel == "telegram":
        config = store.get_channel_config_decrypted(channel)
        expected_secret = (config or {}).get("telegram_secret_token")
        if expected_secret:
            secret = request.headers.get("x-telegram-bot-api-secret-token", "")
            if not hmac.compare_digest(secret, expected_secret):
                raise HTTPException(status_code=401, detail="invalid_telegram_secret")
        import json as _json
        payload = _json.loads(body)
        if "message" in payload:
            msg = payload["message"]
            text = msg.get("text", "")
            user_id = str(msg.get("from", {}).get("id", "unknown"))
            chat_id = msg.get("chat", {}).get("id")
            from beekeeper.channel_allowlist import check_channel_allowlist
            from beekeeper.channel_mention import check_mention_required
            allowed, reason = check_channel_allowlist(config, str(chat_id) if chat_id is not None else None, user_id)
            if not allowed:
                return JSONResponse(content={"ok": True})
            msg = payload.get("message", {})
            chat_type = msg.get("chat", {}).get("type", "private")
            mention_ok, _ = check_mention_required(config, "telegram", text or "", chat_type=chat_type)
            if not mention_ok:
                return JSONResponse(content={"ok": True})  # Silently ignore when require_mention
            is_dm = chat_type == "private"
            if config.get("require_dm_pairing") and is_dm:
                from beekeeper.channel_pairing import looks_like_pairing_code
                if store.is_dm_paired("telegram", user_id):
                    pass
                elif text and looks_like_pairing_code(text):
                    if store.validate_pairing_code("telegram", user_id, text.strip()):
                        reply_msg = "Paired! You can now send messages."
                    else:
                        reply_msg = "Invalid or expired code. Get a new code from the dashboard."
                    bot_token = (config or {}).get("telegram_bot_token")
                    if bot_token:
                        try:
                            import urllib.request
                            import urllib.parse
                            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                            req = urllib.request.Request(url, data=urllib.parse.urlencode({"chat_id": chat_id, "text": reply_msg}).encode(), method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
                            urllib.request.urlopen(req, timeout=10)
                        except Exception:
                            pass
                    return JSONResponse(content={"ok": True})
                elif text:
                    base = __import__("os").environ.get("BEEKEEPER_BASE_URL", "http://localhost:8788")
                    reply_msg = f"DM pairing required. Get a code from the dashboard ({base}/) and send it here."
                    bot_token = (config or {}).get("telegram_bot_token")
                    if bot_token:
                        try:
                            import urllib.request
                            import urllib.parse
                            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                            req = urllib.request.Request(url, data=urllib.parse.urlencode({"chat_id": chat_id, "text": reply_msg}).encode(), method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
                            urllib.request.urlopen(req, timeout=10)
                        except Exception:
                            pass
                    return JSONResponse(content={"ok": True})
            if text and chat_id is not None:
                honeycomb_root = (config or {}).get("honeycomb_root", ".honeycomb")
                dispatch_payload: dict = {"sender": user_id, "text": text, "chat_id": chat_id}
                model_override = store.resolve_llm_model(honeycomb_root=honeycomb_root)
                if model_override:
                    dispatch_payload["model_override"] = model_override
                log_service_call("beekeeper_api", "called", source="channel:telegram")
                queen = QueenAgent(QueenConfig(honeycomb_root=Path(honeycomb_root)))
                hub = ChatHub(queen)
                result = hub.dispatch("telegram", dispatch_payload, intent="research_topic", source="channel:telegram")
                bot_token = (config or {}).get("telegram_bot_token")
                if bot_token:
                    resp = result.get("response", {})
                    results = resp.get("results", [])
                    reply = str(results[0]["output"]) if results and results[0].get("output") else "Request processed."
                    try:
                        import urllib.request
                        import urllib.parse
                        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                        req = urllib.request.Request(url, data=urllib.parse.urlencode({"chat_id": chat_id, "text": reply[:4000]}).encode(), method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
                        urllib.request.urlopen(req, timeout=10)
                    except Exception:
                        pass
        return JSONResponse(content={"ok": True})

    if channel == "discord":
        from beekeeper.channel_auth import verify_discord_signature

        public_key = config.get("discord_public_key")
        sig = request.headers.get("x-signature-ed25519", "")
        timestamp = request.headers.get("x-signature-timestamp", "")
        if public_key and (not verify_discord_signature(body, sig, timestamp, public_key)):
            raise HTTPException(status_code=401, detail="invalid_discord_signature")
        import json as _json
        payload = _json.loads(body)
        itype = payload.get("type")
        if itype == 1:
            return JSONResponse(content={"type": 1})
        if itype == 2:
            data = payload.get("data", {})
            options = data.get("options", [])
            text = ""
            for opt in options:
                if opt.get("name") in ("query", "message", "text") and "value" in opt:
                    text = str(opt["value"])
                    break
            if not text:
                text = " ".join(str(o.get("value", "")) for o in options if "value" in o) or "hello"
            user = payload.get("member", {}).get("user") or payload.get("user", {})
            user_id = str(user.get("id", "unknown"))
            channel_id = payload.get("channel_id", "")
            from beekeeper.channel_allowlist import check_channel_allowlist
            allowed, reason = check_channel_allowlist(config, channel_id, user_id)
            if not allowed:
                return JSONResponse(content={"type": 4, "data": {"content": "You do not have access to this bot.", "flags": 64}})
            honeycomb_root = config.get("honeycomb_root", ".honeycomb")
            dispatch_payload: dict = {"sender": user_id, "text": text, "channel_id": channel_id, "interaction": payload}
            model_override = store.resolve_llm_model(honeycomb_root=honeycomb_root)
            if model_override:
                dispatch_payload["model_override"] = model_override
            log_service_call("beekeeper_api", "called", source="channel:discord")
            queen = QueenAgent(QueenConfig(honeycomb_root=Path(honeycomb_root)))
            hub = ChatHub(queen)
            result = hub.dispatch(
                "discord",
                dispatch_payload,
                intent="research_topic",
                source="channel:discord",
            )
            resp = result.get("response", {})
            results = resp.get("results", [])
            reply = str(results[0]["output"]) if results and results[0].get("output") else "Request processed."
            return JSONResponse(content={"type": 4, "data": {"content": reply[:2000]}})
        return JSONResponse(content={"type": 1})

    if channel == "whatsapp":
        from beekeeper.channel_auth import verify_whatsapp_signature
        from beekeeper.transcribe import fetch_whatsapp_media, transcribe_audio

        app_secret = config.get("whatsapp_app_secret")
        sig_header = request.headers.get("x-hub-signature-256", "")
        if app_secret and not verify_whatsapp_signature(body, sig_header, app_secret):
            raise HTTPException(status_code=401, detail="invalid_whatsapp_signature")
        import json as _json
        payload = _json.loads(body)
        entries = payload.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                if change.get("field") != "messages":
                    continue
                value = change.get("value", {})
                messages = value.get("messages", [])
                phone_number_id = value.get("metadata", {}).get("phone_number_id") or config.get("whatsapp_phone_number_id")
                access_token = config.get("whatsapp_access_token")
                honeycomb_root = config.get("honeycomb_root", ".honeycomb")
                log_service_call("beekeeper_api", "called", source="channel:whatsapp")
                queen = QueenAgent(QueenConfig(honeycomb_root=Path(honeycomb_root)))
                hub = ChatHub(queen)
                whatsapp_chat = store.get_or_create_channel_chat("whatsapp", "WhatsApp")
                chat_id = whatsapp_chat["chat_id"]
                openai_key = config.get("openai_api_key") or __import__("os").environ.get("BEEKEEPER_OPENAI_API_KEY", "")
                for msg in messages:
                    msg_type = msg.get("type", "text")
                    text = ""
                    if msg_type == "text":
                        text_obj = msg.get("text", {})
                        text = text_obj.get("body", "")
                    elif msg_type in ("audio", "voice"):
                        media_obj = msg.get("audio") or msg.get("voice") or {}
                        media_id = media_obj.get("id")
                        if media_id and access_token:
                            raw = fetch_whatsapp_media(media_id, access_token)
                            if raw:
                                text = transcribe_audio(raw, openai_api_key=openai_key or None)
                            else:
                                text = "[Could not fetch audio. Please send a text message.]"
                        else:
                            text = "[Audio received. Configure WhatsApp access token for transcription.]"
                    if not text:
                        continue
                    sender = msg.get("from", "unknown")
                    msg_id = msg.get("id", "")
                    store.append_chat_message(chat_id, "user", text, source="whatsapp")
                    result = hub.dispatch(
                        "whatsapp",
                        {"sender": sender, "text": text, "chat_id": sender, "message_id": msg_id},
                        intent="research_topic",
                        source="channel:whatsapp",
                    )
                    resp = result.get("response", {})
                    results = resp.get("results", [])
                    reply = str(results[0]["output"]) if results and results[0].get("output") else "Request processed."
                    store.append_chat_message(chat_id, "assistant", reply)
                    if access_token and phone_number_id:
                        try:
                            import urllib.request
                            import urllib.parse
                            url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
                            data = _json.dumps({
                                "messaging_product": "whatsapp",
                                "to": sender.replace("@s.whatsapp.net", ""),
                                "type": "text",
                                "text": {"body": reply[:4000]},
                            }).encode("utf-8")
                            req = urllib.request.Request(
                                url,
                                data=data,
                                method="POST",
                                headers={
                                    "Authorization": f"Bearer {access_token}",
                                    "Content-Type": "application/json",
                                },
                            )
                            urllib.request.urlopen(req, timeout=15)
                        except Exception:
                            pass
        return JSONResponse(content={"ok": True})

    raise HTTPException(status_code=400, detail="webhook_not_supported_for_channel")


@router.get("/api/channels/slack/oauth")
def slack_oauth_start(
    redirect_uri: str | None = None,
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
):
    import os
    from fastapi.responses import RedirectResponse
    client_id = os.getenv("BEEKEEPER_SLACK_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=500, detail="Slack OAuth not configured (BEEKEEPER_SLACK_CLIENT_ID)")
    base = os.getenv("BEEKEEPER_BASE_URL", "http://localhost:8788")
    ruri = redirect_uri or f"{base}/api/channels/slack/oauth/callback"
    scope = "bot,chat:write,channels:history,groups:history,im:history,mpim:history"
    url = f"https://slack.com/oauth/v2/authorize?client_id={client_id}&scope={scope}&redirect_uri={ruri}"
    return RedirectResponse(url=url)


@router.get("/api/channels/slack/oauth/callback")
def slack_oauth_callback(
    code: str | None = None,
    error: str | None = None,
):
    import os
    from fastapi.responses import RedirectResponse
    if error:
        return RedirectResponse(url="/?slack_oauth_error=" + (error or "unknown"))
    if not code:
        raise HTTPException(status_code=400, detail="missing_code")
    client_id = os.getenv("BEEKEEPER_SLACK_CLIENT_ID")
    client_secret = os.getenv("BEEKEEPER_SLACK_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Slack OAuth not configured")
    base = os.getenv("BEEKEEPER_BASE_URL", "http://localhost:8788")
    redirect_uri = f"{base}/api/channels/slack/oauth/callback"
    import urllib.request
    import urllib.parse
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }).encode()
    req = urllib.request.Request(
        "https://slack.com/api/oauth.v2.access",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = __import__("json").loads(r.read().decode())
    if not resp.get("ok"):
        return RedirectResponse(url="/?slack_oauth_error=" + resp.get("error", "unknown"))
    bot_token = resp.get("access_token")
    if not bot_token:
        return RedirectResponse(url="/?slack_oauth_error=no_token")
    store = get_store()
    existing = store.get_channel_config_decrypted("slack") or {}
    merged = {**existing, "slack_bot_token": bot_token}
    store.write_channel_config("slack", merged)
    return RedirectResponse(url="/?slack_oauth=success")


@router.post("/api/chat/run")
def run_chat(body: RunChatRequest, user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    log_service_call(
        "beekeeper_api",
        "called",
        source="beekeeper_api:chat_run",
        user_id=user.user_id,
        resource="chat:run",
    )
    queen = _queen_from_request(body)
    result = queen.run(intent=body.intent, payload=body.payload, source="beekeeper_api:chat_run")
    log_service_call(
        "queen",
        "completed",
        source="beekeeper_api:chat_run",
        user_id=user.user_id,
        resource="chat:run",
        trace_id=result.get("trace_id"),
    )
    return result


# --- ChatGPT-style persistent chats ---

@router.post("/api/chats")
def create_chat(
    body: CreateChatRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> dict[str, Any]:
    store = get_store()
    chat = store.create_chat(user.user_id, title=body.title)
    return {"chat": chat}


@router.get("/api/chats")
def list_chats(
    limit: int = Query(50, ge=1, le=200),
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    store = get_store()
    whatsapp_config = _get_whatsapp_config()
    if whatsapp_config and whatsapp_config.get("whatsapp_access_token"):
        store.get_or_create_channel_chat("whatsapp", "WhatsApp")
    chats = store.list_chats(user.user_id, limit=limit)
    return {"chats": chats}


@router.get("/api/chats/{chat_id}")
def get_chat(
    chat_id: str,
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    store = get_store()
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if not _can_access_chat(chat, user.user_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"chat": chat}


@router.post("/api/chats/{chat_id}/messages")
def send_chat_message(
    chat_id: str,
    body: SendMessageRequest,
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    store = get_store()
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if not _can_access_chat(chat, user.user_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content required")
    prior = [{"role": m["role"], "content": m["content"]} for m in chat.get("messages", [])]
    store.append_chat_message(chat_id, "user", content)
    memories = [{"content": m["content"]} for m in store.search_user_memories(user.user_id, query=content, limit=18)]
    payload = {"query": content, "messages": prior, "user_memories": memories, "delegate_to_worker": True, "use_web_search": True}
    log_service_call(
        "beekeeper_api",
        "called",
        source="web_ui",
        user_id=user.user_id,
        resource="chat:message",
    )
    queen = QueenAgent(
        QueenConfig(
            honeycomb_root=Path(body.honeycomb_root),
            scheduler_backend=body.scheduler,
            vector_backend=body.vector,
        )
    )
    result = queen.run(intent=body.intent, payload=payload, source="web_ui")
    log_service_call(
        "queen",
        "completed",
        source="web_ui",
        user_id=user.user_id,
        resource="chat:message",
        trace_id=result.get("trace_id"),
    )
    results = result.get("results", [])
    raw_output = results[0].get("output", {}) if results else {}
    reply = ""
    for k in ("assistant_reply", "answer", "response", "content", "output", "summary", "text"):
        v = raw_output.get(k)
        if isinstance(v, str) and v.strip():
            reply = v
            break
        if v and isinstance(v, dict) and isinstance(v.get("text"), str):
            reply = v.get("text", "")
            break
    if not reply:
        reply = str(raw_output) if raw_output else "No response."
    store.append_chat_message(chat_id, "assistant", reply)
    _enqueue_context_curation(
        body=body,
        user_id=user.user_id,
        chat_id=chat_id,
        user_msg=content,
        assistant_reply=reply,
    )
    updated = store.get_chat(chat_id)
    return {"chat": updated, "reply": reply, "result": result}


@router.post("/api/chats/{chat_id}/messages/stream")
async def send_chat_message_stream(
    chat_id: str,
    body: SendMessageRequest,
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
):
    """Stream real-time Queen execution status, then return final result."""
    store = get_store()
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if not _can_access_chat(chat, user.user_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content required")
    prior = [{"role": m["role"], "content": m["content"]} for m in chat.get("messages", [])]
    store.append_chat_message(chat_id, "user", content)
    memories = [{"content": m["content"]} for m in store.search_user_memories(user.user_id, query=content, limit=18)]
    payload = {"query": content, "messages": prior, "user_memories": memories}

    status_queue: queue.Queue[str | None] = queue.Queue()
    result_holder: list[dict[str, Any]] = []

    def _run() -> None:
        log_service_call(
            "beekeeper_api",
            "called",
            source="web_ui",
            user_id=user.user_id,
            resource="chat:message_stream",
        )
        queen = QueenAgent(
            QueenConfig(
                honeycomb_root=Path(body.honeycomb_root),
                scheduler_backend=body.scheduler,
                vector_backend=body.vector,
            )
        )

        def on_status(msg: str) -> None:
            status_queue.put(msg)

        result = queen.run(intent=body.intent, payload=payload, status_callback=on_status, source="web_ui")
        log_service_call(
            "queen",
            "completed",
            source="web_ui",
            user_id=user.user_id,
            resource="chat:message_stream",
            trace_id=result.get("trace_id"),
        )
        status_queue.put(None)  # sentinel
        results = result.get("results", [])
        raw_output = results[0].get("output", {}) if results else {}
        reply = ""
        for k in ("assistant_reply", "answer", "response", "content", "output", "summary", "text"):
            v = raw_output.get(k)
            if isinstance(v, str) and v.strip():
                reply = v
                break
            if v and isinstance(v, dict) and isinstance(v.get("text"), str):
                reply = v.get("text", "")
                break
        if not reply:
            reply = str(raw_output) if raw_output else "No response."
        store.append_chat_message(chat_id, "assistant", reply)
        _enqueue_context_curation(
            body=body,
            user_id=user.user_id,
            chat_id=chat_id,
            user_msg=content,
            assistant_reply=reply,
        )
        updated = store.get_chat(chat_id)
        result_holder.append({"chat": updated, "reply": reply})

    async def _stream() -> Any:
        thread = threading.Thread(target=_run)
        thread.start()
        while thread.is_alive() or not status_queue.empty():
            try:
                msg = status_queue.get_nowait()
                if msg is not None:
                    yield f"data: {json.dumps({'type': 'status', 'message': msg}, ensure_ascii=True)}\n\n"
            except queue.Empty:
                await asyncio.sleep(0.03)
        await asyncio.to_thread(thread.join)
        if result_holder:
            yield f"data: {json.dumps({'type': 'result', **result_holder[0]}, ensure_ascii=True)}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.patch("/api/chats/{chat_id}")
def update_chat(
    chat_id: str,
    body: UpdateChatRequest,
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    store = get_store()
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if not _can_access_chat(chat, user.user_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    if body.title is not None:
        chat = store.update_chat_title(chat_id, body.title)
    if body.pinned is not None:
        chat = store.update_chat_pinned(chat_id, body.pinned)
    return {"chat": chat}


@router.delete("/api/chats/{chat_id}")
def delete_chat(
    chat_id: str,
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    store = get_store()
    chat = store.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if not _can_access_chat(chat, user.user_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    store.delete_chat(chat_id)
    return {"deleted": True}


@router.post("/api/chat/channel")
def run_channel_chat(body: ChannelRunRequest, user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    log_service_call(
        "beekeeper_api",
        "called",
        source=f"beekeeper_api:channel:{body.channel}",
        user_id=user.user_id,
        resource=f"channel:{body.channel}",
    )
    queen = QueenAgent(QueenConfig(honeycomb_root=Path(body.honeycomb_root)))
    hub = ChatHub(queen)
    result = hub.dispatch(body.channel, body.payload, intent=body.intent, source=f"channel:{body.channel}")
    trace_id = result.get("response", {}).get("trace_id") if isinstance(result.get("response"), dict) else None
    log_service_call(
        "queen",
        "completed",
        source=f"channel:{body.channel}",
        user_id=user.user_id,
        resource=f"channel:{body.channel}",
        trace_id=trace_id,
    )
    return result


@router.get("/api/traces")
def list_traces(
    honeycomb_root: str = ".honeycomb",
    limit: int = 100,
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    honeycomb = get_honeycomb(honeycomb_root)
    trace_ids = honeycomb.list_traces(limit=limit)
    return {"traces": trace_ids}


@router.get("/api/traces/{trace_id}")
def get_trace(
    trace_id: str,
    honeycomb_root: str = ".honeycomb",
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    honeycomb = get_honeycomb(honeycomb_root)
    events = honeycomb.read_events(trace_id)
    edges = honeycomb.read_graph(trace_id)
    return {"trace_id": trace_id, "events": events, "edges": edges}


@router.get("/api/traces/{trace_id}/tree")
def get_trace_tree(
    trace_id: str,
    honeycomb_root: str = ".honeycomb",
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    honeycomb = get_honeycomb(honeycomb_root)
    return honeycomb.get_trace_tree(trace_id)


@router.get("/api/traces/{trace_id}/graph")
def get_trace_graph(
    trace_id: str,
    honeycomb_root: str = ".honeycomb",
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    honeycomb = get_honeycomb(honeycomb_root)
    events = honeycomb.read_events(trace_id)
    edges = honeycomb.read_graph(trace_id)
    task_events = [e for e in events if e.get("kind") == "task" and "task" in e]
    nodes = []
    seen = set()
    for ev in task_events:
        task = ev.get("task", {})
        tid = task.get("task_id")
        if tid and tid not in seen:
            seen.add(tid)
            nodes.append(
                {
                    "task_id": tid,
                    "parent_id": task.get("parent_id"),
                    "worker_kind": task.get("worker_kind", "unknown"),
                    "status": task.get("status", "unknown"),
                    "task_type": task.get("task_type", ""),
                }
            )
    return {"trace_id": trace_id, "nodes": nodes, "edges": edges}


@router.get("/api/analytics/latency")
def get_analytics_latency(
    honeycomb_root: str = ".honeycomb",
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    honeycomb = get_honeycomb(honeycomb_root)
    return compute_ops_metrics(honeycomb.root_dir)


@router.get("/api/ops/overview")
def get_ops_overview(
    honeycomb_root: str = ".honeycomb",
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    honeycomb = get_honeycomb(honeycomb_root)
    metrics = compute_ops_metrics(honeycomb.root_dir)
    pending = honeycomb.list_pending_reviews()
    audit_file = honeycomb.root_dir / "audit" / f"{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    logs: list[dict[str, Any]] = []
    if audit_file.exists():
        try:
            with audit_file.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        logs.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            logs = logs[-12:]
        except OSError:
            logs = []
    alerts = metrics.get("alerts", [])
    return {
        "health": "ok",
        "pending_approvals": len(pending),
        "queue_pressure_10m": metrics.get("hitl_queue_pressure_10m", 0),
        "pending_human_reviews": metrics.get("pending_human_reviews", 0),
        "top_latency_worker": sorted(
            (metrics.get("latency_p95_by_worker") or {}).items(),
            key=lambda pair: float(pair[1]),
            reverse=True,
        )[:1],
        "top_cost_worker": sorted(
            (metrics.get("cost_avg_by_worker") or {}).items(),
            key=lambda pair: float(pair[1]),
            reverse=True,
        )[:1],
        "alerts": alerts,
        "recent_logs": logs,
    }


@router.post("/api/analytics/events")
def track_analytics_event(
    body: AnalyticsEventRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> dict[str, Any]:
    store = get_store()
    existing = store.read_setting("dashboard_analytics_events", default=[])
    if not isinstance(existing, list):
        existing = []
    existing.append(
        {
            "event": body.event,
            "metadata": body.metadata,
            "at": datetime.now(timezone.utc).isoformat(),
            "user_id": user.user_id,
        }
    )
    if len(existing) > 1000:
        existing = existing[-1000:]
    store.write_setting("dashboard_analytics_events", existing)
    return {"ok": True}


@router.get("/api/analytics/events/summary")
def get_analytics_events_summary(
    days: int = Query(14, ge=1, le=180),
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    store = get_store()
    rows = store.read_setting("dashboard_analytics_events", default=[])
    if not isinstance(rows, list):
        rows = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    filtered = []
    for row in rows:
        at = _parse_iso_dt(str(row.get("at", "")))
        if at and at >= cutoff:
            filtered.append(row)
    counter = Counter(str(r.get("event", "unknown")) for r in filtered)
    latest = max((str(r.get("at", "")) for r in filtered), default="")
    return {
        "window_days": days,
        "events_total": len(filtered),
        "events_by_name": [{"event": k, "count": v} for k, v in sorted(counter.items(), key=lambda x: x[1], reverse=True)],
        "latest_event_at": latest,
    }


def _default_staffing() -> dict[str, Any]:
    return {
        "product_manager": "unassigned",
        "designer": "unassigned",
        "frontend_engineer_1": "unassigned",
        "frontend_engineer_2": "unassigned",
        "backend_engineer": "unassigned",
        "qa_automation_engineer": "unassigned",
    }


@router.get("/api/roadmap/staffing")
def roadmap_staffing(user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    staffing = store.read_setting("dashboard_staffing", default=_default_staffing())
    return {"staffing": staffing}


@router.post("/api/roadmap/staffing")
def update_roadmap_staffing(
    body: StaffingUpdateRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> dict[str, Any]:
    store = get_store()
    store.write_setting("dashboard_staffing", body.staffing)
    return {"ok": True}


def _default_contracts() -> list[dict[str, Any]]:
    return [
        {"name": "settings_validation_api", "required_by_sprint": 2, "status": "pending", "owner": "backend"},
        {"name": "settings_precedence_api", "required_by_sprint": 3, "status": "pending", "owner": "backend"},
        {"name": "permissions_simulation_api", "required_by_sprint": 4, "status": "pending", "owner": "backend"},
        {"name": "ops_logs_sessions_api", "required_by_sprint": 5, "status": "pending", "owner": "backend"},
    ]


@router.get("/api/roadmap/contracts")
def roadmap_contracts(user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    contracts = store.read_setting("dashboard_api_contracts", default=_default_contracts())
    return {"contracts": contracts}


@router.post("/api/roadmap/contracts")
def update_roadmap_contracts(
    body: ContractReadinessUpdateRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> dict[str, Any]:
    store = get_store()
    store.write_setting("dashboard_api_contracts", body.contracts)
    return {"ok": True}


@router.get("/api/roadmap/usability")
def roadmap_usability(user: Annotated[UserRecord, Depends(get_current_user)]) -> dict[str, Any]:
    store = get_store()
    sessions = store.read_setting("dashboard_usability_sessions", default=[])
    if not isinstance(sessions, list):
        sessions = []
    return {"sessions": sessions}


@router.post("/api/roadmap/usability")
def log_roadmap_usability(
    body: UsabilitySessionRequest,
    user: Annotated[UserRecord, Depends(get_current_user)],
) -> dict[str, Any]:
    store = get_store()
    sessions = store.read_setting("dashboard_usability_sessions", default=[])
    if not isinstance(sessions, list):
        sessions = []
    sessions.append(
        {
            "sprint": body.sprint,
            "participant_count": body.participant_count,
            "task_success_rate": body.task_success_rate,
            "notes": body.notes,
            "at": datetime.now(timezone.utc).isoformat(),
            "by": user.email,
        }
    )
    sessions = sessions[-200:]
    store.write_setting("dashboard_usability_sessions", sessions)
    return {"ok": True, "count": len(sessions)}


@router.get("/api/activity/series")
def get_activity_series(
    window: str = Query("1h", pattern="^(1h|24h)$"),
    honeycomb_root: str = ".honeycomb",
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    now, start, step_seconds, bucket_count = _activity_window(window)
    bucket_starts = [start + timedelta(seconds=step_seconds * i) for i in range(bucket_count)]
    chat_series = [0 for _ in range(bucket_count)]
    worker_series = [{"running": 0, "completed": 0, "failed": 0} for _ in range(bucket_count)]
    hive_series = [0 for _ in range(bucket_count)]

    store = get_store()
    honeycomb = get_honeycomb(honeycomb_root)

    active_chat_ids: set[str] = set()
    running_chat_requests = 0
    total_chat_messages = 0
    running_cutoff = now - timedelta(minutes=30)
    chats_dir = store.root / "chats"
    for chat_file in chats_dir.glob("*.json"):
        try:
            chat_payload = json.loads(chat_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        chat_id = str(chat_payload.get("chat_id") or chat_file.stem)
        messages = chat_payload.get("messages") or []
        last_message_time: datetime | None = None
        last_message_role = ""
        for msg in messages:
            created_at = _parse_iso_dt(msg.get("created_at"))
            if created_at is None:
                continue
            if created_at >= start and created_at <= now:
                idx = _bucket_index(created_at, start, step_seconds, bucket_count)
                if idx is not None:
                    chat_series[idx] += 1
                    total_chat_messages += 1
                    active_chat_ids.add(chat_id)
            if last_message_time is None or created_at > last_message_time:
                last_message_time = created_at
                last_message_role = str(msg.get("role", ""))
        if last_message_time and last_message_role == "user" and last_message_time >= running_cutoff:
            running_chat_requests += 1

    completed_window = 0
    failed_window = 0
    queued_window = 0
    blocked_window = 0
    by_worker: dict[str, dict[str, int]] = {}
    latest_task_status: dict[str, tuple[datetime, str]] = {}
    events_dir = honeycomb.root_dir / "events"
    for file_path in events_dir.glob("*.jsonl"):
        try:
            with file_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    row = line.strip()
                    if not row:
                        continue
                    try:
                        event = json.loads(row)
                    except json.JSONDecodeError:
                        continue
                    if event.get("kind") != "task":
                        continue
                    at = _parse_iso_dt(event.get("at"))
                    if at is None:
                        continue
                    status = str(event.get("status") or event.get("task", {}).get("status") or "unknown")
                    task_id = str(event.get("task_id") or event.get("task", {}).get("task_id") or "")
                    worker_kind = str(event.get("worker_kind") or event.get("task", {}).get("worker_kind") or "unknown")
                    if task_id:
                        prev = latest_task_status.get(task_id)
                        if prev is None or at > prev[0]:
                            latest_task_status[task_id] = (at, status)
                    if not (start <= at <= now):
                        continue
                    idx = _bucket_index(at, start, step_seconds, bucket_count)
                    if idx is None:
                        continue
                    hive_series[idx] += 1
                    if worker_kind not in by_worker:
                        by_worker[worker_kind] = {"running": 0, "completed": 0, "failed": 0, "queued": 0, "blocked": 0}
                    if status == "running":
                        worker_series[idx]["running"] += 1
                        by_worker[worker_kind]["running"] += 1
                    elif status == "success":
                        worker_series[idx]["completed"] += 1
                        completed_window += 1
                        by_worker[worker_kind]["completed"] += 1
                    elif status == "failed":
                        worker_series[idx]["failed"] += 1
                        failed_window += 1
                        by_worker[worker_kind]["failed"] += 1
                    elif status == "queued":
                        queued_window += 1
                        by_worker[worker_kind]["queued"] += 1
                    elif status == "blocked":
                        blocked_window += 1
                        by_worker[worker_kind]["blocked"] += 1
        except OSError:
            continue

    running_now = sum(1 for _, status in latest_task_status.values() if status == "running")
    window_hours = (bucket_count * step_seconds) / 3600.0
    throughput_per_hour = round(completed_window / window_hours, 2) if window_hours > 0 else 0.0

    return {
        "window": window,
        "from": start.isoformat(),
        "to": now.isoformat(),
        "bucket_size_seconds": step_seconds,
        "chat": {
            "total_messages": total_chat_messages,
            "active_chats": len(active_chat_ids),
            "running_requests": running_chat_requests,
            "series": [{"ts": bucket_starts[i].isoformat(), "count": chat_series[i]} for i in range(bucket_count)],
        },
        "workers": {
            "running": running_now,
            "completed": completed_window,
            "failed": failed_window,
            "queued": queued_window,
            "blocked": blocked_window,
            "series": [
                {
                    "ts": bucket_starts[i].isoformat(),
                    "running": worker_series[i]["running"],
                    "completed": worker_series[i]["completed"],
                    "failed": worker_series[i]["failed"],
                }
                for i in range(bucket_count)
            ],
            "by_worker": [{"worker_kind": name, **counts} for name, counts in sorted(by_worker.items())],
        },
        "hive": {
            "running_work": running_now,
            "throughput_per_hour": throughput_per_hour,
            "events_in_window": sum(hive_series),
            "series": [{"ts": bucket_starts[i].isoformat(), "work": hive_series[i]} for i in range(bucket_count)],
        },
    }


@router.get("/api/workers/registry")
def list_workers_registry(
    honeycomb_root: str = ".honeycomb",
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    registry = get_worker_registry(honeycomb_root)
    return {"workers": registry.list_workers(), "default_worker": registry.get_default_worker().value}


@router.get("/api/queen-updates")
def get_queen_updates(
    honeycomb_root: str = ".honeycomb",
    limit: int = 50,
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """List recent Queen updates (learnings, builds, reports from autonomous runs)."""
    honeycomb = get_honeycomb(honeycomb_root)
    updates = list_queen_updates(honeycomb, limit=limit)
    return {"updates": [u.model_dump(mode="json") for u in updates]}


@router.get("/api/queen/context")
def get_queen_context(
    honeycomb_root: str = ".honeycomb",
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    from pathlib import Path as P
    from beekeeper.queen_context import ensure_queen_context_file, load_queen_context
    root = P(honeycomb_root) if P(honeycomb_root).is_absolute() else P.cwd() / honeycomb_root
    ensure_queen_context_file(root)
    return {"context": load_queen_context(root), "path": str(root / "context" / "queen.md")}


@router.get("/api/audit/logs")
def get_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    since: str | None = Query(None, description="ISO8601 timestamp; only return logs after this time"),
    service: str | None = Query(None, description="Filter by service (redis, queen, qdrant, etc.)"),
    action: str | None = Query(None, description="Filter by action (called, submitted, completed, failed)"),
    source: str | None = Query(None, description="Filter by source (queen_api, web_ui, etc.)"),
    honeycomb_root: str = Query(".honeycomb"),
    user: Annotated[UserRecord, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    """List recent audit log entries (service invocations)."""
    from datetime import datetime, timedelta, timezone

    root = get_honeycomb(honeycomb_root).root_dir
    audit_dir = root / "audit"
    if not audit_dir.exists():
        return {"logs": [], "count": 0}

    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    entries: list[dict[str, Any]] = []
    today = datetime.now(timezone.utc)
    # Read last 7 days of audit files (most recent first)
    for day_offset in range(8):
        d = today - timedelta(days=day_offset)
        path = audit_dir / f"{d.strftime('%Y%m%d')}.jsonl"
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        at = row.get("at", "")
                        if since_dt and at:
                            try:
                                at_dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
                                if at_dt.tzinfo is None:
                                    at_dt = at_dt.replace(tzinfo=timezone.utc)
                                if at_dt < since_dt:
                                    continue
                            except ValueError:
                                pass
                        if service and row.get("service") != service:
                            continue
                        if action and row.get("action") != action:
                            continue
                        if source and row.get("source") != source:
                            continue
                        entries.append(row)
                    except json.JSONDecodeError:
                        pass
        except OSError:
            pass

    # Sort by at descending (most recent first)
    entries.sort(key=lambda e: e.get("at", ""), reverse=True)
    entries = entries[:limit]
    return {"logs": entries, "count": len(entries)}


@router.get("/api/stream/events")
def stream_events() -> StreamingResponse:
    # Lightweight demo stream for dashboard cards and live health chips.
    def _iter() -> Any:
        yield "event: ready\ndata: {\"status\":\"connected\"}\n\n"

    return StreamingResponse(_iter(), media_type="text/event-stream")
