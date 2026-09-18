"""Avatar recipes and the accessory roster (spec 073).

``avatar_blob`` stops being an upload and becomes the *output* of a renderer:
``avatar_source`` says which base it started from and ``avatar_config`` holds
the accessory layers and their transforms. The serving endpoint does not change.

Every existing user gets ``sigil``, which is correct for them — the renderer
produces a crest from their id, and anybody carrying Entra bytes is corrected to
``entra`` in the same step.

Revision ID: 0054
Revises: 0053
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None

# Created explicitly in upgrade(), then referenced through `_ref` with
# ``create_type=False`` so ``create_table`` does not try to create them a second
# time — which is a DuplicateObject error, not a no-op.
AVATAR_SOURCE = postgresql.ENUM("sigil", "entra", "generated", name="avatar_source")
ACCESSORY_SLOT = postgresql.ENUM("head", "eyes", "shoulders", "frame", name="accessory_slot")
UNLOCK_KIND = postgresql.ENUM(
    "always", "class", "achievement", "loot_rarity", name="accessory_unlock_kind"
)


def _ref(name: str) -> postgresql.ENUM:
    """The type as it already exists, for use in a column definition."""
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    AVATAR_SOURCE.create(bind, checkfirst=True)
    ACCESSORY_SLOT.create(bind, checkfirst=True)
    UNLOCK_KIND.create(bind, checkfirst=True)

    op.add_column(
        "user",
        sa.Column("avatar_source", _ref("avatar_source"), nullable=False, server_default="sigil"),
    )
    op.add_column(
        "user",
        sa.Column(
            "avatar_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )

    op.add_column("user", sa.Column("avatar_base", sa.LargeBinary(), nullable=True))

    # Anyone already carrying cached Entra bytes is on the photo, not a crest —
    # and those bytes are the *base* now, since avatar_blob becomes the
    # composited output. Copied across, then cleared so the first request
    # renders and caches the composite.
    op.execute(
        "UPDATE \"user\" SET avatar_source = 'entra', avatar_base = avatar_blob, "
        "avatar_blob = NULL WHERE avatar_blob IS NOT NULL"
    )

    op.create_table(
        "avatar_accessory",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("slot", _ref("accessory_slot"), nullable=False),
        sa.Column("image_key", sa.String(length=255), nullable=False),
        # Reuses the existing class_rarity enum: one rarity ladder, one set of
        # colours, so a legendary hat reads like a legendary class (spec 048).
        sa.Column(
            "rarity",
            _ref("class_rarity"),
            nullable=False,
            server_default="common",
        ),
        sa.Column("anchor_x", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("anchor_y", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("anchor_scale", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("anchor_rotation", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "unlock_kind",
            _ref("accessory_unlock_kind"),
            nullable=False,
            server_default="always",
        ),
        sa.Column("unlock_ref", sa.String(length=64), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("slug", name="uq_avatar_accessory_slug"),
    )
    op.create_index("ix_avatar_accessory_unlock", "avatar_accessory", ["unlock_kind", "unlock_ref"])


def downgrade() -> None:
    op.drop_index("ix_avatar_accessory_unlock", table_name="avatar_accessory")
    op.drop_table("avatar_accessory")
    op.drop_column("user", "avatar_base")
    op.drop_column("user", "avatar_config")
    op.drop_column("user", "avatar_source")

    bind = op.get_bind()
    UNLOCK_KIND.drop(bind, checkfirst=True)
    ACCESSORY_SLOT.drop(bind, checkfirst=True)
    AVATAR_SOURCE.drop(bind, checkfirst=True)
