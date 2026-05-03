from __future__ import annotations

from dataclasses import dataclass

from cambc import Controller, Position


MAP_WIDTH = 50
RIGHT_CORE_CENTER = Position(41, 8)


@dataclass(frozen=True)
class SpawnOrder:
    turn: int
    tile: Position


# Canonical coordinates are written for the right side of pong. The runtime
# mirrors them automatically when this bot is spawned on the left side.
SPAWN_SCHEDULE: tuple[SpawnOrder, ...] = (
    SpawnOrder(turn=0, tile=RIGHT_CORE_CENTER),
)


def is_right_side(pos: Position) -> bool:
    return pos.x >= MAP_WIDTH // 2


def mirror_position(pos: Position) -> Position:
    return Position(MAP_WIDTH - 1 - pos.x, pos.y)


def actual_position(canonical_right_pos: Position, right_side: bool) -> Position:
    if right_side:
        return canonical_right_pos
    return mirror_position(canonical_right_pos)


def builder_number_for_spawn_turn(turn: int) -> int | None:
    for index, order in enumerate(SPAWN_SCHEDULE, start=1):
        if order.turn == turn:
            return index
    return None


def spawn_turn_for_builder_number(builder_number: int) -> int | None:
    if not (1 <= builder_number <= len(SPAWN_SCHEDULE)):
        return None
    return SPAWN_SCHEDULE[builder_number - 1].turn


class CoreAgent:
    def run(self, ct: Controller) -> None:
        current_round = ct.get_current_round()
        right_side = is_right_side(ct.get_position())

        for order in SPAWN_SCHEDULE:
            if order.turn != current_round:
                continue
            ct.spawn_builder(actual_position(order.tile, right_side))
            return
