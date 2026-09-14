"""Restore seeded zones that category pruning destroyed, and re-home their skills

Spec 043. Until this release, deleting the last challenge in a category deleted
the category (spec 013's ``prune_category_if_empty``). That was right when a
category was a string typed into the challenge form; it stopped being right at
spec 018, when the 21 categories became seeded zones carrying ability mappings,
descriptions and display order.

The damage is quiet. An admin who deletes a zone's last challenge and then
recreates the zone by naming it in the editor gets a category back — but one
built by ``resolve_or_create_category`` with a derived slug, no description,
``ability`` at its default and ``display_order`` 0. Nothing looks broken; the
zone is simply no longer the zone the map and the stat blocks were built around.
Its skills, meanwhile, had their ``category_id`` set to NULL on the way past.

So this re-asserts 0021's seed **by name**, for every seeded zone, whether or not
it was damaged — writing values that are already correct on a healthy database.

It does not touch ``map_x``/``map_y``: those are authored in the map editor (spec
021), not seeded, so there is nothing to restore them to and a zone an admin has
placed must not be moved. A zone that lost its position needs re-placing by hand.

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-14
"""

import importlib.util
import pathlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _seed() -> tuple[list[tuple], list[tuple]]:
    """0021's own lists, read from 0021.

    Loaded by path because a version file is named for its revision and so is not
    a legal module name. Worth the awkwardness: copying 21 zones and 73 skills
    into a second file guarantees the two drift, and a repair that restores stale
    values is worse than no repair.
    """
    source = pathlib.Path(__file__).with_name("0021_seed_event_content.py")
    spec = importlib.util.spec_from_file_location("seed_0021", source)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging fault
        raise RuntimeError(f"cannot read the seed at {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CATEGORIES, module.SKILLS


def upgrade() -> None:
    conn = op.get_bind()
    categories, skills = _seed()

    # Recreate any zone that is missing outright, then correct the fields on
    # every one of them. Two steps rather than an upsert, because a zone that
    # was recreated by hand already holds the name and must be *corrected*, not
    # skipped.
    for name, slug, description, ability, order in categories:
        conn.execute(
            sa.text(
                """
                INSERT INTO category (id, name, slug, description, ability, display_order,
                                      created_at, updated_at)
                VALUES (gen_random_uuid(), :name, :slug, :description, CAST(:ability AS ability),
                        :display_order, now(), now())
                ON CONFLICT (name) DO NOTHING
                """
            ),
            {
                "name": name,
                "slug": slug,
                "description": description,
                "ability": ability,
                "display_order": order,
            },
        )
        conn.execute(
            sa.text(
                """
                UPDATE category
                   SET slug = :slug,
                       description = :description,
                       ability = CAST(:ability AS ability),
                       display_order = :display_order,
                       updated_at = now()
                 WHERE name = :name
                   AND (slug IS DISTINCT FROM :slug
                        OR description IS DISTINCT FROM :description
                        OR ability IS DISTINCT FROM CAST(:ability AS ability)
                        OR display_order IS DISTINCT FROM :display_order)
                """
            ),
            {
                "name": name,
                "slug": slug,
                "description": description,
                "ability": ability,
                "display_order": order,
            },
        )

    # Skills whose zone was pruned had category_id set to NULL. Only those are
    # re-homed: a skill an admin has deliberately moved keeps where it is.
    for name, _kind, category, _order in skills:
        conn.execute(
            sa.text(
                """
                UPDATE skill
                   SET category_id = c.id, updated_at = now()
                  FROM category c
                 WHERE skill.name = :name
                   AND skill.category_id IS NULL
                   AND c.name = :category
                """
            ),
            {"name": name, "category": category},
        )


def downgrade() -> None:
    # Nothing to undo: this only writes the values the seed already specified.
    pass
