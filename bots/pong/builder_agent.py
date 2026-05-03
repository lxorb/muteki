from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cambc import Controller, Direction, EntityType, Position

from core_agent import (
    actual_position,
    builder_number_for_spawn_turn,
    is_right_side,
    spawn_turn_for_builder_number,
)


BOT_ROOT = Path(__file__).resolve().parent
STRATEGY_ROOT = BOT_ROOT / "strategies"
PLAN_PATH = BOT_ROOT / "plan.json"

_DIRECTION_BY_NAME = {direction.value: direction for direction in Direction}
_DIRECTION_BY_NAME.update({direction.name.lower(): direction for direction in Direction})

_MIRRORED_DIRECTION = {
    Direction.NORTH: Direction.NORTH,
    Direction.NORTHEAST: Direction.NORTHWEST,
    Direction.EAST: Direction.WEST,
    Direction.SOUTHEAST: Direction.SOUTHWEST,
    Direction.SOUTH: Direction.SOUTH,
    Direction.SOUTHWEST: Direction.SOUTHEAST,
    Direction.WEST: Direction.EAST,
    Direction.NORTHWEST: Direction.NORTHEAST,
    Direction.CENTRE: Direction.CENTRE,
}

_ENTITY_BY_NAME = {
    entity_type.value: entity_type for entity_type in EntityType
}
_ENTITY_BY_NAME.update(
    {entity_type.name.lower(): entity_type for entity_type in EntityType}
)

_DIRECTIONAL_BUILDERS = {
    EntityType.CONVEYOR: "build_conveyor",
    EntityType.SPLITTER: "build_splitter",
    EntityType.ARMOURED_CONVEYOR: "build_armoured_conveyor",
    EntityType.GUNNER: "build_gunner",
    EntityType.SENTINEL: "build_sentinel",
    EntityType.BREACH: "build_breach",
}

_POSITIONAL_BUILDERS = {
    EntityType.HARVESTER: "build_harvester",
    EntityType.ROAD: "build_road",
    EntityType.BARRIER: "build_barrier",
    EntityType.FOUNDRY: "build_foundry",
    EntityType.LAUNCHER: "build_launcher",
}

_ACTION_ALIASES = {
    "destroy": "destroy",
    "destroy_at": "destroy",
    "destroy building at": "destroy",
    "build": "build",
    "build_at": "build",
    "build at": "build",
    "move_to": "move_to",
    "move to": "move_to",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


PLAN = _load_json(PLAN_PATH)
PLAN_TILES = PLAN.get("tiles", {})
STRATEGIES: dict[int, dict[str, Any]] = {}


def _position(raw: Any) -> Position:
    if isinstance(raw, str):
        x, y = raw.split(",", 1)
        return Position(int(x), int(y))
    if isinstance(raw, dict):
        return Position(int(raw["x"]), int(raw["y"]))
    return Position(int(raw[0]), int(raw[1]))


def _direction(raw: str | Direction) -> Direction:
    if isinstance(raw, Direction):
        return raw
    return _DIRECTION_BY_NAME[raw.lower()]


def _entity_type(raw: str | EntityType) -> EntityType:
    if isinstance(raw, EntityType):
        return raw
    return _ENTITY_BY_NAME[raw.lower()]


def _mirror_direction(direction: Direction, right_side: bool) -> Direction:
    if right_side:
        return direction
    return _MIRRORED_DIRECTION[direction]


def _canonical_tile_key(pos: Position) -> str:
    return f"{pos.x},{pos.y}"


def _planned_building(pos: Position) -> Any:
    return PLAN_TILES.get(_canonical_tile_key(pos))


def _load_strategy(builder_number: int) -> dict[str, Any]:
    strategy = STRATEGIES.get(builder_number)
    if strategy is None:
        strategy = _load_json(STRATEGY_ROOT / f"{builder_number}.json")
        STRATEGIES[builder_number] = strategy
    return strategy


def _canonical_action_position(action: dict[str, Any]) -> Position:
    return _position(action.get("at", action.get("to")))


class BuilderAgent:
    def __init__(self) -> None:
        self.builder_number: int | None = None
        self.spawn_turn: int | None = None
        self.first_run_turn: int | None = None
        self.right_side: bool | None = None

    def run(self, ct: Controller) -> None:
        if self.builder_number is None:
            self._infer_identity(ct)
        if self.builder_number is None or self.first_run_turn is None:
            return

        strategy = _load_strategy(self.builder_number)
        current_round = ct.get_current_round()
        relative_turn = current_round - self.first_run_turn

        actions = []
        actions.extend(strategy.get("absolute_turns", {}).get(str(current_round), []))
        actions.extend(strategy.get("turns", {}).get(str(relative_turn), []))

        for action in actions:
            self._execute_action(ct, action)

    def _infer_identity(self, ct: Controller) -> None:
        current_round = ct.get_current_round()
        builder_number = builder_number_for_spawn_turn(current_round)
        spawn_turn = current_round

        if builder_number is None:
            builder_number = builder_number_for_spawn_turn(current_round - 1)
            spawn_turn = current_round - 1

        if builder_number is None:
            return

        self.builder_number = builder_number
        self.spawn_turn = spawn_turn
        self.first_run_turn = current_round
        self.right_side = is_right_side(ct.get_position())

        configured_spawn_turn = spawn_turn_for_builder_number(builder_number)
        if configured_spawn_turn is not None:
            self.spawn_turn = configured_spawn_turn

    def _execute_action(self, ct: Controller, action: dict[str, Any]) -> None:
        action_type = _ACTION_ALIASES[action["action"].lower()]
        if action_type == "destroy":
            self._destroy_at(ct, action)
        elif action_type == "build":
            self._build_at(ct, action)
        elif action_type == "move_to":
            self._move_to(ct, action)

    def _actual_position(self, canonical_pos: Position) -> Position:
        return actual_position(canonical_pos, self.right_side is not False)

    def _destroy_at(self, ct: Controller, action: dict[str, Any]) -> None:
        ct.destroy(self._actual_position(_canonical_action_position(action)))

    def _move_to(self, ct: Controller, action: dict[str, Any]) -> None:
        target = self._actual_position(_canonical_action_position(action))
        current = ct.get_position()
        if target == current:
            return
        ct.move(current.direction_to(target))

    def _build_at(self, ct: Controller, action: dict[str, Any]) -> None:
        canonical_pos = _canonical_action_position(action)
        build_spec = action.get("building", _planned_building(canonical_pos))
        if build_spec is None:
            return

        actual_pos = self._actual_position(canonical_pos)
        if isinstance(build_spec, str):
            build_spec = {"type": build_spec}

        entity_type = _entity_type(build_spec["type"])
        if entity_type == EntityType.BRIDGE:
            target = self._actual_position(_position(build_spec["target"]))
            ct.build_bridge(actual_pos, target)
            return

        builder_name = _DIRECTIONAL_BUILDERS.get(entity_type)
        if builder_name is not None:
            direction = _mirror_direction(
                _direction(build_spec["direction"]),
                self.right_side is not False,
            )
            getattr(ct, builder_name)(actual_pos, direction)
            return

        builder_name = _POSITIONAL_BUILDERS[entity_type]
        getattr(ct, builder_name)(actual_pos)
