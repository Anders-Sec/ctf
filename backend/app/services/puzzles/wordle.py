"""Wordle (spec 044 §4.1).

Six guesses at a five-letter security term, with per-letter feedback. All of it
server-side, because the client cannot be trusted with the answer and therefore
cannot compute the feedback.
"""

from typing import Any

from app.config import get_settings
from app.models.puzzle import PuzzleKind
from app.services.puzzles import words
from app.services.puzzles.base import (
    InvalidMove,
    MoveOutcome,
    PuzzleEngine,
    register,
    require,
    require_int,
)

#: Per-letter verdicts.
EXACT = "exact"
PRESENT = "present"
ABSENT = "absent"

MAX_EXTRA_WORDS = 200


def score_guess(guess: str, answer: str) -> list[str]:
    """Per-letter verdicts, with duplicate letters handled properly.

    The rule everyone gets wrong: a repeated letter is only marked ``present``
    as many times as it actually occurs in the answer, and exact matches claim
    their occurrences first.

    ``ALLOY`` against ``LEMON`` marks the first L present and the second absent —
    not both present, which would tell the player there are two Ls when there is
    one. ``GEESE`` against ``THESE`` marks its leading E absent, because both of
    the answer's Es are already claimed by exact matches further along.
    """
    verdicts = [ABSENT] * len(guess)

    remaining: dict[str, int] = {}
    for index, letter in enumerate(answer):
        if guess[index] == letter:
            verdicts[index] = EXACT
        else:
            remaining[letter] = remaining.get(letter, 0) + 1

    for index, letter in enumerate(guess):
        if verdicts[index] == EXACT:
            continue
        if remaining.get(letter, 0) > 0:
            verdicts[index] = PRESENT
            remaining[letter] -= 1

    return verdicts


class WordleEngine:
    kind = PuzzleKind.WORDLE

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        answer = str(config.get("answer", "")).strip().upper()
        require(bool(answer), "A Wordle needs an answer.", "answer")
        require(answer.isalpha(), "The answer must be letters only.", "answer")
        require(
            len(answer) == words.WORD_LENGTH,
            f"The answer must be {words.WORD_LENGTH} letters — "
            "the guess list covers no other length.",
            "answer",
        )

        max_guesses = require_int(config, "max_guesses", default=6, low=1, high=12)

        raw_extra = config.get("extra_words", []) or []
        require(isinstance(raw_extra, list), "extra_words must be a list.", "extra_words")
        require(
            len(raw_extra) <= MAX_EXTRA_WORDS,
            f"At most {MAX_EXTRA_WORDS} extra words.",
            "extra_words",
        )
        extra: list[str] = []
        for entry in raw_extra:
            word = str(entry).strip().upper()
            if not word:
                continue
            require(word.isalpha(), f"'{entry}' is not a word.", "extra_words")
            require(
                len(word) == len(answer),
                f"'{word}' is not {len(answer)} letters.",
                "extra_words",
            )
            if word not in extra:
                extra.append(word)

        return {
            "answer": answer,
            "length": len(answer),
            "max_guesses": max_guesses,
            "extra_words": extra,
            "reveal_on_fail": bool(config.get("reveal_on_fail", True)),
        }

    def initial_state(self) -> dict[str, Any]:
        return {"guesses": []}

    def view(
        self, config: dict[str, Any], state: dict[str, Any], *, reveal: bool
    ) -> dict[str, Any]:
        guesses = state.get("guesses", [])
        payload: dict[str, Any] = {
            "length": config["length"],
            "max_guesses": config["max_guesses"],
            # Guess and verdicts only. The answer is not in here, and the only
            # branch below that can put it there is gated on a terminal session.
            "guesses": guesses,
            "guesses_remaining": max(0, config["max_guesses"] - len(guesses)),
        }
        if reveal and config.get("reveal_on_fail", True):
            payload["answer"] = config["answer"]
        return payload

    def move(
        self, config: dict[str, Any], state: dict[str, Any], move: dict[str, Any]
    ) -> MoveOutcome:
        guess = str(move.get("guess", "")).strip().upper()
        answer = config["answer"]
        length = config["length"]

        if len(guess) != length or not guess.isalpha():
            raise InvalidMove(f"A guess is {length} letters.")

        guesses = list(state.get("guesses", []))
        if any(entry["guess"] == guess for entry in guesses):
            raise InvalidMove("You have already tried that word.")

        # Checked before anything is spent. A word the list has never heard of
        # costs no guess and is not logged — it never reached the puzzle.
        settings = get_settings()
        recognised = (
            guess == answer
            or guess in config.get("extra_words", [])
            or words.known(settings, guess)
        )
        if not recognised:
            raise InvalidMove("Not in the word list.", code="unknown_word")

        verdicts = score_guess(guess, answer)
        guesses.append({"guess": guess, "verdicts": verdicts})

        solved = guess == answer
        failed = not solved and len(guesses) >= config["max_guesses"]

        return MoveOutcome(
            state={"guesses": guesses},
            feedback={"verdicts": verdicts, "guess": guess},
            solved=solved,
            failed=failed,
            log_value=guess,
        )


register(WordleEngine())

__all__ = ["WordleEngine", "score_guess", "EXACT", "PRESENT", "ABSENT", "PuzzleEngine"]
