"""Challenges, their answer rules, and their downloadable artifacts."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Difficulty(enum.StrEnum):
    """The six-tier ladder (spec 018).

    Difficulty *derives* a challenge's XP rather than merely hinting at it, so the
    economy is knowable before the event runs: roughly 2,000 XP per category and
    42,000 across the board. See :data:`DIFFICULTY_MODIFIER`.
    """

    VERY_EASY = "very_easy"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    VERY_HARD = "very_hard"
    NEARLY_IMPOSSIBLE = "nearly_impossible"


#: Multiplied by ``XP_BASE`` to give a challenge's XP ceiling.
DIFFICULTY_MODIFIER: dict[Difficulty, int] = {
    Difficulty.VERY_EASY: 5,
    Difficulty.EASY: 10,
    Difficulty.MEDIUM: 15,
    Difficulty.HARD: 20,
    Difficulty.VERY_HARD: 25,
    Difficulty.NEARLY_IMPOSSIBLE: 50,
}

#: Decay is the tie-breaker, and only the top two tiers are tie-breakers — so
#: those default to dynamic scoring and everything else to static. Still a
#: per-challenge setting an admin can override on the day.
DECAYING_DIFFICULTIES = frozenset({Difficulty.VERY_HARD, Difficulty.NEARLY_IMPOSSIBLE})

#: The decay floor, as a fraction of the ceiling.
MINIMUM_POINTS_FRACTION = 0.4


def points_for(difficulty: Difficulty, xp_base: int) -> int:
    """A challenge's XP ceiling."""
    return DIFFICULTY_MODIFIER[difficulty] * xp_base


def minimum_points_for(difficulty: Difficulty, xp_base: int) -> int:
    return max(1, int(points_for(difficulty, xp_base) * MINIMUM_POINTS_FRACTION))


def default_scoring_for(difficulty: Difficulty) -> "ScoringMode":
    return ScoringMode.DYNAMIC if difficulty in DECAYING_DIFFICULTIES else ScoringMode.STATIC


class Ability(enum.StrEnum):
    """The D&D six (spec 018).

    Every category maps to exactly one, so abilities *partition* the XP pool: a
    solve's XP lands in one ability and no other. Scores run 8-20 and their
    progress is deliberately hidden from players.
    """

    STR = "str"
    DEX = "dex"
    CON = "con"
    INT = "int"
    WIS = "wis"
    CHA = "cha"


class SkillKind(enum.StrEnum):
    """Useful skills are the real competencies; funny ones are the joke that makes
    the sheet worth reading. Players can filter the funny ones out."""

    USEFUL = "useful"
    FUNNY = "funny"


class ChallengeState(enum.StrEnum):
    """Four genuinely different situations, not a boolean.

    An admin mid-event needs to tell "not written yet" from "pulled because it is
    broken" from "players can see it exists but not attempt it".
    """

    #: Staff only. Work in progress.
    DRAFT = "draft"
    #: Players see nothing at all.
    HIDDEN = "hidden"
    #: Players see the title, category and value — never the body — and cannot submit.
    LOCKED = "locked"
    #: Live.
    PUBLISHED = "published"


class PreReleaseState(enum.StrEnum):
    """What players see before ``release_at``."""

    HIDDEN = "hidden"
    LOCKED = "locked"


class ScoringMode(enum.StrEnum):
    DYNAMIC = "dynamic"
    #: Pinned at initial_points — a participation flag, a sponsor challenge.
    STATIC = "static"


class DecayBasis(enum.StrEnum):
    """Whose solves move the curve.

    Two different questions: how many *people* found this, versus how many
    *groups* did. Both are offered because both are legitimate.
    """

    PLAYERS = "players"
    TEAMS = "teams"


class MatchType(enum.StrEnum):
    """How a submission is compared against an answer rule.

    Open by design: adding a type is one resolver and one member here. Spec 009
    will add a computed per-instance type that fits the same column shape.
    """

    EXACT = "exact"
    CASE_INSENSITIVE = "case_insensitive"
    REGEX = "regex"
    NUMERIC = "numeric"
    #: Multi-part answers — three CVEs in any order, say.
    SET = "set"
    #: A list of accepted alternatives.
    ANY_OF = "any_of"


def _enum(python_enum: type[enum.StrEnum], name: str) -> Enum:
    return Enum(python_enum, name=name, values_callable=lambda e: [m.value for m in e])


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A challenge category.

    A table rather than a string column on ``challenge``: Phase 2 ties stat blocks
    to categories, and attaching that to free text later means a migration that
    first has to invent the missing rows.
    """

    __tablename__ = "category"

    name: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: The ability this category feeds (spec 018). Required: an unmapped category
    #: would silently drop its XP out of the stat block.
    ability: Mapped[Ability] = mapped_column(
        _enum(Ability, "ability"),
        nullable=False,
        default=Ability.INT,
        server_default=Ability.INT.value,
    )


class Challenge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "challenge"
    __table_args__ = (
        Index("ix_challenge_state_release", "state", "release_at"),
        Index("ix_challenge_category", "category_id"),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("category.id", ondelete="RESTRICT"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    difficulty: Mapped[Difficulty] = mapped_column(
        _enum(Difficulty, "challenge_difficulty"),
        nullable=False,
        default=Difficulty.MEDIUM,
        server_default=Difficulty.MEDIUM.value,
    )

    state: Mapped[ChallengeState] = mapped_column(
        _enum(ChallengeState, "challenge_state"),
        nullable=False,
        default=ChallengeState.DRAFT,
        server_default=ChallengeState.DRAFT.value,
    )
    release_at: Mapped[datetime | None] = mapped_column(nullable=True)
    pre_release_state: Mapped[PreReleaseState] = mapped_column(
        _enum(PreReleaseState, "pre_release_state"),
        nullable=False,
        default=PreReleaseState.HIDDEN,
        server_default=PreReleaseState.HIDDEN.value,
    )

    initial_points: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    #: The floor, before the modifier model that lands later.
    minimum_points: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    decay_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    scoring: Mapped[ScoringMode] = mapped_column(
        _enum(ScoringMode, "scoring_mode"),
        nullable=False,
        default=ScoringMode.DYNAMIC,
        server_default=ScoringMode.DYNAMIC.value,
    )
    decay_basis: Mapped[DecayBasis] = mapped_column(
        _enum(DecayBasis, "decay_basis"),
        nullable=False,
        default=DecayBasis.PLAYERS,
        server_default=DecayBasis.PLAYERS.value,
    )

    #: Null (the default) means unlimited attempts — rate limiting is the brake.
    max_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Reserved for spec 009. Nothing reads it yet; it exists so the container
    #: work needs no schema change.
    container_template_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("container_template.id", ondelete="SET NULL"),
        nullable=True,
    )

    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    #: Pinned map coordinates (spec 017). Null — the normal case — means "lay me
    #: out automatically", so a new challenge always lands on the map without an
    #: admin having to place it.
    map_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    map_y: Mapped[int | None] = mapped_column(Integer, nullable=True)

    category: Mapped["Category"] = relationship(lazy="raise")
    answers: Mapped[list["ChallengeAnswer"]] = relationship(
        back_populates="challenge",
        cascade="all, delete-orphan",
        order_by="ChallengeAnswer.display_order",
        lazy="raise",
    )
    artifacts: Mapped[list["ChallengeArtifact"]] = relationship(
        back_populates="challenge",
        cascade="all, delete-orphan",
        order_by="ChallengeArtifact.display_order",
        lazy="raise",
    )

    def effective_state(self, now: datetime) -> ChallengeState:
        """The state a player experiences, after applying the release schedule.

        Before ``release_at`` the challenge behaves as ``pre_release_state``; at
        or after it, its own state applies. Drafts are never released — an
        unfinished challenge going live on a timer is exactly the accident this
        prevents.
        """
        if self.state == ChallengeState.DRAFT:
            return ChallengeState.DRAFT
        if self.release_at is not None and now < self.release_at:
            return ChallengeState(self.pre_release_state.value)
        return self.state

    def __repr__(self) -> str:
        return f"<Challenge {self.slug} {self.state}>"


class ChallengeAnswer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One accepted answer rule. A submission is correct if *any* rule matches."""

    __tablename__ = "challenge_answer"
    __table_args__ = (Index("ix_challenge_answer_challenge", "challenge_id", "display_order"),)

    challenge_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenge.id", ondelete="CASCADE"), nullable=False
    )
    match_type: Mapped[MatchType] = mapped_column(_enum(MatchType, "match_type"), nullable=False)
    #: Plaintext. Regex and computed answers are a requirement, and hashing
    #: forecloses them; the database is not reachable by players.
    value: Mapped[str] = mapped_column(Text, nullable=False)
    #: Per-type settings: tolerance, ordering, case handling, timeouts.
    options: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    #: Admin-facing note, e.g. "accepts the British spelling".
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    challenge: Mapped["Challenge"] = relationship(back_populates="answers", lazy="raise")


class ChallengeArtifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A downloadable file. Bytes live in object storage, not in this row."""

    __tablename__ = "challenge_artifact"
    __table_args__ = (Index("ix_challenge_artifact_challenge", "challenge_id", "display_order"),)

    challenge_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenge.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Opaque key in whichever storage backend is wired in.
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    #: Lets a player verify a download, and lets us detect silent corruption.
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    challenge: Mapped["Challenge"] = relationship(back_populates="artifacts", lazy="raise")


class RequirementType(enum.StrEnum):
    """What kind of condition unlocks a challenge or a zone (spec 017).

    ``challenge_solved`` came from 014; the value-based types arrived with 017 now
    that 015 provides XP and skills. Each type reads a different column set —
    see :class:`UnlockRequirement`.
    """

    CHALLENGE_SOLVED = "challenge_solved"
    #: Total banked XP at or above ``threshold``.
    MIN_XP = "min_xp"
    #: Level ``threshold`` or better in ``required_skill_id``.
    SKILL_LEVEL = "skill_level"
    #: ``threshold`` or more solves inside ``required_category_id``.
    SOLVES_IN_CATEGORY = "solves_in_category"


class UnlockRequirement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A condition a player must meet before a challenge — or a whole zone —
    unlocks for them (spec 017).

    One table gates both things: a row targets **either** a challenge **or** a
    category (a zone), never both and never neither, enforced by the same XOR
    check ``challenge_instance`` uses for its owner. That keeps one evaluator and
    one admin surface rather than two that must be kept in step.

    The target unlocks when **all** of its requirements are met. Every FK cascades,
    so a requirement pointing at something deleted simply stops gating rather than
    becoming unsatisfiable.
    """

    __tablename__ = "unlock_requirement"
    __table_args__ = (
        CheckConstraint(
            "(challenge_id IS NOT NULL) <> (category_id IS NOT NULL)",
            name="ck_unlock_requirement_one_target",
        ),
        Index("ix_unlock_requirement_challenge", "challenge_id"),
        Index("ix_unlock_requirement_category", "category_id"),
        Index("ix_unlock_requirement_required", "required_challenge_id"),
    )

    #: The gated challenge. Null when this row gates a zone instead.
    challenge_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenge.id", ondelete="CASCADE"), nullable=True
    )
    #: The gated zone. Null when this row gates a single challenge instead.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("category.id", ondelete="CASCADE"), nullable=True
    )

    requirement_type: Mapped[RequirementType] = mapped_column(
        _enum(RequirementType, "requirement_type"),
        nullable=False,
        default=RequirementType.CHALLENGE_SOLVED,
        server_default=RequirementType.CHALLENGE_SOLVED.value,
    )

    #: Set for ``challenge_solved``.
    required_challenge_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenge.id", ondelete="CASCADE"), nullable=True
    )
    #: Set for ``skill_level``.
    required_skill_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("skill.id", ondelete="CASCADE"), nullable=True
    )
    #: Set for ``solves_in_category``.
    required_category_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("category.id", ondelete="CASCADE"), nullable=True
    )
    #: The XP amount, the skill level, or the solve count — the row's type says
    #: which. Null for ``challenge_solved``.
    threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
