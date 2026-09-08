"""Seed the Intro zone and the category progression graph

Spec 019. Intro is the only zone open at the start; clearing it opens the first
six. Everything else opens on a share of another zone or on player level.

Idempotent: a gate that already exists is left alone, so re-running cannot
duplicate the graph.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INTRO = (
    "Intro",
    "intro",
    "Start here. One challenge to get your bearings before the dungeon opens up.",
    "int",
)

#: (gated zone, kind, source zone or None, threshold)
GRAPH = [
    ("Networking", "percent", "Intro", 100),
    ("Governance, Risk & Compliance", "percent", "Intro", 100),
    ("Hacker Game Show", "percent", "Intro", 100),
    ("CTI", "percent", "Intro", 100),
    ("Incident Response", "percent", "Intro", 100),
    ("AI/LLM Security", "percent", "Intro", 100),
    ("Cloud Security", "percent", "Networking", 25),
    ("OSINT", "percent", "CTI", 50),
    ("Forensics", "percent", "Incident Response", 25),
    ("Threat Detection", "percent", "Incident Response", 50),
    ("Prompt Injection", "percent", "AI/LLM Security", 50),
    ("Codes and Ciphers", "percent", "Hacker Game Show", 25),
    ("Crypto", "percent", "Hacker Game Show", 25),
    ("Red teaming", "level", None, 5),
    ("Hardware Hacking", "percent", "Red teaming", 25),
    ("Social Engineering", "percent", "Red teaming", 25),
    ("Identity & Access", "percent", "Red teaming", 50),
    ("Web Attacks", "percent", "Red teaming", 50),
    ("Mobile Security", "level", None, 8),
    ("Reverse Engineering", "level", None, 8),
    ("Malware Analysis", "level", None, 8),
]


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            INSERT INTO category (id, name, slug, description, ability, display_order,
                                  created_at, updated_at)
            VALUES (gen_random_uuid(), :name, :slug, :description, CAST(:ability AS ability),
                    0, now(), now())
            ON CONFLICT (name) DO NOTHING
            """
        ),
        {"name": INTRO[0], "slug": INTRO[1], "description": INTRO[2], "ability": INTRO[3]},
    )

    for gated, kind, source, threshold in GRAPH:
        if kind == "percent":
            conn.execute(
                sa.text(
                    """
                    INSERT INTO unlock_requirement
                        (id, category_id, requirement_type, required_category_id,
                         threshold, created_at, updated_at)
                    SELECT gen_random_uuid(), g.id,
                           CAST('percent_in_category' AS requirement_type), s.id,
                           :threshold, now(), now()
                      FROM category g, category s
                     WHERE g.name = :gated AND s.name = :source
                       AND NOT EXISTS (
                           SELECT 1 FROM unlock_requirement u
                            WHERE u.category_id = g.id
                              AND u.required_category_id = s.id
                              AND u.requirement_type =
                                  CAST('percent_in_category' AS requirement_type))
                    """
                ),
                {"gated": gated, "source": source, "threshold": threshold},
            )
        else:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO unlock_requirement
                        (id, category_id, requirement_type, threshold,
                         created_at, updated_at)
                    SELECT gen_random_uuid(), g.id,
                           CAST('player_level' AS requirement_type), :threshold, now(), now()
                      FROM category g
                     WHERE g.name = :gated
                       AND NOT EXISTS (
                           SELECT 1 FROM unlock_requirement u
                            WHERE u.category_id = g.id
                              AND u.requirement_type =
                                  CAST('player_level' AS requirement_type))
                    """
                ),
                {"gated": gated, "threshold": threshold},
            )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM unlock_requirement
             WHERE requirement_type IN (
                 CAST('percent_in_category' AS requirement_type),
                 CAST('player_level' AS requirement_type))
            """
        )
    )
    # Intro is left: a challenge may point at it, and RESTRICT would block the
    # delete anyway.
