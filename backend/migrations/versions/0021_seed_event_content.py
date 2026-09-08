"""Seed the real event content: 21 categories and 73 skills

Spec 018. Ships the categories from ``Ideas.md`` with their ability mappings, and
every useful and funny skill, so a fresh deploy comes up with the real structure
rather than an empty board.

Idempotent on name: a category or skill that already exists is left alone, so
this cannot clobber content an admin has edited.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (name, slug, description, ability, display_order)
CATEGORIES = [
    ("OSINT", "osint", "Use open source tools to find the flag in public data", "wis", 0),
    ("Networking", "networking", "Basic networking based trivia questions", "int", 1),
    (
        "CTI",
        "cti",
        "Players have to lookup famous CVEs and extract artifacts from previous threat intel",
        "wis",
        2,
    ),
    (
        "Hacker Game Show",
        "hacker-game-show",
        "Cyber security themed Wordle, Connections etc",
        "cha",
        3,
    ),
    ("Red teaming", "red-teaming", "General intro to red teaming trivia", "str", 4),
    (
        "Identity & Access",
        "identity-access",
        "Hands on interactive attacks in a simulated sandbox",
        "str",
        5,
    ),
    ("Hardware Hacking", "hardware-hacking", "Trivia related to hardware Hacking", "dex", 6),
    ("Web Attacks", "web-attacks", "Hands on interactive Vulnerable Web sites", "str", 7),
    ("Cloud Security", "cloud-security", "General Clous security trivia", "con", 8),
    ("Crypto", "crypto", "Crypto trivia", "int", 9),
    (
        "Codes and Ciphers",
        "codes-and-ciphers",
        "Flags encoded and players have to decode",
        "int",
        10,
    ),
    ("AI/LLM Security", "ai-llm-security", "LLM hacking trivia", "int", 11),
    ("Prompt Injection", "prompt-injection", "Interactive LLM hacking", "cha", 12),
    ("Social Engineering", "social-engineering", "Trivia", "cha", 13),
    (
        "Forensics",
        "forensics",
        "I'll have forensic artifacts and they have to find info from them,",
        "dex",
        14,
    ),
    ("Governance, Risk & Compliance", "governance-risk-compliance", "Trivia", "wis", 15),
    (
        "Threat Detection",
        "threat-detection",
        "Unsure yet, maybe trivia but also maybe interactive log hunting",
        "wis",
        16,
    ),
    ("Incident Response", "incident-response", "Trivia", "con", 17),
    (
        "Mobile Security",
        "mobile-security",
        "Unsure yet but maybe reversing a app package or other interactive thing or just trivia",
        "dex",
        18,
    ),
    (
        "Reverse Engineering",
        "reverse-engineering",
        "Binaries with flags in them or vulnerable code they have to identify and exploit",
        "con",
        19,
    ),
    (
        "Malware Analysis",
        "malware-analysis",
        "Simulated malware with the flag hidden inside, don't accidentally set it off",
        "con",
        20,
    ),
]

#: (name, kind, category name, display_order)
SKILLS = [
    ("Open Source Sleuthing", "useful", "OSINT", 0),
    ("Digital Tracking", "useful", "OSINT", 1),
    ("Packet Whispering", "useful", "Networking", 0),
    ("Threat Hunting Lore", "useful", "CTI", 0),
    ("Lateral Thinking", "useful", "Hacker Game Show", 0),
    ("Adversarial Mindset", "useful", "Red teaming", 0),
    ("Exploit Crafting", "useful", "Red teaming", 1),
    ("Privilege Escalation", "useful", "Identity & Access", 0),
    ("Credential Harvesting", "useful", "Identity & Access", 1),
    ("Circuit Whispering", "useful", "Hardware Hacking", 0),
    ("Signal Tampering", "useful", "Hardware Hacking", 1),
    ("Injection Artistry", "useful", "Web Attacks", 0),
    ("Auth Bypass", "useful", "Web Attacks", 1),
    ("Cloud Instinct", "useful", "Cloud Security", 0),
    ("Cryptanalysis", "useful", "Crypto", 0),
    ("Pattern Recognition", "useful", "Codes and Ciphers", 0),
    ("Model Interrogation", "useful", "AI/LLM Security", 0),
    ("Machine Persuasion", "useful", "Prompt Injection", 0),
    ("Pretexting", "useful", "Social Engineering", 0),
    ("Evidence Handling", "useful", "Forensics", 0),
    ("Artifact Recovery", "useful", "Forensics", 1),
    ("Risk Judgment", "useful", "Governance, Risk & Compliance", 0),
    ("Anomaly Sense", "useful", "Threat Detection", 0),
    ("Log Divination", "useful", "Threat Detection", 1),
    ("Triage Under Fire", "useful", "Incident Response", 0),
    ("Containment Instinct", "useful", "Incident Response", 1),
    ("APK Teardown", "useful", "Mobile Security", 0),
    ("Disassembly", "useful", "Reverse Engineering", 0),
    ("Debugger's Patience", "useful", "Reverse Engineering", 1),
    ("Sandbox Discipline", "useful", "Malware Analysis", 0),
    ("Static Analysis", "useful", "Malware Analysis", 1),
    ("Professional Stalking", "funny", "OSINT", 0),
    ("Chronic Tab Hoarding", "funny", "OSINT", 1),
    ("Blind Faith in Ping", "funny", "Networking", 0),
    ("IT Crowd Diagnostics", "funny", "Networking", 1),
    ("Acronym Fluency", "funny", "CTI", 0),
    ("Doomscrolling Endurance", "funny", "CTI", 1),
    ("Buzzer Twitchiness", "funny", "Hacker Game Show", 0),
    ("Overconfident Guessing", "funny", "Hacker Game Show", 1),
    ("Aggressive Hoodie Wearing", "funny", "Red teaming", 0),
    ("Mechanical Keyboard Volume", "funny", "Red teaming", 1),
    ("Sticky Note Radar", "funny", "Identity & Access", 0),
    ("Weak Password Sixth Sense", "funny", "Identity & Access", 1),
    ("Static Shock Tolerance", "funny", "Hardware Hacking", 0),
    ("Magic Smoke Attraction", "funny", "Hardware Hacking", 1),
    ("Reflexive Inspect Element", "funny", "Web Attacks", 0),
    ("Chronic URL Bar Tinkering", "funny", "Web Attacks", 1),
    ("Billing Alert Blindness", "funny", "Cloud Security", 0),
    ("Ownership Ambiguity", "funny", "Cloud Security", 1),
    ("Misplaced ROT13 Confidence", "funny", "Crypto", 0),
    ("Whiteboard Math Anxiety", "funny", "Crypto", 1),
    ("Base64 Squinting", "funny", "Codes and Ciphers", 0),
    ("Pattern Overfitting", "funny", "Codes and Ciphers", 1),
    ("Excessive Chatbot Politeness", "funny", "AI/LLM Security", 0),
    ("Instruction-Ignoring Instinct", "funny", "AI/LLM Security", 1),
    ("Roleplay Persuasion", "funny", "Prompt Injection", 0),
    ("Chronic Jailbreak Attempts", "funny", "Prompt Injection", 1),
    ("Convincing IT Voice", "funny", "Social Engineering", 0),
    ("Suspicious Trust in Free Pizza", "funny", "Social Engineering", 1),
    ("Compulsive Ctrl+F", "funny", "Forensics", 0),
    ("Metadata Gossip Radar", "funny", "Forensics", 1),
    ("Policy Skimming Speed", "funny", "Governance, Risk & Compliance", 0),
    ("Compliance Daydreaming", "funny", "Governance, Risk & Compliance", 1),
    ("Caffeinated Paranoia", "funny", "Threat Detection", 0),
    ("False Positive Fatigue", "funny", "Threat Detection", 1),
    ("Panic Typing Speed", "funny", "Incident Response", 0),
    ("Selective Calm Under Fire", "funny", "Incident Response", 1),
    ("Permission Paranoia", "funny", "Mobile Security", 0),
    ("Reflexive Airplane Mode", "funny", "Mobile Security", 1),
    ("Hex Staring Endurance", "funny", "Reverse Engineering", 0),
    ("Rubber Duck Dependency", "funny", "Reverse Engineering", 1),
    ("Reckless Double-Clicking", "funny", "Malware Analysis", 0),
    ("False Antivirus Confidence", "funny", "Malware Analysis", 1),
]


def upgrade() -> None:
    conn = op.get_bind()

    for name, slug, description, ability, order in CATEGORIES:
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

    for name, kind, category, order in SKILLS:
        conn.execute(
            sa.text(
                """
                INSERT INTO skill (id, name, kind, category_id, display_order,
                                   created_at, updated_at)
                SELECT gen_random_uuid(), :name, CAST(:kind AS skill_kind), c.id,
                       :display_order, now(), now()
                  FROM category c
                 WHERE c.name = :category
                ON CONFLICT (name) DO NOTHING
                """
            ),
            {"name": name, "kind": kind, "category": category, "display_order": order},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM skill WHERE name = ANY(:names)"),
        {"names": [s[0] for s in SKILLS]},
    )
    # Categories are left: a challenge may point at one, and RESTRICT would block
    # the delete anyway. Removing the seed should not risk taking content with it.
