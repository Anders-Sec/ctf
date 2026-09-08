"""The System AI's voice for narrated game mechanics (spec 016).

Deterministic persona copy — **not** a model call. When a game event wants the
System AI (spec 013) to say something (the first is the suggested-class nudge),
it comes through here: one place, so the coming narrative overhaul can own and
restyle every narrated line without touching the callers.

Persona rules from spec 013: terse, dry, plain text (no markdown), real security
terms over adventure-game metaphor.
"""


def class_suggestion(skill_name: str, class_name: str) -> str:
    """The System AI noting a player's pattern and naming the archetype that fits.

    Deterministic: the same (skill, class) always yields the same line, so it can
    be asserted without a model in the loop.
    """
    return (
        f"You keep hammering {skill_name} problems. "
        f"The {class_name} build fits the pattern — take it or don't."
    )
