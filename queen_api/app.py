"""OpenAI-compatible API adapter for Queen agent. Used by Open WebUI for chat."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from beehive.queen import QueenAgent, QueenConfig

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

app = FastAPI(title="Queen API", version="0.1.0", description="OpenAI-compatible adapter for Beehive Queen agent")

QUEEN_MODEL_ID = "beehive-queen"


def _get_queen_config() -> QueenConfig:
    honeycomb_root = Path(os.getenv("BEEHIVE_HONEYCOMB_ROOT", ".honeycomb"))
    return QueenConfig(
        honeycomb_root=honeycomb_root,
        scheduler_backend=os.getenv("BEEHIVE_SCHEDULER_BACKEND", "inline"),
        vector_backend=os.getenv("BEEHIVE_VECTOR_BACKEND", "qdrant"),
        vector_url=os.getenv("BEEHIVE_VECTOR_URL", "http://localhost:6333"),
        vector_collection=os.getenv("BEEHIVE_VECTOR_COLLECTION", "honeycomb_memory"),
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
    x_beehive_intent: str | None = Header(None, alias="X-Beehive-Intent"),
    x_beehive_model: str | None = Header(None, alias="X-Beehive-Model"),
):
    """OpenAI-compatible chat completions. Forwards to Queen agent. X-Beehive-Model overrides LLM model."""
    intent = x_beehive_intent or "research_topic"
    model_override = (x_beehive_model or "").strip() or None
    if model_override is None:
        try:
            from beehive.store import BeekeeperStore
            store = BeekeeperStore(root=Path(os.getenv("BEEKEEPER_STORE_ROOT", ".beekeeper_store")))
            honeycomb_root = os.getenv("BEEHIVE_HONEYCOMB_ROOT", ".honeycomb")
            model_override = store.resolve_llm_model(honeycomb_root=honeycomb_root)
        except Exception:
            pass
    query, prior = _parse_messages(request.messages or [])

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

    payload: dict = {"query": query}
    if prior:
        payload["messages"] = prior
    if model_override:
        payload["model_override"] = model_override

    config = _get_queen_config()
    queen = QueenAgent(config)
    result = queen.run(intent=intent, payload=payload)
    reply = _extract_reply(result)

    if request.stream:
        return _stream_reply(reply)

    return {
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
    return {"status": "ok", "service": "queen-api"}


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
    config = _get_queen_config()
    queen = QueenAgent(config)
    result = queen.run(intent=request.intent, payload=payload)
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
    from beehive.worker_registry import WorkerRegistry

    honeycomb_root = Path(os.getenv("BEEHIVE_HONEYCOMB_ROOT", ".honeycomb"))
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
    from beehive.honeycomb import HoneycombConfig, HoneycombStore

    honeycomb_root = Path(os.getenv("BEEHIVE_HONEYCOMB_ROOT", ".honeycomb"))
    store = HoneycombStore(
        HoneycombConfig(
            root_dir=honeycomb_root,
            vector_backend=os.getenv("BEEHIVE_VECTOR_BACKEND", "memory"),
            vector_collection=os.getenv("BEEHIVE_VECTOR_COLLECTION", "honeycomb_memory"),
            vector_url=os.getenv("BEEHIVE_VECTOR_URL", "http://localhost:6333"),
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
    from beehive.honeycomb import HoneycombConfig, HoneycombStore

    honeycomb_root = Path(os.getenv("BEEHIVE_HONEYCOMB_ROOT", ".honeycomb"))
    store = HoneycombStore(
        HoneycombConfig(
            root_dir=honeycomb_root,
            vector_backend=os.getenv("BEEHIVE_VECTOR_BACKEND", "memory"),
            vector_collection=os.getenv("BEEHIVE_VECTOR_COLLECTION", "honeycomb_memory"),
            vector_url=os.getenv("BEEHIVE_VECTOR_URL", "http://localhost:6333"),
        )
    )
    memory_id = store.write_queen_memory(
        content=request.content,
        source=request.source,
        tags=request.tags,
    )
    return {"ok": True, "memory_id": memory_id}


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
