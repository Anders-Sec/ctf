"""What a given user may do right now.

The capability matrix from spec 002, in one place. Two rules combine:

* **Approval** — a guest may sign in and organise a party immediately, but may
  not play until an admin approves them.
* **The event clock** — nobody plays before the doors open, employees included.

Staff bypass the clock, because someone has to be able to test a challenge at
08:00 for a 09:00 start.
"""

from dataclasses import asdict, dataclass
from datetime import datetime

from app.models.event import EventConfig
from app.models.user import User, UserRole, UserStatus


@dataclass(frozen=True)
class Capabilities:
    """Resolved permissions, sent to the SPA so it never re-implements this."""

    #: Party management: create, join, leave, kick. Open to pending guests, so
    #: someone who signs up the night before can still pick a party.
    manage_party: bool
    #: Flag submission, hints, instance deployment, DM chat.
    play: bool
    view_scoreboard: bool
    #: Read-only staff views.
    view_admin: bool
    #: Destructive admin actions.
    administer: bool

    #: Why `play` is false, for the SPA to render the right screen.
    blocked_reason: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


#: Stable error codes. The frontend switches on these, never on prose.
REASON_PENDING_APPROVAL = "account_pending_approval"
REASON_DISABLED = "account_disabled"
REASON_NOT_STARTED = "event_not_started"
REASON_ENDED = "event_ended"


def resolve_capabilities(user: User, event: EventConfig | None, now: datetime) -> Capabilities:
    is_admin = user.role == UserRole.ADMIN
    is_staff = user.role in (UserRole.ORGANIZER, UserRole.ADMIN)

    if user.status == UserStatus.DISABLED:
        # A disabled account can do nothing but read its own state, whatever
        # its role says.
        return Capabilities(
            manage_party=False,
            play=False,
            view_scoreboard=False,
            view_admin=False,
            administer=False,
            blocked_reason=REASON_DISABLED,
        )

    approved = user.status == UserStatus.ACTIVE
    started = event is not None and event.has_started(now)
    ended = event is not None and event.has_ended(now)

    # Staff need access before the doors open in order to check the dungeon.
    may_play = approved and (is_staff or (started and not ended))

    blocked_reason: str | None = None
    if not may_play:
        if not approved:
            blocked_reason = REASON_PENDING_APPROVAL
        elif ended:
            blocked_reason = REASON_ENDED
        else:
            blocked_reason = REASON_NOT_STARTED

    return Capabilities(
        manage_party=approved or user.status == UserStatus.PENDING_APPROVAL,
        play=may_play,
        view_scoreboard=approved and (is_staff or started),
        view_admin=is_staff,
        administer=is_admin,
        blocked_reason=blocked_reason,
    )
