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
    builder: int
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
        return (SpawnOrder(builder=1, turn=0, tile=RIGHT_CORE_CENTER),)

    data = json.loads(SPAWNS_PATH.read_text(encoding="utf-8"))
    raw_builders = (
        data.get("spawn_schedule", data.get("builders", data))
        if isinstance(data, dict)
        else data
    )
    orders = []
    for raw in raw_builders:
        if isinstance(raw, dict) and raw.get("enabled") is False:
            continue
        builder_number = (
            int(raw.get("builder", len(orders) + 1))
            if isinstance(raw, dict)
            else len(orders) + 1
        )
        turn = int(raw.get("turn", 0)) if isinstance(raw, dict) else 0
        tile = raw.get("tile", RIGHT_CORE_CENTER) if isinstance(raw, dict) else raw
        orders.append(
            SpawnOrder(
                builder=builder_number,
                turn=turn,
                tile=_position(tile),
            )
        )
    orders.sort(key=lambda order: order.builder)
    return tuple(orders)


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
    for order in SPAWN_SCHEDULE:
        if order.turn == turn:
            return order.builder
    return None


def spawn_turn_for_builder_number(builder_number: int) -> int | None:
    for order in SPAWN_SCHEDULE:
        if order.builder == builder_number:
            return order.turn
    return None


class CoreAgent:
    def run(self, ct: Controller) -> None:
        current_round = ct.get_current_round()
        core_id = ct.get_id()
        position = ct.get_position()
        right_side = is_right_side(position)
        status = "idle: no spawn scheduled"

        try:
            for order in SPAWN_SCHEDULE:
                builder_number = order.builder
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
