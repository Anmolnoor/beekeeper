from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .routes import router

# Load .env at module load so QueenConfig/LLM get env vars (works with uvicorn and beekeeper-api)
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

app = FastAPI(title="Beekeeper API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
def index() -> JSONResponse:
    """Health/info endpoint."""
    return JSONResponse(
        {"status": "ok", "message": "Beekeeper API. Dashboard at /dashboard. Configure via CLI: beehive settings, beehive channels."}
    )


@app.get("/dashboard")
def dashboard() -> FileResponse:
    """Lightweight control dashboard for channels, templates, settings."""
    return FileResponse(_STATIC_DIR / "dashboard.html")


app.include_router(router)


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    import os
    import uvicorn

    port = int(os.getenv("BEEKEEPER_PORT", "8788"))
    uvicorn.run("beekeeper_api.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
