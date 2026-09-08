"""Seed the 48-class roster (spec 024).

The list in ``Ideas.md``, verbatim: 30 common, 6 uncommon, 5 rare, 3 legendary
and 4 mythic. Preference targets are the abilities or skills the recommender
matches a player against; requirements are the skill levels that gate a class.

Idempotent on name, so a class already present is left alone rather than
duplicated.

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


#: (name, rarity, [(ability, skill)], [(skill, min_level)])
ROSTER = [
    ("Barbarian", "common", [("str", None), ("con", None)], []),
    ("Fighter", "common", [("str", None), ("dex", None)], []),
    ("Berserker", "common", [("str", None), ("con", None), ("cha", None)], []),
    ("Rogue", "common", [("dex", None), ("int", None)], []),
    ("Ranger", "common", [("dex", None), ("wis", None)], []),
    ("Assassin", "common", [("dex", None), ("str", None)], []),
    ("Guardian", "common", [("con", None), ("str", None)], []),
    ("Juggernaut", "common", [("con", None), ("str", None)], []),
    ("Warden", "common", [("con", None), ("wis", None)], []),
    ("Wizard", "common", [("int", None), ("wis", None)], []),
    ("Artificer", "common", [("int", None), ("dex", None)], []),
    ("Archmage", "common", [("int", None), ("cha", None)], []),
    ("Cleric", "common", [("wis", None), ("cha", None)], []),
    ("Druid", "common", [("wis", None), ("con", None)], []),
    ("Oracle", "common", [("wis", None), ("int", None)], []),
    ("Bard", "common", [("cha", None), ("int", None)], []),
    ("Warlock", "common", [("cha", None), ("int", None), ("con", None)], []),
    ("Sorcerer", "common", [("cha", None), ("wis", None)], []),
    ("Analyst", "common", [(None, "Log Divination"), (None, "Anomaly Sense")], []),
    ("Technician", "common", [(None, "Packet Whispering"), (None, "Circuit Whispering")], []),
    ("Auditor", "common", [(None, "Risk Judgment"), (None, "Policy Skimming Speed")], []),
    ("Help Desk Adept", "common", [(None, "Sticky Note Radar"), (None, "Convincing IT Voice")], []),
    ("Sysadmin", "common", [(None, "Packet Whispering"), (None, "Cloud Instinct")], []),
    ("Compliance Officer", "common", [(None, "Risk Judgment")], []),
    ("Junior Pentester", "common", [(None, "Injection Artistry"), (None, "Auth Bypass")], []),
    ("Scanner", "common", [(None, "Anomaly Sense"), (None, "Log Divination")], []),
    ("Researcher", "common", [(None, "Threat Hunting Lore"), (None, "Cryptanalysis")], []),
    ("Archivist", "common", [(None, "Evidence Handling"), (None, "Artifact Recovery")], []),
    ("Triage Nurse", "common", [(None, "Triage Under Fire"), (None, "Containment Instinct")], []),
    (
        "Script Kiddie",
        "common",
        [(None, "Exploit Crafting"), (None, "Reckless Double-Clicking")],
        [],
    ),
    ("Packet Sage", "uncommon", [(None, "Packet Whispering")], [("Packet Whispering", 5)]),
    ("Cipher Adept", "uncommon", [(None, "Cryptanalysis")], [("Cryptanalysis", 6)]),
    (
        "Shadow Broker",
        "uncommon",
        [(None, "Credential Harvesting")],
        [("Credential Harvesting", 6)],
    ),
    ("Signal Hunter", "uncommon", [(None, "Anomaly Sense")], [("Anomaly Sense", 7)]),
    ("Wire Stalker", "uncommon", [(None, "Digital Tracking")], [("Digital Tracking", 5)]),
    ("Breachwright", "uncommon", [(None, "Exploit Crafting")], [("Exploit Crafting", 8)]),
    ("Voidcoder", "rare", [(None, "Model Interrogation")], [("Model Interrogation", 9)]),
    ("Ghost Handler", "rare", [(None, "Pretexting")], [("Pretexting", 8)]),
    ("Ashborn Analyst", "rare", [(None, "Static Analysis")], [("Static Analysis", 10)]),
    ("Sentinel Prime", "rare", [(None, "Log Divination")], [("Log Divination", 9)]),
    ("Cryptomancer", "rare", [(None, "Cryptanalysis")], [("Cryptanalysis", 10)]),
    (
        "Root Ascendant",
        "legendary",
        [(None, "Privilege Escalation")],
        [("Privilege Escalation", 13)],
    ),
    ("The Unwritten", "legendary", [(None, "Disassembly")], [("Disassembly", 14)]),
    ("Herald of Zero-Day", "legendary", [(None, "Exploit Crafting")], [("Exploit Crafting", 15)]),
    (
        "Architect of the Unbreakable Crypt-Covenant",
        "mythic",
        [(None, "Cryptanalysis"), (None, "Pattern Recognition")],
        [("Cryptanalysis", 13), ("Pattern Recognition", 13)],
    ),
    (
        "Imperator of the Core-Kernel Continuum",
        "mythic",
        [(None, "Disassembly"), (None, "Static Analysis"), (None, "Sandbox Discipline")],
        [("Disassembly", 13), ("Static Analysis", 12), ("Sandbox Discipline", 10)],
    ),
    (
        "Avatar of the Quantum Superposition",
        "mythic",
        [(None, "Model Interrogation"), (None, "Threat Hunting Lore")],
        [("Model Interrogation", 12), ("Threat Hunting Lore", 12)],
    ),
    (
        "Sovereign of the Absolute Zero-Day Nexus",
        "mythic",
        [(None, "Exploit Crafting"), (None, "Privilege Escalation")],
        [("Exploit Crafting", 13), ("Privilege Escalation", 12)],
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    skills = {
        name.lower(): sid for sid, name in bind.execute(sa.text("SELECT id, name FROM skill"))
    }

    for order, (name, rarity, prefs, reqs) in enumerate(ROSTER):
        existing = bind.execute(
            sa.text("SELECT id FROM character_class WHERE lower(name) = lower(:n)"),
            {"n": name},
        ).scalar()
        if existing:
            continue

        class_id = bind.execute(
            sa.text(
                "INSERT INTO character_class (id, name, display_order, rarity) "
                "VALUES (gen_random_uuid(), :n, :o, :r) RETURNING id"
            ),
            {"n": name, "o": order, "r": rarity},
        ).scalar()

        for ability, skill_name in prefs:
            skill_id = skills.get(skill_name.lower()) if skill_name else None
            # A preference naming a skill that does not exist would be a target
            # the recommender can never score, so skip rather than store it.
            if skill_name and skill_id is None:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO class_preference (id, class_id, ability, skill_id) "
                    "VALUES (gen_random_uuid(), :c, :a, :s)"
                ),
                {"c": class_id, "a": ability, "s": skill_id},
            )

        for skill_name, level in reqs:
            skill_id = skills.get(skill_name.lower())
            # A requirement on a missing skill could never be met, which would
            # silently make the class unreachable. Skipping keeps it reachable.
            if skill_id is None:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO class_requirement (id, class_id, skill_id, min_level) "
                    "VALUES (gen_random_uuid(), :c, :s, :l)"
                ),
                {"c": class_id, "s": skill_id, "l": level},
            )


def downgrade() -> None:
    bind = op.get_bind()
    for name, *_ in ROSTER:
        bind.execute(
            sa.text("DELETE FROM character_class WHERE lower(name) = lower(:n)"),
            {"n": name},
        )
