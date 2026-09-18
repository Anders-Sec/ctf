"""Portrait traits, jobs and candidates (spec 074).

The trait table holds `prompt_fragment`, which is the reason the whole design
works: players send keys, the server assembles the prompt, and no free text ever
reaches the model. SDXL Turbo runs at guidance_scale=0 so negative prompts are
ignored — the input vocabulary has to be the filter.

Revision ID: 0055
Revises: 0054
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

# Created explicitly, then referenced with create_type=False, for the same
# reason as 0054: create_table would otherwise try to make them a second time.
TRAIT_AXIS = postgresql.ENUM(
    "ancestry",
    "class_look",
    "garb",
    "headwear",
    "expression",
    "palette",
    "setting",
    "art_style",
    name="trait_axis",
)
JOB_STATE = postgresql.ENUM("queued", "running", "done", "failed", name="avatar_job_state")


def _ref(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    bind = op.get_bind()
    TRAIT_AXIS.create(bind, checkfirst=True)
    JOB_STATE.create(bind, checkfirst=True)

    op.create_table(
        "avatar_trait",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("axis", _ref("trait_axis"), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        # Never serialised to a client.
        sa.Column("prompt_fragment", sa.Text(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        *_timestamps(),
        sa.UniqueConstraint("axis", "key", name="uq_avatar_trait_axis_key"),
    )
    op.create_index("ix_avatar_trait_axis", "avatar_trait", ["axis", "display_order"])

    op.create_table(
        "avatar_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", _ref("avatar_job_state"), nullable=False, server_default="queued"),
        # The keys chosen, so a bad portrait is traceable to its inputs.
        sa.Column(
            "traits",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("error", sa.String(length=40), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_avatar_job_user_state", "avatar_job", ["user_id", "state"])

    op.create_table(
        "avatar_candidate",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatar_job.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("image", sa.LargeBinary(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_avatar_candidate_job", "avatar_candidate", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_avatar_candidate_job", table_name="avatar_candidate")
    op.drop_table("avatar_candidate")
    op.drop_index("ix_avatar_job_user_state", table_name="avatar_job")
    op.drop_table("avatar_job")
    op.drop_index("ix_avatar_trait_axis", table_name="avatar_trait")
    op.drop_table("avatar_trait")

    bind = op.get_bind()
    JOB_STATE.drop(bind, checkfirst=True)
    TRAIT_AXIS.drop(bind, checkfirst=True)
