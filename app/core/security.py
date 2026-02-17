"""Password hashing (bcrypt) and credential encryption (AES-256-GCM)."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import BCRYPT_ROUNDS, ENCRYPTION_KEY, SESSION_LIFETIME_DAYS

# --------------- Password hashing ---------------


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plain-text password."""
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(plain.encode(), salt).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Check a plain-text password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# --------------- Session tokens ---------------


def generate_session_token() -> str:
    return str(uuid.uuid4())


def session_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=SESSION_LIFETIME_DAYS)


# --------------- AES-256-GCM encryption ---------------


def _get_aes_key() -> bytes:
    """Derive a 32-byte key from the ENCRYPTION_KEY env var."""
    raw = ENCRYPTION_KEY.encode()
    # If it looks like hex (64 chars), decode it; otherwise hash it to 32 bytes
    if len(raw) == 64:
        try:
            return bytes.fromhex(ENCRYPTION_KEY)
        except ValueError:
            pass
    # Fallback: use SHA-256 of the key material
    import hashlib

    return hashlib.sha256(raw).digest()


def encrypt_credentials(data: dict) -> bytes:
    """Encrypt a dict as JSON using AES-256-GCM. Returns nonce + ciphertext."""
    key = _get_aes_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce
    plaintext = json.dumps(data).encode()
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext  # 12 bytes nonce | ciphertext+tag


def decrypt_credentials(blob: bytes) -> dict:
    """Decrypt AES-256-GCM encrypted credentials back to a dict."""
    key = _get_aes_key()
    aesgcm = AESGCM(key)
    nonce = blob[:12]
    ciphertext = blob[12:]
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode())
