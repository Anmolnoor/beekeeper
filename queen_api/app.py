"""Phase 1 control API for Beekeeper."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from beekeeper.config.settings import Phase1Settings
from beekeeper.lite_agent import LiteAssistant, LiteAssistantConfig
from beekeeper.runtime import get_runtime_service


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

app = FastAPI(title="Beekeeper Phase 1 API", version="0.1.0")
_settings = Phase1Settings()
_runtime = get_runtime_service(_settings)
_assistant = LiteAssistant(LiteAssistantConfig(store_root=_settings.runtime_root / "store"))
_STATIC_DIR = Path(__file__).parent / "static"

class RunJobRequest(BaseModel):
    job_type: str = "task"
    worker_kind: str = "bash"
    payload: dict = Field(default_factory=dict)


class RunCreateRequest(BaseModel):
    goal: str
    workspace_path: str | None = None
    background: bool = False
    worker_kind: str = "bash"
    job_type: str = "task"
    payload: dict = Field(default_factory=dict)
    jobs: list[RunJobRequest] = Field(default_factory=list)


class ApprovalResolveRequest(BaseModel):
    resolved_by: str = "api"


class ChatCompletionRequest(BaseModel):
    model: str = "beekeeper-lite"
    messages: list[dict[str, Any]] = Field(default_factory=list)
    stream: bool = False


def _model_dump(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


@app.get("/")
def index():
    return FileResponse(_STATIC_DIR / "lite.html")


@app.get("/health")
def health():
    return {"status": "ok", "service": "queen-api", "mode": "phase1"}


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "beekeeper-lite",
                "object": "model",
                "created": 0,
                "owned_by": "beekeeper",
            }
        ],
    }


@app.get("/v1/chats")
def list_chats(user_id: str = Query(...)):
    return {"chats": _assistant.list_chats(user_id=user_id)}


@app.get("/v1/chats/{chat_id}")
def get_chat(chat_id: str):
    chat = _assistant.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    return chat


@app.post("/v1/chat/completions")
def create_chat_completion(
    request: ChatCompletionRequest,
    beekeeper_user_id: str | None = Header(default=None, alias="X-Beekeeper-User-Id"),
    beekeeper_chat_id: str | None = Header(default=None, alias="X-Beekeeper-Chat-Id"),
):
    if request.stream:
        raise HTTPException(status_code=400, detail="streaming_not_supported")
    result = _assistant.chat(
        messages=request.messages,
        user_id=(beekeeper_user_id or "local-user").strip() or "local-user",
        chat_id=(beekeeper_chat_id or "").strip() or None,
        model_override=request.model,
    )
    created = _now_unix()
    return {
        "id": f"chatcmpl_{created}",
        "object": "chat.completion",
        "created": created,
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.get("reply", "")},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "provider": result.get("provider", "fallback"),
        "chat_id": result.get("chat_id"),
        "title": result.get("title", "New Chat"),
    }


@app.post("/v1/runs")
def create_run(request: RunCreateRequest):
    run_request = _model_dump(request)
    if request.jobs:
        run_request["jobs"] = [_model_dump(job) for job in request.jobs]
    run = _runtime.submit_run(run_request, background=request.background)
    return run


@app.get("/v1/runs/{run_id}")
def get_run(run_id: str):
    run = _runtime.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@app.get("/v1/runs/{run_id}/trace")
def get_trace(run_id: str):
    run = _runtime.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run_id": run_id, "events": _runtime.get_trace(run_id)}


@app.get("/v1/runs/{run_id}/artifacts")
def get_artifacts(run_id: str):
    run = _runtime.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run_id": run_id, "artifacts": _runtime.get_artifacts(run_id)}


@app.post("/v1/approvals/{approval_id}/approve")
def approve(approval_id: str, request: ApprovalResolveRequest):
    approval = _runtime.resolve_approval(approval_id, approved=True, resolved_by=request.resolved_by)
    return approval


@app.post("/v1/approvals/{approval_id}/reject")
def reject(approval_id: str, request: ApprovalResolveRequest):
    approval = _runtime.resolve_approval(approval_id, approved=False, resolved_by=request.resolved_by)
    return approval


def main() -> None:
    import os
    import uvicorn

    port = int(os.getenv("BEEKEEPER_QUEEN_PORT", os.getenv("BEEKEEPER_PORT", "8788")))
    uvicorn.run("queen_api.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
