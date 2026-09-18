"""User-facing profile endpoints."""

import hashlib
from uuid import UUID

from fastapi import APIRouter, Request, Response, status

from app.api.deps import Authenticated, DbSession
from app.errors import NotFoundError
from app.models.user import User
from app.services.avatars import rendered_for

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}/avatar")
async def get_avatar(
    user_id: UUID,
    request: Request,
    db: DbSession,
    _: Authenticated,
) -> Response:
    """Serve the rendered avatar.

    Since spec 073 there is no "no avatar" case: a player with no photo and no
    accessories still has a procedural crest, so the blank 1x1 PNG this used to
    fall back to is gone, and with it the frontend's second rendering path.

    ``avatar_blob`` is a **cache** of the render rather than an upload. When it
    is empty the recipe is rendered here and stored. Two requests racing is
    harmless: the render is deterministic, so they compute the same bytes.
    """
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("No such user.")

    rendered = await rendered_for(db, user)
    await db.commit()

    etag = f'"{hashlib.sha256(rendered).hexdigest()[:32]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

    return Response(
        content=rendered,
        media_type="image/png",
        headers={
            "ETag": etag,
            # **Short, and revalidated.** This URL is not content-addressed —
            # it is the same string before and after a player changes their
            # face — so an hour of max-age meant a new portrait was invisible
            # everywhere except the one preview carrying its own `?v=`.
            #
            # The ETag makes revalidation cheap: an unchanged avatar costs a
            # 304 and no body. The player's own browser does not even wait for
            # this, because saving bumps a client-side version.
            "Cache-Control": "private, max-age=60, must-revalidate",
        },
    )
