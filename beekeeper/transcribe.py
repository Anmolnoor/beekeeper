"""Audio transcription for WhatsApp voice/audio messages."""
from __future__ import annotations

import os
import tempfile
import urllib.request
from pathlib import Path


def transcribe_audio(audio_bytes: bytes, *, openai_api_key: str | None = None) -> str:
    """
    Transcribe audio bytes to text.
    Uses OpenAI Whisper API if BEEKEEPER_OPENAI_API_KEY or openai_api_key is set.
    Otherwise returns fallback message.
    """
    key = openai_api_key or os.getenv("BEEKEEPER_OPENAI_API_KEY", "").strip()
    if not key:
        return "[Audio received. Transcription requires BEEKEEPER_OPENAI_API_KEY. Please send a text message.]"

    try:
        import openai
    except ImportError:
        return "[Audio received. Install openai package for transcription: pip install openai]"

    try:
        client = openai.OpenAI(api_key=key)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(audio_bytes)
            path = f.name
        try:
            with open(path, "rb") as fp:
                transcript = client.audio.transcriptions.create(model="whisper-1", file=fp)
            return transcript.text.strip() or "[Empty transcription]"
        finally:
            Path(path).unlink(missing_ok=True)
    except Exception as e:
        return f"[Transcription failed: {e}. Please send a text message.]"


def fetch_whatsapp_media(media_id: str, access_token: str) -> bytes | None:
    """Fetch WhatsApp media by ID from Graph API. Returns raw bytes or None on failure."""
    url = f"https://graph.facebook.com/v21.0/{media_id}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
        payload = __import__("json").loads(data.decode("utf-8"))
        media_url = payload.get("url")
        if not media_url:
            return None
        req2 = urllib.request.Request(media_url, headers={"Authorization": f"Bearer {access_token}"})
        with urllib.request.urlopen(req2, timeout=60) as r2:
            return r2.read()
    except Exception:
        return None
