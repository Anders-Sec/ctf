"""Session cookie handling.

Access and refresh tokens live in httpOnly cookies so that no script — injected
or otherwise — can read them. The CSRF token is the one cookie the SPA must be
able to read, which is why it alone is not httpOnly.
"""

from fastapi import Response

from app.config import Settings
from app.services.sessions import IssuedSession

ACCESS_COOKIE = "ctf_access"
REFRESH_COOKIE = "ctf_refresh"
CSRF_COOKIE = "ctf_csrf"
CSRF_HEADER = "X-CSRF-Token"

#: The refresh cookie is only ever sent to the endpoints that rotate or revoke
#: it, so an XSS-free but overly chatty client cannot leak it to every request.
REFRESH_COOKIE_PATH = "/api/auth"


def set_session_cookies(response: Response, settings: Settings, session: IssuedSession) -> None:
    common = {
        "secure": settings.cookie_secure,
        # Lax rather than Strict: the Entra callback is a cross-site top-level
        # redirect back into the app, and Strict would drop the cookie on it.
        "samesite": "lax",
        "domain": settings.cookie_domain,
    }

    response.set_cookie(
        ACCESS_COOKIE,
        session.access_token,
        httponly=True,
        max_age=settings.access_token_ttl_seconds,
        path="/",
        **common,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        session.refresh_token,
        httponly=True,
        max_age=settings.refresh_token_ttl_seconds,
        path=REFRESH_COOKIE_PATH,
        **common,
    )
    response.set_cookie(
        CSRF_COOKIE,
        session.csrf_token,
        # Readable by design: the SPA copies it into the X-CSRF-Token header.
        httponly=False,
        max_age=settings.refresh_token_ttl_seconds,
        path="/",
        **common,
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    for name, path in (
        (ACCESS_COOKIE, "/"),
        (REFRESH_COOKIE, REFRESH_COOKIE_PATH),
        (CSRF_COOKIE, "/"),
    ):
        response.delete_cookie(
            name,
            path=path,
            domain=settings.cookie_domain,
            secure=settings.cookie_secure,
            samesite="lax",
        )
