"""Per-challenge, per-team flags for container instances (spec 046).

Spec 009 gave an instance one ``generated_answer``, which was right when a
container was one challenge's target. Both Web Attacks images are a single image
carrying four challenges, so one string per instance would mean the first solve
handed over the other three. This replaces the column with a table.

``shared_instance`` on the template is the other half: one instance serving every
challenge bound to the template, explicit rather than inferred, so binding a
second challenge to an existing template does not silently change how it behaves.

The ``dynamic`` value is added to the ``match_type`` enum here. Postgres cannot
drop an enum value, so the downgrade rebuilds the type without it — and first
deletes the rules using it, since a rule whose type is about to stop existing
cannot be left behind.

Instances are ephemeral, so the data migration is a formality: any live
``generated_answer`` is carried into the new table against the challenge its
instance was launched from, and nothing else is lost.

Revision ID: 0045
Revises: 0044
"""

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "container_template",
        sa.Column(
            "shared_instance",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_table(
        "challenge_instance_answer",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "instance_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("challenge_instance.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "challenge_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("challenge.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "uq_challenge_instance_answer",
        "challenge_instance_answer",
        ["instance_id", "challenge_id"],
        unique=True,
    )

    # Carry any answer a live instance is holding, so an event mid-flight does
    # not lose a solve to the deploy.
    op.execute(
        """
        INSERT INTO challenge_instance_answer
            (id, instance_id, challenge_id, value, created_at, updated_at)
        SELECT gen_random_uuid(), id, challenge_id, generated_answer, now(), now()
          FROM challenge_instance
         WHERE generated_answer IS NOT NULL
        """
    )
    op.drop_column("challenge_instance", "generated_answer")

    op.execute("ALTER TYPE match_type ADD VALUE IF NOT EXISTS 'dynamic'")


def downgrade() -> None:
    op.add_column(
        "challenge_instance",
        sa.Column("generated_answer", sa.Text(), nullable=True),
    )
    # One answer per instance is all the old column can hold; the oldest is the
    # one the instance was launched with.
    op.execute(
        """
        UPDATE challenge_instance ci
           SET generated_answer = a.value
          FROM (
            SELECT DISTINCT ON (instance_id) instance_id, value
              FROM challenge_instance_answer
             ORDER BY instance_id, created_at
          ) a
         WHERE a.instance_id = ci.id
        """
    )
    op.drop_index("uq_challenge_instance_answer", table_name="challenge_instance_answer")
    op.drop_table("challenge_instance_answer")
    op.drop_column("container_template", "shared_instance")

    # A value cannot be dropped from a Postgres enum, so the type is rebuilt.
    # Rules of the vanishing type go first: there is nowhere to put them.
    op.execute("DELETE FROM challenge_answer WHERE match_type = 'dynamic'")
    op.execute("ALTER TYPE match_type RENAME TO match_type_old")
    op.execute(
        "CREATE TYPE match_type AS ENUM "
        "('exact', 'case_insensitive', 'regex', 'numeric', 'set', 'any_of')"
    )
    op.execute(
        "ALTER TABLE challenge_answer ALTER COLUMN match_type "
        "TYPE match_type USING match_type::text::match_type"
    )
    op.execute("DROP TYPE match_type_old")
