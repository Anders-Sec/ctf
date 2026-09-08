"""Class rarity, preference targets and unlock requirements (spec 024).

016 shipped the class machinery with only a name, order and description. The
roster needs three more things: a rarity (colour only), the abilities or skills
a class is "about" so the recommender has something to match, and the skill
levels that gate it.

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


RARITIES = ("common", "uncommon", "rare", "legendary", "mythic")


def upgrade() -> None:
    rarity = postgresql.ENUM(*RARITIES, name="class_rarity", create_type=False)
    rarity.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "character_class",
        sa.Column(
            "rarity",
            rarity,
            nullable=False,
            server_default="common",
        ),
    )

    # Postgres will not let the new enum's values be *used* in the transaction
    # that created the type, and the seed migration that follows does exactly
    # that. Committing here is the same dance as 0022.
    op.execute("COMMIT")

    ability = postgresql.ENUM(name="ability", create_type=False)

    op.create_table(
        "class_preference",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("character_class.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ability", ability, nullable=True),
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skill.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # An ability or a skill, never both and never neither — mirrors
        # ck_unlock_requirement's XOR for the same reason.
        sa.CheckConstraint(
            "(ability IS NULL) <> (skill_id IS NULL)",
            name="ck_class_preference_one_target",
        ),
    )
    op.create_index("ix_class_preference_class_id", "class_preference", ["class_id"])

    op.create_table(
        "class_requirement",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "class_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("character_class.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skill.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("min_level", sa.Integer(), nullable=False),
        sa.UniqueConstraint("class_id", "skill_id", name="uq_class_requirement_skill"),
    )
    op.create_index("ix_class_requirement_class_id", "class_requirement", ["class_id"])


def downgrade() -> None:
    op.drop_index("ix_class_requirement_class_id", table_name="class_requirement")
    op.drop_table("class_requirement")
    op.drop_index("ix_class_preference_class_id", table_name="class_preference")
    op.drop_table("class_preference")
    op.drop_column("character_class", "rarity")
    op.execute("DROP TYPE IF EXISTS class_rarity")
