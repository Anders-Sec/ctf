"""Abilities on categories, and skills attached to challenges

Spec 018. Categories stop pointing at a skill and start feeding an **ability**
(required — an unmapped category would silently drop its XP out of the stat
block). Skills stop being a coarse grouping and become many small things attached
to individual challenges, each either useful or funny.

``character_class.affinity_skill_id`` goes with it: one skill no longer
characterises a class, and the real recommender will define its own mapping.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ability = postgresql.ENUM(
    "str", "dex", "con", "int", "wis", "cha", name="ability", create_type=False
)
skill_kind = postgresql.ENUM("useful", "funny", name="skill_kind", create_type=False)


def upgrade() -> None:
    ability.create(op.get_bind(), checkfirst=True)
    skill_kind.create(op.get_bind(), checkfirst=True)

    # Existing categories default to INT and are re-pointed by the seed migration.
    op.add_column(
        "category",
        sa.Column("ability", ability, server_default="int", nullable=False),
    )
    op.drop_column("category", "skill_id")

    op.add_column(
        "skill",
        sa.Column("kind", skill_kind, server_default="useful", nullable=False),
    )
    op.add_column("skill", sa.Column("category_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_skill_category", "skill", "category", ["category_id"], ["id"], ondelete="SET NULL"
    )

    op.create_table(
        "challenge_skill",
        sa.Column("challenge_id", sa.UUID(), nullable=False),
        sa.Column("skill_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["challenge_id"],
            ["challenge.id"],
            name="fk_challenge_skill_challenge",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"], ["skill.id"], name="fk_challenge_skill_skill", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("challenge_id", "skill_id", name="uq_challenge_skill"),
    )
    op.create_index("ix_challenge_skill_challenge", "challenge_skill", ["challenge_id"])
    op.create_index("ix_challenge_skill_skill", "challenge_skill", ["skill_id"])

    op.drop_constraint("fk_character_class_affinity_skill", "character_class", type_="foreignkey")
    op.drop_column("character_class", "affinity_skill_id")


def downgrade() -> None:
    op.add_column("character_class", sa.Column("affinity_skill_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_character_class_affinity_skill",
        "character_class",
        "skill",
        ["affinity_skill_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_index("ix_challenge_skill_skill", table_name="challenge_skill")
    op.drop_index("ix_challenge_skill_challenge", table_name="challenge_skill")
    op.drop_table("challenge_skill")

    op.drop_constraint("fk_skill_category", "skill", type_="foreignkey")
    op.drop_column("skill", "category_id")
    op.drop_column("skill", "kind")

    op.add_column("category", sa.Column("skill_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_category_skill", "category", "skill", ["skill_id"], ["id"], ondelete="SET NULL"
    )
    op.drop_column("category", "ability")

    skill_kind.drop(op.get_bind(), checkfirst=True)
    ability.drop(op.get_bind(), checkfirst=True)
