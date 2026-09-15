"""The crossword mini (spec 044 §4.3).

A small grid, across and down clues, whole-grid checking that marks wrong cells
without correcting them, and a tight check limit — three checks against 25 cells
is nowhere near enough to solve it by bisection, which is what keeps the marking
from being a free oracle.
"""

from typing import Any

from app.models.puzzle import PuzzleKind
from app.services.puzzles.base import (
    InvalidMove,
    MoveOutcome,
    register,
    require,
    require_int,
)

ACROSS = "across"
DOWN = "down"
MIN_SIZE = 3
MAX_SIZE = 7
MAX_CLUE_LENGTH = 200
#: A block, in the letters grid and in the solution.
BLOCK = "#"
EMPTY = ""


def _blocks(config: dict[str, Any]) -> set[tuple[int, int]]:
    return {(cell[0], cell[1]) for cell in config.get("blocks", [])}


def number_grid(
    width: int, height: int, blocks: set[tuple[int, int]]
) -> tuple[dict[tuple[int, int], int], dict[tuple[int, int, str], int]]:
    """Number the grid the way a crossword is numbered.

    **Derived, never authored.** An author who typed the numbers in could produce
    a grid whose numbering contradicts its own geometry, and every clue list
    built from it would be wrong in a way that is maddening to debug.

    Returns the number at each starting cell, and a lookup from
    ``(row, col, direction)`` to the number of the entry starting there.
    """
    numbers: dict[tuple[int, int], int] = {}
    starts: dict[tuple[int, int, str], int] = {}
    next_number = 1

    for row in range(height):
        for col in range(width):
            if (row, col) in blocks:
                continue

            opens_across = (col == 0 or (row, col - 1) in blocks) and (
                col + 1 < width and (row, col + 1) not in blocks
            )
            opens_down = (row == 0 or (row - 1, col) in blocks) and (
                row + 1 < height and (row + 1, col) not in blocks
            )
            if not (opens_across or opens_down):
                continue

            numbers[(row, col)] = next_number
            if opens_across:
                starts[(row, col, ACROSS)] = next_number
            if opens_down:
                starts[(row, col, DOWN)] = next_number
            next_number += 1

    return numbers, starts


def _run_length(
    row: int, col: int, direction: str, width: int, height: int, blocks: set[tuple[int, int]]
) -> int:
    """How far an entry runs from here before a block or the edge stops it."""
    length = 0
    while 0 <= row < height and 0 <= col < width and (row, col) not in blocks:
        length += 1
        if direction == ACROSS:
            col += 1
        else:
            row += 1
    return length


def _cells(row: int, col: int, direction: str, length: int) -> list[tuple[int, int]]:
    if direction == ACROSS:
        return [(row, col + step) for step in range(length)]
    return [(row + step, col) for step in range(length)]


class CrosswordEngine:
    kind = PuzzleKind.CROSSWORD

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        width = require_int(config, "width", default=5, low=MIN_SIZE, high=MAX_SIZE)
        height = require_int(config, "height", default=5, low=MIN_SIZE, high=MAX_SIZE)

        raw_blocks = config.get("blocks") or []
        require(isinstance(raw_blocks, list), "blocks must be a list.", "blocks")
        blocks: set[tuple[int, int]] = set()
        for cell in raw_blocks:
            require(
                isinstance(cell, list | tuple) and len(cell) == 2,
                "A block is a [row, column] pair.",
                "blocks",
            )
            row, col = int(cell[0]), int(cell[1])
            require(
                0 <= row < height and 0 <= col < width,
                f"Block [{row}, {col}] is off the grid.",
                "blocks",
            )
            blocks.add((row, col))

        _, starts = number_grid(width, height, blocks)

        raw_entries = config.get("entries") or []
        require(isinstance(raw_entries, list), "entries must be a list.", "entries")
        require(bool(raw_entries), "A crossword needs at least one entry.", "entries")

        # Built as we go, so a crossing that disagrees is caught against the
        # letter already placed there rather than by a second pass.
        solution: dict[tuple[int, int], str] = {}
        entries: list[dict[str, Any]] = []
        seen: set[tuple[int, int, str]] = set()

        for index, raw in enumerate(raw_entries):
            where = f"entries.{index}"
            require(isinstance(raw, dict), f"Entry {index + 1} is malformed.", where)

            direction = str(raw.get("direction", "")).strip().lower()
            require(
                direction in (ACROSS, DOWN), "Direction is across or down.", f"{where}.direction"
            )

            row, col = int(raw.get("row", -1)), int(raw.get("col", -1))
            require(
                0 <= row < height and 0 <= col < width,
                f"Entry {index + 1} starts off the grid.",
                where,
            )
            require((row, col) not in blocks, f"Entry {index + 1} starts on a block.", where)

            number = starts.get((row, col, direction))
            require(
                number is not None,
                f"No {direction} entry starts at row {row + 1}, column {col + 1}.",
                where,
            )
            require((row, col, direction) not in seen, "Two entries claim the same start.", where)
            seen.add((row, col, direction))

            answer = "".join(str(raw.get("answer", "")).split()).upper()
            require(bool(answer), f"Entry {number} {direction} needs an answer.", f"{where}.answer")
            require(answer.isalpha(), "An answer is letters only.", f"{where}.answer")

            run = _run_length(row, col, direction, width, height, blocks)
            require(
                len(answer) == run,
                f"{number} {direction} has room for {run} letters, not {len(answer)}.",
                f"{where}.answer",
            )

            clue = str(raw.get("clue", "")).strip()
            require(bool(clue), f"Entry {number} {direction} needs a clue.", f"{where}.clue")
            require(len(clue) <= MAX_CLUE_LENGTH, "That clue is too long.", f"{where}.clue")

            for (cell_row, cell_col), letter in zip(
                _cells(row, col, direction, run), answer, strict=True
            ):
                existing = solution.get((cell_row, cell_col))
                require(
                    existing is None or existing == letter,
                    f"Row {cell_row + 1}, column {cell_col + 1} is '{existing}' one way and "
                    f"'{letter}' the other.",
                    f"{where}.answer",
                )
                solution[(cell_row, cell_col)] = letter

            entries.append(
                {
                    "number": number,
                    "direction": direction,
                    "row": row,
                    "col": col,
                    "length": run,
                    "answer": answer,
                    "clue": clue,
                }
            )

        # A cell no entry covers has no clue and can never be filled correctly,
        # so the puzzle would be unsolvable without looking unsolvable.
        for row in range(height):
            for col in range(width):
                require(
                    (row, col) in blocks or (row, col) in solution,
                    f"Row {row + 1}, column {col + 1} is in no entry.",
                    "entries",
                )

        entries.sort(key=lambda entry: (entry["number"], entry["direction"]))
        return {
            "width": width,
            "height": height,
            "blocks": sorted([row, col] for row, col in blocks),
            "entries": entries,
            "max_checks": require_int(config, "max_checks", default=3, low=1, high=10),
        }

    def initial_state(self) -> dict[str, Any]:
        return {"letters": [], "wrong": [], "checks": 0}

    def _solution(self, config: dict[str, Any]) -> dict[tuple[int, int], str]:
        solution: dict[tuple[int, int], str] = {}
        for entry in config["entries"]:
            cells = _cells(entry["row"], entry["col"], entry["direction"], entry["length"])
            for cell, letter in zip(cells, entry["answer"], strict=True):
                solution[cell] = letter
        return solution

    def normalise_letters(self, config: dict[str, Any], raw: Any) -> list[list[str]]:
        """A player's grid, forced into shape.

        Anything unexpected becomes an empty cell rather than an error: this runs
        on every save from a live grid, and refusing the whole thing over one odd
        cell would lose the player everything they had typed.
        """
        width, height = config["width"], config["height"]
        blocks = _blocks(config)
        rows = raw if isinstance(raw, list) else []

        letters: list[list[str]] = []
        for row in range(height):
            source = rows[row] if row < len(rows) and isinstance(rows[row], list) else []
            line: list[str] = []
            for col in range(width):
                if (row, col) in blocks:
                    line.append(BLOCK)
                    continue
                value = source[col] if col < len(source) else EMPTY
                text = str(value).strip().upper() if value is not None else EMPTY
                line.append(text[0] if len(text) == 1 and text.isalpha() else EMPTY)
            letters.append(line)
        return letters

    def save(
        self, config: dict[str, Any], state: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Store typing. Evaluates nothing and consumes no check."""
        return {**state, "letters": self.normalise_letters(config, payload.get("grid"))}

    def view(
        self, config: dict[str, Any], state: dict[str, Any], *, reveal: bool
    ) -> dict[str, Any]:
        numbers, _ = number_grid(config["width"], config["height"], _blocks(config))
        payload: dict[str, Any] = {
            "width": config["width"],
            "height": config["height"],
            "blocks": config["blocks"],
            "numbers": [
                {"row": row, "col": col, "number": number}
                for (row, col), number in sorted(numbers.items())
            ],
            # Clue, number, direction and *length* — never the answer.
            "clues": [
                {
                    "number": entry["number"],
                    "direction": entry["direction"],
                    "row": entry["row"],
                    "col": entry["col"],
                    "length": entry["length"],
                    "clue": entry["clue"],
                }
                for entry in config["entries"]
            ],
            "letters": state.get("letters") or self.normalise_letters(config, None),
            "wrong": state.get("wrong", []),
            "checks": state.get("checks", 0),
            "max_checks": config["max_checks"],
            "checks_remaining": max(0, config["max_checks"] - state.get("checks", 0)),
        }
        if reveal:
            solution = self._solution(config)
            payload["solution"] = [
                [
                    BLOCK if (row, col) in _blocks(config) else solution.get((row, col), EMPTY)
                    for col in range(config["width"])
                ]
                for row in range(config["height"])
            ]
            payload["answers"] = [
                {
                    "number": entry["number"],
                    "direction": entry["direction"],
                    "answer": entry["answer"],
                }
                for entry in config["entries"]
            ]
        return payload

    def move(
        self, config: dict[str, Any], state: dict[str, Any], move: dict[str, Any]
    ) -> MoveOutcome:
        if "grid" not in move:
            raise InvalidMove("Send the grid to check.")

        letters = self.normalise_letters(config, move.get("grid"))
        solution = self._solution(config)

        wrong: list[list[int]] = []
        complete = True
        for (row, col), expected in solution.items():
            actual = letters[row][col]
            if not actual:
                complete = False
            elif actual != expected:
                wrong.append([row, col])

        checks = state.get("checks", 0) + 1
        solved = complete and not wrong
        new_state = {"letters": letters, "wrong": wrong, "checks": checks}

        return MoveOutcome(
            state=new_state,
            feedback={
                # Which cells are wrong, never what they should be.
                "wrong": wrong,
                "complete": complete,
                "checks_remaining": max(0, config["max_checks"] - checks),
            },
            solved=solved,
            failed=not solved and checks >= config["max_checks"],
            log_value="".join("".join(cell or "." for cell in row) for row in letters)[:1024],
        )


register(CrosswordEngine())

__all__ = ["CrosswordEngine", "number_grid", "ACROSS", "DOWN", "BLOCK"]
