from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from cambc import Controller, Position


BOT_ROOT = Path(__file__).resolve().parent
SPAWNS_PATH = BOT_ROOT / "spawns.json"
MAP_WIDTH = 50
RIGHT_CORE_CENTER = Position(41, 8)


@dataclass(frozen=True)
class SpawnOrder:
    turn: int
    tile: Position


def _position(raw) -> Position:
    if isinstance(raw, str):
        x, y = raw.split(",", 1)
        return Position(int(x), int(y))
    if isinstance(raw, dict):
        return Position(int(raw["x"]), int(raw["y"]))
    return Position(int(raw[0]), int(raw[1]))


def _load_spawn_schedule() -> tuple[SpawnOrder, ...]:
    if not SPAWNS_PATH.exists():
        return (SpawnOrder(turn=0, tile=RIGHT_CORE_CENTER),)

    data = json.loads(SPAWNS_PATH.read_text(encoding="utf-8"))
    raw_builders = data.get("builders", data) if isinstance(data, dict) else data
    orders = []
    for raw in raw_builders:
        orders.append(
            SpawnOrder(
                turn=int(raw.get("turn", 0)),
                tile=_position(raw.get("tile", RIGHT_CORE_CENTER)),
            )
        )
    return tuple(orders) or (SpawnOrder(turn=0, tile=RIGHT_CORE_CENTER),)


# Canonical coordinates are written for the right side of pong. The runtime
# mirrors them automatically when this bot is spawned on the left side.
SPAWN_SCHEDULE: tuple[SpawnOrder, ...] = _load_spawn_schedule()


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
        core_id = ct.get_id()
        position = ct.get_position()
        right_side = is_right_side(position)
        status = "idle: no spawn scheduled"

        try:
            for builder_number, order in enumerate(SPAWN_SCHEDULE, start=1):
                if order.turn != current_round:
                    continue

                spawn_tile = actual_position(order.tile, right_side)
                if not ct.can_spawn(spawn_tile):
                    status = f"spawn blocked: builder {builder_number} at {spawn_tile}"
                    break

                try:
                    ct.spawn_builder(spawn_tile)
                    status = f"spawned builder {builder_number} at {spawn_tile}"
                except Exception as exc:
                    status = f"spawn error: {type(exc).__name__}: {exc}"
                break
        except Exception as exc:
            status = f"error: {type(exc).__name__}: {exc}"

        print(f"[pong][core id={core_id} round={current_round} pos={position}] {status}")
