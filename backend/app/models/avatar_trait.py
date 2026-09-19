"""Portrait traits and generation jobs (spec 074).

The single most important thing in this file is that ``prompt_fragment`` never
leaves the server. A player picks trait **keys**; the server assembles the
prompt. That is not a nicety — SDXL Turbo runs at ``guidance_scale=0.0``, which
means negative prompts are ignored, so the usual "add a negative prompt" NSFW
control is not available. **The input vocabulary is the filter.**
"""

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TraitAxis(enum.StrEnum):
    """The eight things a player chooses.

    Eight rather than three because the traits are the game's own vocabulary —
    the 48-class roster, the ancestries, the palettes — and a portrait built
    from them looks like it came from this event rather than from a generic
    model. Eight rather than twenty because past that it stops being a choice
    and becomes a form.
    """

    ANCESTRY = "ancestry"
    CLASS_LOOK = "class_look"
    GARB = "garb"
    EXPRESSION = "expression"
    PALETTE = "palette"
    ART_STYLE = "art_style"
    #: How the portrait reads, not who anybody is — hence "-presenting", and
    #: hence no fourth "prefer not to say": leaving it unset already is that
    #: (spec 074 §11.2).
    PRESENTATION = "presentation"

    #: Retired by spec 074 §11.2. Kept on the enum because the database type
    #: still carries the values and rows may still reference them; the roster no
    #: longer authors any, so seeding disables what is left.
    HEADWEAR = "headwear"
    SETTING = "setting"


class JobState(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class AvatarTrait(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One option on one axis."""

    __tablename__ = "avatar_trait"
    __table_args__ = (
        UniqueConstraint("axis", "key", name="uq_avatar_trait_axis_key"),
        Index("ix_avatar_trait_axis", "axis", "display_order"),
    )

    axis: Mapped[TraitAxis] = mapped_column(
        Enum(TraitAxis, name="trait_axis", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    #: What the client sends. Stable; the label is what it sees.
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)

    #: **Never serialised to a client.** The prompt engineering stays here, and
    #: a response body carrying this would defeat the point of the whole design.
    prompt_fragment: Mapped[str] = mapped_column(Text, nullable=False)

    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: Lets an operator disable one fragment that is producing bad portraits
    #: without touching the other hundred and seventeen.
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")


class AvatarJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One request for a set of candidate portraits.

    A request is not a request, it is a **job**: one GPU and 200 players means
    the work queues, and the finished grid arrives through the inbox so nobody
    has to sit on the page.
    """

    __tablename__ = "avatar_job"
    __table_args__ = (Index("ix_avatar_job_user_state", "user_id", "state"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[JobState] = mapped_column(
        Enum(JobState, name="avatar_job_state", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=JobState.QUEUED,
        server_default=JobState.QUEUED.value,
    )

    #: The trait **keys** the player chose, as ``{axis: key}``. Logged so a bad
    #: portrait is traceable to the exact inputs that produced it and the
    #: offending fragment can be disabled (spec 074 §6).
    traits: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

    #: Coarse reason from ``image_client`` when this failed.
    error: Mapped[str | None] = mapped_column(String(40), nullable=True)

    #: Which candidate is currently the player's avatar, so the grid can mark it
    #: and a reload still knows. Not a foreign key: the candidates go when the
    #: next job replaces the grid, and a FK would either block that or null this
    #: out, losing the record of what was chosen (spec 074 §11.1).
    chosen_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )


class AvatarCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One of the portraits a job produced.

    The bytes live here rather than in object storage because they are small,
    short-lived and always fetched one at a time by the one player who owns
    them — a bucket round trip would be the slow part of showing the grid.
    """

    __tablename__ = "avatar_candidate"
    __table_args__ = (Index("ix_avatar_candidate_job", "job_id"),)

    job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("avatar_job.id", ondelete="CASCADE"), nullable=False
    )
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    image: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
