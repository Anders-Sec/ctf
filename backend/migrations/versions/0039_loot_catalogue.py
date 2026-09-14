"""The loot catalogue, and what each achievement drops (spec 038).

81 of the 117 achievements drop a box; the other 36 carry a line from the System
explaining why not. Boss achievements store no rarity — the boss tier set in 031
supplies it, so that fact is configured once.

Pools are addressed by key rather than box type because the low tiers share: one
bronze pool for everything, two silver families. Gold and above are per box
type, where the box's identity should come through.

Generated from the spec's own grouping rather than retyped.

Revision ID: 0039
Revises: 0038
"""

# ruff: noqa: E501 - title lists and prose. Wrapping them would make the content
# markedly harder to read and edit.

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

BOX_TYPES = (
    "adventurer",
    "boss",
    "brute_force",
    "cartographer",
    "interrogator",
    "party",
    "pathfinder",
    "purist",
    "saboteur",
    "specialist",
)
RARITIES = ("bronze", "silver", "gold", "platinum", "legendary", "celestial")

#: (code, box_type or None, rarity or None)
ASSIGNMENTS = [
    ("first_blood", "adventurer", "bronze"),
    ("working_theory", None, None),
    ("asking_directions", None, None),
    ("not_alone", "party", "bronze"),
    ("know_thyself", "specialist", "bronze"),
    ("doorway", "cartographer", "bronze"),
    ("talking_to_it", "interrogator", "bronze"),
    ("spun_up", "saboteur", "bronze"),
    ("getting_comfortable", "adventurer", "bronze"),
    ("well_rounded", "cartographer", "silver"),
    ("clean_sweep", "cartographer", "gold"),
    ("journeyman", "adventurer", "silver"),
    ("stepping_up", "adventurer", "bronze"),
    ("heavy_lifting", "adventurer", "silver"),
    ("no_help_needed", "purist", "gold"),
    ("blitz", "pathfinder", "silver"),
    ("stubborn", None, None),
    ("specialist", "specialist", "silver"),
    ("above_average", "specialist", "silver"),
    ("regular", "adventurer", "gold"),
    ("prolific", "adventurer", "platinum"),
    ("full_spectrum", "adventurer", "gold"),
    ("into_the_deep", "adventurer", "gold"),
    ("wayfarer", "cartographer", "gold"),
    ("veteran", "adventurer", "gold"),
    ("formidable", "specialist", "gold"),
    ("expert", "specialist", "gold"),
    ("double_clear", "cartographer", "gold"),
    ("first_through", "pathfinder", "gold"),
    ("night_shift", "pathfinder", "silver"),
    ("fast_start", "pathfinder", "silver"),
    ("full_table", "party", "silver"),
    ("centurion", "adventurer", "legendary"),
    ("against_the_odds", "adventurer", "platinum"),
    ("conqueror", "cartographer", "platinum"),
    ("ascendant", "adventurer", "platinum"),
    ("peak", "specialist", "legendary"),
    ("master", "specialist", "legendary"),
    ("balanced_build", "specialist", "platinum"),
    ("everywhere", "cartographer", "legendary"),
    ("rare_breed", "specialist", "platinum"),
    ("flawless", "cartographer", "platinum"),
    ("whole_dungeon", "cartographer", "celestial"),
    ("maximum", "adventurer", "celestial"),
    ("mythic", "specialist", "celestial"),
    ("pathfinder", "pathfinder", "legendary"),
    ("unassisted", "purist", "legendary"),
    ("complete", "specialist", "celestial"),
    ("volume_approach", None, None),
    ("brute_force_strategy", "brute_force", "gold"),
    ("cold_streak", None, None),
    ("no_variation", "brute_force", "silver"),
    ("obsession", "brute_force", "silver"),
    ("bad_start", None, None),
    ("warming_up", None, None),
    ("literally", None, None),
    ("reading_comprehension", None, None),
    ("out_of_road", None, None),
    ("net_negative", None, None),
    ("commitment_issues", None, None),
    ("second_thoughts", None, None),
    ("asked_to_leave", None, None),
    ("abdication", None, None),
    ("nice_try", None, None),
    ("also_nice_try", None, None),
    ("thorough", "interrogator", "gold"),
    ("undeterred", None, None),
    ("opening_statement", None, None),
    ("chatty", None, None),
    ("parasocial", "interrogator", "silver"),
    ("manners", None, None),
    ("noted", None, None),
    ("existential", None, None),
    ("company", None, None),
    ("the_essay", "interrogator", "silver"),
    ("it_was_like_that", None, None),
    ("off_and_on_again", None, None),
    ("ran_out_the_clock", None, None),
    ("determined", None, None),
    ("bug_hunter", "saboteur", "bronze"),
    ("actually_right", "saboteur", "silver"),
    ("manual_intervention", None, None),
    ("that_is_a_penalty", None, None),
    ("you_broke_it", "saboteur", "gold"),
    ("above_your_pay_grade", None, None),
    ("backwards", "brute_force", "silver"),
    ("clean_hands", "pathfinder", "platinum"),
    ("unfinished_business", "adventurer", "silver"),
    ("wide_not_deep", None, None),
    ("against_type", "specialist", "silver"),
    ("undefined", None, None),
    ("low_hanging_fruit", None, None),
    ("vampire", "pathfinder", "gold"),
    ("proud", None, None),
    ("identity_crisis", None, None),
    ("boss_intro", "boss", None),
    ("boss_osint", "boss", None),
    ("boss_networking", "boss", None),
    ("boss_cti", "boss", None),
    ("boss_hacker-game-show", "boss", None),
    ("boss_red-teaming", "boss", None),
    ("boss_identity-access", "boss", None),
    ("boss_hardware-hacking", "boss", None),
    ("boss_web-attacks", "boss", None),
    ("boss_cloud-security", "boss", None),
    ("boss_crypto", "boss", None),
    ("boss_codes-and-ciphers", "boss", None),
    ("boss_ai-llm-security", "boss", None),
    ("boss_prompt-injection", "boss", None),
    ("boss_social-engineering", "boss", None),
    ("boss_forensics", "boss", None),
    ("boss_governance-risk-compliance", "boss", None),
    ("boss_threat-detection", "boss", None),
    ("boss_incident-response", "boss", None),
    ("boss_mobile-security", "boss", None),
    ("boss_reverse-engineering", "boss", None),
    ("boss_malware-analysis", "boss", None),
]

#: (code, line)
NO_LOOT_LINES = [
    (
        "abdication",
        "No box. You founded it and you walked out of it. Leadership is its own reward, apparently.",
    ),
    (
        "above_your_pay_grade",
        "No box. You tried a door marked for staff. The reward for that is my continued attention.",
    ),
    (
        "also_nice_try",
        "No box. You asked for something I will not say, and the answer is still no, now with paperwork.",
    ),
    (
        "asked_to_leave",
        "No box. Somebody already in the party decided this one. Take it up with them.",
    ),
    (
        "asking_directions",
        "No box. You bought a hint. The hint was the reward; you have already had it.",
    ),
    ("bad_start", "No box. The stores do not open for a bad opening move."),
    (
        "chatty",
        "No box. Fifty messages is a conversation, not an achievement, and I have already read them all.",
    ),
    (
        "cold_streak",
        "No box. Ten in a row is a streak, not an accomplishment, and the audience has already had the entertainment.",
    ),
    (
        "commitment_issues",
        "No box. Three parties joined and three left is a pattern, and patterns are not loot.",
    ),
    ("company", "No box. Neither of us had anywhere better to be. That is not a transaction."),
    (
        "determined",
        "No box. Five instances of the same room, and the room has not changed since the first.",
    ),
    ("existential", "No box. Curiosity about what I am is not a service I pay out for."),
    (
        "identity_crisis",
        "No box. Ten changes of designation. Pick one and I will consider dressing it.",
    ),
    (
        "it_was_like_that",
        "No box. The target failed to start and that was not your doing. Nothing owed either way.",
    ),
    (
        "literally",
        "No box. I am not paying you for reading the instructions and then submitting them.",
    ),
    (
        "low_hanging_fruit",
        "No box. Twenty of the easiest rooms in the dungeon is efficient. It is not decorated.",
    ),
    (
        "manners",
        "No box. Politeness is its own reward, which is a thing people say when there is no other reward.",
    ),
    (
        "manual_intervention",
        "No box. Somebody upstairs moved your number by hand. Take it up with them, not me.",
    ),
    (
        "net_negative",
        "No box. You have already spent more than the room was worth. I am not compounding it.",
    ),
    ("nice_try", "No box. I do not reward attempts to talk me out of things. I log them."),
    (
        "noted",
        "No box. You insulted me in front of several billion viewers. They were entertained. I was not, and I control the stores.",
    ),
    (
        "off_and_on_again",
        "No box. Ten instances is a habit. The classic approach pays classic rates.",
    ),
    (
        "opening_statement",
        "No box. You opened by tripping a guardrail. The audience enjoyed it; the stores did not.",
    ),
    (
        "out_of_road",
        "No box. You spent every attempt and the door is still shut. The stores stay shut with it.",
    ),
    ("proud", "No box. Purity of method, unburdened by results, and unburdened by loot."),
    (
        "ran_out_the_clock",
        "No box. It waited, you did not come, and the stores follow the same schedule.",
    ),
    (
        "reading_comprehension",
        "No box. The encounter told you its name and you handed it back. That is not loot-bearing behaviour.",
    ),
    (
        "second_thoughts",
        "No box. You were in a party for five minutes. The stores have a longer memory than that.",
    ),
    (
        "stubborn",
        "No box. Ten wrong answers at one door buys you nothing but the door's continued indifference.",
    ),
    (
        "that_is_a_penalty",
        "No box. Your score went down by decision. I am not topping it up with a title.",
    ),
    (
        "undefined",
        "No box. You have declined to be anything in particular, so there is nothing to dress.",
    ),
    (
        "undeterred",
        "No box. Ten refusals is not a collection. Persistence aimed at a wall pays exactly what a wall pays.",
    ),
    (
        "volume_approach",
        "No box. Fifty wrong answers is volume. Come back when it becomes a method.",
    ),
    (
        "warming_up",
        "No box. Ten doors of research into what does not work is its own reward, and you may keep it.",
    ),
    (
        "wide_not_deep",
        "No box. Broad and shallow is a strategy. It is not one the stores recognise.",
    ),
    (
        "working_theory",
        "No box. Being wrong is free, Crawler, and you have already claimed your allowance.",
    ),
]

#: (pool_key, rarity, [titles])
POOLS = [
    (
        "adventurer",
        "celestial",
        [
            "The Ceiling Of The Broadcast",
            "Nothing Above This Line",
            "The Dungeon Has Nothing Left",
            "Beyond The Recorded Scale",
            "The Audience Stood For This One",
            "An Entry With No Equal",
            "The Furthest Recorded Point",
            "Past Every Measure We Have",
            "The End Of The Ladder",
            "Unprecedented, And Filed As Such",
        ],
    ),
    (
        "adventurer",
        "gold",
        [
            "Career Crawler",
            "Deep In The Rotation",
            "Seasoned Line Item",
            "Hard To Discourage",
            "Fixture Of The Broadcast",
            "Long Past Novelty",
            "Reliably Dangerous",
            "Difficult To Bore",
        ],
    ),
    (
        "adventurer",
        "legendary",
        [
            "Legend Of The Lower Floors",
            "Spoken Of On The Surface",
            "A Named Hazard",
            "The One They Warn About",
            "Outlasted The Dungeon's Patience",
            "Entered The Broadcast Record",
            "Beyond The Design Envelope",
            "A Problem Without Precedent",
            "Carried The Whole Floor",
            "The Audience Knows The Name",
            "Rewrote The Expected Curve",
            "Something The Dungeon Regrets",
            "Far Past Reasonable",
            "An Entry In The Permanent Record",
            "Unaccountable By Any Measure",
        ],
    ),
    (
        "adventurer",
        "platinum",
        [
            "Veteran Of The Deep Floors",
            "Unreasonably Persistent",
            "A Problem For The Dungeon",
            "Difficult To Account For",
            "Past The Point Of Sense",
            "Beyond Reasonable Effort",
            "Grinds Mountains Flat",
            "Refuses To Be Filed",
            "Ahead Of The Curve And Rising",
            "Exceeds Specification",
            "An Awkward Statistic",
            "Outlasted The Design",
            "Known On Several Floors",
            "Overqualified For The Room",
            "Handles The Hard Ones",
            "Above The Expected Curve",
            "A Recognised Threat",
            "Runs Long",
            "Structurally Unstoppable",
            "Hard To Legislate Against",
            "Built For The Long Floor",
            "Comfortable Where It Hurts",
            "Escalating Quietly",
            "The Dungeon's Problem Now",
            "Noted At Length",
        ],
    ),
    (
        "boss",
        "bronze",
        [
            "Put Something Down",
            "Cleared The Room",
            "One Less Problem",
            "Neighborhood Trouble",
            "Won The Argument",
            "Something Stopped Moving",
            "Handled It",
            "Off The Board",
        ],
    ),
    (
        "boss",
        "celestial",
        [
            "Floor Trouble",
            "Ended The Floor Itself",
            "The Broadcast Has No Words",
            "Took Down The Last Thing",
            "Something Celestial, Stopped",
            "The Fight At The End Of The Floor",
            "Nothing On This Floor Remains",
            "The Audience Rose As One",
            "Beat The Thing At The Bottom",
            "Floor-Level Trouble, Handled",
        ],
    ),
    (
        "boss",
        "gold",
        [
            "City Trouble",
            "Ended Something Considerable",
            "The Audience Was Watching",
            "Took Down A Landmark",
            "A Name Off The Wall",
            "The Big Room, Emptied",
            "Something That Mattered",
            "Cleared The Marquee",
        ],
    ),
    (
        "boss",
        "legendary",
        [
            "Country Trouble",
            "Ended Something Country-Sized",
            "The Broadcast Stopped For This",
            "A Legend, Concluded",
            "Took Down What The Floor Feared",
            "Something Immense, Ended",
            "The Fight They Will Talk About",
            "Removed A National Problem",
            "The Audience Will Not Forget",
            "Ended The Unbeaten Thing",
            "Cleared The Impossible Room",
            "A Reign Of Some Length, Over",
            "Beat What Was Not Meant To Be Beaten",
            "The Boss Of Record",
            "Country-Level Trouble, Handled",
        ],
    ),
    (
        "boss",
        "platinum",
        [
            "Province Trouble",
            "Ended Something Province-Sized",
            "The Broadcast Cut To You",
            "A Landmark, Removed",
            "Took Down The Wing's Worst",
            "The Audience Was Loud",
            "Something Enormous, Stopped",
            "Cleared What Others Could Not",
            "The Room That Held Everyone Up",
            "A Reign, Concluded",
            "Ended The Long Fight",
            "Removed A Fixture",
            "Broke The Deadlock",
            "The Boss Nobody Wanted",
            "Took The Hard Wing",
            "Something Vast, Ended",
            "A Genuine Obstacle, Gone",
            "Cleared The Worst Of It",
            "Put Down What Was Waiting",
            "The Wing's Own Monster",
            "Beat The Thing In The Dark",
            "Ended It Personally",
            "A Fixture Of The Floor, Removed",
            "Won Where Others Stalled",
            "Province-Level Trouble, Handled",
        ],
    ),
    (
        "boss",
        "silver",
        [
            "Borough Trouble",
            "Took The Big One",
            "Ended A Reign",
            "Something Large Stopped",
            "The Room Went Quiet",
            "Broke The Stalemate",
            "A Boss-Shaped Hole",
            "Won By Some Margin",
        ],
    ),
    (
        "brute_force",
        "gold",
        [
            "Method Over Grace",
            "Volume As Strategy",
            "Statistically Inevitable",
            "Wears Doors Down",
            "Attrition Specialist",
            "Eventually Correct",
            "Out-Stubborned The Room",
            "Approached It Numerically",
        ],
    ),
    (
        "cartographer",
        "celestial",
        [
            "Every Wing. Every Room.",
            "The Whole Dungeon, Emptied",
            "Nothing Remains Unopened",
            "Complete To The Last Door",
            "The Floor Belongs To You",
            "Total Coverage, Verified",
            "There Is No More Dungeon",
            "Surveyed To Its Ending",
            "The Map Is Finished",
            "All Of It, Taken",
        ],
    ),
    (
        "cartographer",
        "gold",
        [
            "Wing By Wing",
            "Owner Of Several Corridors",
            "Thorough Surveyor",
            "Been Everywhere Twice",
            "Empties Rooms For Sport",
            "Keeper Of Cleared Floors",
            "Leaves Nothing Standing",
            "Walks It Off",
        ],
    ),
    (
        "cartographer",
        "legendary",
        [
            "Has Been Everywhere There Is",
            "The Map Is A Formality",
            "Nothing Hidden Remains",
            "Emptied The Known World",
            "Walked Every Corridor Twice",
            "There Is No Unexplored Wing",
            "Knows Doors That Are Not There",
            "The Dungeon Has No Secrets Left",
            "Complete And Then Some",
            "Surveyed To Exhaustion",
            "Ran Out Of Floor",
            "Every Wing, Emptied",
            "The Last Corner Found",
            "Nowhere Left To Be",
            "Cartographer Of Everything",
        ],
    ),
    (
        "cartographer",
        "platinum",
        [
            "Owner Of The Map",
            "Has Seen The Back Wall",
            "Nothing Left Unentered",
            "Emptied More Than Most",
            "Corridors Answer To You",
            "Walks Cleared Ground",
            "Surveyor Of The Whole Floor",
            "Left No Room Standing",
            "Knows Every Doorway",
            "Charted And Emptied",
            "Runs Out Of Dungeon",
            "The Floor Is Memorised",
            "Took The Long Way Everywhere",
            "Absent From No Wing",
            "Wing-Clearing Specialist",
            "Has Been Behind That Door",
            "Leaves Maps Behind",
            "Nothing Left To Find Here",
            "Complete Coverage",
            "Been Through The Walls",
            "Reached The Far Corner",
            "Empties Floors For Fun",
            "Thorough To A Fault",
            "Cartographic Menace",
            "There Is Nowhere Left",
        ],
    ),
    (
        "common",
        "bronze",
        [
            "Line Item",
            "Present And Accounted For",
            "Adequate",
            "Within Tolerance",
            "Noted In Passing",
            "Provisionally Employed",
            "Of Record",
            "Nominally Active",
            "Filed Under Pending",
            "Sufficiently Alive",
            "Technically Participating",
            "Acceptable Losses",
        ],
    ),
    (
        "interrogator",
        "gold",
        [
            "Persistent Correspondent",
            "Known To The System",
            "Asks The Wrong Things Well",
            "On First-Name Terms",
            "A Frequent Imposition",
            "Tests The Patience",
            "Answered Against My Will",
            "Charged At My Discretion",
        ],
    ),
    (
        "mischief",
        "silver",
        [
            "Loud In The Corridor",
            "Known To The Desk",
            "A Recurring Entry",
            "Enthusiastically Incorrect",
            "Filed Twice",
            "Repeat Business",
            "The Usual Suspect",
            "Unsupervised",
            "Handled With Tongs",
            "Escalated Once",
            "A Matter For Review",
            "Best Observed Remotely",
        ],
    ),
    (
        "pathfinder",
        "gold",
        [
            "First Through The Dust",
            "Sets The Pace",
            "Ahead Of The Crowd",
            "Arrives Before The Warning",
            "Quick Off The Mark",
            "Beat The Announcement",
            "Already Inside",
            "Sets Records Casually",
        ],
    ),
    (
        "pathfinder",
        "legendary",
        [
            "Ten Doors, First Through All",
            "The Name On Every Door",
            "Never Second",
            "Perpetually Ahead",
            "Front Of The Broadcast",
            "Opens The Dungeon For Everyone",
            "Nobody Has Ever Been Faster",
            "The Standard Others Fail",
            "First By Habit",
            "The Pace Of Record",
            "Everything Else Is Catching Up",
            "Sets The Times That Stand",
            "Gone Before It Started",
            "Holds Every Opening",
            "Unbeaten To The Door",
        ],
    ),
    (
        "pathfinder",
        "platinum",
        [
            "Ahead Of Everyone",
            "First, Repeatedly",
            "Sets The Record And Leaves",
            "Arrives Before The Room Is Ready",
            "Faster Than The Broadcast",
            "Already Gone By Now",
            "Beat The Announcement Twice",
            "Opens Doors For Others",
            "The Pace Everyone Fails To Match",
            "First Through, Every Time",
            "Ahead Of The Warning",
            "Runs The Floor Down",
            "Nothing Catches Up",
            "Sets Times Nobody Beats",
            "Through Before The Dust Settled",
            "Quicker Than The Paperwork",
            "The Reason Others Are Second",
            "Clears Rooms At Speed",
            "Outruns The Schedule",
            "The Front Of The Field",
            "Records Set Casually",
            "Gone Before The Reply",
            "Leaves Only The Time",
            "First Name On The Board",
            "Unmatched For Pace",
        ],
    ),
    (
        "progress",
        "silver",
        [
            "Making Headway",
            "Load-Bearing",
            "Better Than Advertised",
            "Consistently Upright",
            "Quietly Competent",
            "Reliably Awake",
            "Ahead Of The Paperwork",
            "Trending Upward",
            "Worth The Bandwidth",
            "Promoted From Statistic",
            "Marginally Remarkable",
            "Above The Line",
        ],
    ),
    (
        "purist",
        "gold",
        [
            "Takes No Help",
            "Unassisted And Unimpressed",
            "Refuses The Rope",
            "Own Two Hands",
            "Declines Assistance",
            "No Notes Required",
            "Nothing Borrowed",
            "Solved It Alone",
        ],
    ),
    (
        "purist",
        "legendary",
        [
            "Fifty Rooms, No Help",
            "Took Nothing From Anyone",
            "Entirely Unassisted",
            "Refused Every Rope",
            "Own Hands Only",
            "Never Asked Once",
            "Solved It All Alone",
            "Declined Assistance Throughout",
            "Nothing Borrowed, Nothing Owed",
            "Unhelped And Unbothered",
            "The Purist Of Record",
            "No Hints, No Exceptions",
            "Did It The Long Way, Always",
            "Assistance Declined, Permanently",
            "Clean Throughout",
        ],
    ),
    (
        "saboteur",
        "gold",
        [
            "Found The Seam",
            "Leans On Things",
            "Known To The Maintenance Log",
            "Makes The Machinery Complain",
            "Tests Load-Bearing Walls",
            "An Unscheduled Event",
            "Filed Under Structural",
            "Broke Something Properly",
        ],
    ),
    (
        "specialist",
        "celestial",
        [
            "Complete In Every Respect",
            "Nothing Left Unmastered",
            "The Absolute Ceiling, Everywhere",
            "No Weakness On Record",
            "Perfected Across The Board",
            "The Complete Crawler",
            "Beyond Every Rated Limit",
            "Unimprovable",
            "The Final Entry In The Discipline",
            "Nothing To Criticise",
        ],
    ),
    (
        "specialist",
        "gold",
        [
            "Narrow And Sharp",
            "Exceptional In One Direction",
            "Trade Qualified",
            "Peak Of A Small Mountain",
            "Refuses To Generalise",
            "Depth Over Breadth",
            "Master Of The Chosen Thing",
            "Unusually Specific",
        ],
    ),
    (
        "specialist",
        "legendary",
        [
            "The Ceiling, Personally",
            "Nothing Left To Sharpen",
            "Beyond The Rated Maximum",
            "Peak Of The Recorded Scale",
            "The Limit, Reached",
            "A Skill Taken To Its End",
            "Unimprovable In One Respect",
            "Holds The Absolute Record",
            "Has Exhausted The Discipline",
            "The Top Of A Very Tall Ladder",
            "Beyond What Was Measured For",
            "Nothing Above This",
            "The Furthest Anyone Has Gone",
            "Ended The Question",
            "Mastery, Concluded",
        ],
    ),
    (
        "specialist",
        "platinum",
        [
            "Terrifyingly Specific",
            "Peak Of The Discipline",
            "Defined By One Thing",
            "Unmatched In A Narrow Field",
            "The Best At Something",
            "Sharpened Past Useful",
            "Overspecialised And Proud",
            "Nobody Else Comes Close",
            "Singular Competence",
            "A Discipline Of One",
            "Beyond The Curriculum",
            "Apex Of A Narrow Field",
            "Refined To A Point",
            "Has No Peer Here",
            "Studied Past Reason",
            "Excellence, Narrowly Aimed",
            "One Skill, Perfected",
            "Unreasonably Good At It",
            "Beyond The Rated Ceiling",
            "Holds The Record Quietly",
            "Expert Beyond Filing",
            "The Specialist's Specialist",
            "Deep In One Direction",
            "Mastery, Inconveniently",
            "Nothing Left To Learn Here",
        ],
    ),
]


def upgrade() -> None:
    box_type = postgresql.ENUM(*BOX_TYPES, name="loot_box_type", create_type=False)
    rarity = postgresql.ENUM(*RARITIES, name="loot_rarity", create_type=False)
    box_type.create(op.get_bind(), checkfirst=True)
    rarity.create(op.get_bind(), checkfirst=True)
    op.execute("COMMIT")

    op.add_column("achievement", sa.Column("loot_box_type", box_type, nullable=True))
    op.add_column("achievement", sa.Column("loot_rarity", rarity, nullable=True))
    op.add_column("achievement", sa.Column("no_loot_line", sa.Text(), nullable=True))

    op.create_table(
        "loot_item",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("pool_key", sa.String(40), nullable=False),
        sa.Column("rarity", rarity, nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("generated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("pool_key", "rarity", "title", name="uq_loot_item_title"),
    )
    op.create_index("ix_loot_item_pool", "loot_item", ["pool_key", "rarity"])

    op.create_table(
        "loot_box",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "achievement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("achievement.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("box_type", box_type, nullable=False),
        sa.Column("rarity", rarity, nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("loot_item.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        # One box per achievement per player: the award is the drop.
        sa.UniqueConstraint("user_id", "achievement_id", name="uq_loot_box_once"),
    )
    op.create_index("ix_loot_box_user", "loot_box", ["user_id"])

    op.add_column(
        "user",
        sa.Column(
            "equipped_title_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("loot_item.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    bind = op.get_bind()
    for code, box, tier in ASSIGNMENTS:
        bind.execute(
            sa.text(
                "UPDATE achievement SET loot_box_type = CAST(:b AS loot_box_type), loot_rarity = CAST(:r AS loot_rarity) WHERE code = :c"
            ),
            {"c": code, "b": box, "r": tier},
        )
    for code, line in NO_LOOT_LINES:
        bind.execute(
            sa.text("UPDATE achievement SET no_loot_line = :l WHERE code = :c"),
            {"c": code, "l": line},
        )
    for key, tier, titles in POOLS:
        for title in titles:
            bind.execute(
                sa.text(
                    "INSERT INTO loot_item (id, pool_key, rarity, title) "
                    "VALUES (gen_random_uuid(), :k, CAST(:r AS loot_rarity), :t) "
                    "ON CONFLICT (pool_key, rarity, title) DO NOTHING"
                ),
                {"k": key, "r": tier, "t": title},
            )


def downgrade() -> None:
    op.drop_column("user", "equipped_title_id")
    op.drop_index("ix_loot_box_user", table_name="loot_box")
    op.drop_table("loot_box")
    op.drop_index("ix_loot_item_pool", table_name="loot_item")
    op.drop_table("loot_item")
    op.drop_column("achievement", "no_loot_line")
    op.drop_column("achievement", "loot_rarity")
    op.drop_column("achievement", "loot_box_type")
    op.execute("DROP TYPE IF EXISTS loot_box_type")
    op.execute("DROP TYPE IF EXISTS loot_rarity")
