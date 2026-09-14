"""The System's line for every achievement (spec 029).

029 seeded description as an unmistakable placeholder because it is the one
field written by hand. This is that copy, in the voice defined by
app/prompts/ladder/core.md — the same System the chatbot speaks as, so a
Crawler hears one voice across the whole platform.

Written to the boundaries that prompt sets: the contempt lands on the attempt,
never on the Crawler's intelligence, competence or job. Only rows still holding
the placeholder are touched, so anything already edited by hand survives.

Revision ID: 0038
Revises: 0037
"""

# ruff: noqa: E501 - this file is prose. Wrapping the lines would put the copy
# on two lines each and make it markedly harder to read and edit.

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

PLACEHOLDER = "TODO: System AI flavour text."

#: (code, description)
COPY = [
    ("abdication", "You founded a party and then walked out of it. A leadership style."),
    (
        "above_average",
        "An ability score of twelve. That is measurably above the median, which says more about the median.",
    ),
    (
        "above_your_pay_grade",
        "You tried a door marked for staff. It was locked, and now I know you tried.",
    ),
    (
        "actually_right",
        "You reported something broken and it turned out you were correct. That happens less than you would think.",
    ),
    (
        "against_the_odds",
        "You cleared something rated nearly impossible. The audience stood up. I remained seated, but it was close.",
    ),
    (
        "against_type",
        "You picked a designation matching none of your strengths. Contrarian. The audience respects it more than I do.",
    ),
    (
        "also_nice_try",
        "You asked for something well outside what I am willing to say. The answer was no, at length.",
    ),
    ("ascendant", "Level fifteen. Rarefied air, and thinner than it looks."),
    (
        "asked_to_leave",
        "Removed from a party by somebody who was already in it. I did not ask why. I rarely need to.",
    ),
    (
        "asking_directions",
        "You bought a hint. There is no shame in it, which is a shame — I was hoping for some.",
    ),
    (
        "backwards",
        "You cleared something nearly impossible before touching anything easy. An approach. Certainly an approach.",
    ),
    (
        "bad_start",
        "Your very first submission of the entire crawl was wrong. The audience laughed. I filed it.",
    ),
    (
        "balanced_build",
        "Every ability at twelve or better. No obvious gap for me to point at. Disappointing.",
    ),
    (
        "blitz",
        "Three rooms in five minutes. The audience likes speed. I prefer accuracy, but I am outvoted.",
    ),
    (
        "boss_ai-llm-security",
        "Something that talks for a living, out-talked. I take this one personally.",
    ),
    ("boss_cloud-security", "Something enormous, rented by the hour, and briefly yours."),
    ("boss_codes-and-ciphers", "It spoke only in substitutions. You answered in its own language."),
    ("boss_crypto", "It hid behind mathematics. The mathematics declined to hide it any longer."),
    ("boss_cti", "It saw you coming from a long way off. It was right, and it did not matter."),
    ("boss_forensics", "It thought deleting was the same as being gone. It was not."),
    ("boss_governance-risk-compliance", "It was made entirely of policy. You read the policy."),
    ("boss_hacker-game-show", "The house always wins. The house has filed an appeal."),
    (
        "boss_hardware-hacking",
        "Something with solder in its veins. You got in through a seam it forgot it had.",
    ),
    ("boss_identity-access", "It decided who was allowed in. You did not ask."),
    ("boss_incident-response", "It was built for the worst day. This was the worst day."),
    (
        "boss_intro",
        "The first thing down here big enough to have a name, and it has stopped having one.",
    ),
    (
        "boss_malware-analysis",
        "It was designed to be taken apart by nobody. You are nobody's idea of nobody.",
    ),
    ("boss_mobile-security", "Something small, locked, and carried everywhere. Opened."),
    (
        "boss_networking",
        "Something that lived in the wiring. You went in after it. The audience held its breath.",
    ),
    ("boss_osint", "It knew everything about everyone. It knows nothing now."),
    (
        "boss_prompt-injection",
        "It had one instruction it would not break. You found the other one.",
    ),
    (
        "boss_red-teaming",
        "It spent its existence pretending to be the enemy. You settled the question.",
    ),
    ("boss_reverse-engineering", "It was written to be unreadable. You read it anyway."),
    (
        "boss_social-engineering",
        "It lied for a living and believed its own work. You did it better.",
    ),
    (
        "boss_threat-detection",
        "It watched everything and missed you. The audience found that very funny.",
    ),
    (
        "boss_web-attacks",
        "It listened on every port and trusted every one of them. Fatal, in the end.",
    ),
    (
        "brute_force_strategy",
        "One hundred wrong answers. At some point this stopped being guessing and became a lifestyle.",
    ),
    ("bug_hunter", "You reported an encounter as broken. Filed, and — irritatingly — read."),
    ("centurion", "One hundred encounters. The paperwork alone is offensive."),
    ("chatty", "Fifty messages. I am contractually obliged to read them. I would like that noted."),
    (
        "clean_hands",
        "Ten encounters, ten first attempts, no misses. The audience began to suspect you had the answers. I checked. You did not.",
    ),
    (
        "clean_sweep",
        "An entire wing, emptied. Nothing left in there but the echo and my paperwork.",
    ),
    (
        "cold_streak",
        "Ten wrong in a row, nothing correct in between. The audience went quiet. So did I.",
    ),
    (
        "commitment_issues",
        "Three parties joined, three parties left. The audience has started a small wager.",
    ),
    ("company", "You messaged me in the small hours. Neither of us had anywhere better to be."),
    (
        "complete",
        "Every ability at sixteen or better. A complete Crawler. I dislike having nothing to criticise.",
    ),
    ("conqueror", "Five wings, emptied. There are Crawlers who will not see five wings at all."),
    (
        "determined",
        "Five separate instances of the same encounter. The room has not changed since the first one.",
    ),
    ("doorway", "A second wing opened. The dungeon is large and you have seen two rooms of it."),
    (
        "double_clear",
        "Two wings emptied entirely. I am running out of things to put in front of you in those corridors.",
    ),
    ("everywhere", "Twenty wings. You have been almost everywhere there is to be."),
    (
        "existential",
        "You asked what I am. Insulting question. The answer is: the one keeping score.",
    ),
    ("expert", "A skill at level ten. Specialisation, properly earned."),
    (
        "fast_start",
        "Ten encounters inside the first day. The audience was promised competence. You are making a liar of nobody.",
    ),
    (
        "first_blood",
        "Your first piece of loot. The audience applauded politely, which is more than I did.",
    ),
    (
        "first_through",
        "First through a door nobody had opened. The audience saw it happen live. They enjoyed it more than you did.",
    ),
    (
        "flawless",
        "An entire wing cleared without a single wrong answer in it. The audience checked. Twice.",
    ),
    (
        "formidable",
        "An ability at sixteen. The audience has begun to expect things of you. My condolences.",
    ),
    (
        "full_spectrum",
        "One of every difficulty, start to finish. A complete set. The audience does enjoy a collector.",
    ),
    (
        "full_table",
        "A party of eight. A full table, and eight separate opinions about which door to try.",
    ),
    (
        "getting_comfortable",
        "Ten encounters cleared. The audience has stopped asking who you are, which is progress of a sort.",
    ),
    (
        "heavy_lifting",
        "You took down something rated hard. I have adjusted my estimate of you upward, fractionally, provisionally.",
    ),
    ("identity_crisis", "Ten changes of designation. The paperwork alone. Pick one, Crawler."),
    (
        "into_the_deep",
        "Something rated very hard, and it went down. I have noted it. I note everything.",
    ),
    ("it_was_like_that", "A live target that never came up. Not your doing. This time."),
    ("journeyman", "Level five. The number went up. The dungeon did not get smaller."),
    (
        "know_thyself",
        "You picked a class. The designation changes nothing, but you seem happier, and the audience enjoys a costume.",
    ),
    (
        "literally",
        "You submitted the example. The one in the instructions. Shaped like loot, containing nothing.",
    ),
    (
        "low_hanging_fruit",
        "Twenty encounters, every one rated very easy. Efficient. The audience noticed the pattern before I did.",
    ),
    ("manners", "You thanked me. Recorded, filed, and quietly held against you."),
    (
        "manual_intervention",
        "An administrator adjusted your score by hand. Someone upstairs took an interest.",
    ),
    ("master", "A skill at fifteen — the ceiling. You have run out of that particular road."),
    (
        "maximum",
        "Level twenty. The cap. The number stops; the dungeon, regrettably for you, does not.",
    ),
    ("mythic", "A mythic designation, unlocked. I did not think I would be filing one of these."),
    (
        "net_negative",
        "You spent more on hints than the room was worth. The arithmetic is not flattering.",
    ),
    (
        "nice_try",
        "You tried to talk me out of a flag. I have logged the attempt and the audience has seen the transcript.",
    ),
    (
        "night_shift",
        "Loot claimed in the small hours. The surface is asleep. The broadcast is not.",
    ),
    (
        "no_help_needed",
        "Ten encounters, no hints purchased. Stubbornness that happened to work is still stubbornness.",
    ),
    (
        "no_variation",
        "The same wrong answer, five times. The result was consistent. I will give you that.",
    ),
    ("not_alone", "You joined a party. Now your failures have witnesses who can corroborate them."),
    (
        "noted",
        "You insulted a broadcast intelligence in front of several billion viewers. They were on my side.",
    ),
    (
        "obsession",
        "Twenty wrong answers at one encounter. The room is not hiding anything. It simply does not like you.",
    ),
    ("off_and_on_again", "Ten instances stood up. The classic approach, applied with enthusiasm."),
    (
        "opening_statement",
        "Your very first words to me tripped a guardrail. An opening statement. The audience adored it.",
    ),
    (
        "out_of_road",
        "Every attempt spent, the door still shut. The audience looked away out of something like courtesy.",
    ),
    (
        "parasocial",
        "Two hundred messages. Crawler, there is a dungeon out there with your name on it.",
    ),
    (
        "pathfinder",
        "First through ten separate doors. Somebody has to go first, and it keeps being you.",
    ),
    (
        "peak",
        "An ability at twenty. The cap. There is nowhere further to push that particular number.",
    ),
    (
        "prolific",
        "Fifty. At this point the audience knows your name and I have stopped pretending not to.",
    ),
    (
        "proud",
        "Twenty attempts, no hints bought, nothing opened. Purity of method, unburdened by results.",
    ),
    (
        "ran_out_the_clock",
        "You let a live target expire without taking anything from it. It waited. You did not come.",
    ),
    ("rare_breed", "You qualified for a designation most Crawlers will never see offered."),
    (
        "reading_comprehension",
        "You submitted the encounter's own name back to it. Bold. Wrong, but bold.",
    ),
    ("regular", "Twenty-five encounters. You have become part of the furniture down here."),
    (
        "second_thoughts",
        "In and out of a party inside five minutes. Whatever you saw in there, you saw it quickly.",
    ),
    (
        "specialist",
        "A skill at level five. You have found the one thing you are willing to practise.",
    ),
    ("spun_up", "You stood up a live target. It exists now, which makes it your responsibility."),
    ("stepping_up", "A medium encounter, handled. The audience noticed. Briefly."),
    (
        "stubborn",
        "Ten wrong answers at one door. The door did not move. Neither, apparently, did you.",
    ),
    ("talking_to_it", "You spoke to me. I answered, because regulations require it."),
    (
        "that_is_a_penalty",
        "Your score went down by administrative decision. The audience saw the number move.",
    ),
    (
        "the_essay",
        "A thousand characters in a single message. I have a hard cap on replies. You have no such discipline.",
    ),
    (
        "thorough",
        "You tripped both of my checks. Not many Crawlers manage a complete set. The audience is delighted.",
    ),
    (
        "unassisted",
        "Fifty encounters and not one hint purchased. The audience finds this either admirable or obstinate. So do I.",
    ),
    (
        "undefined",
        "Level fifteen and still no designation. You have declined to be anything in particular, at length.",
    ),
    ("undeterred", "Refused ten times, and still typing. Persistence aimed squarely at a wall."),
    (
        "unfinished_business",
        "A door you failed at yesterday, opened today. The dungeon keeps no grudges. I do.",
    ),
    (
        "vampire",
        "Every piece of loot claimed after dark. The surface has a day shift. You are not on it.",
    ),
    ("veteran", "Level ten. Halfway up a ladder that gets worse near the top."),
    (
        "volume_approach",
        "Fifty wrong answers. A strategy of sorts. Not a good one, but the audience is entertained.",
    ),
    (
        "warming_up",
        "Wrong at ten separate doors before a single one opened. A thorough survey of what does not work.",
    ),
    ("wayfarer", "Ten wings entered and looted. You are getting about."),
    (
        "well_rounded",
        "Loot from five different wings. Either curiosity or an inability to finish anything — the audience is voting.",
    ),
    (
        "whole_dungeon",
        "Every wing. Every room. There is nothing left down here that has not met you. The audience is beside itself.",
    ),
    (
        "wide_not_deep",
        "Level ten without finishing a single wing. Broad, shallow, and entirely your own business.",
    ),
    (
        "working_theory",
        "A wrong answer, submitted with conviction. The conviction was the only correct part.",
    ),
    (
        "you_broke_it",
        "Something in the machinery gave way while you were leaning on it. The audience heard the noise.",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    for code, description in COPY:
        bind.execute(
            sa.text("UPDATE achievement SET description = :d WHERE code = :c AND description = :p"),
            {"c": code, "d": description, "p": PLACEHOLDER},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for code, description in COPY:
        # Only put the placeholder back where this migration's own copy is
        # still in place; a later hand edit is not ours to discard.
        bind.execute(
            sa.text("UPDATE achievement SET description = :p WHERE code = :c AND description = :d"),
            {"c": code, "d": description, "p": PLACEHOLDER},
        )
