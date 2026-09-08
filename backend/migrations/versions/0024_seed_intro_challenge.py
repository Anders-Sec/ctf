"""Seed the Intro challenge

Spec 019. Intro gates the first six zones on "clear 100% of Intro", and a zone
with no visible challenges can never be cleared — so without this the whole
dungeon is permanently sealed behind an empty room.

Placeholder content: an admin is expected to rewrite the body and flag. It exists
so the progression works out of the box rather than silently deadlocking.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SLUG = "intro-getting-started"
FLAG = "flag{welcome_to_the_dungeon}"


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            INSERT INTO challenge (id, title, slug, category_id, body, difficulty,
                                   state, pre_release_state, initial_points,
                                   minimum_points, decay_threshold, scoring,
                                   decay_basis, created_at, updated_at)
            SELECT gen_random_uuid(), 'Getting Started', :slug, c.id,
                   'Welcome. Submit the flag below to open the dungeon.'
                   || E'\n\n`' || :flag || '`',
                   CAST('very_easy' AS challenge_difficulty),
                   CAST('published' AS challenge_state),
                   CAST('hidden' AS pre_release_state),
                   50, 20, 40,
                   CAST('static' AS scoring_mode),
                   CAST('players' AS decay_basis),
                   now(), now()
              FROM category c
             WHERE c.name = 'Intro'
            ON CONFLICT (slug) DO NOTHING
            """
        ),
        {"slug": SLUG, "flag": FLAG},
    )

    conn.execute(
        sa.text(
            """
            INSERT INTO challenge_answer (id, challenge_id, match_type, value,
                                          options, display_order,
                                          created_at, updated_at)
            SELECT gen_random_uuid(), ch.id,
                   CAST('case_insensitive' AS match_type), :flag,
                   '{}'::jsonb, 0, now(), now()
              FROM challenge ch
             WHERE ch.slug = :slug
               AND NOT EXISTS (
                   SELECT 1 FROM challenge_answer a WHERE a.challenge_id = ch.id)
            """
        ),
        {"slug": SLUG, "flag": FLAG},
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM challenge WHERE slug = :slug"), {"slug": SLUG})
