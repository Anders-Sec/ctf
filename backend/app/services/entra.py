"""Entra ID (OIDC) login for employees.

Authorization Code with PKCE, handled entirely server-side: the SPA never sees
an Entra token, only our own session cookie. Every employee signs in this way,
so no password is ever stored, transmitted or checked by this platform.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import jwt
from jwt import PyJWKClient

from app.config import Settings
from app.logging import get_logger

logger = get_logger(__name__)

GRAPH_PHOTO_URL = "https://graph.microsoft.com/v1.0/me/photos/96x96/$value"
SCOPES = "openid profile email User.Read"

#: Entra photos are small; this cap exists so a surprising response cannot put
#: megabytes into a row that is read on every avatar request.
MAX_AVATAR_BYTES = 128 * 1024

#: The login round trip is a redirect out and back. Ten minutes is generous for
#: a human at an SSO prompt and short enough to limit replay of a state cookie.
STATE_TTL_SECONDS = 600

_jwk_clients: dict[str, PyJWKClient] = {}


class EntraError(Exception):
    """The login could not be completed."""


@dataclass(frozen=True)
class EntraProfile:
    object_id: UUID
    email: str
    display_name: str
    access_token: str


def _tenant_base(settings: Settings) -> str:
    return f"https://login.microsoftonline.com/{settings.entra_tenant_id}"


def _jwk_client(settings: Settings) -> PyJWKClient:
    """Cached per tenant: refetching JWKS on every login would be a rate limit."""
    url = f"{_tenant_base(settings)}/discovery/v2.0/keys"
    if url not in _jwk_clients:
        _jwk_clients[url] = PyJWKClient(url, cache_keys=True)
    return _jwk_clients[url]


def build_authorization_url(settings: Settings) -> tuple[str, str]:
    """Return the URL to redirect to, and a signed cookie value holding the state.

    PKCE verifier, state and nonce live in a short-lived signed cookie rather
    than in server memory, so a login survives the pod being replaced midway.
    """
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    now = datetime.now(UTC)
    state_cookie = jwt.encode(
        {
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "exp": int((now + timedelta(seconds=STATE_TTL_SECONDS)).timestamp()),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )

    params = {
        "client_id": settings.entra_client_id or "",
        "response_type": "code",
        "redirect_uri": settings.entra_redirect_uri or "",
        "response_mode": "query",
        "scope": SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    query = str(httpx.QueryParams(params))
    return f"{_tenant_base(settings)}/oauth2/v2.0/authorize?{query}", state_cookie


def decode_state_cookie(settings: Settings, cookie_value: str) -> dict[str, Any]:
    try:
        return jwt.decode(cookie_value, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise EntraError("login state expired or invalid") from exc


async def exchange_code(
    settings: Settings, code: str, verifier: str, *, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        response = await client.post(
            f"{_tenant_base(settings)}/oauth2/v2.0/token",
            data={
                "client_id": settings.entra_client_id or "",
                "client_secret": settings.entra_client_secret or "",
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.entra_redirect_uri or "",
                "code_verifier": verifier,
                "scope": SCOPES,
            },
        )
        if response.status_code != 200:
            # The body can echo the client secret back in an error description,
            # so only the status is logged.
            logger.warning("entra_token_exchange_failed", extra={"status": response.status_code})
            raise EntraError("token exchange rejected")
        return response.json()
    finally:
        if owns_client:
            await client.aclose()


def validate_id_token(settings: Settings, id_token: str, expected_nonce: str) -> dict[str, Any]:
    """Verify signature, issuer, audience and nonce.

    Skipping any one of these turns "signed by Entra" into "signed by someone",
    so they are all checked rather than trusted from the redirect.
    """
    try:
        signing_key = _jwk_client(settings).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.entra_client_id,
            issuer=f"{_tenant_base(settings)}/v2.0",
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise EntraError(f"id_token rejected: {exc}") from exc

    if claims.get("nonce") != expected_nonce:
        raise EntraError("id_token nonce mismatch")

    return claims


def profile_from_claims(claims: dict[str, Any], access_token: str) -> EntraProfile:
    object_id = claims.get("oid")
    if not object_id:
        raise EntraError("id_token has no object id")

    # Some tenants and B2B guest accounts omit `email`. Fall back rather than
    # inventing an identity key, and fail loudly if nothing usable is present.
    email = claims.get("email") or claims.get("preferred_username") or claims.get("upn")
    if not email or "@" not in email:
        raise EntraError("no usable email claim on the Entra profile")

    display_name = claims.get("name") or email.split("@")[0]

    try:
        parsed_object_id = UUID(str(object_id))
    except ValueError as exc:
        raise EntraError("object id is not a uuid") from exc

    return EntraProfile(
        object_id=parsed_object_id,
        email=str(email).strip(),
        display_name=str(display_name)[:64],
        access_token=access_token,
    )


async def fetch_avatar(
    access_token: str, *, client: httpx.AsyncClient | None = None
) -> bytes | None:
    """Fetch the profile photo, or None if there isn't one.

    A missing photo is the common case, not an error — plenty of accounts have
    none — so this never fails a login.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        response = await client.get(
            GRAPH_PHOTO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        if response.status_code != 200:
            return None
        content = response.content
        if len(content) > MAX_AVATAR_BYTES:
            logger.info("entra_avatar_too_large", extra={"bytes": len(content)})
            return None
        return content
    except httpx.HTTPError as exc:
        logger.warning("entra_avatar_fetch_failed", extra={"error_type": type(exc).__name__})
        return None
    finally:
        if owns_client:
            await client.aclose()
