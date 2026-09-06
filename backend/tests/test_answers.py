"""Answer matching, every type (spec 003).

Plaintext answers are what make regex and computed answers possible, and those
are the reason this platform exists rather than an off-the-shelf one — so the
matcher gets exhaustive coverage rather than a sample.
"""

import time
import uuid
from typing import Any

import pytest

from app.models.challenge import ChallengeAnswer, MatchType
from app.services.answers import (
    InvalidAnswerRule,
    check,
    supported_match_types,
    validate_rule,
)


def rule(match_type: MatchType, value: str, **options: Any) -> ChallengeAnswer:
    answer = ChallengeAnswer(
        challenge_id=uuid.uuid4(),
        match_type=match_type,
        value=value,
        options=options,
        display_order=0,
    )
    answer.id = uuid.uuid4()
    return answer


class TestExact:
    def test_matches_the_literal_answer(self) -> None:
        assert check("flag{abc}", [rule(MatchType.EXACT, "flag{abc}")]).correct

    def test_is_case_sensitive(self) -> None:
        assert not check("FLAG{abc}", [rule(MatchType.EXACT, "flag{abc}")]).correct

    def test_trims_surrounding_whitespace(self) -> None:
        """Players paste out of terminals; a trailing newline should not cost a solve."""
        assert check("  flag{abc}\n", [rule(MatchType.EXACT, "flag{abc}")]).correct

    def test_whitespace_can_be_made_significant(self) -> None:
        answer = rule(MatchType.EXACT, "a b", strip_whitespace=False)

        assert check("a b", [answer]).correct
        assert not check(" a b", [answer]).correct


class TestCaseInsensitive:
    @pytest.mark.parametrize("submitted", ["FLAG{ABC}", "flag{abc}", "FlAg{AbC}"])
    def test_case_is_ignored(self, submitted: str) -> None:
        assert check(submitted, [rule(MatchType.CASE_INSENSITIVE, "flag{abc}")]).correct

    def test_folds_unicode(self) -> None:
        # casefold, not lower: the German sharp s folds to "ss".
        assert check("STRASSE", [rule(MatchType.CASE_INSENSITIVE, "straße")]).correct


class TestRegex:
    def test_matches_a_pattern(self) -> None:
        assert check("flag{a1b2c3}", [rule(MatchType.REGEX, r"flag\{[a-z0-9]{6}\}")]).correct

    def test_is_anchored_by_default(self) -> None:
        """Otherwise 'flag{abc} and junk' would pass a pattern for the flag alone."""
        answer = rule(MatchType.REGEX, r"flag\{\w+\}")

        assert check("flag{abc}", [answer]).correct
        assert not check("prefix flag{abc} suffix", [answer]).correct

    def test_anchoring_can_be_turned_off(self) -> None:
        answer = rule(MatchType.REGEX, r"flag\{\w+\}", anchored=False)

        assert check("prefix flag{abc} suffix", [answer]).correct

    def test_can_ignore_case(self) -> None:
        assert check("FLAG{ABC}", [rule(MatchType.REGEX, r"flag\{\w+\}", ignore_case=True)]).correct

    def test_catastrophic_backtracking_is_contained(self) -> None:
        """An admin pattern meeting player input must not hang a worker."""
        answer = rule(MatchType.REGEX, r"(a|a)*$", timeout_ms=100)
        started = time.perf_counter()

        verdict = check("a" * 60 + "!", [answer])

        elapsed = time.perf_counter() - started
        assert not verdict.correct
        assert elapsed < 2.0, f"regex ran for {elapsed:.1f}s"
        # The admin is told; the player is simply not matched.
        assert any("timed out" in error for error in verdict.errors)

    def test_a_timeout_does_not_stop_later_rules_matching(self) -> None:
        """One pathological rule must not make a challenge unsolvable."""
        verdict = check(
            "a" * 60 + "!",
            [
                rule(MatchType.REGEX, r"(a|a)*$", timeout_ms=100),
                rule(MatchType.EXACT, "a" * 60 + "!"),
            ],
        )

        assert verdict.correct


class TestNumeric:
    def test_accepts_the_ways_people_type_numbers(self) -> None:
        answer = rule(MatchType.NUMERIC, "1000")

        for submitted in ("1000", "1,000", "1e3", "1000.0", " 1000 "):
            assert check(submitted, [answer]).correct, submitted

    def test_absolute_tolerance(self) -> None:
        answer = rule(MatchType.NUMERIC, "100", tolerance=5)

        assert check("95", [answer]).correct
        assert check("105", [answer]).correct
        assert not check("94.9", [answer]).correct

    def test_percentage_tolerance(self) -> None:
        answer = rule(MatchType.NUMERIC, "200", tolerance_percent=10)

        assert check("180", [answer]).correct
        assert not check("179", [answer]).correct

    def test_a_range_accepts_anything_inside_it(self) -> None:
        answer = rule(MatchType.NUMERIC, "0", min=10, max=20)

        assert check("15", [answer]).correct
        assert check("10", [answer]).correct
        assert check("20", [answer]).correct
        assert not check("21", [answer]).correct

    def test_non_numeric_input_is_simply_wrong(self) -> None:
        assert not check("not a number", [rule(MatchType.NUMERIC, "100")]).correct

    def test_decimal_precision_is_exact(self) -> None:
        """Decimal, not float: 0.1 + 0.2 must not lose someone a solve."""
        assert check("0.3", [rule(MatchType.NUMERIC, "0.3")]).correct


class TestSet:
    def test_order_does_not_matter_by_default(self) -> None:
        answer = rule(MatchType.SET, "CVE-2021-1,CVE-2021-2,CVE-2021-3")

        assert check("CVE-2021-3,CVE-2021-1,CVE-2021-2", [answer]).correct

    def test_ordering_can_be_required(self) -> None:
        answer = rule(MatchType.SET, "first,second", ordered=True)

        assert check("first,second", [answer]).correct
        assert not check("second,first", [answer]).correct

    def test_a_missing_member_fails(self) -> None:
        answer = rule(MatchType.SET, "a,b,c")

        assert not check("a,b", [answer]).correct

    def test_whitespace_around_members_is_forgiven(self) -> None:
        assert check(" a , b ,c ", [rule(MatchType.SET, "a,b,c")]).correct

    def test_the_separator_is_configurable(self) -> None:
        assert check("a|b", [rule(MatchType.SET, "a|b", separator="|")]).correct

    def test_case_can_be_ignored(self) -> None:
        assert check("A,B", [rule(MatchType.SET, "a,b", case_insensitive=True)]).correct


class TestAnyOf:
    def test_any_listed_alternative_is_accepted(self) -> None:
        answer = rule(MatchType.ANY_OF, "colour\ncolor")

        assert check("colour", [answer]).correct
        assert check("color", [answer]).correct
        assert not check("colours", [answer]).correct

    def test_case_can_be_ignored(self) -> None:
        assert check("COLOUR", [rule(MatchType.ANY_OF, "colour", case_insensitive=True)]).correct


class TestMultipleRules:
    def test_any_rule_matching_makes_the_submission_correct(self) -> None:
        answers = [
            rule(MatchType.EXACT, "one"),
            rule(MatchType.EXACT, "two"),
            rule(MatchType.REGEX, r"three|3"),
        ]

        assert check("two", answers).correct
        assert check("3", answers).correct
        assert not check("four", answers).correct

    def test_the_matching_rule_is_reported(self) -> None:
        """So an admin can debug a challenge that behaves oddly."""
        second = rule(MatchType.EXACT, "two")

        verdict = check("two", [rule(MatchType.EXACT, "one"), second])

        assert verdict.matched_answer is second

    def test_no_rules_means_nothing_is_correct(self) -> None:
        assert not check("anything", []).correct

    def test_an_overlong_submission_is_capped_not_rejected(self) -> None:
        # The cap is a denial-of-service defence, not a validation rule.
        assert not check("x" * 100_000, [rule(MatchType.EXACT, "x")]).correct


class TestRuleValidation:
    def test_a_broken_pattern_is_rejected_when_saved(self) -> None:
        """Far better than a challenge that silently rejects every answer."""
        with pytest.raises(InvalidAnswerRule):
            validate_rule(MatchType.REGEX, "(unclosed", {})

    def test_a_valid_pattern_passes(self) -> None:
        validate_rule(MatchType.REGEX, r"flag\{\w+\}", {})

    def test_an_empty_value_is_rejected(self) -> None:
        with pytest.raises(InvalidAnswerRule):
            validate_rule(MatchType.EXACT, "   ", {})

    def test_a_numeric_rule_needs_a_number_or_a_range(self) -> None:
        with pytest.raises(InvalidAnswerRule):
            validate_rule(MatchType.NUMERIC, "abc", {})

        validate_rule(MatchType.NUMERIC, "abc", {"min": 1, "max": 2})

    def test_two_kinds_of_tolerance_at_once_is_rejected(self) -> None:
        with pytest.raises(InvalidAnswerRule):
            validate_rule(MatchType.NUMERIC, "10", {"tolerance": 1, "tolerance_percent": 5})

    def test_an_any_of_rule_needs_alternatives(self) -> None:
        with pytest.raises(InvalidAnswerRule):
            validate_rule(MatchType.ANY_OF, "\n\n", {})


def test_every_match_type_has_a_resolver() -> None:
    """A type in the enum with no resolver would silently never match."""
    assert set(supported_match_types()) == {member.value for member in MatchType}
