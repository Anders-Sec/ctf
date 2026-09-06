"""Answer matching.

A challenge carries any number of answer rules and a submission is correct if
**any** of them matches. Each `MatchType` has a resolver here; adding a type
later is one function plus one enum member, which is the whole reason this is a
registry rather than a chain of comparisons.

Answers are stored in plaintext. Regex and computed answers are a requirement,
and hashing forecloses them; the database is not reachable by players.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import regex

from app.errors import AppError
from app.logging import get_logger
from app.models.challenge import ChallengeAnswer, MatchType
from app.models.play import MAX_SUBMISSION_LENGTH

logger = get_logger(__name__)

#: A pattern written by an admin meeting input written by a player is a
#: denial-of-service waiting to happen. `regex` (unlike `re`) enforces this.
DEFAULT_REGEX_TIMEOUT_MS = 250
MAX_REGEX_TIMEOUT_MS = 2000


class InvalidAnswerRule(AppError):
    """The rule itself is malformed — caught when saving, not when playing."""

    status_code = 422
    code = "invalid_answer_rule"
    message = "That answer rule is not valid."


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    #: Set when a rule could not be evaluated (a regex timeout, say). The player
    #: is told nothing; the admin is told everything.
    error: str | None = None


Resolver = Callable[[str, ChallengeAnswer], MatchResult]

_RESOLVERS: dict[MatchType, Resolver] = {}


def resolver(match_type: MatchType) -> Callable[[Resolver], Resolver]:
    def register(func: Resolver) -> Resolver:
        _RESOLVERS[match_type] = func
        return func

    return register


def normalise(value: str, answer: ChallengeAnswer) -> str:
    """Trim unless a rule explicitly wants raw input.

    Players paste flags out of terminals; a trailing newline should not cost
    them a solve. A rule can opt out where whitespace is genuinely significant.
    """
    if answer.options.get("strip_whitespace", True):
        return value.strip()
    return value


@resolver(MatchType.EXACT)
def _exact(submitted: str, answer: ChallengeAnswer) -> MatchResult:
    return MatchResult(normalise(submitted, answer) == answer.value.strip())


@resolver(MatchType.CASE_INSENSITIVE)
def _case_insensitive(submitted: str, answer: ChallengeAnswer) -> MatchResult:
    return MatchResult(normalise(submitted, answer).casefold() == answer.value.strip().casefold())


@resolver(MatchType.REGEX)
def _regex(submitted: str, answer: ChallengeAnswer) -> MatchResult:
    options = answer.options
    flags = regex.IGNORECASE if options.get("ignore_case") else 0
    timeout = min(int(options.get("timeout_ms", DEFAULT_REGEX_TIMEOUT_MS)), MAX_REGEX_TIMEOUT_MS)

    try:
        compiled = regex.compile(answer.value, flags)
    except regex.error as exc:
        # Should be unreachable: patterns are compiled when saved.
        return MatchResult(False, f"invalid pattern: {exc}")

    candidate = normalise(submitted, answer)
    matcher = compiled.fullmatch if options.get("anchored", True) else compiled.search

    try:
        return MatchResult(matcher(candidate, timeout=timeout / 1000) is not None)
    except TimeoutError:
        # Treated as a non-match, never as an error shown to the player — their
        # answer may well have been right, and our pattern is the problem.
        logger.warning(
            "answer_regex_timeout",
            extra={"answer_id": str(answer.id), "challenge_id": str(answer.challenge_id)},
        )
        return MatchResult(False, "pattern timed out")


@resolver(MatchType.NUMERIC)
def _numeric(submitted: str, answer: ChallengeAnswer) -> MatchResult:
    candidate = _parse_number(normalise(submitted, answer))
    if candidate is None:
        return MatchResult(False)

    options = answer.options
    lower, upper = options.get("min"), options.get("max")
    if lower is not None and candidate < Decimal(str(lower)):
        return MatchResult(False)
    if upper is not None and candidate > Decimal(str(upper)):
        return MatchResult(False)
    if lower is not None or upper is not None:
        # A pure range check: the rule's own value is not the target.
        return MatchResult(True)

    expected = _parse_number(answer.value)
    if expected is None:
        return MatchResult(False, "answer value is not a number")

    tolerance = Decimal(str(options.get("tolerance", 0)))
    if "tolerance_percent" in options:
        tolerance = abs(expected) * Decimal(str(options["tolerance_percent"])) / Decimal(100)

    return MatchResult(abs(candidate - expected) <= tolerance)


def _parse_number(raw: str) -> Decimal | None:
    """Accept the ways a person actually types a number: 1000, 1,000, 1e3."""
    cleaned = raw.strip().replace(",", "").replace(" ", "")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


@resolver(MatchType.SET)
def _set(submitted: str, answer: ChallengeAnswer) -> MatchResult:
    """Multi-part answers — three CVEs, in any order unless ordering is required."""
    options = answer.options
    separator = options.get("separator", ",")
    fold = bool(options.get("case_insensitive", False))

    expected = _split(answer.value, separator, fold)
    candidate = _split(normalise(submitted, answer), separator, fold)

    if options.get("ordered", False):
        return MatchResult(expected == candidate)
    # Sets, not lists: a duplicate entry should not fail an otherwise right answer.
    return MatchResult(set(expected) == set(candidate))


def _split(raw: str, separator: str, fold: bool) -> list[str]:
    parts = [part.strip() for part in raw.split(separator)]
    parts = [part for part in parts if part]
    return [part.casefold() for part in parts] if fold else parts


@resolver(MatchType.ANY_OF)
def _any_of(submitted: str, answer: ChallengeAnswer) -> MatchResult:
    fold = bool(answer.options.get("case_insensitive", False))
    candidate = normalise(submitted, answer)
    if fold:
        candidate = candidate.casefold()

    for alternative in answer.value.splitlines():
        expected = alternative.strip()
        if not expected:
            continue
        if (expected.casefold() if fold else expected) == candidate:
            return MatchResult(True)
    return MatchResult(False)


@dataclass(frozen=True)
class Verdict:
    correct: bool
    matched_answer: ChallengeAnswer | None = None
    #: Rules that could not be evaluated. Admin-facing only.
    errors: tuple[str, ...] = ()


def check(submitted: str, answers: Iterable[ChallengeAnswer]) -> Verdict:
    """Evaluate a submission against every rule until one matches."""
    # Cap before matching, not only before storage: an unbounded string is the
    # other half of the regex denial-of-service.
    candidate = submitted[:MAX_SUBMISSION_LENGTH]
    errors: list[str] = []

    for answer in answers:
        resolve = _RESOLVERS.get(answer.match_type)
        if resolve is None:
            errors.append(f"no resolver for {answer.match_type}")
            continue

        result = resolve(candidate, answer)
        if result.error:
            errors.append(result.error)
        if result.matched:
            return Verdict(True, answer, tuple(errors))

    return Verdict(False, None, tuple(errors))


def validate_rule(match_type: MatchType, value: str, options: dict[str, Any]) -> None:
    """Reject a malformed rule when it is saved rather than mid-event.

    A pattern that fails to compile at 09:00 on event day is a challenge that
    silently rejects every correct answer, which is far worse than a validation
    error in the editor.
    """
    if not value.strip():
        raise InvalidAnswerRule("An answer rule needs a value.")

    if match_type == MatchType.REGEX:
        try:
            regex.compile(value, regex.IGNORECASE if options.get("ignore_case") else 0)
        except regex.error as exc:
            raise InvalidAnswerRule(f"That pattern will not compile: {exc}") from exc

    if match_type == MatchType.NUMERIC:
        has_range = options.get("min") is not None or options.get("max") is not None
        if not has_range and _parse_number(value) is None:
            raise InvalidAnswerRule("A numeric answer needs a number, or a min/max range.")
        if options.get("tolerance") is not None and options.get("tolerance_percent") is not None:
            raise InvalidAnswerRule("Use either tolerance or tolerance_percent, not both.")

    if match_type == MatchType.SET and not _split(value, options.get("separator", ","), False):
        raise InvalidAnswerRule("A set answer needs at least one member.")

    if match_type == MatchType.ANY_OF and not [line for line in value.splitlines() if line.strip()]:
        raise InvalidAnswerRule("Provide at least one alternative, one per line.")


def supported_match_types() -> list[str]:
    return [match_type.value for match_type in _RESOLVERS]
