"""OpenAI-compatible API adapter for Beekeeper Lite."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from beekeeper.lite_agent import LiteAssistant


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

app = FastAPI(title="Beekeeper Lite API", version="0.1.0")
_assistant = LiteAssistant()
_STATIC_DIR = Path(__file__).parent / "static"
MODEL_ID = "beekeeper-lite"


class ChatCompletionRequest(BaseModel):
    model: str = MODEL_ID
    messages: list[dict] = Field(default_factory=list)
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


@app.get("/")
def index():
    return FileResponse(_STATIC_DIR / "lite.html")


@app.get("/health")
def health():
    return {"status": "ok", "service": "queen-api", "mode": "lite"}


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "created": 0}],
    }


@app.get("/v1/chats")
def list_chats(user_id: str = "local-user", limit: int = 50):
    chats = _assistant.list_chats(user_id=user_id, limit=limit)
    return {"chats": chats}


@app.get("/v1/chats/{chat_id}")
def get_chat(chat_id: str):
    chat = _assistant.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="chat not found")
    return chat


@app.post("/v1/chat/completions")
def chat_completions(
    request: ChatCompletionRequest,
    x_beekeeper_user_id: str | None = Header(None, alias="X-Beekeeper-User-Id"),
    x_beekeeper_chat_id: str | None = Header(None, alias="X-Beekeeper-Chat-Id"),
    x_beekeeper_model: str | None = Header(None, alias="X-Beekeeper-Model"),
):
    user_id = (x_beekeeper_user_id or "").strip() or "local-user"
    model_override = (x_beekeeper_model or "").strip() or None
    result = _assistant.chat(
        messages=request.messages,
        user_id=user_id,
        chat_id=(x_beekeeper_chat_id or "").strip() or None,
        model_override=model_override,
    )
    reply = result["reply"]
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
        "chat_id": result.get("chat_id"),
        "provider": result.get("provider"),
        "title": result.get("title"),
    }


def _stream_reply(reply: str) -> StreamingResponse:
    cid = f"chatcmpl-{uuid4().hex}"

    def _generate():
        yield "data: " + json.dumps(
            {
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
        ) + "\n\n"
        yield "data: " + json.dumps(
            {
                "id": cid,
                "object": "chat.completion.chunk",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
        ) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


def main() -> None:
    import os
    import uvicorn

    port = int(os.getenv("BEEKEEPER_QUEEN_PORT", os.getenv("BEEKEEPER_PORT", "8788")))
    uvicorn.run("queen_api.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
