"""The Wordle guess list (spec 044 §4.1).

A guess must be a real word, which means the platform has to hold an opinion
about what a real word is. That opinion ships as a data file and is loaded once.

Three things are always accepted regardless of the list: the puzzle's own answer,
its ``extra_words``, and nothing else. The answer especially — an author writing
a security term no dictionary carries must not be able to produce a puzzle whose
solution the platform itself rejects, and finding that out mid-event is not an
acceptable way to learn it.
"""

from functools import lru_cache
from pathlib import Path

from app.config import Settings
from app.logging import get_logger

logger = get_logger(__name__)

#: The bundled list. ~1,000 common five-letter words — enough that ordinary play
#: is not fighting the dictionary, small enough to read and edit by hand. A
#: bigger list can be mounted over it; see ``Settings.wordle_word_list_path``.
BUNDLED = Path(__file__).resolve().parents[2] / "data" / "wordle_words_5.txt"

#: The only length the bundled list covers, and therefore the only length a
#: puzzle may use. Five is what the game is anyway.
WORD_LENGTH = 5


@lru_cache(maxsize=4)
def _load(path: str) -> frozenset[str]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        # A missing list must not take the whole event's puzzles down with it.
        # Empty means every guess falls through to the answer and extra_words,
        # which is a degraded puzzle rather than a broken endpoint — and the log
        # line is what tells an admin why players are complaining.
        logger.exception("wordle_word_list_unreadable", extra={"path": path})
        return frozenset()

    words = frozenset(
        word for line in text.splitlines() if (word := line.strip().lower()) and word.isalpha()
    )
    logger.info("wordle_word_list_loaded", extra={"path": path, "count": len(words)})
    return words


def word_list(settings: Settings) -> frozenset[str]:
    return _load(settings.wordle_word_list_path or str(BUNDLED))


def known(settings: Settings, word: str) -> bool:
    return word.strip().lower() in word_list(settings)


def count_of_length(settings: Settings, length: int) -> int:
    """How many list words are this long — shown to an author on save, so a
    puzzle whose length the list does not cover is obvious before the event."""
    return sum(1 for word in word_list(settings) if len(word) == length)
