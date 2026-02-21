from __future__ import annotations

import asyncio
import hmac
import json
import queue
import threading
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from beehive.channels import ChatHub
from beehive.ops import compute_ops_metrics
from beehive.queen import QueenAgent, QueenConfig
from beehive.queen_updates import list_queen_updates
from beehive.store import BeekeeperStore
from beehive.tenancy import UserRecord
from beehive.user_memory import extract_memories

from .auth import create_access_token, get_current_user, hash_password, verify_password
from .deps import get_honeycomb, get_store, get_worker_registry

router = APIRouter()


# def _get_whatsapp_config() -> dict[str, Any] | None:
#     """WhatsApp config from store + env (env overrides). Allows full config via .env."""
#     import os
#
#     store = get_store()
#     config = dict(store.get_channel_config_decrypted("whatsapp") or {})
#     env_keys = [
#         ("WHATSAPP_ACCESS_TOKEN", "whatsapp_access_token"),
#         ("WHATSAPP_PHONE_NUMBER_ID", "whatsapp_phone_number_id"),
#         ("WHATSAPP_APP_SECRET", "whatsapp_app_secret"),
#         ("WHATSAPP_VERIFY_TOKEN", "whatsapp_verify_token"),
#     ]
#     for env_name, config_key in env_keys:
#         val = os.getenv(env_name)
#         if val:
#             config[config_key] = val
#     return config if (config.get("whatsapp_access_token") or config.get("whatsapp_verify_token")) else None


def _can_access_chat(chat: dict[str, Any], user_id: str) -> bool:
    """Allow access if user owns the chat or it's a channel chat (WhatsApp, etc.)."""
    return chat.get("user_id") == user_id or chat.get("user_id") == "__channel__"


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
    scheduler: str = "inline"
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
    scheduler: str = "inline"
    vector: str = "memory"


class UpdateChatRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None


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
        from beehive.contracts import AgentBlueprint

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
    if channel == "whatsapp":
        raise HTTPException(status_code=404, detail="not_found")  # WhatsApp disabled
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
    from beehive.channel_auth import verify_slack_signature
    from beehive.channels import ChatHub
    from beehive.queen import QueenAgent, QueenConfig

    body = await request.body()
    store = get_store()
    if channel == "whatsapp":
        raise HTTPException(status_code=404, detail="channel_not_configured")  # WhatsApp disabled
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
                from beehive.channel_allowlist import check_channel_allowlist
                from beehive.channel_mention import check_mention_required, _get_slack_bot_user_id
                allowed, reason = check_channel_allowlist(config, channel_id, user_id)
                if not allowed:
                    return JSONResponse(content={"ok": True})  # Silently ignore; avoid leaking allowlist
                bot_user_id = config.get("slack_bot_user_id") or (config.get("slack_bot_token") and _get_slack_bot_user_id(config["slack_bot_token"]))
                mention_ok, _ = check_mention_required(config, "slack", text, bot_user_id=bot_user_id)
                if not mention_ok:
                    return JSONResponse(content={"ok": True})  # Silently ignore when require_mention and no @mention
                is_dm = ev.get("channel_type") == "im"
                if config.get("require_dm_pairing") and is_dm:
                    from beehive.channel_pairing import looks_like_pairing_code
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
                queen = QueenAgent(QueenConfig(honeycomb_root=Path(honeycomb_root)))
                hub = ChatHub(queen)
                result = hub.dispatch(
                    "slack",
                    dispatch_payload,
                    intent="research_topic",
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
            from beehive.channel_allowlist import check_channel_allowlist
            from beehive.channel_mention import check_mention_required
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
                from beehive.channel_pairing import looks_like_pairing_code
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
                queen = QueenAgent(QueenConfig(honeycomb_root=Path(honeycomb_root)))
                hub = ChatHub(queen)
                result = hub.dispatch("telegram", dispatch_payload, intent="research_topic")
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
        from beehive.channel_auth import verify_discord_signature

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
            from beehive.channel_allowlist import check_channel_allowlist
            allowed, reason = check_channel_allowlist(config, channel_id, user_id)
            if not allowed:
                return JSONResponse(content={"type": 4, "data": {"content": "You do not have access to this bot.", "flags": 64}})
            honeycomb_root = config.get("honeycomb_root", ".honeycomb")
            dispatch_payload: dict = {"sender": user_id, "text": text, "channel_id": channel_id, "interaction": payload}
            model_override = store.resolve_llm_model(honeycomb_root=honeycomb_root)
            if model_override:
                dispatch_payload["model_override"] = model_override
            queen = QueenAgent(QueenConfig(honeycomb_root=Path(honeycomb_root)))
            hub = ChatHub(queen)
            result = hub.dispatch(
                "discord",
                dispatch_payload,
                intent="research_topic",
            )
            resp = result.get("response", {})
            results = resp.get("results", [])
            reply = str(results[0]["output"]) if results and results[0].get("output") else "Request processed."
            return JSONResponse(content={"type": 4, "data": {"content": reply[:2000]}})
        return JSONResponse(content={"type": 1})

    # if channel == "whatsapp":
    #     from beehive.channel_auth import verify_whatsapp_signature
    #
    #     app_secret = config.get("whatsapp_app_secret")
    #     sig_header = request.headers.get("x-hub-signature-256", "")
    #     if app_secret and not verify_whatsapp_signature(body, sig_header, app_secret):
    #         raise HTTPException(status_code=401, detail="invalid_whatsapp_signature")
    #     import json as _json
    #     payload = _json.loads(body)
    #     entries = payload.get("entry", [])
    #     for entry in entries:
    #         for change in entry.get("changes", []):
    #             if change.get("field") != "messages":
    #                 continue
    #             value = change.get("value", {})
    #             messages = value.get("messages", [])
    #             phone_number_id = value.get("metadata", {}).get("phone_number_id") or config.get("whatsapp_phone_number_id")
    #             access_token = config.get("whatsapp_access_token")
    #             honeycomb_root = config.get("honeycomb_root", ".honeycomb")
    #             queen = QueenAgent(QueenConfig(honeycomb_root=Path(honeycomb_root)))
    #             hub = ChatHub(queen)
    #             whatsapp_chat = store.get_or_create_channel_chat("whatsapp", "WhatsApp")
    #             chat_id = whatsapp_chat["chat_id"]
    #             for msg in messages:
    #                 if msg.get("type") != "text":
    #                     continue
    #                 text_obj = msg.get("text", {})
    #                 text = text_obj.get("body", "")
    #                 if not text:
    #                     continue
    #                 sender = msg.get("from", "unknown")
    #                 msg_id = msg.get("id", "")
    #                 store.append_chat_message(chat_id, "user", text, source="whatsapp")
    #                 result = hub.dispatch(
    #                     "whatsapp",
    #                     {"sender": sender, "text": text, "chat_id": sender, "message_id": msg_id},
    #                     intent="research_topic",
    #                 )
    #                 resp = result.get("response", {})
    #                 results = resp.get("results", [])
    #                 reply = str(results[0]["output"]) if results and results[0].get("output") else "Request processed."
    #                 store.append_chat_message(chat_id, "assistant", reply)
    #                 if access_token and phone_number_id:
    #                     try:
    #                         import urllib.request
    #                         import urllib.parse
    #                         url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
    #                         data = _json.dumps({
    #                             "messaging_product": "whatsapp",
    #                             "to": sender.replace("@s.whatsapp.net", ""),
    #                             "type": "text",
    #                             "text": {"body": reply[:4000]},
    #                         }).encode("utf-8")
    #                         req = urllib.request.Request(
    #                             url,
    #                             data=data,
    #                             method="POST",
    #                             headers={
    #                                 "Authorization": f"Bearer {access_token}",
    #                                 "Content-Type": "application/json",
    #                             },
    #                         )
    #                         urllib.request.urlopen(req, timeout=15)
    #                     except Exception:
    #                         pass
    #     return JSONResponse(content={"ok": True})

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
    queen = _queen_from_request(body)
    return queen.run(intent=body.intent, payload=body.payload)


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
    # # Ensure WhatsApp chat exists when channel is configured (shows in sidebar)
    # whatsapp_config = _get_whatsapp_config()
    # if whatsapp_config and whatsapp_config.get("whatsapp_access_token"):
    #     store.get_or_create_channel_chat("whatsapp", "WhatsApp")
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
    memories = [{"content": m["content"]} for m in store.list_user_memories(user.user_id)]
    payload = {"query": content, "messages": prior, "user_memories": memories}
    queen = QueenAgent(
        QueenConfig(
            honeycomb_root=Path(body.honeycomb_root),
            scheduler_backend=body.scheduler,
            vector_backend=body.vector,
        )
    )
    result = queen.run(intent=body.intent, payload=payload)
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
    for mem in extract_memories(content, reply, honeycomb_root=body.honeycomb_root):
        store.append_user_memory(user.user_id, mem, chat_id=chat_id)
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
    memories = [{"content": m["content"]} for m in store.list_user_memories(user.user_id)]
    payload = {"query": content, "messages": prior, "user_memories": memories}

    status_queue: queue.Queue[str | None] = queue.Queue()
    result_holder: list[dict[str, Any]] = []

    def _run() -> None:
        queen = QueenAgent(
            QueenConfig(
                honeycomb_root=Path(body.honeycomb_root),
                scheduler_backend=body.scheduler,
                vector_backend=body.vector,
            )
        )

        def on_status(msg: str) -> None:
            status_queue.put(msg)

        result = queen.run(intent=body.intent, payload=payload, status_callback=on_status)
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
        for mem in extract_memories(content, reply, honeycomb_root=body.honeycomb_root):
            store.append_user_memory(user.user_id, mem, chat_id=chat_id)
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
    queen = QueenAgent(QueenConfig(honeycomb_root=Path(body.honeycomb_root)))
    hub = ChatHub(queen)
    return hub.dispatch(body.channel, body.payload, intent=body.intent)


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
    root = Path(honeycomb_root)
    if not root.is_absolute():
        root = Path.cwd() / root
    return compute_ops_metrics(root)


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
    from beehive.queen_context import ensure_queen_context_file, load_queen_context
    root = P(honeycomb_root) if P(honeycomb_root).is_absolute() else P.cwd() / honeycomb_root
    ensure_queen_context_file(root)
    return {"context": load_queen_context(root), "path": str(root / "context" / "queen.md")}


@router.get("/api/stream/events")
def stream_events() -> StreamingResponse:
    # Lightweight demo stream for dashboard cards and live health chips.
    def _iter() -> Any:
        yield "event: ready\ndata: {\"status\":\"connected\"}\n\n"

    return StreamingResponse(_iter(), media_type="text/event-stream")
