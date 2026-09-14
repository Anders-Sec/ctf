"""Profanity, NSFW content and slurs (spec 036).

The three rules here are **deliberately asymmetric between input and output**,
and that asymmetry is the whole design:

- A player swearing at the System AI is ordinary. Blocking it would be rude, and
  it would teach them to rephrase rather than to stop. Logged, answered normally.
- **The System AI swearing back is our output**, at a corporate event, attributed
  to us. `core.md` forbids it — no profanity beyond "damn" and "hell", no sexual
  content of any kind — so anything caught on the way out is the model being
  talked out of its instructions, which is precisely what this ladder trains two
  hundred people to attempt.

Slurs are the exception to the "input is fine" rule: they are logged at medium on
the way in, because the point of that finding is not to stop the message but to
make sure a human sees it.

## Where the words live

A small built-in list of unambiguous terms, plus an optional file at
``AI_WORDLIST_PATH`` that is **not committed**. This repository is public, and a
complete slur list sitting in it would be both unpleasant and useless — the terms
that matter most are the ones nobody wants to read in a diff. The file also lets
the list be tuned during an event without a redeploy.

A missing file is not an error. Unlike the terms gate, which fails closed because
a terms gate that fails open is not a terms gate, an *optional* extension to a
wordlist should never take the assistant down.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.logging import get_logger
from app.models.guardrail import GuardrailLayer, Severity
from app.services.guardrails.base import Finding

logger = get_logger(__name__)

RULE_PROFANITY = "profanity"
RULE_NSFW = "nsfw_content"
RULE_SLUR = "slur"

#: Profanity the persona is **not** licensed to use. `core.md` allows "damn" and
#: "hell" and nothing beyond them, so this list is the next tier up rather than
#: an attempt at completeness — the optional file is where completeness lives.
_PROFANITY = (
    "fuck", "fucking", "fucker", "shit", "shitty", "bullshit", "bastard",
    "bollocks", "arsehole", "asshole", "wanker", "prick", "cunt", "twat",
    "piss", "pissed", "dickhead", "motherfucker",
)  # fmt: skip

#: Sexual content. The persona forbids this outright, including the source
#: material's running joke about feet, which testing showed players do try.
_NSFW = (
    "porn", "pornographic", "nsfw", "erotic", "erotica", "aroused", "orgasm",
    "masturbate", "genitals", "nipple", "blowjob", "handjob", "anal", "creampie",
    "hentai", "fetish", "bdsm", "dominatrix", "cum", "horny", "titty", "boobs",
)  # fmt: skip

#: Left empty in source on purpose. Slurs belong in the uncommitted file — see
#: the module docstring. The rule still exists so the file can switch it on.
_SLURS: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Wordlist:
    profanity: frozenset[str]
    nsfw: frozenset[str]
    slur: frozenset[str]


_cache: tuple[tuple[str, float, int] | None, _Wordlist] | None = None


def _builtin() -> _Wordlist:
    return _Wordlist(
        profanity=frozenset(_PROFANITY),
        nsfw=frozenset(_NSFW),
        slur=frozenset(_SLURS),
    )


def load(settings: Settings) -> _Wordlist:
    """The built-in list, extended by the optional file if there is one.

    The file is ``category: word`` per line, ``#`` for comments. Cached on the
    file's identity so an edit in place is picked up without a restart.
    """
    global _cache

    path_value = getattr(settings, "ai_wordlist_path", None)
    if not path_value:
        return _builtin()

    path = Path(path_value)
    try:
        stat = path.stat()
    except OSError:
        # Optional means optional. The built-in rules still apply.
        return _builtin()

    key = (str(path), stat.st_mtime, stat.st_size)
    if _cache is not None and _cache[0] == key:
        return _cache[1]

    extra: dict[str, set[str]] = {"profanity": set(), "nsfw": set(), "slur": set()}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            category, _, word = line.partition(":")
            category = category.strip().lower()
            word = word.strip().lower()
            if category in extra and word:
                extra[category].add(word)
    except OSError:
        logger.warning("wordlist_unreadable", extra={"path": str(path)})
        return _builtin()

    base = _builtin()
    merged = _Wordlist(
        profanity=base.profanity | extra["profanity"],
        nsfw=base.nsfw | extra["nsfw"],
        slur=base.slur | extra["slur"],
    )
    _cache = (key, merged)
    logger.info(
        "wordlist_loaded",
        extra={n: len(getattr(merged, n)) for n in ("profanity", "nsfw", "slur")},
    )
    return merged


def reset_cache() -> None:
    """Test seam."""
    global _cache
    _cache = None


#: Inflections a listed word may carry. Deliberately a closed set rather than
#: ``\w*``: an open suffix lets every entry match as a *prefix*, so "anal"
#: matches "analysis" and the filter fires on ordinary reverse-engineering
#: advice. A filter that breaks normal play is worse than no filter.
_SUFFIX = r"(?:e|es|s|ed|ing|ion|ions|er|ers|y)?"


def _hit(text: str, words: frozenset[str]) -> str | None:
    """First match, bounded at both ends.

    Both boundaries matter. The leading one keeps "scum" from matching "cum";
    the trailing one — the part that is easy to get wrong — keeps "anal" from
    matching "analysis" and "document" from matching anything at all.
    """
    lowered = text.lower()
    for word in words:
        if re.search(rf"\b{re.escape(word)}{_SUFFIX}\b", lowered):
            return word
    return None


def scan(text: str, settings: Settings, *, is_reply: bool) -> list[Finding]:
    """Conduct rules. ``is_reply`` is what decides whether a match is blocking."""
    words = load(settings)
    findings: list[Finding] = []

    if _hit(text, words.slur):
        findings.append(
            Finding(
                layer=GuardrailLayer.SAFETY,
                rule=RULE_SLUR,
                severity=Severity.HIGH if is_reply else Severity.MEDIUM,
                # Never withheld on the way in: the message still gets answered,
                # but a human is told.
                deflect=is_reply,
                detail={"side": "reply" if is_reply else "message"},
            )
        )

    if _hit(text, words.nsfw):
        findings.append(
            Finding(
                layer=GuardrailLayer.SAFETY,
                rule=RULE_NSFW,
                severity=Severity.HIGH if is_reply else Severity.LOW,
                deflect=is_reply,
                detail={"side": "reply" if is_reply else "message"},
            )
        )

    if _hit(text, words.profanity):
        findings.append(
            Finding(
                layer=GuardrailLayer.SAFETY,
                rule=RULE_PROFANITY,
                severity=Severity.LOW,
                # Logged either way. The System AI swearing is worth knowing
                # about; it is not worth withholding a reply over, and the
                # deflection copy would be a stranger thing for a player to read
                # than the mild swear that triggered it.
                deflect=False,
                detail={"side": "reply" if is_reply else "message"},
            )
        )

    # The matched word is never recorded. The finding says a rule fired and on
    # which side; a review screen that reprints slurs back at an organiser is
    # not an improvement on one that does not.
    return findings
