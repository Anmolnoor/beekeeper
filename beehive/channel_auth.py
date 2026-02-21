"""Channel auth: secret encryption and webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac
import os
from base64 import urlsafe_b64encode
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def _derive_key() -> bytes:
    secret = os.getenv("BEEKEEPER_CHANNEL_SECRET_KEY", "")
    if not secret:
        return Fernet.generate_key()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"beekeeper_channel_v1",
        iterations=100000,
    )
    key = urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))
    return key


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    try:
        f = Fernet(_derive_key())
        return f.encrypt(plain.encode("utf-8")).decode("ascii")
    except Exception:
        return plain


def decrypt_secret(encrypted: str) -> str:
    if not encrypted:
        return ""
    try:
        f = Fernet(_derive_key())
        return f.decrypt(encrypted.encode("ascii")).decode("utf-8")
    except Exception:
        return encrypted


def verify_slack_signature(body: bytes, signature: str, signing_secret: str) -> bool:
    if not signature or not signing_secret:
        return False
    if not signature.startswith("v0="):
        return False
    expected = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def verify_telegram_secret(token: str, secret: str) -> bool:
    return hmac.compare_digest(token, secret) if token and secret else False


def verify_discord_signature(body: bytes, signature: str, timestamp: str, public_key_hex: str) -> bool:
    """Verify Discord interaction ED25519 signature. Message is timestamp + body (bytes)."""
    if not signature or not timestamp or not public_key_hex:
        return False
    try:
        from nacl.signing import VerifyKey
        from nacl.encoding import HexEncoder

        key = VerifyKey(public_key_hex.encode("utf-8"), encoder=HexEncoder)
        message = timestamp.encode("utf-8") + body
        sig_bytes = bytes.fromhex(signature)
        key.verify(message, sig_bytes)
        return True
    except Exception:
        return False


def verify_whatsapp_signature(body: bytes, signature_header: str, app_secret: str) -> bool:
    """Verify WhatsApp/Meta webhook X-Hub-Signature-256 (sha256=hex(hmac_sha256(body, app_secret)))."""
    if not signature_header or not app_secret:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected_hex = signature_header[7:]
    computed = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_hex, computed)
