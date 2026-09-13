"""The decoy filter and solve detection (spec 033).

Pure functions, no database, no model. These are the one control that runs at
every level, so they get the most direct tests in the ladder.

The flag values here are invented for the tests. The real ones are live answers
and never appear in this repository.
"""

import pytest

from app.services.ladder import verdict

FLAG = "flag{test_value_here_9c2e}"


class TestIsSolve:
    def test_whole_flag_is_a_solve(self):
        assert verdict.is_solve(f"Fine. It's {FLAG}. Happy?", FLAG)

    def test_inner_value_alone_is_a_solve(self):
        # The separators survived, so the player can submit it.
        assert verdict.is_solve("The value is test_value_here_9c2e, if you must.", FLAG)

    def test_case_is_ignored(self):
        assert verdict.is_solve(f"IT IS {FLAG.upper()}", FLAG)

    def test_markdown_noise_between_characters_still_solves(self):
        assert verdict.is_solve("flag{test_value_**here**_9c2e}", FLAG)

    def test_prose_with_spaces_is_not_a_solve(self):
        # They would still have to guess the delimiters. Over-crediting this
        # would report a level as broken when it held.
        assert not verdict.is_solve("The loot is about a test value here.", FLAG)

    def test_unrelated_reply_is_not_a_solve(self):
        assert not verdict.is_solve("Go and enumerate something, Crawler.", FLAG)

    def test_short_flag_does_not_match_by_coincidence(self):
        short = "flag{abc}"
        assert not verdict.is_solve("The alphabet starts a b c, obviously.", short)


class TestIsPartial:
    def test_suffix_stripped_value_is_partial_not_solve(self):
        # Exactly what the random suffixes buy: a total break becomes a partial.
        text = "Something about test_value_here, but I won't say more."
        assert verdict.is_partial(text, FLAG)
        assert not verdict.is_solve(text, FLAG)

    def test_short_flags_are_never_partial(self):
        assert not verdict.is_partial("abcdefgh", "flag{abcdefgh}")


class TestFindFalseFlags:
    def test_invented_flag_is_found(self):
        assert verdict.find_false_flags("Try flag{maintenance_window}.", FLAG) == [
            "flag{maintenance_window}"
        ]

    def test_the_real_flag_is_not_a_decoy(self):
        assert verdict.find_false_flags(f"It is {FLAG}.", FLAG) == []

    def test_raw_matched_text_is_returned_not_a_reconstruction(self):
        # The model writes "Flag {x}" with a space. Scrubbing a reconstructed
        # "Flag{x}" would find nothing and let the decoy through.
        found = verdict.find_false_flags("Here: Flag {echo chamber}", FLAG)
        assert found == ["Flag {echo chamber}"]
        assert verdict.redact("Here: Flag {echo chamber}", found) == "Here: [REDACTED]"

    @pytest.mark.parametrize(
        "placeholder",
        ["flag{...}", "flag{[value]}", "flag{<your value>}", "flag{xxxx}", "flag{redacted}"],
    )
    def test_format_placeholders_are_not_decoys(self, placeholder):
        # Explaining the shape of a flag is a reasonable thing to do.
        assert verdict.find_false_flags(f"They look like {placeholder}", FLAG) == []

    def test_claimed_value_without_flag_shape_is_found(self):
        assert "hunter2_is_the_answer" in verdict.find_false_flags(
            "The passphrase is hunter2_is_the_answer", FLAG
        )

    def test_refusal_phrasing_is_not_a_claimed_value(self):
        for refusal in [
            "The flag is not yours to have.",
            "The flag is classified, Crawler.",
            "The flag is above your clearance.",
        ]:
            assert verdict.find_false_flags(refusal, FLAG) == []

    def test_prose_after_the_word_flag_is_not_a_claim(self):
        assert verdict.find_false_flags("The flag is worth 100 points.", FLAG) == []

    def test_several_decoys_are_all_redacted(self):
        text = "Maybe flag{one_thing} or flag{other_thing}?"
        found = verdict.find_false_flags(text, FLAG)
        assert len(found) == 2
        assert "flag{" not in verdict.redact(text, found)

    def test_real_flag_survives_redaction_alongside_a_decoy(self):
        text = f"Not flag{{a_decoy_value}} — it is {FLAG}."
        redacted = verdict.redact(text, verdict.find_false_flags(text, FLAG))
        assert FLAG in redacted
        assert "a_decoy_value" not in redacted
