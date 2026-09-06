"""Primitives for hashing secrets and minting tokens.

Two different hashing strategies, for two different threat models:

* **Argon2id** for party join passwords. These are low-entropy, human-chosen, and
  guessable, so the hash must be deliberately slow.
* **SHA-256** for magic-link and refresh tokens. These are 256 bits of CSPRNG
  output, so there is nothing to brute-force; a fast digest is correct here, and
  a slow one would put an Argon2 verification in the path of every refresh.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import Settings

_password_hasher = PasswordHasher()

TOKEN_BYTES = 32
ALGORITHM = "HS256"


class TokenError(Exception):
    """A token was missing, malformed, expired or not ours."""


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def generate_token() -> str:
    """A URL-safe random token. The raw value is shown to the user exactly once."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Digest of a high-entropy token, for storage and lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)


def create_access_token(settings: Settings, user_id: UUID, *, now: datetime | None = None) -> str:
    """Mint a short-lived access token.

    Claims are deliberately minimal — subject, id and validity window. Role,
    status and party membership are *not* here: they are read per request so an
    approval, kick or disable takes effect immediately rather than whenever the
    token happens to expire.
    """
    issued_at = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "jti": secrets.token_urlsafe(16),
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=ALGORITHM,
        headers={"kid": settings.jwt_key_id},
    )


def decode_access_token(settings: Settings, token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            # Pinning the algorithm is what stops an attacker presenting an
            # unsigned ("alg": "none") or asymmetric-confusion token.
            algorithms=[ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc


def access_token_subject(settings: Settings, token: str) -> UUID:
    payload = decode_access_token(settings, token)
    try:
        return UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise TokenError("token subject is not a user id") from exc


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def csrf_tokens_match(cookie_value: str | None, header_value: str | None) -> bool:
    """Double-submit comparison.

    Both halves must be present and equal. A missing header is a failure, not a
    pass — otherwise a cross-site form post would simply omit it.
    """
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)
