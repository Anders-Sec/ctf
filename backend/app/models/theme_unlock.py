"""Secret themes a player holds (spec 058 §5).

Two routes in: earning an achievement that carries one, and an admin handing it
over directly (§5.1). The row records which, because "why do I have this?" is a
question somebody will ask.

A row is the grant. Removing it takes the theme away, and spec 048's
unknown-theme fallback then moves the player off it without anything else having
to notice — which is why that fallback is load-bearing rather than defensive.
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UnlockSource(enum.StrEnum):
    ACHIEVEMENT = "achievement"
    ADMIN = "admin"


class UserThemeUnlock(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_theme_unlock"
    __table_args__ = (
        # Earning it twice, or earning what an admin already gave you, is not a
        # conflict — it is the same grant. The constraint makes the award path
        # idempotent without it having to check first.
        UniqueConstraint("user_id", "theme", name="uq_user_theme_unlock"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    theme: Mapped[str] = mapped_column(String(32), nullable=False)

    source: Mapped[UnlockSource] = mapped_column(
        Enum(UnlockSource, name="unlock_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    #: Which achievement handed it over, where one did. SET NULL so deleting an
    #: achievement does not take the theme back from everyone who earned it.
    source_achievement_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("achievement.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<UserThemeUnlock {self.theme} {self.source}>"
