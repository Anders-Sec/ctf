"""User-facing profile endpoints."""

import hashlib
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.api.deps import Authenticated, DbSession
from app.errors import NotFoundError
from app.models.user import User

router = APIRouter(prefix="/users", tags=["users"])

#: A neutral 1x1 transparent PNG. Guests without an Entra photo get an identicon
#: generated in the browser from their id; this is only the fallback for a user
#: whose avatar was expected but is missing.
_BLANK_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


@router.get("/{user_id}/avatar")
async def get_avatar(
    user_id: UUID,
    request: Request,
    db: DbSession,
    _: Authenticated,
) -> Response:
    """Serve a cached Entra profile photo.

    Graph will not serve these without a token, so the bytes are cached at login
    and handed out from here instead of the browser fetching Microsoft directly.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")

    if user.avatar_blob is None:
        return Response(
            content=_BLANK_PNG,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=300"},
        )

    # Derived from the content, so a changed photo invalidates the cache and an
    # unchanged one costs a 304 rather than a download.
    etag = f'"{hashlib.sha256(user.avatar_blob).hexdigest()[:32]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

    return Response(
        content=user.avatar_blob,
        media_type="image/jpeg",
        headers={"ETag": etag, "Cache-Control": "private, max-age=3600"},
    )
