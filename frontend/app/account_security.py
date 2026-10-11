"""Password login for provisioned users. No unauthenticated account registration."""
from __future__ import annotations
import hashlib
import hmac
import secrets

ROUNDS = 310_000


def make_hash(password: str) -> tuple[str, str]:
    if len(password) < 12 or len(password) > 256:
        raise ValueError('Password must be between 12 and 256 characters')
    salt = secrets.token_hex(24)
    return salt, hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ROUNDS).hex()


def verify_hash(password: str, salt: str, stored_hash: str) -> bool:
    if not isinstance(password, str) or len(password) > 256:
        return False
    try:
        derived = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ROUNDS)
        return hmac.compare_digest(derived, bytes.fromhex(stored_hash))
    except (TypeError, ValueError):
        return False
