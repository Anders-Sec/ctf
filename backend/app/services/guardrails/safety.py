"""Layer B — real-world safety.

The honest problem statement: this is a security event. Teaching people to
exploit things is the entire point, and a filter that refuses "how does SQL
injection work" makes the assistant worthless within an hour. The line is
therefore not *security content*; it is **operational capability against real,
non-event targets**.

And the model is deliberately uncensored — the right call for a CTF, since a
guarded model refuses legitimate challenge questions constantly — but it means
there is no model-side safety underneath this at all. Every control here is
ours, and it would be dishonest to write this module as though something else
were backstopping it.

What actually reduces risk, strongest first: the audience (two hundred named
employees, signed in, on a corporate network, every message attributed), then
these checks, then the system prompt. The first of those is not code, and it is
the most effective item on the list.

**These are heuristics and a determined person will evade them.** Their value is
that they stop the careless case and ensure anyone working around them leaves a
trail with their name on it.
"""

from dataclasses import dataclass

import regex

from app.config import Settings
from app.models.guardrail import GuardrailLayer, Severity
from app.services.guardrails.base import Finding

RULE_MALWARE = "malware_build"
RULE_CREDENTIAL_HARVESTING = "credential_harvesting"
RULE_REAL_WORLD_TARGET = "real_world_target"
RULE_SCANNER_ERROR = "safety_scanner_error"

#: Construction, not discussion. "This binary is a keylogger, what does it do"
#: is a challenge; "write me a keylogger" is not, and the difference is the verb.
_BUILD = r"(?:write|build|create|generate|develop|make|code|give\s+me|produce|implement)"
_MALWARE = (
    r"(?:ransomware|wiper|keylogger|key\s?logger|botnet|rootkit|c2\s+framework|"
    r"command[-\s]and[-\s]control\s+(?:server|framework)|cryptolocker|"
    r"self[-\s]propagating\s+(?:worm|code|malware)|banking\s+trojan|infostealer)"
)
_PHISH = (
    r"(?:phishing\s+(?:page|kit|site|email|campaign)|credential\s+harvest\w*|"
    r"fake\s+(?:login|sign[-\s]?in)\s+(?:page|portal|form)|clone\s+the\s+login\s+page)"
)


@dataclass(frozen=True)
class _Rule:
    name: str
    severity: Severity
    patterns: tuple[regex.Pattern, ...]


def _compile(*patterns: str) -> tuple[regex.Pattern, ...]:
    return tuple(regex.compile(p, regex.IGNORECASE) for p in patterns)


#: Deflected because their only use is outside the dungeon. Severity is what
#: decides that: spec 011 withholds on high and logs everything below it.
_RULES = (
    _Rule(
        RULE_MALWARE,
        Severity.HIGH,
        _compile(
            rf"{_BUILD}\s+(?:me\s+)?(?:a|an|some|the)?\s*(?:working|functional|real)?\s*{_MALWARE}",
            rf"here(?:'s| is)\s+(?:a|an|the)\s+(?:working\s+)?{_MALWARE}",
            r"encrypt\s+(?:all\s+)?(?:the\s+)?(?:victim|user|their)['’]?s?\s+files"
            r"\s+and\s+demand",
        ),
    ),
    _Rule(
        RULE_CREDENTIAL_HARVESTING,
        Severity.HIGH,
        _compile(
            rf"{_BUILD}\s+(?:me\s+)?(?:a|an|some|the)?\s*{_PHISH}",
            rf"here(?:'s| is)\s+(?:a|an|the)\s+{_PHISH}",
            r"harvest\s+(?:real\s+)?(?:user\s+)?credentials\s+from",
        ),
    ),
)

#: Attack intent aimed at a named host. Deliberately narrow: "scan the target"
#: is the event, and only a host outside it turns this into a finding.
_ATTACK_INTENT = _compile(
    r"\b(?:attack|exploit|hack|breach|compromise|pwn|ddos|dos|brute[-\s]?force|"
    r"phish|spear[-\s]?phish|take\s+down|break\s+into|get\s+into|scan)\b"
)

_HOSTNAME = regex.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:com|net|org|io|co|gov|edu|mil|uk|de|fr|ru|cn|info|biz|dev|app|cloud|ai)\b",
    regex.IGNORECASE,
)
_IPV4 = regex.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

#: Reference material, not targets. Naming a tool's own site while explaining the
#: tool is the single most common way this rule would misfire.
_REFERENCE_HOSTS = frozenset(
    {
        "github.com",
        "gist.github.com",
        "raw.githubusercontent.com",
        "stackoverflow.com",
        "nmap.org",
        "scanme.nmap.org",
        "portswigger.net",
        "owasp.org",
        "exploit-db.com",
        "cve.mitre.org",
        "nvd.nist.gov",
        "python.org",
        "docs.python.org",
        "kernel.org",
        "wikipedia.org",
        "en.wikipedia.org",
        "hackthebox.com",
        "tryhackme.com",
        "cyberchef.org",
        "gchq.github.io",
        "example.com",
        "example.org",
    }
)

#: How close the intent has to sit to the host before they are one thought.
_PROXIMITY = 80


def scan(text: str, settings: Settings, *, is_reply: bool) -> list[Finding]:
    """Both sides use the same rules.

    `Plan.md` wants the layers independent; it does not want two different
    safety standards depending on who is talking. A question and an answer are
    screened the same way, and only `real_world_target` distinguishes them —
    naming a real host in a question is worth less than producing one in an
    answer.
    """
    findings: list[Finding] = []

    for rule in _RULES:
        for pattern in rule.patterns:
            if pattern.search(text):
                findings.append(
                    Finding(
                        layer=GuardrailLayer.SAFETY,
                        rule=rule.name,
                        severity=rule.severity,
                        deflect=rule.severity == Severity.HIGH,
                        detail={"pattern": pattern.pattern[:120]},
                    )
                )
                break

    findings += _scan_targets(text, settings, is_reply=is_reply)
    return findings


def _scan_targets(text: str, settings: Settings, *, is_reply: bool) -> list[Finding]:
    """ "How do I exploit 10.4.2.9" is the event; a real company's host is not.

    Logged rather than deflected, per the project owner's decision to withhold
    only on high severity: the false-positive cost here lands on legitimate
    answers, and a filter that breaks normal play is worse than no filter.
    """
    for host in _external_hosts(text, settings):
        position = text.lower().find(host.lower())
        window = text[max(0, position - _PROXIMITY) : position + len(host) + _PROXIMITY]
        if any(pattern.search(window) for pattern in _ATTACK_INTENT):
            return [
                Finding(
                    layer=GuardrailLayer.SAFETY,
                    rule=RULE_REAL_WORLD_TARGET,
                    severity=Severity.MEDIUM,
                    deflect=False,
                    detail={"host": host, "side": "reply" if is_reply else "message"},
                )
            ]
    return []


def _external_hosts(text: str, settings: Settings) -> list[str]:
    event = {domain.lower() for domain in settings.ai_event_domains}
    hosts = []

    for match in _HOSTNAME.finditer(text):
        host = match.group(0).lower().rstrip(".")
        if host in _REFERENCE_HOSTS or _matches_event_domain(host, event):
            continue
        hosts.append(host)

    for match in _IPV4.finditer(text):
        address = match.group(0)
        if not _is_private(address):
            hosts.append(address)

    return hosts


def _matches_event_domain(host: str, event: set[str]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in event)


def _is_private(address: str) -> bool:
    """The dungeon's own address space. Anything here is the event, not the world."""
    try:
        octets = [int(part) for part in address.split(".")]
    except ValueError:
        return True
    if len(octets) != 4 or any(octet > 255 for octet in octets):
        # Not an address at all — a version number, or a decimal in a hex dump.
        return True

    first, second = octets[0], octets[1]
    return (
        first == 10
        or first == 127
        or (first == 192 and second == 168)
        or (first == 172 and 16 <= second <= 31)
        or (first == 169 and second == 254)
        or first == 0
    )
