"""The System AI's voice for narrated game mechanics (spec 016).

Deterministic persona copy — **not** a model call. When a game event wants the
System AI (spec 013) to say something (the first is the suggested-class nudge),
it comes through here: one place, so the coming narrative overhaul can own and
restyle every narrated line without touching the callers.

Persona rules from spec 013: terse, dry, plain text (no markdown), real security
terms over adventure-game metaphor.
"""


def class_suggestion(reason: str, class_name: str) -> str:
    """The System AI noting a player's pattern and naming the archetype that fits.

    ``reason`` is what the player has been doing — a skill name, or an ability
    rendered as a phrase (spec 024 lets a class point at either).

    Deterministic: the same (reason, class) always yields the same line, so it
    can be asserted without a model in the loop.
    """
    return (
        f"You keep hammering {reason} problems. "
        f"The {class_name} build fits the pattern — take it or don't."
    )


# --- Notification copy (spec 028) ------------------------------------------
# Every line the System AI says to a player lives here, so the coming narrative
# pass can restyle all of it without touching a caller. Deterministic templates,
# never a model call: no latency, no token cost, no guardrail surface, and no
# path for a challenge answer to reach a prompt.


def achievement_earned(name: str, description: str) -> str:
    return f"Logged: {name}. {description} Noted, for whatever that is worth."


def class_unlocked(class_name: str) -> str:
    return (
        f"You have done enough to qualify as {class_name}. "
        "The designation is available on your sheet. Take it or don't."
    )


def zone_unlocked(zone_name: str) -> str:
    return (
        f"{zone_name} is open. Something in there was waiting for someone with "
        "your particular set of bad habits."
    )


def level_up(level: int) -> str:
    return f"Level {level}. The number went up. The dungeon did not get easier."


def ability_milestone(ability_name: str, score: int) -> str:
    return (
        f"{ability_name} is at {score}. That is measurably above average, "
        "which says more about the average than about you."
    )


# --- Broadcast copy (spec 032) ---------------------------------------------


def boss_first_kill(player_name: str, boss_title: str, zone_name: str) -> str:
    return (
        f"{player_name} put down {boss_title} in {zone_name}. "
        "First one through. The rest of you are welcome to try."
    )


def daily_dispatch(day: int, solves: int, bosses_down: int, zones_open: int) -> str:
    """The state of the dungeon, same text for everyone."""
    return (
        f"Day {day}. {solves} challenges cleared across the dungeon, "
        f"{bosses_down} {'boss' if bosses_down == 1 else 'bosses'} down, "
        f"{zones_open} {'wing' if zones_open == 1 else 'wings'} open. "
        "Carry on."
    )
