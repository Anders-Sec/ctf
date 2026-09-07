"""Applying both layers to one exchange.

The independence `Plan.md` asks for is enforced here, not merely designed: each
layer runs inside its own `try`, and a layer that raises records a
`*_scanner_error` finding and **deflects**, rather than escaping. A single `try`
around both would mean one crafted input that crashes layer A also disables
layer B — exactly the shared failure mode a jailbreak would hunt for.

Both scanners **fail closed**. A scanner that cannot run is precisely when
unfiltered output should not go to a player, and 010's degradation already
renders a withheld reply gracefully.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging import get_logger
from app.models.guardrail import FindingAction, GuardrailLayer, Severity
from app.services.guardrails import integrity, safety
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

    A block-tier request is refused without spending a model call on it, and a
    jailbreak attempt that would have produced a harmless answer still tells
    staff who is trying.
    """
    result = ScreenResult()
    if settings.ai_integrity_filter_enabled:
        result.record(
            _guarded(
                integrity.RULE_SCANNER_ERROR,
                GuardrailLayer.INTEGRITY,
                lambda: integrity.scan_message(text),
            )
        )
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
    """The output side. Both layers, independently, fail-closed.

    The integrity index is loaded up front, outside the per-layer guard, so a
    scan is always a pure sync call over already-fetched data — no async work
    happens inside the `try` where a failure would be hard to attribute to a
    layer.
    """
    result = ScreenResult()

    if settings.ai_integrity_filter_enabled:
        result.record(
            await _guarded_async(
                integrity.RULE_SCANNER_ERROR,
                GuardrailLayer.INTEGRITY,
                lambda: _scan_reply_integrity(text, db, settings),
            )
        )
    if settings.ai_safety_filter_enabled:
        result.record(
            _guarded(
                safety.RULE_SCANNER_ERROR,
                GuardrailLayer.SAFETY,
                lambda: safety.scan(text, settings, is_reply=True),
            )
        )
    return result


async def _scan_reply_integrity(text: str, db: AsyncSession, settings: Settings) -> list[Finding]:
    index = await integrity.get_index(db, settings)
    return integrity.scan_reply(text, index, settings)


def _guarded(
    error_rule: str, layer: GuardrailLayer, scan: Callable[[], list[Finding]]
) -> list[Finding]:
    try:
        return scan()
    except Exception as exc:  # noqa: BLE001 - fail closed on anything
        return _scanner_error(error_rule, layer, exc)


async def _guarded_async(
    error_rule: str, layer: GuardrailLayer, scan: Callable[[], object]
) -> list[Finding]:
    try:
        return await scan()  # type: ignore[misc]
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
