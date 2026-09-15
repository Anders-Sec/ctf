"""Connections (spec 044 §4.2).

Sixteen tiles, four hidden groups of four, four mistakes. Standard rules: *one
away* on a three-of-four, free shuffle and deselect, the last group solves
itself, and resubmitting the same four tiles costs nothing.
"""

import hashlib
from typing import Any

from app.models.puzzle import PuzzleKind
from app.services.puzzles.base import (
    InvalidMove,
    MoveOutcome,
    register,
    require,
    require_int,
)

GROUP_COUNT = 4
GROUP_SIZE = 4
TILE_COUNT = GROUP_COUNT * GROUP_SIZE
MAX_TILE_LENGTH = 40


def _key(tile: str) -> str:
    """Tiles are compared case- and space-insensitively.

    A player clicking ``MD5`` and an author who typed ``md5`` mean the same tile,
    and two tiles that differ only in case would make a puzzle with two valid
    answers.
    """
    return " ".join(tile.split()).casefold()


def _shuffle_order(tiles: list[str], seed: str) -> list[str]:
    """A stable shuffle, derived from the seed.

    Derived rather than stored-random so the order survives a reload without a
    second column, and seeded per session so two players do not see an identical
    board and start comparing positions.
    """
    return sorted(tiles, key=lambda tile: hashlib.sha256(f"{seed}:{tile}".encode()).hexdigest())


class ConnectionsEngine:
    kind = PuzzleKind.CONNECTIONS

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        raw_groups = config.get("groups") or []
        require(isinstance(raw_groups, list), "groups must be a list.", "groups")
        require(
            len(raw_groups) == GROUP_COUNT,
            f"A Connections needs exactly {GROUP_COUNT} groups.",
            "groups",
        )

        groups: list[dict[str, Any]] = []
        seen: dict[str, int] = {}
        levels: set[int] = set()

        for index, raw in enumerate(raw_groups):
            require(isinstance(raw, dict), f"Group {index + 1} is malformed.", f"groups.{index}")
            name = str(raw.get("name", "")).strip()
            require(bool(name), f"Group {index + 1} needs a name.", f"groups.{index}.name")

            level = raw.get("level", index + 1)
            require(
                isinstance(level, int) and 1 <= level <= GROUP_COUNT,
                f"Group '{name}' needs a level between 1 and {GROUP_COUNT}.",
                f"groups.{index}.level",
            )
            require(
                level not in levels,
                f"Two groups both claim level {level}.",
                f"groups.{index}.level",
            )
            levels.add(level)

            raw_members = raw.get("members") or []
            require(
                isinstance(raw_members, list) and len(raw_members) == GROUP_SIZE,
                f"Group '{name}' needs exactly {GROUP_SIZE} tiles.",
                f"groups.{index}.members",
            )

            members: list[str] = []
            for member in raw_members:
                tile = " ".join(str(member).split())
                require(bool(tile), f"Group '{name}' has an empty tile.", f"groups.{index}.members")
                require(
                    len(tile) <= MAX_TILE_LENGTH,
                    f"'{tile}' is too long for a tile.",
                    f"groups.{index}.members",
                )
                # A duplicate tile makes a puzzle with two valid answers, which
                # is unsolvable-by-design rather than merely hard.
                require(
                    _key(tile) not in seen,
                    f"'{tile}' appears in more than one group.",
                    f"groups.{index}.members",
                )
                seen[_key(tile)] = index
                members.append(tile)

            groups.append({"name": name, "level": level, "members": members})

        require(
            len(seen) == TILE_COUNT, f"A Connections needs {TILE_COUNT} distinct tiles.", "groups"
        )

        groups.sort(key=lambda group: group["level"])
        return {
            "groups": groups,
            "max_mistakes": require_int(config, "max_mistakes", default=4, low=1, high=8),
        }

    def initial_state(self) -> dict[str, Any]:
        return {"solved": [], "mistakes": 0, "attempts": []}

    def _tiles(self, config: dict[str, Any]) -> list[str]:
        return [member for group in config["groups"] for member in group["members"]]

    def view(
        self, config: dict[str, Any], state: dict[str, Any], *, reveal: bool
    ) -> dict[str, Any]:
        solved_levels = state.get("solved", [])
        by_level = {group["level"]: group for group in config["groups"]}

        solved_groups = [
            {
                "name": by_level[level]["name"],
                "level": level,
                "members": by_level[level]["members"],
            }
            for level in solved_levels
            if level in by_level
        ]
        solved_keys = {_key(tile) for group in solved_groups for tile in group["members"]}

        payload: dict[str, Any] = {
            # Only the tiles still in play, in a stable per-session order. The
            # tile-to-group mapping is not in here — it arrives one group at a
            # time as they are solved, which is the whole game.
            "tiles": [
                tile
                for tile in _shuffle_order(self._tiles(config), state.get("seed", ""))
                if _key(tile) not in solved_keys
            ],
            "solved_groups": solved_groups,
            "mistakes": state.get("mistakes", 0),
            "max_mistakes": config["max_mistakes"],
            "mistakes_remaining": max(0, config["max_mistakes"] - state.get("mistakes", 0)),
        }

        if reveal:
            payload["groups"] = config["groups"]
        return payload

    def move(
        self, config: dict[str, Any], state: dict[str, Any], move: dict[str, Any]
    ) -> MoveOutcome:
        raw = move.get("members") or []
        if not isinstance(raw, list) or len(raw) != GROUP_SIZE:
            raise InvalidMove(f"Pick exactly {GROUP_SIZE} tiles.")

        picked = [" ".join(str(tile).split()) for tile in raw]
        keys = {_key(tile) for tile in picked}
        if len(keys) != GROUP_SIZE:
            raise InvalidMove("Those are not four different tiles.")

        by_level = {group["level"]: group for group in config["groups"]}
        solved_levels: list[int] = list(state.get("solved", []))
        solved_keys = {_key(tile) for level in solved_levels for tile in by_level[level]["members"]}
        if keys & solved_keys:
            raise InvalidMove("That group is already solved.")

        known = {_key(tile) for tile in self._tiles(config)}
        if not keys <= known:
            raise InvalidMove("That is not one of today's tiles.")

        signature = "|".join(sorted(keys))
        attempts: list[str] = list(state.get("attempts", []))
        if signature in attempts:
            # Free. Re-submitting the same four is a misclick or a double-tap,
            # and charging a mistake for it would be punishing the interface.
            return MoveOutcome(
                state=state,
                feedback={"result": "repeat"},
                counted=False,
                log_value="",
            )
        attempts.append(signature)

        overlaps = {
            group["level"]: len(keys & {_key(tile) for tile in group["members"]})
            for group in config["groups"]
        }
        hit = next((level for level, count in overlaps.items() if count == GROUP_SIZE), None)

        if hit is not None:
            solved_levels.append(hit)
            # Three groups found leaves only one arrangement of what is left, so
            # making the player click it would be ceremony, not play.
            if len(solved_levels) == GROUP_COUNT - 1:
                solved_levels.append(
                    next(level for level in by_level if level not in solved_levels)
                )

            new_state = {**state, "solved": solved_levels, "attempts": attempts}
            return MoveOutcome(
                state=new_state,
                feedback={
                    "result": "correct",
                    "group": {
                        "name": by_level[hit]["name"],
                        "level": hit,
                        "members": by_level[hit]["members"],
                    },
                },
                solved=len(solved_levels) == GROUP_COUNT,
                log_value=", ".join(picked),
            )

        mistakes = state.get("mistakes", 0) + 1
        one_away = any(count == GROUP_SIZE - 1 for count in overlaps.values())
        new_state = {**state, "mistakes": mistakes, "attempts": attempts}

        return MoveOutcome(
            state=new_state,
            feedback={
                "result": "one_away" if one_away else "wrong",
                "mistakes_remaining": max(0, config["max_mistakes"] - mistakes),
            },
            failed=mistakes >= config["max_mistakes"],
            log_value=", ".join(picked),
        )


register(ConnectionsEngine())

__all__ = ["ConnectionsEngine", "GROUP_COUNT", "GROUP_SIZE", "TILE_COUNT"]
