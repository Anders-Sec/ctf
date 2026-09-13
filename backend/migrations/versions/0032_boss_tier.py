"""Boss tiers on challenges, and the per-zone boss achievements (spec 031).

A boss is one challenge per zone, flagged by an admin because it is the fight in
that wing. The partial unique index is what makes "the boss of this area" exact,
which is in turn what lets each boss achievement key on the zone rather than on
whichever challenge currently holds the slot.

Revision ID: 0032
Revises: 0031
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

TIERS = ("neighborhood", "borough", "city", "province", "country", "floor")

PLACEHOLDER = "TODO: System AI flavour text."


def upgrade() -> None:
    tier = postgresql.ENUM(*TIERS, name="boss_tier", create_type=False)
    tier.create(op.get_bind(), checkfirst=True)
    op.execute("COMMIT")

    op.add_column("challenge", sa.Column("boss_tier", tier, nullable=True))

    # One boss per zone. Partial, so the many challenges that are not bosses do
    # not collide with each other.
    op.create_index(
        "uq_challenge_one_boss_per_category",
        "challenge",
        ["category_id"],
        unique=True,
        postgresql_where=sa.text("boss_tier IS NOT NULL"),
    )

    # A placeholder achievement per zone, to be renamed and themed later. A zone
    # that never gets a boss simply has one nobody can earn, which is the same
    # inert state the roster already tolerates.
    bind = op.get_bind()
    zones = bind.execute(sa.text("SELECT slug, name FROM category ORDER BY display_order")).all()
    base = bind.execute(
        sa.text("SELECT COALESCE(MAX(display_order), 0) + 1 FROM achievement")
    ).scalar()
    for offset, (slug, name) in enumerate(zones):
        bind.execute(
            sa.text(
                "INSERT INTO achievement "
                "(id, code, name, description, earned_by, display_order) "
                "VALUES (gen_random_uuid(), :c, :n, :d, :e, :o) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {
                "c": f"boss_{slug}",
                "n": f"Boss: {name}",
                "d": PLACEHOLDER,
                "e": f"Beating the boss of {name}.",
                "o": base + offset,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    # left() rather than LIKE: '_' is a wildcard, and escaping it through a
    # heredoc, Python and SQL is three chances to get it wrong.
    bind.execute(sa.text("DELETE FROM achievement WHERE left(code, 5) = 'boss_'"))
    op.drop_index("uq_challenge_one_boss_per_category", table_name="challenge")
    op.drop_column("challenge", "boss_tier")
    op.execute("DROP TYPE IF EXISTS boss_tier")
