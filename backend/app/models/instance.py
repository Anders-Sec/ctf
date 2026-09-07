"""Live challenge containers: templates and running instances (spec 009).

The isolation reasoning lives in spec 008; this is the data it decided. The two
things worth reading twice are the XOR owner constraint (an instance belongs to a
party *or* a lone player, never both or neither) and the partial unique index
that caps concurrent instances per owner at the database rather than trusting the
application to have counted right.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class InstanceProtocol(enum.StrEnum):
    """How players reach the target.

    Only ``http`` is implemented in Phase 1 — a NodePort for raw TCP cannot be
    authorised at the edge (spec 009 decision 3). The member stays so a future
    phase can add it without a migration, and a ``tcp`` template is refused at
    save time until then.
    """

    HTTP = "http"
    TCP = "tcp"


class EgressPolicy(enum.StrEnum):
    """What outbound access a template's instances get.

    ``none`` is the default and the safe one. Anything wider is recorded on the
    template so it is visible in review rather than discovered later.
    """

    NONE = "none"
    DNS = "dns"
    CIDR = "cidr"


class InstanceStatus(enum.StrEnum):
    #: Objects created, not yet ready. The poll target waits on this.
    PENDING = "pending"
    RUNNING = "running"
    #: Provisioning failed; ``last_error`` says why.
    FAILED = "failed"
    #: Past its TTL, reaped by the expiry loop.
    EXPIRED = "expired"
    #: Torn down deliberately — by the player, an admin, party disband, or event end.
    DESTROYED = "destroyed"


#: pending/running: an instance that still owns cluster objects and counts
#: against the per-owner cap. The others are terminal.
LIVE_STATUSES = (InstanceStatus.PENDING, InstanceStatus.RUNNING)


def _enum(python_enum: type[enum.StrEnum], name: str) -> Enum:
    return Enum(python_enum, name=name, values_callable=lambda e: [m.value for m in e])


class ContainerTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A challenge author's container configuration, set once and reused.

    ``env`` is non-secret only, by rule: a template is reviewed like app code and
    committed nowhere near a secret store. The generated per-instance answer is
    injected separately at launch, never stored here.
    """

    __tablename__ = "container_template"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    image: Mapped[str] = mapped_column(String(300), nullable=False)
    image_tag: Mapped[str] = mapped_column(String(120), nullable=False, default="latest")
    container_port: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    protocol: Mapped[InstanceProtocol] = mapped_column(
        _enum(InstanceProtocol, "instance_protocol"),
        nullable=False,
        default=InstanceProtocol.HTTP,
        server_default=InstanceProtocol.HTTP.value,
    )

    cpu_request: Mapped[str] = mapped_column(String(16), nullable=False, default="100m")
    cpu_limit: Mapped[str] = mapped_column(String(16), nullable=False, default="250m")
    memory_request: Mapped[str] = mapped_column(String(16), nullable=False, default="128Mi")
    memory_limit: Mapped[str] = mapped_column(String(16), nullable=False, default="256Mi")

    ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    env: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    egress_policy: Mapped[EgressPolicy] = mapped_column(
        _enum(EgressPolicy, "egress_policy"),
        nullable=False,
        default=EgressPolicy.NONE,
        server_default=EgressPolicy.NONE.value,
    )
    egress_cidrs: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    #: When true, each instance gets a generated answer as an env var and the
    #: submission is checked against that instance's value (spec 008 Decision 6).
    injects_answer: Mapped[bool] = mapped_column(
        nullable=False, default=True, server_default="true"
    )
    #: HTTP path the readiness probe hits before the instance is called running.
    readiness_path: Mapped[str] = mapped_column(String(200), nullable=False, default="/")
    #: The sandboxed runtime. Setting it to the host runtime is the deliberate,
    #: visible opt-out spec 008 Decision 2 describes.
    runtime_class: Mapped[str | None] = mapped_column(String(120), nullable=True, default="gvisor")

    instances: Mapped[list["ChallengeInstance"]] = relationship(
        back_populates="template", lazy="raise", passive_deletes=True
    )


class ChallengeInstance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "challenge_instance"
    __table_args__ = (
        # Exactly one owner. Mirrors score_adjustment from spec 006.
        CheckConstraint(
            "(owner_user_id IS NOT NULL) <> (owner_team_id IS NOT NULL)",
            name="ck_challenge_instance_one_owner",
        ),
        Index("ix_challenge_instance_status", "status", "expires_at"),
        Index("ix_challenge_instance_challenge", "challenge_id"),
        # The per-owner cap lives partly here: a lookup of a given owner's live
        # instances is the hot path for both the cap check and the reconciler.
        Index("ix_challenge_instance_owner_user", "owner_user_id"),
        Index("ix_challenge_instance_owner_team", "owner_team_id"),
    )

    challenge_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("challenge.id", ondelete="CASCADE"), nullable=False
    )
    #: Nullable + SET NULL so a template can be deleted without erasing the
    #: history of instances launched from it — a terminal instance keeps its row,
    #: it just loses the now-gone template link.
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("container_template.id", ondelete="SET NULL"),
        nullable=True,
    )

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=True
    )
    owner_team_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("team.id", ondelete="CASCADE"), nullable=True
    )

    #: The name of the Kubernetes objects (Pod/Service/Ingress/NetworkPolicy
    #: share it). Also the instance's subdomain label, so it must be DNS-safe.
    k8s_name: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    status: Mapped[InstanceStatus] = mapped_column(
        _enum(InstanceStatus, "instance_status"),
        nullable=False,
        default=InstanceStatus.PENDING,
        server_default=InstanceStatus.PENDING.value,
    )
    connection_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    node_port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: The answer baked into this one instance. Unique per instance, which is what
    #: closes the answer-sharing hole a shared live target would open.
    generated_answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    destroyed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)

    template: Mapped["ContainerTemplate | None"] = relationship(
        back_populates="instances", lazy="raise"
    )
