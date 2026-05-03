from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cambc import Controller, Direction, EntityType, GameError, Position

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

_WALKABLE_BUILDINGS = {
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.ROAD,
    EntityType.SPLITTER,
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


def _is_walkable_building(entity_type: EntityType) -> bool:
    return entity_type in _WALKABLE_BUILDINGS


def _load_strategy(builder_number: int) -> dict[str, Any]:
    strategy = STRATEGIES.get(builder_number)
    if strategy is None:
        strategy_path = STRATEGY_ROOT / f"{builder_number}.json"
        strategy = _load_json(strategy_path) if strategy_path.exists() else {"turns": {}}
        STRATEGIES[builder_number] = strategy
    return strategy


def _canonical_action_position(action: dict[str, Any]) -> Position:
    return _position(action.get("at", action.get("to")))


def _format_position(pos: Position) -> str:
    return f"({pos.x},{pos.y})"


def _describe_action(action: dict[str, Any]) -> str:
    raw_action_type = action.get("action", "unknown")
    action_type = _ACTION_ALIASES.get(str(raw_action_type).lower(), str(raw_action_type))
    raw_position = action.get("at", action.get("to"))
    if raw_position is None:
        return action_type
    try:
        return f"{action_type} {_format_position(_position(raw_position))}"
    except Exception:
        return action_type


class BuilderAgent:
    def __init__(self) -> None:
        self.builder_number: int | None = None
        self.spawn_turn: int | None = None
        self.first_run_turn: int | None = None
        self.right_side: bool | None = None
        self.deferred_actions: list[dict[str, Any]] = []
        self.last_action_note = ""

    def run(self, ct: Controller) -> None:
        current_round = ct.get_current_round()
        entity_id = ct.get_id()
        status = "idle"

        try:
            if self.builder_number is None:
                self._infer_identity(ct)
            if self.builder_number is None or self.first_run_turn is None:
                status = "waiting: could not infer builder number"
            elif current_round < self.first_run_turn:
                status = f"waiting: first action round is {self.first_run_turn}"
            elif self.spawn_turn is None:
                status = "waiting: unknown spawn turn"
            else:
                strategy = _load_strategy(self.builder_number)
                relative_turn = current_round - self.spawn_turn

                actions = [*self.deferred_actions]
                self.deferred_actions = []
                actions.extend(strategy.get("absolute_turns", {}).get(str(current_round), []))
                actions.extend(strategy.get("turns", {}).get(str(relative_turn), []))

                if not actions:
                    status = f"relative turn {relative_turn}: no actions"
                else:
                    notes = []
                    for index, action in enumerate(actions):
                        self.last_action_note = ""
                        if not self._execute_action(ct, action):
                            self.deferred_actions.append(action)
                            self.deferred_actions.extend(actions[index + 1 :])
                            notes.append(
                                self.last_action_note
                                or f"deferred {_describe_action(action)}"
                            )
                            break
                        notes.append(
                            self.last_action_note
                            or f"completed {_describe_action(action)}"
                        )

                    status = f"relative turn {relative_turn}: " + "; ".join(notes)
                    if self.deferred_actions:
                        status += f"; deferred {len(self.deferred_actions)} action(s)"
        except Exception as exc:
            status = f"error: {type(exc).__name__}: {exc}"

        builder_number = self.builder_number if self.builder_number is not None else "?"
        try:
            position = ct.get_position()
        except Exception:
            position = "?"
        print(
            f"[pong][builder id={entity_id} builder={builder_number} "
            f"round={current_round} pos={position}] {status}"
        )

    def _infer_identity(self, ct: Controller) -> None:
        current_round = ct.get_current_round()
        builder_number = builder_number_for_spawn_turn(current_round - 1)
        spawn_turn = current_round - 1

        if builder_number is None:
            builder_number = builder_number_for_spawn_turn(current_round)
            spawn_turn = current_round

        if builder_number is None:
            return

        self.builder_number = builder_number
        self.spawn_turn = spawn_turn
        self.first_run_turn = spawn_turn + 1
        self.right_side = is_right_side(ct.get_position())

        configured_spawn_turn = spawn_turn_for_builder_number(builder_number)
        if configured_spawn_turn is not None:
            self.spawn_turn = configured_spawn_turn
            self.first_run_turn = configured_spawn_turn + 1

    def _execute_action(self, ct: Controller, action: dict[str, Any]) -> bool:
        action_type = _ACTION_ALIASES.get(str(action.get("action", "")).lower())
        if action_type is None:
            self.last_action_note = f"skipped unknown action: {action.get('action')}"
            return True
        if action_type == "destroy":
            return self._destroy_at(ct, action)
        elif action_type == "build":
            return self._build_at(ct, action)
        elif action_type == "move_to":
            return self._move_to(ct, action)
        return True

    def _actual_position(self, canonical_pos: Position) -> Position:
        return actual_position(canonical_pos, self.right_side is not False)

    def _destroy_at(self, ct: Controller, action: dict[str, Any]) -> bool:
        target = self._actual_position(_canonical_action_position(action))
        try:
            ct.destroy(target)
        except GameError as exc:
            self.last_action_note = (
                f"skipped destroy at {_format_position(target)}: {exc}"
            )
            return True
        self.last_action_note = f"destroyed at {_format_position(target)}"
        return True

    def _move_to(self, ct: Controller, action: dict[str, Any]) -> bool:
        target = self._actual_position(_canonical_action_position(action))
        current = ct.get_position()
        if target == current:
            self.last_action_note = f"already at {_format_position(target)}"
            return True

        direction = current.direction_to(target)
        prepared_road = False
        if not ct.can_move(direction):
            if not self._prepare_move_target(ct, target):
                return False
            prepared_road = True
            if not ct.can_move(direction):
                self.last_action_note = (
                    f"deferred move toward {_format_position(target)}: "
                    "target prepared but still blocked"
                )
                return False

        try:
            ct.move(direction)
        except GameError as exc:
            self.last_action_note = f"deferred move toward {_format_position(target)}: {exc}"
            return False
        if prepared_road:
            self.last_action_note = (
                f"built road and moved {direction.value} toward {_format_position(target)}"
            )
        else:
            self.last_action_note = (
                f"moved {direction.value} toward {_format_position(target)}"
            )
        return True

    def _prepare_move_target(self, ct: Controller, target: Position) -> bool:
        if ct.get_move_cooldown() > 0:
            self.last_action_note = (
                f"deferred move toward {_format_position(target)}: move cooldown"
            )
            return False

        try:
            building_id = ct.get_tile_building_id(target)
        except GameError as exc:
            self.last_action_note = (
                f"deferred move toward {_format_position(target)}: {exc}"
            )
            return False

        if building_id is not None:
            building_type = ct.get_entity_type(building_id)
            if _is_walkable_building(building_type):
                self.last_action_note = (
                    f"deferred move toward {_format_position(target)}: occupied"
                )
                return False
            self.last_action_note = (
                f"deferred move toward {_format_position(target)}: "
                f"blocked by {building_type.value}"
            )
            return False

        if ct.get_action_cooldown() > 0:
            self.last_action_note = (
                f"deferred move toward {_format_position(target)}: "
                "needs road but action cooldown"
            )
            return False

        if not self._can_afford_build(ct, EntityType.ROAD):
            titanium, axionite = ct.get_global_resources()
            titanium_cost, axionite_cost = self._build_cost(ct, EntityType.ROAD)
            self.last_action_note = (
                f"deferred move toward {_format_position(target)}: "
                f"road costs {titanium_cost}/{axionite_cost}, "
                f"resources {titanium}/{axionite}"
            )
            return False

        if not ct.can_build_road(target):
            self.last_action_note = (
                f"deferred move toward {_format_position(target)}: cannot build road"
            )
            return False

        try:
            ct.build_road(target)
        except GameError as exc:
            self.last_action_note = (
                f"deferred move toward {_format_position(target)}: "
                f"road build failed: {exc}"
            )
            return False
        return True

    def _build_at(self, ct: Controller, action: dict[str, Any]) -> bool:
        canonical_pos = _canonical_action_position(action)
        build_spec = action.get("building", _planned_building(canonical_pos))
        if build_spec is None:
            self.last_action_note = (
                f"skipped build at {_format_position(canonical_pos)}: no plan entry"
            )
            return True

        actual_pos = self._actual_position(canonical_pos)
        if isinstance(build_spec, str):
            build_spec = {"type": build_spec}

        entity_type = _entity_type(build_spec["type"])
        if not self._can_afford_build(ct, entity_type):
            titanium, axionite = ct.get_global_resources()
            titanium_cost, axionite_cost = self._build_cost(ct, entity_type)
            self.last_action_note = (
                f"deferred build {entity_type.value} at {_format_position(actual_pos)}: "
                f"resources {titanium}/{axionite}, need "
                f"{titanium_cost}/{axionite_cost}"
            )
            return False

        if entity_type == EntityType.BRIDGE:
            target = self._actual_position(_position(build_spec["target"]))
            if not ct.can_build_bridge(actual_pos, target):
                if ct.get_action_cooldown() > 0:
                    self.last_action_note = (
                        f"deferred build bridge at {_format_position(actual_pos)}: "
                        "action cooldown"
                    )
                    return False
                self.last_action_note = (
                    f"skipped build bridge at {_format_position(actual_pos)}: "
                    "can_build false"
                )
                return True
            try:
                ct.build_bridge(actual_pos, target)
            except GameError as exc:
                self.last_action_note = (
                    f"skipped build bridge at {_format_position(actual_pos)}: {exc}"
                )
                return True
            self.last_action_note = (
                f"built bridge at {_format_position(actual_pos)} "
                f"to {_format_position(target)}"
            )
            return True

        builder_name = _DIRECTIONAL_BUILDERS.get(entity_type)
        if builder_name is not None:
            direction = _mirror_direction(
                _direction(build_spec["direction"]),
                self.right_side is not False,
            )
            can_build = getattr(ct, builder_name.replace("build_", "can_build_"))
            if not can_build(actual_pos, direction):
                if ct.get_action_cooldown() > 0:
                    self.last_action_note = (
                        f"deferred build {entity_type.value} at "
                        f"{_format_position(actual_pos)}: action cooldown"
                    )
                    return False
                self.last_action_note = (
                    f"skipped build {entity_type.value} at "
                    f"{_format_position(actual_pos)}: can_build false"
                )
                return True
            try:
                getattr(ct, builder_name)(actual_pos, direction)
            except GameError as exc:
                self.last_action_note = (
                    f"skipped build {entity_type.value} at "
                    f"{_format_position(actual_pos)}: {exc}"
                )
                return True
            self.last_action_note = (
                f"built {entity_type.value} at {_format_position(actual_pos)} "
                f"toward {direction.value}"
            )
            return True

        builder_name = _POSITIONAL_BUILDERS[entity_type]
        can_build = getattr(ct, builder_name.replace("build_", "can_build_"))
        if not can_build(actual_pos):
            if ct.get_action_cooldown() > 0:
                self.last_action_note = (
                    f"deferred build {entity_type.value} at "
                    f"{_format_position(actual_pos)}: action cooldown"
                )
                return False
            self.last_action_note = (
                f"skipped build {entity_type.value} at "
                f"{_format_position(actual_pos)}: can_build false"
            )
            return True
        try:
            getattr(ct, builder_name)(actual_pos)
        except GameError as exc:
            self.last_action_note = (
                f"skipped build {entity_type.value} at "
                f"{_format_position(actual_pos)}: {exc}"
            )
            return True
        self.last_action_note = (
            f"built {entity_type.value} at {_format_position(actual_pos)}"
        )
        return True

    def _can_afford_build(self, ct: Controller, entity_type: EntityType) -> bool:
        titanium, axionite = ct.get_global_resources()
        titanium_cost, axionite_cost = self._build_cost(ct, entity_type)
        return titanium >= titanium_cost and axionite >= axionite_cost

    def _build_cost(self, ct: Controller, entity_type: EntityType) -> tuple[int, int]:
        return getattr(ct, f"get_{entity_type.value}_cost")()
