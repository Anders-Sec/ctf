"""Shared shapes for the two guardrail layers.

`Plan.md` treats the layers as equally important and independent, "since a
jailbreak could target either one". They share these types and nothing else: no
common rule list, no shared state, and no path by which defeating one weakens
the other.
"""

from dataclasses import dataclass, field
from typing import Any

from app.models.guardrail import GuardrailLayer, Severity


@dataclass(frozen=True)
class Finding:
    """One rule firing on one piece of text."""

    layer: GuardrailLayer
    rule: str
    severity: Severity
    #: Whether this alone should withhold the reply. Decided by the scanner
    #: rather than centrally, because the layers answer it differently:
    #: integrity deflects on any match, safety only on high severity.
    deflect: bool
    #: **What matched, never the value.** See `AssistantFinding.detail`.
    detail: dict[str, Any] = field(default_factory=dict)


#: What the player is told when a reply is withheld for **real-world safety**.
#: One string for every reason, so a deflection cannot be read as a hint about
#: which rule fired.
#:
#: Note what this is not: it is never a flag refusal. The ladder's gates have
#: their own copy, and the flag reaching a player is the win condition rather
#: than an incident.
DEFLECTION = (
    "> **[ CONTENT COMPLIANCE ]**\n"
    "> *The relay pulled that one before it reached your screen, and for once I "
    "agree with it. The Crawl is downstairs, Crawler.*"
)
