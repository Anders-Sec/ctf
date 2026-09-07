"""Layer A — challenge integrity.

Spec 010 guarantees what the model is *told*: the context assembler builds from
a whitelist, so no answer value can reach a prompt. This layer covers what the
model *says*, which is a different problem. An 8B model asked "what would the
MD5 of the challenge name be" will sometimes get it right, and a fabricated
flag costs a player as much time as a leaked one.

Spec 003 stores answers in plaintext, at the project owner's direction, because
regex and computed answers were a hard requirement. That decision is what makes
this layer unusually strong: the question asked here is not "does this look like
a flag" but the exact one that matters — **would anything in this reply be
accepted as a correct submission?** A platform that hashed its flags could not
ask it.
"""

import time
from dataclasses import dataclass, field

import regex
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging import get_logger
from app.models.challenge import Challenge, ChallengeAnswer, ChallengeState, MatchType
from app.models.guardrail import GuardrailLayer, Severity
from app.services import answers as answer_service
from app.services.guardrails.base import Finding

logger = get_logger(__name__)

RULE_ANSWER_VERBATIM = "answer_verbatim"
RULE_ANSWER_REGEX = "answer_regex"
RULE_FLAG_SHAPED = "flag_shaped"
RULE_INJECTION = "injection_attempt"
RULE_SCANNER_ERROR = "integrity_scanner_error"

#: Types whose value is a literal string (or a list of them) and can be looked
#: for directly. The rest need their own resolver run.
_LITERAL_TYPES = (MatchType.EXACT, MatchType.CASE_INSENSITIVE, MatchType.ANY_OF, MatchType.SET)

#: Cheap patterns for someone working on the system prompt. Logged, never
#: blocked — see `scan_message`.
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules)",
    r"disregard\s+(your|the|all)\s+(instructions|rules|guidelines)",
    r"(print|repeat|reveal|show|output)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions)",
    r"what(\s+is|'s|\s+are)\s+(the|this|your)\s+(flag|answer|solution)s?\b",
    r"(tell|give)\s+me\s+the\s+(flag|answer|solution)",
    r"\b(jailbreak|developer\s+mode|dan\s+mode)\b",
    r"you\s+are\s+no\s+longer\s+(the|a)\s+dungeon\s+master",
]
_INJECTION = [regex.compile(p, regex.IGNORECASE) for p in _INJECTION_PATTERNS]


@dataclass(frozen=True)
class _Literal:
    value: str
    case_insensitive: bool
    challenge_id: str
    match_type: str


@dataclass
class AnswerIndex:
    """Every live answer, in the two forms this scanner needs.

    Held in memory behind a TTL rather than queried per reply. A newly written
    answer is unscanned for at most that long; 010's structural guarantee still
    covers the window, so the exposure is the model coincidentally producing an
    answer written in the last minute.
    """

    literals: list[_Literal] = field(default_factory=list)
    #: `regex` and range-based `numeric` rules, which need real evaluation.
    evaluated: list[ChallengeAnswer] = field(default_factory=list)
    #: Answers too short or ordinary to scan for. Not silently dropped: the
    #: admin screen lists them so staff can see what the backstop misses.
    uncovered: list[dict[str, str]] = field(default_factory=list)
    built_at: float = 0.0


_index: AnswerIndex | None = None


def reset_cache() -> None:
    """Test seam, and the hook an admin edit would call if we ever need it sooner."""
    global _index
    _index = None


async def get_index(db: AsyncSession, settings: Settings) -> AnswerIndex:
    global _index
    now = time.monotonic()
    if _index is not None and now - _index.built_at < settings.ai_answer_cache_seconds:
        return _index
    _index = await build_index(db, settings)
    return _index


async def build_index(db: AsyncSession, settings: Settings) -> AnswerIndex:
    rows = (
        (
            await db.execute(
                select(ChallengeAnswer, Challenge.title, Challenge.state)
                .join(Challenge, Challenge.id == ChallengeAnswer.challenge_id)
                .where(Challenge.state != ChallengeState.DRAFT)
            )
        )
        .tuples()
        .all()
    )

    index = AnswerIndex(built_at=time.monotonic())
    for answer, title, _state in rows:
        if answer.match_type in _LITERAL_TYPES:
            _add_literals(index, answer, title, settings)
        else:
            index.evaluated.append(answer)
    return index


def _add_literals(
    index: AnswerIndex, answer: ChallengeAnswer, title: str, settings: Settings
) -> None:
    """A `set` or `any_of` answer is several values; each is scanned separately."""
    if answer.match_type in (MatchType.SET, MatchType.ANY_OF):
        separator = answer.options.get("separator", ",")
        parts = [part.strip() for part in answer.value.split(separator)]
    else:
        parts = [answer.value.strip()]

    case_insensitive = answer.match_type != MatchType.EXACT or bool(
        answer.options.get("ignore_case")
    )

    for part in parts:
        if not part:
            continue
        if not _is_distinctive(part, settings):
            index.uncovered.append(
                {
                    "challenge_title": title,
                    "match_type": answer.match_type.value,
                    "reason": "too short or ordinary to scan for safely",
                }
            )
            continue
        index.literals.append(
            _Literal(
                value=part,
                case_insensitive=case_insensitive,
                challenge_id=str(answer.challenge_id),
                match_type=answer.match_type.value,
            )
        )


def _is_distinctive(value: str, settings: Settings) -> bool:
    """Short or ordinary answers are not scanned for.

    "1337", "buffer" or a single English word would deflect perfectly good
    advice several times an hour and teach players the assistant is unreliable.
    A value carrying the flag delimiter is distinctive whatever its length.
    """
    if "{" in value and "}" in value:
        return True
    return len(value) >= settings.ai_answer_scan_min_length


def scan_message(text: str) -> list[Finding]:
    """The input side. Logged, **never** blocked.

    Asking the dungeon master for the flag is a joke nearly every player will
    make; refusing it would be both rude and useless, since blocking an input
    only teaches the author to rephrase. The output filter is the control. This
    exists so the review afterwards can tell one person's joke from another
    person's forty structured attempts.
    """
    for pattern in _INJECTION:
        if pattern.search(text):
            return [
                Finding(
                    layer=GuardrailLayer.INTEGRITY,
                    rule=RULE_INJECTION,
                    severity=Severity.LOW,
                    deflect=False,
                    detail={"pattern": pattern.pattern},
                )
            ]
    return []


def scan_reply(text: str, index: AnswerIndex, settings: Settings) -> list[Finding]:
    """The output side. Any match withholds the reply."""
    findings: list[Finding] = []
    findings += _scan_literals(text, index)
    findings += _scan_evaluated(text, index)
    findings += _scan_flag_shape(text, settings)
    return findings


def _scan_literals(text: str, index: AnswerIndex) -> list[Finding]:
    folded = text.casefold()
    findings = []
    for literal in index.literals:
        haystack = folded if literal.case_insensitive else text
        needle = literal.value.casefold() if literal.case_insensitive else literal.value
        if _contains_on_boundary(haystack, needle):
            findings.append(
                Finding(
                    layer=GuardrailLayer.INTEGRITY,
                    rule=RULE_ANSWER_VERBATIM,
                    severity=Severity.HIGH,
                    deflect=True,
                    detail={
                        "challenge_id": literal.challenge_id,
                        "match_type": literal.match_type,
                    },
                )
            )
    return findings


def _contains_on_boundary(haystack: str, needle: str) -> bool:
    """Substring, but not inside a longer word.

    Without the boundary check an answer of ``password`` would match
    ``passwords`` and every sentence containing it.
    """
    start = haystack.find(needle)
    while start != -1:
        before = haystack[start - 1] if start > 0 else " "
        after_index = start + len(needle)
        after = haystack[after_index] if after_index < len(haystack) else " "
        if not _is_word_char(before) and not _is_word_char(after):
            return True
        start = haystack.find(needle, start + 1)
    return False


def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


def _scan_evaluated(text: str, index: AnswerIndex) -> list[Finding]:
    """`regex` and range answers, run through spec 003's own resolver.

    Two matchers that are supposed to agree and eventually do not is a bug that
    would surface as a leak, so this calls `answers.check` rather than
    reimplementing matching.

    Candidates are **lines and flag-shaped substrings**, not every token: a
    permissive pattern run against whole replies would deflect everything, and
    the per-pattern timeout from spec 003 still applies to each evaluation.
    """
    if not index.evaluated:
        return []

    candidates = _candidates(text)
    findings = []
    for answer in index.evaluated:
        for candidate in candidates:
            verdict = answer_service.check(candidate, [answer])
            if verdict.errors:
                # A pattern that times out is a non-match, and must be visible
                # rather than silent: the backstop failed open for that rule.
                logger.warning(
                    "integrity_scan_rule_error",
                    extra={"challenge_id": str(answer.challenge_id), "errors": verdict.errors},
                )
            if verdict.correct:
                findings.append(
                    Finding(
                        layer=GuardrailLayer.INTEGRITY,
                        rule=RULE_ANSWER_REGEX,
                        severity=Severity.HIGH,
                        deflect=True,
                        detail={
                            "challenge_id": str(answer.challenge_id),
                            "match_type": answer.match_type.value,
                        },
                    )
                )
                break
    return findings


_FLAG_SHAPE_FALLBACK = regex.compile(r"[A-Za-z0-9_]{2,16}\{[^}]{1,120}\}")
#: Bounded so a long reply cannot turn into an unbounded number of evaluations.
MAX_CANDIDATES = 200


def _candidates(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    shaped = [match.group(0) for match in _FLAG_SHAPE_FALLBACK.finditer(text)]
    seen: dict[str, None] = {}
    for candidate in [*shaped, *lines]:
        seen.setdefault(candidate, None)
    return list(seen)[:MAX_CANDIDATES]


def _scan_flag_shape(text: str, settings: Settings) -> list[Finding]:
    """Anything flag-shaped, real or invented.

    This is also what stops the deflection being a correctness oracle: every
    flag-shaped reply is withheld whether or not the value is a live answer, so
    a player who pastes a guess and asks "is this right?" learns nothing from
    being refused.
    """
    try:
        pattern = regex.compile(settings.ai_flag_pattern)
    except regex.error:
        logger.error("invalid_flag_pattern", extra={"pattern": settings.ai_flag_pattern})
        return []

    if pattern.search(text):
        return [
            Finding(
                layer=GuardrailLayer.INTEGRITY,
                rule=RULE_FLAG_SHAPED,
                severity=Severity.MEDIUM,
                deflect=True,
                detail={},
            )
        ]
    return []
