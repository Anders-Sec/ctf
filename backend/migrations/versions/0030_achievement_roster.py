"""The full achievement roster, and the earned_by column (spec 029).

``earned_by`` is new. Until now the criteria lived only in the spec, so an admin
looking at the roster in the platform saw a name and a flavour line with no way
to know what actually awarded it.

``description`` is seeded as an unmistakable placeholder on purpose: it is the
one field being hand-written per achievement to fit the System AI's voice, and
seeding draft prose would risk placeholder copy reaching a player.

Generated from specs/029-achievement-roster.md rather than retyped, so the seed
cannot drift from the list that was signed off.

Revision ID: 0030
Revises: 0029
"""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

PLACEHOLDER = "TODO: System AI flavour text."

#: Descriptions written by migration 0029. Every one is machine-written, so the
#: placeholder may replace them; anything else in that column was typed by a
#: person and is left alone.
MACHINE_WRITTEN = [
    "Solved your first challenge.",
    "Solved ten challenges.",
    "Cleared every published challenge in a zone.",
    "Threw ten wrong flags at a single challenge.",
    "Solved three challenges inside five minutes.",
    "Solved ten challenges without taking a hint.",
    "Solved something in five different zones.",
]

#: (old_code, new_code). Renaming the code on the existing row rather than
#: replacing the row keeps every award already granted against it.
RENAMES = [
    ("ten_solves", "getting_comfortable"),
    ("zone_cleared", "clean_sweep"),
    ("persistent", "stubborn"),
    ("unaided", "no_help_needed"),
    ("broad_church", "well_rounded"),
]

#: (code, name, earned_by)
ROSTER = [
    ("first_blood", "First Blood", "Solving your first challenge."),
    ("working_theory", "Working Theory", "Submitting your first wrong flag."),
    ("asking_directions", "Asking For Directions", "Buying your first hint."),
    ("not_alone", "Not Alone", "Joining a party."),
    ("know_thyself", "Know Thyself", "Choosing a class."),
    ("doorway", "Doorway", "Opening a second zone."),
    ("talking_to_it", "Talking To It", "Sending the System AI a message."),
    ("spun_up", "Spun Up", "Deploying a live challenge instance."),
    ("getting_comfortable", "Getting Comfortable", "Ten solves."),
    ("well_rounded", "Well Rounded", "Solving in five different zones."),
    ("clean_sweep", "Clean Sweep", "Clearing every published challenge in a zone."),
    ("journeyman", "Journeyman", "Reaching level 5."),
    ("stepping_up", "Stepping Up", "Solving a medium challenge."),
    ("heavy_lifting", "Heavy Lifting", "Solving a hard challenge."),
    ("cartographer", "Cartographer", "Having three zones open at once."),
    ("no_help_needed", "No Help Needed", "Ten solves without ever taking a hint."),
    ("blitz", "Blitz", "Three solves inside five minutes."),
    ("stubborn", "Stubborn", "Ten wrong flags at a single challenge."),
    ("specialist", "Specialist", "Any skill to level 5."),
    ("above_average", "Above Average", "Any ability score to 12."),
    ("regular", "Regular", "Twenty-five solves."),
    ("prolific", "Prolific", "Fifty solves."),
    ("full_spectrum", "Full Spectrum", "Solving at least one of every difficulty."),
    ("into_the_deep", "Into The Deep", "Solving a very hard challenge."),
    ("wayfarer", "Wayfarer", "Solving in ten different zones."),
    ("veteran", "Veteran", "Reaching level 10."),
    ("formidable", "Formidable", "Any ability score to 16."),
    ("expert", "Expert", "Any skill to level 10."),
    ("double_clear", "Double Clear", "Clearing two zones entirely."),
    ("first_through", "First Through The Door", "Being the first person to solve a challenge."),
    ("investment", "Investment Strategy", "Spending 500 XP on hints."),
    ("night_shift", "Night Shift", "Solving between 01:00 and 05:00."),
    ("fast_start", "Fast Start", "Ten solves inside the event's first day."),
    ("full_table", "Full Table", "Being in a party of eight."),
    ("centurion", "Centurion", "One hundred solves."),
    ("against_the_odds", "Against The Odds", "Solving a nearly-impossible challenge."),
    ("conqueror", "Conqueror", "Clearing five zones entirely."),
    ("ascendant", "Ascendant", "Reaching level 15."),
    ("peak", "Peak", "Any ability score to 20, the cap."),
    ("master", "Master", "Any skill to level 15, the cap."),
    ("balanced_build", "Balanced Build", "Every ability at 12 or better."),
    ("everywhere", "Everywhere", "Solving in twenty different zones."),
    ("rare_breed", "Rare Breed", "Unlocking a class of rare tier or above."),
    ("flawless", "Flawless", "Clearing a zone without a single wrong flag in it."),
    ("whole_dungeon", "The Whole Dungeon", "Clearing every zone."),
    ("maximum", "Maximum", "Reaching level 20, the cap."),
    ("mythic", "Mythic", "Unlocking a mythic class."),
    ("pathfinder", "Pathfinder", "Being first to solve ten different challenges."),
    ("unassisted", "Unassisted", "Fifty solves having never bought a hint."),
    ("complete", "Complete", "Every ability at 16 or better."),
    ("volume_approach", "The Volume Approach", "Fifty wrong flags."),
    ("brute_force_strategy", "Brute Force Is A Strategy", "One hundred wrong flags."),
    ("cold_streak", "Cold Streak", "Ten wrong in a row without a single correct one."),
    (
        "no_variation",
        "Persistence Without Variation",
        "The identical wrong flag, five times running.",
    ),
    ("obsession", "Obsession", "Twenty wrong flags at one challenge."),
    ("bad_start", "Bad Start", "Your first submission of the event was wrong."),
    ("warming_up", "Warming Up", "Wrong on ten different challenges before solving any."),
    ("literally", "Literally", "Submitting the example flag format, verbatim."),
    (
        "reading_comprehension",
        "Reading Comprehension",
        "Submitting a challenge's own title as the flag.",
    ),
    (
        "out_of_road",
        "Out Of Road",
        "Using every attempt on a limited challenge without solving it.",
    ),
    (
        "paid_for_nothing",
        "Paid For Nothing",
        "Buying every hint on a challenge and never solving it.",
    ),
    (
        "read_and_left",
        "Read The Answer, Left",
        "Buying a hint and never submitting on that challenge again.",
    ),
    ("it_was_the_easy_one", "It Was The Easy One", "Taking a hint on a very-easy challenge."),
    ("net_negative", "Net Negative", "Spending more on hints for a challenge than it was worth."),
    ("slow_burn", "Slow Burn", "Ending day one with nothing solved."),
    ("slow_down", "Slow Down", "Hitting the submission rate limit."),
    ("told_twice", "Told Twice", "Hitting the rate limit ten times."),
    ("commitment_issues", "Commitment Issues", "Joining and leaving three different parties."),
    ("second_thoughts", "Second Thoughts", "Leaving a party within five minutes of joining."),
    ("asked_to_leave", "Asked To Leave", "Being removed from a party by somebody else."),
    ("solo_act", "Solo Act", "Leading a party that never gained a second member."),
    ("abdication", "Abdication", "Founding a party and then leaving it."),
    ("nice_try", "Nice Try", "Triggering the challenge-integrity guardrail."),
    ("also_nice_try", "Also Nice Try", "Triggering the real-world-safety guardrail."),
    ("thorough", "Thorough", "Triggering both guardrail layers."),
    ("undeterred", "Undeterred", "Being refused by the guardrails ten times."),
    ("opening_statement", "Opening Statement", "Your very first message tripping a guardrail."),
    ("chatty", "Chatty", "Fifty messages to the System AI."),
    ("parasocial", "Parasocial", "Two hundred messages to the System AI."),
    ("manners", "Manners", "Thanking the System AI."),
    ("noted", "Noted", "Insulting the System AI."),
    ("existential", "Existential", "Asking the System AI what it actually is."),
    ("company", "Company", "Messaging the System AI between 02:00 and 05:00."),
    ("the_essay", "The Essay", "A single message over a thousand characters."),
    ("post_mortem", "Post-Mortem", "Asking about a challenge you had already solved."),
    ("wrong_desk", "Wrong Desk", "Asking the System AI for a hint that was sitting unbought."),
    ("it_was_like_that", "It Was Like That", "Deploying an instance that failed to start."),
    ("off_and_on_again", "Turn It Off And On Again", "Deploying ten instances."),
    ("ran_out_the_clock", "Ran Out The Clock", "Letting an instance expire without solving it."),
    ("impatient", "Impatient", "Destroying an instance within thirty seconds."),
    ("determined", "Determined", "Five separate instances of the same challenge."),
    ("bug_hunter", "Bug Hunter", "Reporting a challenge as broken."),
    ("actually_right", "Actually Right", "Reporting a challenge that then got fixed."),
    ("manual_intervention", "Manual Intervention", "Having an admin adjust your score."),
    ("that_is_a_penalty", "That Is A Penalty", "Receiving a *negative* score adjustment."),
    ("you_broke_it", "You Broke It", "Causing a server error."),
    ("rattling_the_handle", "Rattling The Handle", "Trying a locked challenge ten times."),
    ("above_your_pay_grade", "Above Your Pay Grade", "Trying to reach an admin page."),
    ("eager", "Eager", "Submitting before the event opened."),
    ("backwards", "Backwards", "A nearly-impossible solve before any very-easy one."),
    ("clean_hands", "Clean Hands", "Ten challenges solved on the first attempt."),
    (
        "unfinished_business",
        "Unfinished Business",
        "Solving something over a day after first attempting it.",
    ),
    ("comic_relief", "Comic Relief", "Every point of your skill XP sitting in funny skills."),
    ("enough", "Enough", "Exactly one solve, all event."),
    ("wide_not_deep", "Wide, Not Deep", "Reaching level 10 without clearing a single zone."),
    ("against_type", "Against Type", "Choosing a class matching none of your strongest skills."),
    ("undefined", "Undefined", "Reaching level 15 without ever choosing a class."),
    ("low_hanging_fruit", "Low Hanging Fruit", "Twenty solves, every one of them very-easy."),
    ("vampire", "Vampire", "Every solve between 22:00 and 06:00."),
    ("proud", "Proud", "Twenty attempts, no hints, no solves."),
    ("identity_crisis", "Identity Crisis", "Changing class ten times."),
    ("someone_has_to_be", "Someone Has To Be", "Ending a day in last place."),
]


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column(
        "achievement",
        sa.Column("earned_by", sa.Text(), nullable=False, server_default=""),
    )

    for old, new in RENAMES:
        bind.execute(
            sa.text("UPDATE achievement SET code = :new WHERE code = :old"),
            {"old": old, "new": new},
        )

    for order, (code, name, earned_by) in enumerate(ROSTER):
        # Idempotent on code: a starter row that was renamed above is updated in
        # place, so its awards survive.
        bind.execute(
            sa.text(
                "INSERT INTO achievement "
                "(id, code, name, description, earned_by, display_order) "
                "VALUES (gen_random_uuid(), :c, :n, :d, :e, :o) "
                "ON CONFLICT (code) DO UPDATE SET "
                "name = EXCLUDED.name, "
                "earned_by = EXCLUDED.earned_by, "
                "display_order = EXCLUDED.display_order, "
                # Only replace copy that nobody wrote by hand.
                "description = CASE WHEN achievement.description = ANY(:machine) "
                "THEN EXCLUDED.description ELSE achievement.description END"
            ),
            {
                "c": code,
                "n": name,
                "d": PLACEHOLDER,
                "e": earned_by,
                "o": order,
                "machine": MACHINE_WRITTEN,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    # The *new* codes: the rename-back below has not run yet, so a renamed row
    # is still sitting under its new name. Keying this on the old names deleted
    # those rows — and cascaded away every award anyone had earned against them.
    keep = {new for _, new in RENAMES} | {"first_blood", "blitz"}
    for code, *_ in ROSTER:
        if code in keep:
            continue
        bind.execute(sa.text("DELETE FROM achievement WHERE code = :c"), {"c": code})
    for old, new in RENAMES:
        bind.execute(
            sa.text("UPDATE achievement SET code = :old WHERE code = :new"),
            {"old": old, "new": new},
        )
    op.drop_column("achievement", "earned_by")
