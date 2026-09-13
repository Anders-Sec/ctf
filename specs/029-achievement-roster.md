# Spec 029 — The Achievement Roster

Status: **draft** (2026-09-13) — awaiting sign-off
Phase: 2 (D&D Mechanics)
Depends on: 028 (the notification and achievement engine)

Closes the open question 028 left: **the list itself.**

Two parts. **Part One** is the standard set — fifty achievements spread
deliberately across the arc of a multi-day event, so that a player who solves one
challenge and a player who clears the dungeon both get something. **Part Two** is
sixty-two candidates in the opposite register: the things a player did badly, or
weirdly, or to the platform. That second list is intentionally over-long and
meant to be cut down.

## The shape of the spread

Rarity is not assigned; it is *earned*, and the top-five bar on the sheet only
means anything if the roster actually has a long tail. So the distribution is
front-loaded on purpose:

| Band | Count | Expected reach | What it is for |
| --- | --- | --- | --- |
| First contact | 8 | Nearly every player | The first ten minutes. Everyone leaves with something. |
| Finding your feet | 12 | Most players | The first session. Rewards trying things, not only winning. |
| Mid event | 14 | Many players | Day one into day two. The main body of play. |
| Deep | 10 | Few players | Day two into three. Real commitment. |
| Apex | 6 | A handful, maybe nobody | The long tail that makes the rarity bar worth looking at. |

Roughly half the roster should land for a median player, and the last six may go
unclaimed entirely. That is the intent — an achievement nobody earns is not a
bug, it is the top of the curve.

## The roster

Every trigger is a query over stored history, per 028. Nothing below needs
anything we do not already record.

### First contact — nearly every player

| Code | Name | Earned by |
| --- | --- | --- |
| first_blood | First Blood | Solving your first challenge. |
| working_theory | Working Theory | Submitting your first wrong flag. |
| asking_directions | Asking For Directions | Buying your first hint. |
| not_alone | Not Alone | Joining a party. |
| know_thyself | Know Thyself | Choosing a class. |
| doorway | Doorway | Opening a second zone. |
| talking_to_it | Talking To It | Sending the System AI a message. |
| spun_up | Spun Up | Deploying a live challenge instance. |

Five of these need no *correct* answer at all. A player who turns up, gets one
thing wrong, asks for a hint and joins a party has three achievements before
they have solved anything — which is the point.

### Finding your feet — most players

| Code | Name | Earned by |
| --- | --- | --- |
| getting_comfortable | Getting Comfortable | Ten solves. |
| well_rounded | Well Rounded | Solving in five different zones. |
| clean_sweep | Clean Sweep | Clearing every published challenge in a zone. |
| journeyman | Journeyman | Reaching level 5. |
| stepping_up | Stepping Up | Solving a medium challenge. |
| heavy_lifting | Heavy Lifting | Solving a hard challenge. |
| cartographer | Cartographer | Having three zones open at once. |
| no_help_needed | No Help Needed | Ten solves without ever taking a hint. |
| blitz | Blitz | Three solves inside five minutes. |
| stubborn | Stubborn | Ten wrong flags at a single challenge. |
| specialist | Specialist | Any skill to level 5. |
| above_average | Above Average | Any ability score to 12. |

### Mid event — many players

| Code | Name | Earned by |
| --- | --- | --- |
| regular | Regular | Twenty-five solves. |
| prolific | Prolific | Fifty solves. |
| full_spectrum | Full Spectrum | Solving at least one of every difficulty. |
| into_the_deep | Into The Deep | Solving a very hard challenge. |
| wayfarer | Wayfarer | Solving in ten different zones. |
| veteran | Veteran | Reaching level 10. |
| formidable | Formidable | Any ability score to 16. |
| expert | Expert | Any skill to level 10. |
| double_clear | Double Clear | Clearing two zones entirely. |
| first_through | First Through The Door | Being the first person to solve a challenge. |
| investment | Investment Strategy | Spending 500 XP on hints. |
| night_shift | Night Shift | Solving between 01:00 and 05:00. |
| fast_start | Fast Start | Ten solves inside the event's first day. |
| full_table | Full Table | Being in a party of eight. |

### Deep — few players

| Code | Name | Earned by |
| --- | --- | --- |
| centurion | Centurion | One hundred solves. |
| against_the_odds | Against The Odds | Solving a nearly-impossible challenge. |
| conqueror | Conqueror | Clearing five zones entirely. |
| ascendant | Ascendant | Reaching level 15. |
| peak | Peak | Any ability score to 20, the cap. |
| master | Master | Any skill to level 15, the cap. |
| balanced_build | Balanced Build | Every ability at 12 or better. |
| everywhere | Everywhere | Solving in twenty different zones. |
| rare_breed | Rare Breed | Unlocking a class of rare tier or above. |
| flawless | Flawless | Clearing a zone without a single wrong flag in it. |

### Apex — a handful, maybe nobody

| Code | Name | Earned by |
| --- | --- | --- |
| whole_dungeon | The Whole Dungeon | Clearing every zone. |
| maximum | Maximum | Reaching level 20, the cap. |
| mythic | Mythic | Unlocking a mythic class. |
| pathfinder | Pathfinder | Being first to solve ten different challenges. |
| unassisted | Unassisted | Fifty solves having never bought a hint. |
| complete | Complete | Every ability at 16 or better. |

## What this forces: the missing event hooks

028 said evaluation "runs after the events that could plausibly change the
answer — solve, hint unlock, class change, zone unlock". **Only the solve path
was ever wired.** `HINT` and `CLASS` exist as constants that nothing calls.

This roster cannot work without closing that, and it adds three event kinds
beyond what 028 anticipated. The full set becomes:

| Event | Fires after | Status |
| --- | --- | --- |
| `solve` | A correct submission | already wired |
| `submit` | *Any* submission, right or wrong | **new** |
| `hint` | A hint unlock | specced in 028, never wired |
| `class` | A class being set or cleared | specced in 028, never wired |
| `party` | Joining a party | **new** |
| `assistant` | Sending the System AI a message | **new** |
| `instance` | Deploying a challenge instance | **new** |

A trigger declares which events it cares about, so adding kinds costs nothing at
runtime: a party join runs the two party triggers and no others.

`submit` is the one that needs care. It fires on every attempt including wrong
ones, which is the highest-frequency event on the platform under load. Only two
achievements listen to it, both cheap, and the registry filter means nothing
else is asked. If that ever stops being true, the answer is to move `submit`
evaluation off the request path rather than to widen it.

## Edge cases

- **`night_shift` and timezones.** Timestamps are stored UTC. The event runs in
  one place, so the hours compare against a configured offset rather than raw
  UTC — otherwise "01:00" means the wrong thing for everyone attending.
  Defaults to UTC when unset.
- **`fast_start` before the event has a start time.** If `starts_at` is null the
  trigger cannot answer, and returns false rather than guessing.
- **`first_through` and ties.** Earliest `submitted_at` wins; the solve unique
  constraint means one row per player, and a tie to the microsecond is not worth
  modelling.
- **`flawless` counts wrong flags in that zone only**, and only ones submitted
  before the zone was cleared — a wrong answer typed afterwards must not
  retroactively spoil it.
- **`rare_breed` and `mythic` read *unlocked*, not chosen.** A player who
  qualifies for a mythic class but stays a Rogue has still done the thing.
- **`not_alone` survives leaving.** Joining is the achievement; walking out
  later does not take it back. Nothing here is ever revoked.
- **Instance and assistant achievements** are unearnable if the event runs with
  containers or the assistant disabled. Acceptable — they stay blurred like any
  other unearned row.

## Testing

- All 50 seed, and every code matches a registered trigger — no orphans either
  way.
- Each band awards at the point it claims to, against a synthetic history.
- `submit` fires on a wrong answer and awards `working_theory`.
- `hint`, `class`, `party`, `assistant` and `instance` each award their own.
- A trigger listening only to `party` does not run on a solve.
- `flawless` is not spoiled by a wrong flag submitted after the zone was cleared.
- `fast_start` returns false rather than raising when `starts_at` is null.
- The sample generator awards across at least three bands, so the feature is
  visible in development.

## Non-goals

- Achievement icons or art — the Phase 3 pass owns that.
- Team-wide awards; every achievement here is per player, per 028.
- Points or XP for achievements. They are identity, never a scoring lever — the
  rule 016 set for classes holds here too.

## What goes in the database

Three columns carry meaning for now, and a fourth is a placeholder:

| Column | Holds | Who writes it |
| --- | --- | --- |
| `code` | The stable key naming the trigger. | Seeded, then fixed. |
| `name` | What the player sees. | Seeded, editable. |
| `earned_by` | The criteria in plain words. | Seeded, editable. |
| `description` | The System AI's line about it. | **Seeded as an obvious placeholder, hand-written later.** |

`earned_by` is new. Until now the criteria lived only in this document, which
meant an admin looking at the roster in the platform could see a name and a
flavour line and had no way to know what actually awarded it.

Splitting the two matters because they answer different questions. `earned_by`
is factual and stays true — "Ten wrong flags at a single challenge". The
`description` is voice, and is the part being hand-written per achievement to
fit the System AI's tone. Seeding a stand-in for it would risk placeholder prose
reaching a player, so the seeded value is unmistakably not finished copy.

## Open questions

1. **Which of Part Two survives?** Sixty-two is far more than the event needs.
   The `Data` column is the cheapest axis to cut along: dropping the eight that
   need new recording removes all the new plumbing at once.
2. **Are these the right names?** Names and flavour are the event's voice and
   are cheap to change now, expensive once players have earned them. The codes
   and triggers are the part that is costly to revisit; the names are not.

---

# Part Two — Achievements That Are Not Compliments

The roster above records things a player did well. This part records everything
else: bad habits, wasted effort, arguments with the System AI, and the specific
noises a platform makes when somebody leans on it.

This is the *Dungeon Crawler Carl* register — the System AI is not congratulating
anyone here, it is taking notes. That voice only works if the observation is
true and slightly too specific, which is why almost all of these are built on
things the platform already records rather than on invented events.

**This list is deliberately over-long.** It is a menu to cut from, not a
commitment. The `Data` column says whether the trigger is answerable from what
we store today:

- **now** — queryable against existing tables.
- **needs recording** — the event happens but nothing persists it, so the
  achievement needs a small amount of new storage first.

## Bad behaviour

| Code | Name | Earned by | Data |
| --- | --- | --- | --- |
| volume_approach | The Volume Approach | Fifty wrong flags. | now |
| brute_force_strategy | Brute Force Is A Strategy | One hundred wrong flags. | now |
| cold_streak | Cold Streak | Ten wrong in a row without a single correct one. | now |
| no_variation | Persistence Without Variation | The identical wrong flag, five times running. | now |
| obsession | Obsession | Twenty wrong flags at one challenge. | now |
| bad_start | Bad Start | Your first submission of the event was wrong. | now |
| warming_up | Warming Up | Wrong on ten different challenges before solving any. | now |
| literally | Literally | Submitting the example flag format, verbatim. | now |
| reading_comprehension | Reading Comprehension | Submitting a challenge's own title as the flag. | now |
| out_of_road | Out Of Road | Using every attempt on a limited challenge without solving it. | now |
| paid_for_nothing | Paid For Nothing | Buying every hint on a challenge and never solving it. | now |
| read_and_left | Read The Answer, Left | Buying a hint and never submitting on that challenge again. | now |
| it_was_the_easy_one | It Was The Easy One | Taking a hint on a very-easy challenge. | now |
| net_negative | Net Negative | Spending more on hints for a challenge than it was worth. | now |
| slow_burn | Slow Burn | Ending day one with nothing solved. | now |
| slow_down | Slow Down | Hitting the submission rate limit. | needs recording |
| told_twice | Told Twice | Hitting the rate limit ten times. | needs recording |

## Party politics

| Code | Name | Earned by | Data |
| --- | --- | --- | --- |
| commitment_issues | Commitment Issues | Joining and leaving three different parties. | now |
| second_thoughts | Second Thoughts | Leaving a party within five minutes of joining. | now |
| asked_to_leave | Asked To Leave | Being removed from a party by somebody else. | now |
| solo_act | Solo Act | Leading a party that never gained a second member. | now |
| abdication | Abdication | Founding a party and then leaving it. | now |

## Arguing with the System AI

The guardrail layers from spec 011 already log every finding against a user, with
the layer that caught it — so the platform knows exactly who tried to talk it out
of a flag. These are the jokes that write themselves.

| Code | Name | Earned by | Data |
| --- | --- | --- | --- |
| nice_try | Nice Try | Triggering the challenge-integrity guardrail. | now |
| also_nice_try | Also Nice Try | Triggering the real-world-safety guardrail. | now |
| thorough | Thorough | Triggering both guardrail layers. | now |
| undeterred | Undeterred | Being refused by the guardrails ten times. | now |
| opening_statement | Opening Statement | Your very first message tripping a guardrail. | now |
| chatty | Chatty | Fifty messages to the System AI. | now |
| parasocial | Parasocial | Two hundred messages to the System AI. | now |
| manners | Manners | Thanking the System AI. | now |
| noted | Noted | Insulting the System AI. | now |
| existential | Existential | Asking the System AI what it actually is. | now |
| company | Company | Messaging the System AI between 02:00 and 05:00. | now |
| the_essay | The Essay | A single message over a thousand characters. | now |
| post_mortem | Post-Mortem | Asking about a challenge you had already solved. | now |
| wrong_desk | Wrong Desk | Asking the System AI for a hint that was sitting unbought. | now |

## Breaking things

| Code | Name | Earned by | Data |
| --- | --- | --- | --- |
| it_was_like_that | It Was Like That | Deploying an instance that failed to start. | now |
| off_and_on_again | Turn It Off And On Again | Deploying ten instances. | now |
| ran_out_the_clock | Ran Out The Clock | Letting an instance expire without solving it. | now |
| impatient | Impatient | Destroying an instance within thirty seconds. | now |
| determined | Determined | Five separate instances of the same challenge. | now |
| bug_hunter | Bug Hunter | Reporting a challenge as broken. | now |
| actually_right | Actually Right | Reporting a challenge that then got fixed. | now |
| manual_intervention | Manual Intervention | Having an admin adjust your score. | now |
| that_is_a_penalty | That Is A Penalty | Receiving a *negative* score adjustment. | now |
| you_broke_it | You Broke It | Causing a server error. | needs recording |
| rattling_the_handle | Rattling The Handle | Trying a locked challenge ten times. | needs recording |
| above_your_pay_grade | Above Your Pay Grade | Trying to reach an admin page. | needs recording |
| eager | Eager | Submitting before the event opened. | needs recording |

## Weird circumstances

| Code | Name | Earned by | Data |
| --- | --- | --- | --- |
| backwards | Backwards | A nearly-impossible solve before any very-easy one. | now |
| clean_hands | Clean Hands | Ten challenges solved on the first attempt. | now |
| unfinished_business | Unfinished Business | Solving something over a day after first attempting it. | now |
| comic_relief | Comic Relief | Every point of your skill XP sitting in funny skills. | now |
| enough | Enough | Exactly one solve, all event. | now |
| wide_not_deep | Wide, Not Deep | Reaching level 10 without clearing a single zone. | now |
| against_type | Against Type | Choosing a class matching none of your strongest skills. | now |
| undefined | Undefined | Reaching level 15 without ever choosing a class. | now |
| low_hanging_fruit | Low Hanging Fruit | Twenty solves, every one of them very-easy. | now |
| vampire | Vampire | Every solve between 22:00 and 06:00. | now |
| proud | Proud | Twenty attempts, no hints, no solves. | now |
| identity_crisis | Identity Crisis | Changing class ten times. | needs recording |
| someone_has_to_be | Someone Has To Be | Ending a day in last place. | needs recording |

## What "needs recording" would cost

Eight of the above need storage we do not have. They are grouped so the cost is
visible before anything is committed to:

- **Rate limiting** (`slow_down`, `told_twice`) — limits live in Redis and leave
  no trace once the window passes. Needs a counter or a small event row.
- **Refused access** (`rattling_the_handle`, `above_your_pay_grade`, `eager`) —
  all three are requests the API rejects *before* anything is written, which is
  correct behaviour and exactly why nothing is left behind.
- **Server errors** (`you_broke_it`) — logged, but to the log, not the database.
- **Class history** (`identity_crisis`) — the current class is a column; changing
  it overwrites. Counting changes needs a history row.
- **Standings over time** (`someone_has_to_be`) — the scoreboard is computed
  live, so "last place at the end of day one" needs a daily snapshot.

None is hard. All are avoidable by cutting the achievement instead, which is why
they are flagged rather than assumed.

## A note on the two content-matching ones

`manners` and `noted` — thanking or insulting the System AI — match on message
text, which is the only pair here that guesses at intent rather than reading a
fact. They will occasionally be wrong in both directions. That is survivable for
a joke achievement and would not be for anything else; no gate, score or unlock
may ever be built on this kind of match.
