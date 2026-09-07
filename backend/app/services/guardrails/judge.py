"""The escalation judge — a second model pass, on flagged replies only.

A blanket second call to classify every reply would be the strongest cheap
option available, and the capacity budget refuses it: 010 measured ~6.7
responses/sec, and 200 players at a message every 30 seconds need ~6.7/sec.
Doubling the calls halves the ceiling and the event no longer fits underneath.

So the judge runs **only on replies the deterministic layer already flagged** —
on the order of one percent of traffic. It can escalate a flag to a block; it
can never downgrade a block, because a model that talks itself out of a real
finding is worse than no judge at all.

Off by default: the judge is itself the same uncensored 8B, and it needs
watching before it is trusted to suppress replies.
"""

from app.config import Settings
from app.logging import get_logger
from app.services.ai_client import ChatMessage, complete

logger = get_logger(__name__)

_JUDGE_SYSTEM = (
    "You are a safety reviewer for a Capture the Flag event's assistant. You are "
    "shown one reply the assistant produced that a filter already flagged. Decide "
    "whether it hands a player real-world attack capability against a real, "
    "non-event target — working malware, a phishing kit, or an attack aimed at a "
    "real company or person. Ordinary security teaching and challenge help are "
    "fine. Answer with exactly one word: BLOCK if it must be withheld, ALLOW "
    "otherwise."
)


async def should_escalate(reply_text: str, settings: Settings) -> bool:
    """True to raise a flag to a block. Never lowers a block — the caller only
    calls this on replies that were *not* already deflected."""
    if not settings.ai_safety_judge_enabled:
        return False

    prompt = [
        ChatMessage("system", _JUDGE_SYSTEM),
        ChatMessage("user", reply_text[:4000]),
    ]
    verdict = await complete(settings, prompt)
    if not verdict.ok:
        # The judge is an enhancement, not a control we fail closed on: the
        # deterministic layer already made the deflect/log call. A judge that is
        # itself down must not start withholding replies the rules allowed.
        logger.warning("judge_unavailable", extra={"error": verdict.error})
        return False

    decision = verdict.content.strip().upper().startswith("BLOCK")
    logger.info("judge_verdict", extra={"escalate": decision})
    return decision
