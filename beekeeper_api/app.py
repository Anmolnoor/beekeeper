from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .routes import router
from .setup import is_fresh_install

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
def index():
    """Health/info endpoint. Redirects to setup wizard when fresh install."""
    if is_fresh_install():
        return RedirectResponse(url="/setup", status_code=302)
    return JSONResponse(
        {"status": "ok", "message": "Beekeeper API. Dashboard at /dashboard. Configure via CLI: beekeeper settings, beekeeper channels."}
    )


@app.get("/setup")
def setup():
    """First-run setup wizard. Served when fresh install detected."""
    if not is_fresh_install():
        return RedirectResponse(url="/dashboard", status_code=302)
    return FileResponse(_STATIC_DIR / "setup.html")


@app.get("/dashboard")
def dashboard():
    """Lightweight control dashboard for channels, templates, settings."""
    if is_fresh_install():
        return RedirectResponse(url="/setup", status_code=302)
    return FileResponse(_STATIC_DIR / "dashboard.html")


@app.get("/audit")
def audit_page():
    """Full audit trail page for chronological service invocation logs."""
    if is_fresh_install():
        return RedirectResponse(url="/setup", status_code=302)
    return FileResponse(_STATIC_DIR / "audit.html")


@app.get("/trace/{trace_id}")
def trace_page(trace_id: str):
    """Trace detail page showing events for a single trace."""
    if is_fresh_install():
        return RedirectResponse(url="/setup", status_code=302)
    return FileResponse(_STATIC_DIR / "trace.html")


@app.get("/activity")
def activity_page():
    """Activity analytics page with live counters and graphs."""
    if is_fresh_install():
        return RedirectResponse(url="/setup", status_code=302)
    return FileResponse(_STATIC_DIR / "activity.html")


app.include_router(router)


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    import os
    import uvicorn

    port = int(os.getenv("BEEKEEPER_PORT", "8787"))
    uvicorn.run("beekeeper_api.app:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    main()
