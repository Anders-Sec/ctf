"""The three puzzle engines (spec 044 §4).

Pure functions over dicts — no database, no HTTP. The engine is where the
answer-leak rule and every game rule actually live, so this is where they are
pinned down.
"""

import pytest

from app.models.puzzle import PuzzleKind
from app.services.puzzles import engine_for
from app.services.puzzles.base import InvalidMove, InvalidPuzzleConfig
from app.services.puzzles.crossword import number_grid
from app.services.puzzles.wordle import ABSENT, EXACT, PRESENT, score_guess

WORDLE = engine_for(PuzzleKind.WORDLE)
CONNECTIONS = engine_for(PuzzleKind.CONNECTIONS)
CROSSWORD = engine_for(PuzzleKind.CROSSWORD)


def wordle_config(**overrides):
    return WORDLE.validate({"answer": "PROXY", **overrides})


def connections_config(**overrides):
    return CONNECTIONS.validate(
        {
            "groups": [
                {"name": "Ports", "level": 1, "members": ["22", "80", "443", "3389"]},
                {"name": "Hashes", "level": 2, "members": ["MD5", "SHA1", "BCRYPT", "ARGON2"]},
                {"name": "Tools", "level": 3, "members": ["NMAP", "BURP", "HYDRA", "JOHN"]},
                {"name": "Attacks", "level": 4, "members": ["XSS", "CSRF", "SQLI", "SSRF"]},
            ],
            **overrides,
        }
    )


def crossword_config(**overrides):
    """A 3x3 with no blocks: three across, three down, every cell crossed."""
    return CROSSWORD.validate(
        {
            "width": 3,
            "height": 3,
            "entries": [
                {"direction": "across", "row": 0, "col": 0, "answer": "CAT", "clue": "Feline"},
                {"direction": "across", "row": 1, "col": 0, "answer": "ARE", "clue": "Exist"},
                {"direction": "across", "row": 2, "col": 0, "answer": "TEN", "clue": "Count"},
                {"direction": "down", "row": 0, "col": 0, "answer": "CAT", "clue": "Feline again"},
                {"direction": "down", "row": 0, "col": 1, "answer": "ARE", "clue": "Exist again"},
                {"direction": "down", "row": 0, "col": 2, "answer": "TEN", "clue": "Count again"},
            ],
            **overrides,
        }
    )


class TestWordleScoring:
    def test_exact_and_absent(self):
        assert score_guess("PROXY", "PROXY") == [EXACT] * 5
        assert score_guess("CLAMP", "ROUTE") == [ABSENT] * 5

    def test_a_repeated_guess_letter_is_marked_once_when_the_answer_has_one(self):
        # ALLOY against LEMON: one L in the answer, so one L in the guess.
        assert score_guess("ALLOY", "LEMON") == [ABSENT, PRESENT, ABSENT, EXACT, ABSENT]

    def test_exact_matches_claim_their_letters_before_present_ones(self):
        # Both of THESE's Es are taken by exact matches, so GEESE's leading E
        # has nothing left to claim.
        assert score_guess("GEESE", "THESE") == [ABSENT, ABSENT, EXACT, EXACT, EXACT]

    def test_a_guess_may_mark_two_of_a_letter_when_the_answer_has_two(self):
        assert score_guess("SPEED", "ERASE").count(PRESENT) == 3


class TestWordleConfig:
    def test_the_answer_is_normalised_to_upper_case(self):
        assert wordle_config()["answer"] == "PROXY"
        assert WORDLE.validate({"answer": " proxy "})["answer"] == "PROXY"

    @pytest.mark.parametrize("answer", ["FOUR", "SIXSIX", "", "PR0XY", "PR XY"])
    def test_an_answer_that_is_not_five_letters_is_refused(self, answer):
        with pytest.raises(InvalidPuzzleConfig):
            WORDLE.validate({"answer": answer})

    def test_extra_words_must_match_the_answer_length(self):
        assert wordle_config(extra_words=["xsrfs"])["extra_words"] == ["XSRFS"]
        with pytest.raises(InvalidPuzzleConfig):
            wordle_config(extra_words=["toolong"])


class TestWordlePlay:
    def test_a_word_outside_the_list_is_refused_and_costs_nothing(self):
        config = wordle_config()
        with pytest.raises(InvalidMove) as caught:
            WORDLE.move(config, WORDLE.initial_state(), {"guess": "ZZZZZ"})
        assert caught.value.code == "unknown_word"

    def test_the_answer_is_always_accepted_even_outside_the_list(self):
        # The point of the carve-out: an author's security term must never be
        # rejected by the platform's own dictionary.
        config = WORDLE.validate({"answer": "XSRFS"})
        outcome = WORDLE.move(config, WORDLE.initial_state(), {"guess": "XSRFS"})
        assert outcome.solved

    def test_extra_words_are_accepted(self):
        config = wordle_config(extra_words=["ZZZZZ"])
        assert not WORDLE.move(config, WORDLE.initial_state(), {"guess": "ZZZZZ"}).solved

    def test_the_same_word_cannot_be_guessed_twice(self):
        config = wordle_config()
        state = WORDLE.move(config, WORDLE.initial_state(), {"guess": "AUDIT"}).state
        with pytest.raises(InvalidMove):
            WORDLE.move(config, state, {"guess": "audit"})

    def test_running_out_of_guesses_fails(self):
        config = wordle_config(max_guesses=2)
        first = WORDLE.move(config, WORDLE.initial_state(), {"guess": "AUDIT"})
        assert not first.failed
        second = WORDLE.move(config, first.state, {"guess": "CLAMP"})
        assert second.failed and not second.solved

    def test_the_last_guess_being_right_solves_rather_than_fails(self):
        config = wordle_config(max_guesses=1)
        outcome = WORDLE.move(config, WORDLE.initial_state(), {"guess": "PROXY"})
        assert outcome.solved and not outcome.failed


class TestWordleLeakage:
    def test_the_view_never_carries_the_answer_while_in_progress(self):
        config = wordle_config()
        state = WORDLE.move(config, WORDLE.initial_state(), {"guess": "AUDIT"}).state
        assert "PROXY" not in repr(WORDLE.view(config, state, reveal=False))

    def test_the_answer_appears_only_on_reveal(self):
        config = wordle_config()
        assert WORDLE.view(config, WORDLE.initial_state(), reveal=True)["answer"] == "PROXY"

    def test_reveal_on_fail_off_withholds_it_even_then(self):
        config = wordle_config(reveal_on_fail=False)
        assert "PROXY" not in repr(WORDLE.view(config, WORDLE.initial_state(), reveal=True))


class TestConnectionsConfig:
    def test_a_duplicate_tile_is_refused(self):
        # Two valid answers is unsolvable-by-design, not merely hard.
        with pytest.raises(InvalidPuzzleConfig):
            CONNECTIONS.validate(
                {
                    "groups": [
                        {"name": "A", "level": 1, "members": ["1", "2", "3", "4"]},
                        {"name": "B", "level": 2, "members": ["4", "5", "6", "7"]},
                        {"name": "C", "level": 3, "members": ["8", "9", "10", "11"]},
                        {"name": "D", "level": 4, "members": ["12", "13", "14", "15"]},
                    ]
                }
            )

    def test_tiles_differing_only_in_case_count_as_duplicates(self):
        with pytest.raises(InvalidPuzzleConfig):
            CONNECTIONS.validate(
                {
                    "groups": [
                        {"name": "A", "level": 1, "members": ["md5", "2", "3", "4"]},
                        {"name": "B", "level": 2, "members": ["MD5", "5", "6", "7"]},
                        {"name": "C", "level": 3, "members": ["8", "9", "10", "11"]},
                        {"name": "D", "level": 4, "members": ["12", "13", "14", "15"]},
                    ]
                }
            )

    def test_the_wrong_number_of_groups_or_tiles_is_refused(self):
        with pytest.raises(InvalidPuzzleConfig):
            CONNECTIONS.validate({"groups": []})
        with pytest.raises(InvalidPuzzleConfig):
            CONNECTIONS.validate(
                {
                    "groups": [
                        {"name": "A", "level": 1, "members": ["1", "2", "3"]},
                        {"name": "B", "level": 2, "members": ["4", "5", "6", "7"]},
                        {"name": "C", "level": 3, "members": ["8", "9", "10", "11"]},
                        {"name": "D", "level": 4, "members": ["12", "13", "14", "15"]},
                    ]
                }
            )

    def test_two_groups_cannot_claim_the_same_level(self):
        with pytest.raises(InvalidPuzzleConfig):
            CONNECTIONS.validate(
                {
                    "groups": [
                        {"name": "A", "level": 1, "members": ["1", "2", "3", "4"]},
                        {"name": "B", "level": 1, "members": ["5", "6", "7", "8"]},
                        {"name": "C", "level": 3, "members": ["9", "10", "11", "12"]},
                        {"name": "D", "level": 4, "members": ["13", "14", "15", "16"]},
                    ]
                }
            )


class TestConnectionsPlay:
    def state(self):
        return {**CONNECTIONS.initial_state(), "seed": "seed"}

    def test_a_correct_group_locks_in(self):
        config = connections_config()
        outcome = CONNECTIONS.move(config, self.state(), {"members": ["22", "80", "443", "3389"]})
        assert outcome.feedback["result"] == "correct"
        assert outcome.state["solved"] == [1]
        assert not outcome.solved

    def test_three_of_four_is_one_away_and_costs_a_mistake(self):
        config = connections_config()
        outcome = CONNECTIONS.move(config, self.state(), {"members": ["22", "80", "443", "MD5"]})
        assert outcome.feedback["result"] == "one_away"
        assert outcome.state["mistakes"] == 1

    def test_a_scattered_guess_is_wrong_rather_than_one_away(self):
        config = connections_config()
        outcome = CONNECTIONS.move(config, self.state(), {"members": ["22", "80", "MD5", "NMAP"]})
        assert outcome.feedback["result"] == "wrong"

    def test_resubmitting_the_same_four_costs_nothing(self):
        config = connections_config()
        first = CONNECTIONS.move(config, self.state(), {"members": ["22", "80", "443", "MD5"]})
        repeat = CONNECTIONS.move(config, first.state, {"members": ["MD5", "443", "80", "22"]})
        assert repeat.feedback["result"] == "repeat"
        assert not repeat.counted
        assert repeat.state["mistakes"] == 1

    def test_solving_three_groups_auto_solves_the_fourth(self):
        config = connections_config()
        state = self.state()
        for members in (
            ["22", "80", "443", "3389"],
            ["MD5", "SHA1", "BCRYPT", "ARGON2"],
            ["NMAP", "BURP", "HYDRA", "JOHN"],
        ):
            outcome = CONNECTIONS.move(config, state, {"members": members})
            state = outcome.state
        assert outcome.solved
        assert sorted(state["solved"]) == [1, 2, 3, 4]

    def test_running_out_of_mistakes_fails(self):
        config = connections_config(max_mistakes=2)
        first = CONNECTIONS.move(config, self.state(), {"members": ["22", "80", "MD5", "NMAP"]})
        second = CONNECTIONS.move(config, first.state, {"members": ["22", "80", "MD5", "XSS"]})
        assert second.failed

    def test_an_already_solved_group_cannot_be_replayed(self):
        config = connections_config()
        state = CONNECTIONS.move(
            config, self.state(), {"members": ["22", "80", "443", "3389"]}
        ).state
        with pytest.raises(InvalidMove):
            CONNECTIONS.move(config, state, {"members": ["22", "80", "443", "3389"]})

    def test_tiles_that_are_not_in_the_puzzle_are_refused(self):
        config = connections_config()
        with pytest.raises(InvalidMove):
            CONNECTIONS.move(config, self.state(), {"members": ["A", "B", "C", "D"]})


class TestConnectionsLeakage:
    def test_the_view_does_not_say_which_tile_belongs_to_which_group(self):
        config = connections_config()
        view = CONNECTIONS.view(config, {**CONNECTIONS.initial_state(), "seed": "s"}, reveal=False)
        assert set(view) == {
            "tiles",
            "solved_groups",
            "mistakes",
            "max_mistakes",
            "mistakes_remaining",
        }
        assert len(view["tiles"]) == 16
        assert "Ports" not in repr(view)

    def test_a_solved_group_leaves_the_tile_pool(self):
        config = connections_config()
        state = CONNECTIONS.move(
            config,
            {**CONNECTIONS.initial_state(), "seed": "s"},
            {"members": ["22", "80", "443", "3389"]},
        ).state
        view = CONNECTIONS.view(config, state, reveal=False)
        assert len(view["tiles"]) == 12
        assert view["solved_groups"][0]["name"] == "Ports"

    def test_the_shuffle_is_stable_for_a_session_and_differs_between_them(self):
        config = connections_config()
        one = CONNECTIONS.view(config, {**CONNECTIONS.initial_state(), "seed": "a"}, reveal=False)
        again = CONNECTIONS.view(config, {**CONNECTIONS.initial_state(), "seed": "a"}, reveal=False)
        other = CONNECTIONS.view(config, {**CONNECTIONS.initial_state(), "seed": "b"}, reveal=False)
        assert one["tiles"] == again["tiles"]
        assert one["tiles"] != other["tiles"]


class TestCrosswordNumbering:
    def test_a_clear_grid_numbers_down_the_top_and_left(self):
        numbers, starts = number_grid(3, 3, set())
        assert numbers == {(0, 0): 1, (0, 1): 2, (0, 2): 3, (1, 0): 4, (2, 0): 5}
        assert starts[(0, 0, "across")] == 1
        assert starts[(0, 0, "down")] == 1
        assert (1, 1, "across") not in starts

    def test_a_block_suppresses_starts_whose_run_would_be_one_cell(self):
        # With the middle blocked, 1-across/1-down still open at the top left,
        # 2-down at the top right and 3-across at the bottom left — but nothing
        # starts at (1, 0) or (2, 1), where a "run" would be a single cell and a
        # one-letter entry is not an entry.
        numbers, starts = number_grid(3, 3, {(1, 1)})
        assert numbers == {(0, 0): 1, (0, 2): 2, (2, 0): 3}
        assert starts == {
            (0, 0, "across"): 1,
            (0, 0, "down"): 1,
            (0, 2, "down"): 2,
            (2, 0, "across"): 3,
        }


class TestCrosswordConfig:
    def test_a_valid_grid_derives_its_numbers_and_lengths(self):
        config = crossword_config()
        assert [(e["number"], e["direction"]) for e in config["entries"]] == [
            (1, "across"),
            (1, "down"),
            (2, "down"),
            (3, "down"),
            (4, "across"),
            (5, "across"),
        ]
        assert all(entry["length"] == 3 for entry in config["entries"])

    def test_crossings_that_disagree_are_refused(self):
        with pytest.raises(InvalidPuzzleConfig) as caught:
            CROSSWORD.validate(
                {
                    "width": 3,
                    "height": 3,
                    "entries": [
                        {"direction": "across", "row": 0, "col": 0, "answer": "CAT", "clue": "a"},
                        {"direction": "down", "row": 0, "col": 0, "answer": "DOG", "clue": "b"},
                    ],
                }
            )
        assert "one way" in caught.value.message

    def test_an_answer_that_does_not_fit_its_run_is_refused(self):
        with pytest.raises(InvalidPuzzleConfig):
            CROSSWORD.validate(
                {
                    "width": 3,
                    "height": 3,
                    "entries": [
                        {"direction": "across", "row": 0, "col": 0, "answer": "CATS", "clue": "a"}
                    ],
                }
            )

    def test_a_cell_covered_by_no_entry_is_refused(self):
        with pytest.raises(InvalidPuzzleConfig) as caught:
            CROSSWORD.validate(
                {
                    "width": 3,
                    "height": 3,
                    "entries": [
                        {"direction": "across", "row": 0, "col": 0, "answer": "CAT", "clue": "a"}
                    ],
                }
            )
        assert "is in no entry" in caught.value.message

    def test_an_entry_that_starts_where_no_entry_starts_is_refused(self):
        with pytest.raises(InvalidPuzzleConfig):
            CROSSWORD.validate(
                {
                    "width": 3,
                    "height": 3,
                    "entries": [
                        {"direction": "across", "row": 0, "col": 1, "answer": "AT", "clue": "a"}
                    ],
                }
            )


class TestCrosswordPlay:
    SOLUTION = [["C", "A", "T"], ["A", "R", "E"], ["T", "E", "N"]]

    def test_a_full_correct_grid_solves(self):
        config = crossword_config()
        outcome = CROSSWORD.move(config, CROSSWORD.initial_state(), {"grid": self.SOLUTION})
        assert outcome.solved and not outcome.failed

    def test_wrong_cells_are_marked_and_not_corrected(self):
        config = crossword_config()
        grid = [list(row) for row in self.SOLUTION]
        grid[0][0] = "X"
        outcome = CROSSWORD.move(config, CROSSWORD.initial_state(), {"grid": grid})
        assert outcome.feedback["wrong"] == [[0, 0]]
        assert not outcome.solved
        # The letter the player typed stays. Marking is not correcting.
        assert outcome.state["letters"][0][0] == "X"
        assert "C" not in repr(outcome.feedback)

    def test_an_incomplete_grid_is_not_solved_and_its_blanks_are_not_wrong(self):
        config = crossword_config()
        grid = [["C", "A", "T"], ["A", "R", "E"], ["", "", ""]]
        outcome = CROSSWORD.move(config, CROSSWORD.initial_state(), {"grid": grid})
        assert not outcome.solved
        assert outcome.feedback["wrong"] == []
        assert outcome.feedback["complete"] is False

    def test_running_out_of_checks_fails(self):
        config = crossword_config(max_checks=2)
        blank = [["", "", ""], ["", "", ""], ["", "", ""]]
        first = CROSSWORD.move(config, CROSSWORD.initial_state(), {"grid": blank})
        assert not first.failed
        assert CROSSWORD.move(config, first.state, {"grid": blank}).failed

    def test_the_last_check_being_right_solves_rather_than_fails(self):
        config = crossword_config(max_checks=1)
        outcome = CROSSWORD.move(config, CROSSWORD.initial_state(), {"grid": self.SOLUTION})
        assert outcome.solved and not outcome.failed

    def test_saving_stores_letters_without_consuming_a_check(self):
        config = crossword_config()
        state = CROSSWORD.save(config, CROSSWORD.initial_state(), {"grid": [["C"]]})
        assert state["letters"][0][0] == "C"
        assert state["checks"] == 0

    def test_a_ragged_or_junk_grid_becomes_empty_cells_rather_than_an_error(self):
        # This runs on every save from a live grid; refusing the lot over one odd
        # cell would lose the player everything they had typed.
        config = crossword_config()
        state = CROSSWORD.save(
            config, CROSSWORD.initial_state(), {"grid": [["c", "!!", None], "x"]}
        )
        assert state["letters"] == [["C", "", ""], ["", "", ""], ["", "", ""]]


class TestCrosswordLeakage:
    def test_the_view_carries_clues_and_lengths_but_no_answers(self):
        config = crossword_config()
        view = CROSSWORD.view(config, CROSSWORD.initial_state(), reveal=False)
        assert "solution" not in view and "answers" not in view
        assert {clue["clue"] for clue in view["clues"]} >= {"Feline"}
        assert all("answer" not in clue for clue in view["clues"])

    def test_the_solution_appears_only_on_reveal(self):
        config = crossword_config()
        view = CROSSWORD.view(config, CROSSWORD.initial_state(), reveal=True)
        assert view["solution"][0] == ["C", "A", "T"]
        assert {entry["answer"] for entry in view["answers"]} == {"CAT", "ARE", "TEN"}
