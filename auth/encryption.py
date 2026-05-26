"""
backend/auth/encryption.py
==========================
AES-256-GCM encryption for API credentials stored in the database.
Uses the APP_SECRET_KEY from settings as the master key.

Why AES-GCM?
- Authenticated encryption: detects tampering (unlike AES-CBC)
- Each encryption generates a unique nonce → same plaintext encrypts differently
- Industry standard for secrets at rest
"""

import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from config.settings import get_settings

settings = get_settings()

# Derive a 32-byte AES key from the app secret
# Using PBKDF2 so the raw secret isn't used directly
_SALT = b"trading-system-v1-salt"  # fixed salt; change requires re-encryption


def _get_key() -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=100_000,
    )
    return kdf.derive(settings.app_secret_key.encode())


_KEY = _get_key()
_AESGCM = AESGCM(_KEY)


def encrypt(plaintext: str) -> str:
    """
    Encrypt plaintext → base64-encoded string (nonce + ciphertext).
    Store this in the database.
    """
    nonce = os.urandom(12)                       # 96-bit nonce for GCM
    ciphertext = _AESGCM.encrypt(nonce, plaintext.encode(), None)
    combined = nonce + ciphertext                # prepend nonce for decryption
    return base64.b64encode(combined).decode()


def decrypt(token: str) -> str:
    """
    Decrypt base64-encoded token back to plaintext.
    Raises InvalidTag if the data was tampered with.
    """
    combined = base64.b64decode(token.encode())
    nonce = combined[:12]
    ciphertext = combined[12:]
    plaintext = _AESGCM.decrypt(nonce, ciphertext, None)
    return plaintext.decode()
