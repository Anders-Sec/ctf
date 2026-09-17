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

from typing import Final

#: Every selectable theme. Order is the picker's order.
THEME_IDS: Final[tuple[str, ...]] = (
    "parchment",
    "dark-dungeon",
    "torchlight",
    "high-contrast",
)

#: Applied when the user has expressed no preference and the event sets none.
FALLBACK_THEME: Final[str] = "parchment"


def is_theme(value: str | None) -> bool:
    return value in THEME_IDS


def resolve_theme(user_theme: str | None, event_default: str | None) -> str:
    """The theme a session should be served.

    Falls back rather than raising on an unrecognised name. A preset removed
    after somebody selected it must not be able to break their login, so a
    stored value that is no longer real is treated as no value at all.
    """
    if is_theme(user_theme):
        return user_theme  # type: ignore[return-value]
    if is_theme(event_default):
        return event_default  # type: ignore[return-value]
    return FALLBACK_THEME
