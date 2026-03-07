"""OpenAI-compatible API adapter for Queen agent. Used by Open WebUI for chat."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from beekeeper.audit_logger import log_service_call
from beekeeper.config import format_runtime_validation_errors, resolve_runtime_mode, validate_runtime_config
from beekeeper.queen import QueenAgent, QueenConfig
from beekeeper.runtime_env import resolve_runtime_context

# Load .env at module load so QueenConfig/LLM get env vars
def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        root = Path(__file__).resolve().parent.parent
        env_path = root / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        load_dotenv()
    except ImportError:
        pass


_load_env()


def _enforce_runtime_config() -> None:
    report = validate_runtime_config(resolve_runtime_mode())
    if report.ok:
        return
    raise RuntimeError(format_runtime_validation_errors(report))


_enforce_runtime_config()

app = FastAPI(title="Queen API", version="0.1.0", description="OpenAI-compatible adapter for Beekeeper Queen agent")

# Module-level QueenAgent cache keyed on (honeycomb_root, execution_mode, scheduler_backend).
# Avoids 500ms–2s of expensive init ops (registry loads, Qdrant connect, etc.) per request.
_queen_cache: dict[str, QueenAgent] = {}


def _get_queen(config: QueenConfig) -> QueenAgent:
    key = f"{config.honeycomb_root}|{config.execution_mode}|{config.scheduler_backend}"
    if key not in _queen_cache:
        _queen_cache[key] = QueenAgent(config)
    return _queen_cache[key]


def _runtime_metadata() -> dict[str, str]:
    try:
        import beekeeper.queen as queen_module
        queen_path = Path(queen_module.__file__ or "").resolve()
        queen_mtime = str(int(queen_path.stat().st_mtime))
        queen_module_path = str(queen_path)
    except Exception:
        queen_mtime = "unknown"
        queen_module_path = "unknown"
    return {
        "runtime_context": resolve_runtime_context(),
        "runtime_version": os.getenv("BEEKEEPER_RUNTIME_VERSION", "dev-local"),
        "queen_module_path": queen_module_path,
        "queen_module_mtime_epoch": queen_mtime,
    }

QUEEN_MODEL_ID = "beekeeper-queen"


def _get_queen_config(execution_mode: str | None = None) -> QueenConfig:
    honeycomb_root = Path(os.getenv("BEEKEEPER_HONEYCOMB_ROOT", ".honeycomb"))
    mode = execution_mode or os.getenv("BEEKEEPER_EXECUTION_MODE", "legacy_worker")
    if mode not in ("legacy_worker", "model_tools", "hybrid"):
        mode = "legacy_worker"
    return QueenConfig(
        honeycomb_root=honeycomb_root,
        scheduler_backend=os.getenv("BEEKEEPER_SCHEDULER_BACKEND", "auto"),
        vector_backend=os.getenv("BEEKEEPER_VECTOR_BACKEND", "qdrant"),
        vector_url=os.getenv("BEEKEEPER_VECTOR_URL", "http://localhost:6333"),
        vector_collection=os.getenv("BEEKEEPER_VECTOR_COLLECTION", "honeycomb_memory"),
        execution_mode=mode,
    )


def _extract_reply(run_output: dict) -> str:
    """Extract assistant reply from Queen run result."""
    results = run_output.get("results", [])
    if not results or not isinstance(results[0], dict):
        return "No response."
    raw_output = results[0].get("output", {})
    for k in ("assistant_reply", "answer", "response", "content", "output", "summary", "text", "synthesis"):
        v = raw_output.get(k)
        if isinstance(v, str) and v.strip():
            return v
        if v and isinstance(v, dict) and isinstance(v.get("text"), str):
            return str(v.get("text", ""))
    return str(raw_output) if raw_output else "No response."


def _enqueue_context_curation(
    *,
    query: str,
    reply: str,
    user_id: str | None,
    chat_id: str | None,
    honeycomb_root: Path,
) -> None:
    """Run context curation in a daemon thread so API responses are non-blocking."""
    if not query.strip() or not reply.strip():
        return

    def _run() -> None:
        try:
            config = _get_queen_config()
            queen = _get_queen(config)
            payload: dict[str, str | bool] = {
                "user_msg": query[:1200],
                "assistant_reply": reply[:3000],
                "honeycomb_root": str(honeycomb_root),
                "delegate_to_worker": True,
            }
            if user_id:
                payload["user_id"] = user_id
            if chat_id:
                payload["chat_id"] = chat_id
            queen.run(intent="context_curation", payload=payload, source="queen_api:context_curator")
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


class ChatMessage(BaseModel):
    role: str
    content: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str = QUEEN_MODEL_ID
    messages: list[dict] = Field(default_factory=list)
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


def _parse_messages(messages: list) -> tuple[str, list[dict[str, str]]]:
    """Extract query (last user content) and prior conversation from messages."""
    normalized: list[dict[str, str]] = []
    for m in messages:
        if isinstance(m, dict):
            role = str(m.get("role", "user"))
            content = m.get("content", "")
            if isinstance(content, str):
                pass
            elif hasattr(content, "__iter__") and not isinstance(content, str):
                # Handle multi-part content (e.g. [{"type":"text","text":"..."}])
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(str(part.get("text", "")))
                    elif isinstance(part, str):
                        parts.append(part)
                content = " ".join(parts)
            else:
                content = str(content) if content else ""
        else:
            role = getattr(m, "role", "user")
            content = getattr(m, "content", "") or ""
        normalized.append({"role": role, "content": str(content).strip()})

    query = ""
    prior: list[dict[str, str]] = []
    for i in range(len(normalized) - 1, -1, -1):
        if normalized[i]["role"] == "user" and normalized[i]["content"]:
            query = normalized[i]["content"]
            prior = normalized[:i]
            break
    return query, prior


@app.get("/v1/models")
def list_models():
    """OpenAI-compatible models endpoint. Returns Queen as the only model."""
    return {
        "object": "list",
        "data": [
            {
                "id": QUEEN_MODEL_ID,
                "object": "model",
                "created": 0,
            }
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(
    request: ChatCompletionRequest,
    x_beekeeper_intent: str | None = Header(None, alias="X-Beekeeper-Intent"),
    x_beekeeper_model: str | None = Header(None, alias="X-Beekeeper-Model"),
    x_beekeeper_user_id: str | None = Header(None, alias="X-Beekeeper-User-Id"),
    x_beekeeper_delegate_worker: str | None = Header(None, alias="X-Beekeeper-Delegate-Worker"),
    x_beekeeper_use_web_search: str | None = Header(None, alias="X-Beekeeper-Use-Web-Search"),
    x_beekeeper_execution_mode: str | None = Header(None, alias="X-Beekeeper-Execution-Mode"),
    x_beekeeper_debug: str | None = Header(None, alias="X-Beekeeper-Debug"),
):
    """OpenAI-compatible chat completions. X-Beekeeper-Execution-Mode: legacy_worker|model_tools|hybrid. X-Beekeeper-Debug: include tool_trace in response."""
    intent = x_beekeeper_intent or "research_topic"
    model_override = (x_beekeeper_model or "").strip() or None
    if model_override is None:
        try:
            from beekeeper.store import BeekeeperStore
            store = BeekeeperStore(root=Path(os.getenv("BEEKEEPER_STORE_ROOT", ".beekeeper_store")))
            honeycomb_root = os.getenv("BEEKEEPER_HONEYCOMB_ROOT", ".honeycomb")
            model_override = store.resolve_llm_model(honeycomb_root=honeycomb_root)
        except Exception:
            pass
    query, prior = _parse_messages(request.messages or [])

    user_id = (x_beekeeper_user_id or "").strip() or None
    user_memories: list[dict] = []
    if user_id:
        try:
            from beekeeper.store import BeekeeperStore
            store = BeekeeperStore(root=Path(os.getenv("BEEKEEPER_STORE_ROOT", ".beekeeper_store")))
            user_memories = [{"content": m["content"]} for m in store.search_user_memories(user_id, query=query, limit=18)]
        except Exception:
            pass

    empty_reply = "Please provide a message to process."
    if not query.strip():
        if request.stream:
            return _stream_reply(empty_reply)
        return {
            "id": f"chatcmpl-{uuid4().hex}",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": empty_reply},
                    "finish_reason": "stop",
                }
            ],
        }

    # Default to worker delegation for Open WebUI traffic; allow explicit override via headers.
    delegate_to_worker = (x_beekeeper_delegate_worker or "true").strip().lower() in {"1", "true", "yes", "on"}
    use_web_search = (x_beekeeper_use_web_search or "true").strip().lower() in {"1", "true", "yes", "on"}
    payload: dict = {
        "query": query,
        "delegate_to_worker": delegate_to_worker,
        "use_web_search": use_web_search,
    }
    if prior:
        payload["messages"] = prior
    if model_override:
        payload["model_override"] = model_override
    if user_memories:
        payload["user_memories"] = user_memories

    log_service_call("queen_api", "called", source="queen_api", user_id=user_id, resource="queen:chat")
    config = _get_queen_config(execution_mode=(x_beekeeper_execution_mode or "").strip() or None)
    queen = _get_queen(config)
    result = queen.run(intent=intent, payload=payload, source="queen_api")
    log_service_call(
        "queen",
        "completed",
        source="queen_api",
        user_id=user_id,
        resource="queen:chat",
        trace_id=result.get("trace_id"),
    )
    reply = _extract_reply(result)

    honeycomb_root = Path(os.getenv("BEEKEEPER_HONEYCOMB_ROOT", ".honeycomb"))
    _enqueue_context_curation(
        query=query,
        reply=reply,
        user_id=user_id,
        chat_id=result.get("trace_id"),
        honeycomb_root=honeycomb_root,
    )

    if request.stream:
        return _stream_reply(reply)

    resp: dict = {
        "id": f"chatcmpl-{uuid4().hex}",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
    }
    include_debug = (x_beekeeper_debug or "").strip().lower() in ("1", "true", "yes", "on")
    if include_debug and result.get("results"):
        first = result["results"][0] if isinstance(result["results"][0], dict) else {}
        tool_trace = (first.get("output") or {}).get("tool_trace")
        if tool_trace is not None:
            resp["tool_trace"] = tool_trace
            resp["trace_id"] = result.get("trace_id")
    return resp


def _stream_reply(reply: str) -> StreamingResponse:
    """Wrap a complete reply as an SSE stream. Open WebUI requires stream=true responses
    to be text/event-stream — returning a plain dict causes it to hang indefinitely."""
    cid = f"chatcmpl-{uuid4().hex}"

    def _generate():
        # First chunk: role + full content (single-chunk stream is valid per OpenAI spec)
        first = {
            "id": cid,
            "object": "chat.completion.chunk",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": reply},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(first)}\n\n"
        # Final chunk: signals end of stream
        done = {
            "id": cid,
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(done)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "queen-api", **_runtime_metadata()}


# ---------------------------------------------------------------------------
# Actions endpoint — let the Queen take direct actions
# ---------------------------------------------------------------------------

class ActionsRequest(BaseModel):
    actions: list[dict] = Field(default_factory=list)
    intent: str = "research_topic"
    stop_after_actions: bool = True


@app.post("/v1/actions")
def run_actions(request: ActionsRequest):
    """Execute one or more Queen actions (remember, web_search, spawn_worker, run_task, summarize)."""
    if not request.actions:
        return {"ok": False, "error": "no actions provided"}

    payload: dict = {
        "query": request.intent,
        "queen_actions": request.actions,
        "stop_after_actions": request.stop_after_actions,
    }
    log_service_call("queen_api", "called", source="queen_api:actions", resource="queen:actions")
    config = _get_queen_config()
    queen = _get_queen(config)
    result = queen.run(intent=request.intent, payload=payload, source="queen_api")
    log_service_call("queen", "completed", source="queen_api", resource="queen:actions", trace_id=result.get("trace_id"))
    return {
        "ok": True,
        "trace_id": result.get("trace_id"),
        "action_loop": result.get("action_loop", {}),
    }


# ---------------------------------------------------------------------------
# Workers endpoint — dynamically register a new custom worker
# ---------------------------------------------------------------------------

class SpawnWorkerRequest(BaseModel):
    name: str
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    intent_patterns: list[str] = Field(default_factory=list)
    payload_triggers: list[str] = Field(default_factory=list)
    priority: int = 15


@app.post("/v1/workers")
def spawn_worker(request: SpawnWorkerRequest):
    """Dynamically register a new custom worker blueprint in the Queen's registry."""
    from beekeeper.worker_registry import WorkerRegistry

    honeycomb_root = Path(os.getenv("BEEKEEPER_HONEYCOMB_ROOT", ".honeycomb"))
    registry = WorkerRegistry(honeycomb_root)
    registry.ensure_registry_file()

    worker_kind = f"custom_{request.name.lower().replace(' ', '_')}"
    entry = registry.register_custom_worker(
        worker_kind=worker_kind,
        name=request.name,
        description=request.description or f"Custom worker: {request.name}",
        capabilities=request.capabilities or ["custom"],
        intent_patterns=request.intent_patterns,
        payload_triggers=request.payload_triggers,
        priority=request.priority,
        persist=True,
    )
    return {"ok": True, "worker": entry}


# ---------------------------------------------------------------------------
# Memories endpoints — read and write Queen memories
# ---------------------------------------------------------------------------

@app.get("/v1/memories")
def list_memories(limit: int = 50, tag: str | None = None):
    """List the Queen's persisted memories, most recent first."""
    from beekeeper.honeycomb import HoneycombConfig, HoneycombStore

    honeycomb_root = Path(os.getenv("BEEKEEPER_HONEYCOMB_ROOT", ".honeycomb"))
    store = HoneycombStore(
        HoneycombConfig(
            root_dir=honeycomb_root,
            vector_backend=os.getenv("BEEKEEPER_VECTOR_BACKEND", "qdrant"),
            vector_collection=os.getenv("BEEKEEPER_VECTOR_COLLECTION", "honeycomb_memory"),
            vector_url=os.getenv("BEEKEEPER_VECTOR_URL", "http://localhost:6333"),
        )
    )
    memories = store.read_queen_memories(limit=limit, tag=tag)
    return {"memories": memories, "count": len(memories)}


class MemoryWriteRequest(BaseModel):
    content: str
    source: str = "api"
    tags: list[str] = Field(default_factory=list)


@app.post("/v1/memories")
def write_memory(request: MemoryWriteRequest):
    """Manually add a memory entry to the Queen's memory store."""
    from beekeeper.honeycomb import HoneycombConfig, HoneycombStore

    honeycomb_root = Path(os.getenv("BEEKEEPER_HONEYCOMB_ROOT", ".honeycomb"))
    store = HoneycombStore(
        HoneycombConfig(
            root_dir=honeycomb_root,
            vector_backend=os.getenv("BEEKEEPER_VECTOR_BACKEND", "qdrant"),
            vector_collection=os.getenv("BEEKEEPER_VECTOR_COLLECTION", "honeycomb_memory"),
            vector_url=os.getenv("BEEKEEPER_VECTOR_URL", "http://localhost:6333"),
        )
    )
    memory_id = store.write_queen_memory(
        content=request.content,
        source=request.source,
        tags=request.tags,
    )
    return {"ok": True, "memory_id": memory_id}


# ---------------------------------------------------------------------------
# Policy endpoints — per-user autonomy policy (no auth in queen_api, user_id via header)
# ---------------------------------------------------------------------------

class PolicyUpdateRequest(BaseModel):
    always_allow: list[str] | None = None
    always_ask: list[str] | None = None
    always_deny: list[str] | None = None
    max_auto_cost_usd: float | None = None


@app.get("/v1/policy")
def get_policy(x_beekeeper_user_id: str | None = Header(None, alias="X-Beekeeper-User-Id")):
    """Get autonomy policy for a user (identified by X-Beekeeper-User-Id header)."""
    from beekeeper.user_policy import load_user_policy

    user_id = (x_beekeeper_user_id or "").strip() or "default"
    store_root = os.getenv("BEEKEEPER_STORE_ROOT", ".beekeeper_store")
    policy = load_user_policy(store_root, user_id)
    return {"policy": policy.model_dump(mode="json"), "user_id": user_id}


@app.put("/v1/policy")
def update_policy(
    request: PolicyUpdateRequest,
    x_beekeeper_user_id: str | None = Header(None, alias="X-Beekeeper-User-Id"),
):
    """Update autonomy policy for a user."""
    from beekeeper.user_policy import load_user_policy, save_user_policy

    user_id = (x_beekeeper_user_id or "").strip() or "default"
    store_root = os.getenv("BEEKEEPER_STORE_ROOT", ".beekeeper_store")
    policy = load_user_policy(store_root, user_id)
    if request.always_allow is not None:
        policy.always_allow = request.always_allow
    if request.always_ask is not None:
        policy.always_ask = request.always_ask
    if request.always_deny is not None:
        policy.always_deny = request.always_deny
    if request.max_auto_cost_usd is not None:
        policy.max_auto_cost_usd = request.max_auto_cost_usd
    save_user_policy(store_root, user_id, policy)
    return {"ok": True, "policy": policy.model_dump(mode="json"), "user_id": user_id}


# ---------------------------------------------------------------------------
# Workers catalog — list all workers with generation status
# ---------------------------------------------------------------------------

@app.get("/v1/workers")
def list_workers():
    """List all registered workers (built-in + custom + generated)."""
    from beekeeper.worker_registry import WorkerRegistry

    honeycomb_root = Path(os.getenv("BEEKEEPER_HONEYCOMB_ROOT", ".honeycomb"))
    registry = WorkerRegistry(honeycomb_root)
    all_workers = registry.list_workers()
    generated_dir = honeycomb_root / "workers" / "generated"
    generated_kinds: set[str] = set()
    if generated_dir.exists():
        for f in generated_dir.glob("*.py"):
            generated_kinds.add(f.stem)
    enriched = []
    for w in all_workers:
        entry = dict(w)
        kind = entry.get("worker_kind", "")
        entry["is_generated"] = kind in generated_kinds
        enriched.append(entry)
    return {
        "workers": enriched,
        "total": len(enriched),
        "generated_count": len(generated_kinds),
        "default_worker": registry.get_default_worker().value,
    }


# ---------------------------------------------------------------------------
# HITL reviews — list, approve, deny pending human reviews
# ---------------------------------------------------------------------------

class ReviewActionRequest(BaseModel):
    approver: str = "operator"
    note: str | None = None


@app.get("/v1/reviews")
def list_reviews(x_beekeeper_user_id: str | None = Header(None, alias="X-Beekeeper-User-Id")):
    """List pending HITL review requests."""
    from beekeeper.honeycomb import HoneycombConfig, HoneycombStore

    honeycomb_root = Path(os.getenv("BEEKEEPER_HONEYCOMB_ROOT", ".honeycomb"))
    store = HoneycombStore(
        HoneycombConfig(
            root_dir=honeycomb_root,
            vector_backend=os.getenv("BEEKEEPER_VECTOR_BACKEND", "qdrant"),
            vector_collection=os.getenv("BEEKEEPER_VECTOR_COLLECTION", "honeycomb_memory"),
            vector_url=os.getenv("BEEKEEPER_VECTOR_URL", "http://localhost:6333"),
        )
    )
    pending = store.list_pending_reviews()
    return {
        "pending_count": len(pending),
        "reviews": [r.model_dump(mode="json") for r in pending],
    }


@app.post("/v1/reviews/{review_id}/approve")
def approve_review(
    review_id: str,
    request: ReviewActionRequest = ReviewActionRequest(),
    x_beekeeper_user_id: str | None = Header(None, alias="X-Beekeeper-User-Id"),
):
    """Approve a pending HITL review."""
    from fastapi import HTTPException

    from beekeeper.honeycomb import HoneycombConfig, HoneycombStore

    honeycomb_root = Path(os.getenv("BEEKEEPER_HONEYCOMB_ROOT", ".honeycomb"))
    store = HoneycombStore(
        HoneycombConfig(
            root_dir=honeycomb_root,
            vector_backend=os.getenv("BEEKEEPER_VECTOR_BACKEND", "qdrant"),
            vector_collection=os.getenv("BEEKEEPER_VECTOR_COLLECTION", "honeycomb_memory"),
            vector_url=os.getenv("BEEKEEPER_VECTOR_URL", "http://localhost:6333"),
        )
    )
    review = store.get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="review_not_found")
    if review.status != "pending":
        return {"review": review.model_dump(mode="json"), "resumed": False}
    approver = (x_beekeeper_user_id or "").strip() or request.approver or "operator"
    config = _get_queen_config()
    queen = _get_queen(config)
    result = queen.resume_human_review(
        review_id,
        approver=approver,
        approved=True,
        note=request.note or "",
    )
    resolved = store.get_review(review_id)
    return {
        "review": resolved.model_dump(mode="json") if resolved else {},
        "resumed": result.get("resumed", False),
    }


@app.post("/v1/reviews/{review_id}/deny")
def deny_review(
    review_id: str,
    request: ReviewActionRequest = ReviewActionRequest(),
    x_beekeeper_user_id: str | None = Header(None, alias="X-Beekeeper-User-Id"),
):
    """Deny a pending HITL review."""
    from fastapi import HTTPException

    from beekeeper.honeycomb import HoneycombConfig, HoneycombStore

    honeycomb_root = Path(os.getenv("BEEKEEPER_HONEYCOMB_ROOT", ".honeycomb"))
    store = HoneycombStore(
        HoneycombConfig(
            root_dir=honeycomb_root,
            vector_backend=os.getenv("BEEKEEPER_VECTOR_BACKEND", "qdrant"),
            vector_collection=os.getenv("BEEKEEPER_VECTOR_COLLECTION", "honeycomb_memory"),
            vector_url=os.getenv("BEEKEEPER_VECTOR_URL", "http://localhost:6333"),
        )
    )
    review = store.get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="review_not_found")
    if review.status != "pending":
        return {"review": review.model_dump(mode="json")}
    approver = (x_beekeeper_user_id or "").strip() or request.approver or "operator"
    resolved = store.resolve_review(
        review_id,
        approved=False,
        approver=approver,
        note=request.note,
    )
    return {"review": resolved.model_dump(mode="json")}


# ---------------------------------------------------------------------------
# Work history — recent trace summaries
# ---------------------------------------------------------------------------

@app.get("/v1/history")
def get_history(limit: int = 20):
    """Return recent Queen trace summaries."""
    from beekeeper.honeycomb import HoneycombConfig, HoneycombStore

    honeycomb_root = Path(os.getenv("BEEKEEPER_HONEYCOMB_ROOT", ".honeycomb"))
    store = HoneycombStore(
        HoneycombConfig(
            root_dir=honeycomb_root,
            vector_backend=os.getenv("BEEKEEPER_VECTOR_BACKEND", "qdrant"),
            vector_collection=os.getenv("BEEKEEPER_VECTOR_COLLECTION", "honeycomb_memory"),
            vector_url=os.getenv("BEEKEEPER_VECTOR_URL", "http://localhost:6333"),
        )
    )
    summaries = store.list_recent_traces(limit=max(1, min(limit, 100)))
    return {"history": summaries, "count": len(summaries)}


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    import uvicorn

    uvicorn.run("queen_api.app:app", host="0.0.0.0", port=8788, reload=False)


if __name__ == "__main__":
    main()
