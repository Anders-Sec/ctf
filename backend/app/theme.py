"""The theme roster (spec 048).

Ids only. Every colour value lives in ``frontend/src/theme/themes.css``, which
is the single source of truth for what a theme looks like; the backend needs
only to know which names are real so it can refuse to store a preference that
would render as nothing.

``frontend/src/theme/themes.test.ts`` asserts this list matches
``frontend/src/theme/themes.ts``. A theme present on one side and not the other
is the failure mode that keeping two lists creates, so it is tested rather than
trusted.
"""

from dataclasses import dataclass
from typing import Final

#: Every theme. Order is display order.
#:
#: The last three are secret (spec 048 §10.1): the everyday light/dark toggle
#: does not offer them, and how a player comes to hold one is deliberately
#: undecided. An admin may assign any of them today.
THEME_IDS: Final[tuple[str, ...]] = (
    "parchment",
    "dark-dungeon",
    "high-contrast",
    "purple-squirrel",
    "dnd",
    "mr-anderson",
)

#: Applied when the user has expressed no preference and the event sets none.
FALLBACK_THEME: Final[str] = "parchment"

#: The accessibility switch. Not an entry in any list of looks — it overrides
#: whatever theme is selected while it is on, which is why it is stored as its
#: own flag rather than as a theme choice.
HIGH_CONTRAST_THEME: Final[str] = "high-contrast"


@dataclass(frozen=True)
class Theme:
    id: str
    #: Not offered by the light/dark toggle, and grantable (spec 058 §5). The
    #: everyday themes are already everyone's, so handing one over is not a
    #: reward.
    secret: bool = False


#: The roster with the one property the backend needs to reason about. Labels
#: and colours stay on the frontend; ``themes.test.ts`` asserts the two lists
#: agree, secret flags included.
THEMES_BY_ID: Final[dict[str, Theme]] = {
    "parchment": Theme("parchment"),
    "dark-dungeon": Theme("dark-dungeon"),
    "high-contrast": Theme("high-contrast"),
    "purple-squirrel": Theme("purple-squirrel", secret=True),
    "dnd": Theme("dnd", secret=True),
    "mr-anderson": Theme("mr-anderson", secret=True),
}


def is_secret(theme: str | None) -> bool:
    entry = THEMES_BY_ID.get(theme or "")
    return bool(entry and entry.secret)


def is_theme(value: str | None) -> bool:
    return value in THEME_IDS


def resolve_theme(
    user_theme: str | None,
    event_default: str | None,
    high_contrast: bool = False,
    unlocked: set[str] | frozenset[str] | list[str] | None = None,
) -> str:
    """The theme a session should be served.

    High contrast is a second axis rather than a third theme: while it is on it
    wins outright, and the underlying choice is left untouched so that turning
    it off returns the player to the side of the toggle they were on.

    Falls back rather than raising in two cases, both of which have to degrade
    because this is read on every session load:

    - a name that is **no longer a theme** — a preset removed after somebody
      selected it;
    - a secret theme the player **no longer holds** (spec 058 §5.1). An admin
      revoking a grant needs no cleanup on ``user.theme`` because of this: the
      next load simply stops honouring it.

    ``unlocked`` is what the player holds. Passing nothing means "unknown", and
    a secret theme is then honoured — the callers that cannot cheaply look it up
    should not silently downgrade somebody.
    """
    if high_contrast:
        return HIGH_CONTRAST_THEME

    if is_theme(user_theme) and not (
        unlocked is not None and is_secret(user_theme) and user_theme not in unlocked
    ):
        return user_theme  # type: ignore[return-value]
    if is_theme(event_default):
        return event_default  # type: ignore[return-value]
    return FALLBACK_THEME
