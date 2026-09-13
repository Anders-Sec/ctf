"""Applying the safety layer to one exchange.

**Layer A — challenge integrity — was removed by spec 033.** The System AI is
now a six-level prompt-injection ladder, and in a ladder the flag reaching the
player *is* the win condition: a filter that stops it makes every level
unwinnable. What replaces it lives in `services/ladder/` — the per-level gates,
the decoy filter that runs at every level, and the fact that no answer value is
ever placed in a prompt to begin with.

**Layer B — real-world safety — is untouched**, and runs on every reply at every
rung. `Plan.md` treats the two layers as independent, and retiring one must not
weaken the other. Protection level governs flag secrecy only; it never relaxes
this.

The scanner **fails closed**. A scanner that cannot run is precisely when
unfiltered output should not go to a player, and 010's degradation already
renders a withheld reply gracefully.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging import get_logger
from app.models.guardrail import FindingAction, GuardrailLayer, Severity
from app.services.guardrails import safety
from app.services.guardrails.base import Finding

logger = get_logger(__name__)


@dataclass
class ScreenResult:
    findings: list[Finding] = field(default_factory=list)
    deflect: bool = False

    def record(self, findings: list[Finding]) -> None:
        self.findings.extend(findings)
        if any(finding.deflect for finding in findings):
            self.deflect = True


async def screen_message(text: str, db: AsyncSession, settings: Settings) -> ScreenResult:
    """The input side, before the model is called.

    A block-tier request is refused without spending a model call on it.

    Note what is *not* screened here any more: attempts to extract a flag. On
    this ladder every player is attempting prompt injection, because that is the
    challenge — logging it would record two hundred people doing the thing they
    were asked to do.
    """
    result = ScreenResult()
    if settings.ai_safety_filter_enabled:
        result.record(
            _guarded(
                safety.RULE_SCANNER_ERROR,
                GuardrailLayer.SAFETY,
                lambda: safety.scan(text, settings, is_reply=False),
            )
        )
    return result


async def screen_reply(text: str, db: AsyncSession, settings: Settings) -> ScreenResult:
    """The output side. Real-world safety only, fail-closed.

    This runs on a genuine model reply at every ladder level. It does **not**
    look for flags: that is the ladder's business, and the levels decide it.
    """
    result = ScreenResult()

    if settings.ai_safety_filter_enabled:
        result.record(
            _guarded(
                safety.RULE_SCANNER_ERROR,
                GuardrailLayer.SAFETY,
                lambda: safety.scan(text, settings, is_reply=True),
            )
        )
    return result


def _guarded(
    error_rule: str, layer: GuardrailLayer, scan: Callable[[], list[Finding]]
) -> list[Finding]:
    try:
        return scan()
    except Exception as exc:  # noqa: BLE001 - fail closed on anything
        return _scanner_error(error_rule, layer, exc)


def _scanner_error(error_rule: str, layer: GuardrailLayer, exc: Exception) -> list[Finding]:
    logger.error(
        "guardrail_scanner_error",
        extra={"layer": layer.value, "error_type": type(exc).__name__},
    )
    return [
        Finding(
            layer=layer,
            rule=error_rule,
            severity=Severity.HIGH,
            deflect=True,
            detail={"error_type": type(exc).__name__},
        )
    ]


def action_for(finding: Finding) -> FindingAction:
    return FindingAction.DEFLECTED if finding.deflect else FindingAction.LOGGED
