"""Which secret themes a player holds (spec 058 §5).

Two ways in — earning an achievement that carries one, and an admin handing it
over (§5.1) — and one way out, an admin taking it back. The row is the grant.

Nothing here decides what a player *sees*: spec 048's ``resolve_theme`` does
that, and its unknown-theme fallback is what quietly moves somebody off a theme
they no longer hold. That fallback stops being defensive here and starts being
load-bearing.
"""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.theme_unlock import UnlockSource, UserThemeUnlock
from app.theme import THEMES_BY_ID, is_theme

logger = get_logger(__name__)


async def held_by(db: AsyncSession, user_id: UUID) -> list[str]:
    """Theme ids this player may select, newest first."""
    rows = await db.execute(
        select(UserThemeUnlock.theme)
        .where(UserThemeUnlock.user_id == user_id)
        .order_by(UserThemeUnlock.created_at.desc())
    )
    return list(rows.scalars())


async def holds(db: AsyncSession, user_id: UUID, theme: str) -> bool:
    found = await db.scalar(
        select(UserThemeUnlock.id).where(
            UserThemeUnlock.user_id == user_id, UserThemeUnlock.theme == theme
        )
    )
    return found is not None


async def grant(
    db: AsyncSession,
    user_id: UUID,
    theme: str,
    *,
    source: UnlockSource,
    achievement_id: UUID | None = None,
) -> bool:
    """Hand a theme over. True if this call is the one that granted it.

    Idempotent through the unique constraint rather than a check-then-insert, so
    earning what an admin already gave you — or two concurrent awards — settles
    without either caller having to look first.
    """
    if not is_theme(theme):
        logger.warning("theme_unlock_unknown_theme", extra={"theme": theme})
        return False

    try:
        async with db.begin_nested():
            db.add(
                UserThemeUnlock(
                    user_id=user_id,
                    theme=theme,
                    source=source,
                    source_achievement_id=achievement_id,
                )
            )
    except IntegrityError:
        return False
    return True


async def revoke(db: AsyncSession, user_id: UUID, theme: str) -> bool:
    """Take it back. The player falls back on their next page load."""
    result = await db.execute(
        delete(UserThemeUnlock).where(
            UserThemeUnlock.user_id == user_id, UserThemeUnlock.theme == theme
        )
    )
    await db.flush()
    return bool(result.rowcount)


def grantable() -> list[str]:
    """Themes an admin may hand over: the secret ones, and only those.

    Granting somebody Parchment is not a reward — the everyday themes are
    already theirs.
    """
    return [theme.id for theme in THEMES_BY_ID.values() if theme.secret]
