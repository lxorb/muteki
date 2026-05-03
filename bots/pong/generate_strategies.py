from __future__ import annotations

import argparse
import copy
import heapq
import json
from pathlib import Path
from typing import Any


BOT_ROOT = Path(__file__).resolve().parent
PLAN_PATH = BOT_ROOT / "plan.json"
MAP_PATH = BOT_ROOT / "pong_map.json"
CONFIG_PATH = BOT_ROOT / "strategy_config.json"
SPAWNS_PATH = BOT_ROOT / "spawns.json"
STRATEGY_ROOT = BOT_ROOT / "strategies"

RIGHT_MIN_X = 25
CORE_TILES = {(x, y) for x in range(40, 43) for y in range(7, 10)}
WALKABLE_TYPES = {"conveyor", "road", "bridge", "armoured_conveyor"}
BUILDER_RANGE_SQ = 2
ORTHOGONAL_STEPS = ((0, -1), (1, 0), (0, 1), (-1, 0))
FLOW_DIRECTIONS = {
    "north": (0, -1),
    "east": (1, 0),
    "south": (0, 1),
    "west": (-1, 0),
}

SPAWNS = {
    1: {"turn": 0, "tile": (40, 9)},
    2: {"turn": 1, "tile": (42, 9)},
    3: {"turn": 2, "tile": (40, 7)},
}

TEMP_BOUNDS = {
    1: (29, 41, 7, 22),
    2: (42, 49, 3, 22),
    3: (36, 43, 3, 22),
}

DEFAULT_CONFIG: dict[str, Any] = {
    "spawns": [
        {"turn": 0, "tile": [40, 9]},
        {"turn": 1, "tile": [42, 9]},
        {"turn": 2, "tile": [40, 7]},
    ],
    "owner_policy": {
        "mode": "thresholds",
        "left_x": 36,
        "center_left_x": 40,
        "center_y_min": 10,
        "center_y_max": 13,
        "right_x": 43,
        "fallback_owner": 3,
        "rules": [],
    },
    "temp_bounds": {
        "1": [29, 41, 7, 22],
        "2": [42, 49, 3, 22],
        "3": [36, 43, 3, 22],
    },
    "auto_temp_bounds": False,
    "temp_margin": 2,
    "phase": {
        "titanium_path_base": 0,
        "titanium_path_weight": 2,
        "titanium_harvester_base": 1,
        "titanium_harvester_weight": 2,
        "foundry_base": 900,
        "foundry_core_weight": 1,
        "generic_walkable_base": 1000,
        "generic_walkable_flow_weight": 1,
        "axionite_harvester_base": 2000,
        "axionite_harvester_core_weight": 1,
        "other_base": 3000,
        "other_core_weight": 1,
    },
    "target_scoring": {
        "path_weight": 10,
        "manhattan_weight": 1,
        "flow_weight": 0,
        "core_distance_weight": 0,
    },
    "cleanup": {
        "mode": "nearest",
    },
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = copy.deepcopy(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged.get(key), value)
        return merged
    if override is None:
        return copy.deepcopy(base)
    return copy.deepcopy(override)


def normalize_config(raw_config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = deep_merge(DEFAULT_CONFIG, raw_config or {})
    spawns = {}
    for index, raw_spawn in enumerate(config["spawns"], start=1):
        spawns[index] = {
            "turn": int(raw_spawn["turn"]),
            "tile": _tuple_position(raw_spawn["tile"]),
        }
    config["_spawns_by_builder"] = spawns
    config["_builder_numbers"] = tuple(sorted(spawns))
    return config


def _tuple_position(raw: Any) -> tuple[int, int]:
    if isinstance(raw, str):
        x, y = raw.split(",", 1)
        return int(x), int(y)
    if isinstance(raw, dict):
        return int(raw["x"]), int(raw["y"])
    return int(raw[0]), int(raw[1])


def tile_key(pos: tuple[int, int]) -> str:
    return f"{pos[0]},{pos[1]}"


def distance_sq(a: tuple[int, int], b: tuple[int, int]) -> int:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def spec_type(spec: Any) -> str:
    if isinstance(spec, str):
        return spec
    return spec["type"]


def is_walkable_spec(spec: Any) -> bool:
    return spec_type(spec) in WALKABLE_TYPES


def flow_target(pos: tuple[int, int], spec: Any) -> tuple[int, int] | None:
    if isinstance(spec, str):
        return None
    kind = spec["type"]
    if kind == "conveyor":
        dx, dy = FLOW_DIRECTIONS[spec["direction"]]
        return pos[0] + dx, pos[1] + dy
    if kind == "bridge":
        return tuple(spec["target"])
    return None


def compute_flow_distances(
    final_tiles: dict[tuple[int, int], Any],
) -> dict[tuple[int, int], int]:
    distances = {core_tile: 0 for core_tile in CORE_TILES}
    changed = True
    while changed:
        changed = False
        for pos, spec in final_tiles.items():
            target = flow_target(pos, spec)
            if target is None or target not in distances:
                continue
            distance = distances[target] + 1
            if distance < distances.get(pos, 1_000_000):
                distances[pos] = distance
                changed = True
    return distances


def compute_titanium_supply_priorities(
    final_tiles: dict[tuple[int, int], Any],
    rows: list[list[int]],
    flow_distances: dict[tuple[int, int], int],
) -> tuple[set[tuple[int, int]], dict[tuple[int, int], int]]:
    supply_tiles: set[tuple[int, int]] = set()
    harvester_distances: dict[tuple[int, int], int] = {}

    for pos, spec in final_tiles.items():
        if spec_type(spec) != "harvester" or rows[pos[1]][pos[0]] != 2:
            continue

        adjacent_outputs = []
        for dx, dy in ORTHOGONAL_STEPS:
            neighbor = pos[0] + dx, pos[1] + dy
            if neighbor in flow_distances:
                adjacent_outputs.append(neighbor)

        if not adjacent_outputs:
            continue

        best_output = min(adjacent_outputs, key=lambda tile: flow_distances[tile])
        harvester_distances[pos] = flow_distances[best_output] + 1

        current: tuple[int, int] | None = best_output
        seen: set[tuple[int, int]] = set()
        while current is not None and current not in CORE_TILES and current not in seen:
            seen.add(current)
            supply_tiles.add(current)
            current_spec = final_tiles.get(current)
            current = flow_target(current, current_spec) if current_spec is not None else None

    return supply_tiles, harvester_distances


def build_action(pos: tuple[int, int], building: Any | None = None) -> dict[str, Any]:
    action: dict[str, Any] = {"action": "build", "at": [pos[0], pos[1]]}
    if building is not None:
        action["building"] = building
    return action


def move_action(pos: tuple[int, int]) -> dict[str, Any]:
    return {"action": "move_to", "to": [pos[0], pos[1]]}


def destroy_action(pos: tuple[int, int]) -> dict[str, Any]:
    return {"action": "destroy", "at": [pos[0], pos[1]]}


class BuilderPlan:
    def __init__(
        self,
        builder: int,
        spawn: tuple[int, int],
        rows: list[list[int]],
        final_tiles: dict[tuple[int, int], Any],
        owner: dict[tuple[int, int], int],
        temp_bounds: tuple[int, int, int, int],
        cleanup_mode: str,
    ) -> None:
        self.builder = builder
        self.pos = spawn
        self.rows = rows
        self.final_tiles = final_tiles
        self.owner = owner
        self.temp_bounds = temp_bounds
        self.cleanup_mode = cleanup_mode
        self.turn = 1
        self.turns: dict[str, list[dict[str, Any]]] = {}
        self.built_final: set[tuple[int, int]] = set()
        self.walkable: set[tuple[int, int]] = set(CORE_TILES)
        self.temp_roads: set[tuple[int, int]] = set()
        self.temp_build_order: list[tuple[int, int]] = []

    def add_turn(self, actions: list[dict[str, Any]]) -> None:
        self.turns[str(self.turn)] = actions
        self.turn += 1

    def terrain(self, pos: tuple[int, int]) -> int:
        return self.rows[pos[1]][pos[0]]

    def in_map(self, pos: tuple[int, int]) -> bool:
        x, y = pos
        return RIGHT_MIN_X <= x < len(self.rows[0]) and 0 <= y < len(self.rows)

    def in_temp_bounds(self, pos: tuple[int, int]) -> bool:
        min_x, max_x, min_y, max_y = self.temp_bounds
        return min_x <= pos[0] <= max_x and min_y <= pos[1] <= max_y

    def can_step_on(self, pos: tuple[int, int]) -> bool:
        if not self.in_map(pos) or self.terrain(pos) != 0:
            return pos in self.walkable
        if pos in self.walkable:
            return True
        spec = self.final_tiles.get(pos)
        if spec is None:
            return self.in_temp_bounds(pos)
        return is_walkable_spec(spec) and self.owner[pos] == self.builder

    def step_cost(self, pos: tuple[int, int]) -> int:
        if pos in self.walkable:
            return 1
        spec = self.final_tiles.get(pos)
        if spec is not None and is_walkable_spec(spec) and self.owner[pos] == self.builder:
            return 2
        return 5

    def neighbors(self, pos: tuple[int, int]) -> list[tuple[int, int]]:
        result = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                candidate = (pos[0] + dx, pos[1] + dy)
                if self.can_step_on(candidate):
                    result.append(candidate)
        return result

    def path_to_any(
        self,
        goals: set[tuple[int, int]],
        allow_new_builds: bool = True,
    ) -> list[tuple[int, int]] | None:
        if self.pos in goals:
            return []

        queue: list[tuple[int, int, tuple[int, int]]] = [(0, 0, self.pos)]
        best = {self.pos: 0}
        previous: dict[tuple[int, int], tuple[int, int]] = {}
        counter = 1

        while queue:
            cost, _, pos = heapq.heappop(queue)
            if cost != best[pos]:
                continue
            if pos in goals:
                path = []
                current = pos
                while current != self.pos:
                    path.append(current)
                    current = previous[current]
                path.reverse()
                return path

            for neighbor in self.neighbors(pos):
                if not allow_new_builds and neighbor not in self.walkable:
                    continue
                next_cost = cost + self.step_cost(neighbor)
                if next_cost >= best.get(neighbor, 1_000_000):
                    continue
                best[neighbor] = next_cost
                previous[neighbor] = pos
                heapq.heappush(queue, (next_cost, counter, neighbor))
                counter += 1

        return None

    def walkable_path_to_any(
        self,
        start: tuple[int, int],
        goals: set[tuple[int, int]],
        walkable: set[tuple[int, int]],
    ) -> list[tuple[int, int]] | None:
        if start in goals:
            return []

        queue: list[tuple[int, tuple[int, int]]] = [(0, start)]
        seen = {start}
        previous: dict[tuple[int, int], tuple[int, int]] = {}

        while queue:
            _, pos = heapq.heappop(queue)
            if pos in goals:
                path = []
                current = pos
                while current != start:
                    path.append(current)
                    current = previous[current]
                path.reverse()
                return path

            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    neighbor = (pos[0] + dx, pos[1] + dy)
                    if neighbor in seen or neighbor not in walkable:
                        continue
                    seen.add(neighbor)
                    previous[neighbor] = pos
                    heapq.heappush(queue, (len(seen), neighbor))

        return None

    def stand_goals_for(self, target: tuple[int, int]) -> set[tuple[int, int]]:
        goals = set()
        target_spec = self.final_tiles[target]
        for x in range(target[0] - 1, target[0] + 2):
            for y in range(target[1] - 1, target[1] + 2):
                pos = (x, y)
                if distance_sq(pos, target) > BUILDER_RANGE_SQ:
                    continue
                if pos == target and not (is_walkable_spec(target_spec) and pos in self.walkable):
                    continue
                if self.can_step_on(pos):
                    goals.add(pos)
        return goals

    def materialize_path(self, path: list[tuple[int, int]]) -> None:
        for step in path:
            if step in self.walkable:
                self.add_turn([move_action(step)])
                self.pos = step
                continue

            spec = self.final_tiles.get(step)
            if spec is not None and is_walkable_spec(spec) and self.owner[step] == self.builder:
                self.add_turn([build_action(step), move_action(step)])
                self.built_final.add(step)
                self.walkable.add(step)
                self.pos = step
                continue

            self.add_turn([move_action(step)])
            self.walkable.add(step)
            self.temp_roads.add(step)
            self.temp_build_order.append(step)
            self.pos = step

    def build_target(self, target: tuple[int, int]) -> None:
        if target in self.built_final:
            return

        goals = self.stand_goals_for(target)
        path = self.path_to_any(goals)
        if path is None:
            raise RuntimeError(f"builder {self.builder} cannot reach {target}")
        self.materialize_path(path)

        if target in self.built_final:
            return
        if distance_sq(self.pos, target) > BUILDER_RANGE_SQ:
            raise RuntimeError(f"builder {self.builder} is out of range for {target}")

        self.add_turn([build_action(target)])
        self.built_final.add(target)
        if is_walkable_spec(self.final_tiles[target]):
            self.walkable.add(target)

    def cleanup_temp_roads(self) -> int:
        destroyed = 0
        while True:
            best: tuple[int, tuple[int, int], list[tuple[int, int]]] | None = None
            for road in self.temp_roads:
                goals = {
                    pos
                    for pos in self.walkable
                    if pos != road and distance_sq(pos, road) <= BUILDER_RANGE_SQ
                }
                path = self.walkable_path_to_any(self.pos, goals, self.walkable)
                if path is None:
                    continue
                destroy_pos = path[-1] if path else self.pos
                walkable_after = set(self.walkable)
                walkable_after.remove(road)
                if not self._remaining_temp_roads_reachable(
                    destroy_pos,
                    road,
                    walkable_after,
                ):
                    continue
                candidate = (len(path), road, path)
                if self.cleanup_mode == "farthest":
                    is_better = best is None or candidate > best
                else:
                    is_better = best is None or candidate < best
                if is_better:
                    best = candidate

            if best is None:
                break
            _, road, path = best
            self.materialize_path(path)
            self.add_turn([destroy_action(road)])
            self.temp_roads.remove(road)
            self.walkable.remove(road)
            destroyed += 1
        return destroyed

    def _remaining_temp_roads_reachable(
        self,
        start: tuple[int, int],
        removed_road: tuple[int, int],
        walkable: set[tuple[int, int]],
    ) -> bool:
        for road in self.temp_roads:
            if road == removed_road:
                continue
            goals = {
                pos
                for pos in walkable
                if pos != road and distance_sq(pos, road) <= BUILDER_RANGE_SQ
            }
            if self.walkable_path_to_any(start, goals, walkable) is None:
                return False
        return True


def nearest_owner(
    pos: tuple[int, int],
    spawns: dict[int, dict[str, Any]],
) -> int:
    return min(
        spawns,
        key=lambda builder: (
            distance_sq(pos, spawns[builder]["tile"]),
            builder,
        ),
    )


def owner_for(
    pos: tuple[int, int],
    config: dict[str, Any],
) -> int:
    spawns: dict[int, dict[str, Any]] = config["_spawns_by_builder"]
    policy = config["owner_policy"]

    for rule in policy.get("rules", []):
        min_x = int(rule.get("min_x", RIGHT_MIN_X))
        max_x = int(rule.get("max_x", 10_000))
        min_y = int(rule.get("min_y", 0))
        max_y = int(rule.get("max_y", 10_000))
        if min_x <= pos[0] <= max_x and min_y <= pos[1] <= max_y:
            owner = int(rule["owner"])
            return owner if owner in spawns else nearest_owner(pos, spawns)

    if policy.get("mode") == "nearest":
        return nearest_owner(pos, spawns)

    x, y = pos
    if x <= int(policy["left_x"]) or (
        x <= int(policy["center_left_x"])
        and int(policy["center_y_min"]) <= y <= int(policy["center_y_max"])
    ):
        owner = 1
    elif x >= int(policy["right_x"]):
        owner = 2
    else:
        owner = int(policy["fallback_owner"])
    return owner if owner in spawns else nearest_owner(pos, spawns)


def temp_bounds_for(
    builder: int,
    assigned: list[tuple[int, int]],
    spawn: tuple[int, int],
    rows: list[list[int]],
    config: dict[str, Any],
) -> tuple[int, int, int, int]:
    raw_bounds = config.get("temp_bounds", {}).get(str(builder))
    if raw_bounds is not None and not config.get("auto_temp_bounds", False):
        return tuple(int(value) for value in raw_bounds)

    margin = int(config.get("temp_margin", 2))
    points = [spawn, *assigned, *CORE_TILES]
    min_x = max(RIGHT_MIN_X, min(x for x, _ in points) - margin)
    max_x = min(len(rows[0]) - 1, max(x for x, _ in points) + margin)
    min_y = max(0, min(y for _, y in points) - margin)
    max_y = min(len(rows) - 1, max(y for _, y in points) + margin)
    return min_x, max_x, min_y, max_y


def target_phase(
    pos: tuple[int, int],
    spec: Any,
    rows: list[list[int]],
    flow_distances: dict[tuple[int, int], int],
    titanium_supply_tiles: set[tuple[int, int]],
    titanium_harvester_distances: dict[tuple[int, int], int],
    config: dict[str, Any],
) -> tuple[int, int, int, int]:
    kind = spec_type(spec)
    terrain = rows[pos[1]][pos[0]]
    core_distance = abs(pos[0] - 41) + abs(pos[1] - 8)
    flow_distance = flow_distances.get(pos, core_distance + 100)
    phase_config = config["phase"]
    if kind in WALKABLE_TYPES and pos in titanium_supply_tiles:
        phase = (
            int(phase_config["titanium_path_base"])
            + flow_distance * int(phase_config["titanium_path_weight"])
        )
    elif kind == "harvester" and terrain == 2:
        phase = (
            int(phase_config["titanium_harvester_base"])
            + titanium_harvester_distances.get(pos, 500)
            * int(phase_config["titanium_harvester_weight"])
        )
    elif kind in WALKABLE_TYPES:
        phase = (
            int(phase_config["generic_walkable_base"])
            + flow_distance * int(phase_config["generic_walkable_flow_weight"])
        )
    elif kind == "foundry":
        phase = (
            int(phase_config["foundry_base"])
            + core_distance * int(phase_config["foundry_core_weight"])
        )
    elif kind == "harvester":
        phase = (
            int(phase_config["axionite_harvester_base"])
            + core_distance * int(phase_config["axionite_harvester_core_weight"])
        )
    else:
        phase = (
            int(phase_config["other_base"])
            + core_distance * int(phase_config["other_core_weight"])
        )
    return phase, flow_distance, pos[1], pos[0]


def choose_next_target(
    planner: BuilderPlan,
    targets: list[tuple[int, int]],
    flow_distances: dict[tuple[int, int], int],
    config: dict[str, Any],
) -> tuple[int, int]:
    best_target = targets[0]
    best_score = 1_000_000_000
    scoring = config["target_scoring"]
    for target in targets:
        goals = planner.stand_goals_for(target)
        path = planner.path_to_any(goals)
        if path is None:
            continue
        manhattan = abs(target[0] - planner.pos[0]) + abs(target[1] - planner.pos[1])
        core_distance = abs(target[0] - 41) + abs(target[1] - 8)
        score = (
            len(path) * int(scoring["path_weight"])
            + manhattan * int(scoring["manhattan_weight"])
            + flow_distances.get(target, core_distance + 100)
            * int(scoring["flow_weight"])
            + core_distance * int(scoring["core_distance_weight"])
        )
        if score < best_score:
            best_score = score
            best_target = target
    return best_target


def generate(
    raw_config: dict[str, Any] | None = None,
    plan_path: Path = PLAN_PATH,
    map_path: Path = MAP_PATH,
    spawns_path: Path = SPAWNS_PATH,
    strategy_root: Path = STRATEGY_ROOT,
    cleanup_stale: bool = True,
) -> dict[str, Any]:
    config = normalize_config(raw_config)
    spawns: dict[int, dict[str, Any]] = config["_spawns_by_builder"]
    plan = load_json(plan_path)
    map_data = load_json(map_path)
    rows = map_data["rows"]

    final_tiles: dict[tuple[int, int], Any] = {}
    for raw_key, spec in plan["tiles"].items():
        if spec is None:
            continue
        pos = tuple(int(part) for part in raw_key.split(",", 1))
        if pos[0] < RIGHT_MIN_X or pos in CORE_TILES:
            continue
        final_tiles[pos] = spec

    flow_distances = compute_flow_distances(final_tiles)
    titanium_supply_tiles, titanium_harvester_distances = (
        compute_titanium_supply_priorities(final_tiles, rows, flow_distances)
    )

    owner = {pos: owner_for(pos, config) for pos in final_tiles}

    assigned_by_builder = {
        builder: [pos for pos in final_tiles if owner[pos] == builder]
        for builder in spawns
    }
    temp_bounds = {
        builder: temp_bounds_for(
            builder,
            assigned_by_builder[builder],
            spawn["tile"],
            rows,
            config,
        )
        for builder, spawn in spawns.items()
    }
    planners = {
        builder: BuilderPlan(
            builder,
            spawn["tile"],
            rows,
            final_tiles,
            owner,
            temp_bounds[builder],
            config["cleanup"].get("mode", "nearest"),
        )
        for builder, spawn in spawns.items()
    }

    for builder, planner in planners.items():
        assigned = assigned_by_builder[builder]
        phases = sorted(
            {
                target_phase(
                    pos,
                    final_tiles[pos],
                    rows,
                    flow_distances,
                    titanium_supply_tiles,
                    titanium_harvester_distances,
                    config,
                )[0]
                for pos in assigned
            }
        )
        for phase in phases:
            phase_targets = [
                pos
                for pos in assigned
                if target_phase(
                    pos,
                    final_tiles[pos],
                    rows,
                    flow_distances,
                    titanium_supply_tiles,
                    titanium_harvester_distances,
                    config,
                )[0]
                == phase
            ]
            phase_targets.sort(
                key=lambda pos: target_phase(
                    pos,
                    final_tiles[pos],
                    rows,
                    flow_distances,
                    titanium_supply_tiles,
                    titanium_harvester_distances,
                    config,
                )
            )
            while phase_targets:
                target = choose_next_target(
                    planner,
                    phase_targets,
                    flow_distances,
                    config,
                )
                planner.build_target(target)
                phase_targets.remove(target)
        planner.cleanup_temp_roads()

    write_json(
        spawns_path,
        {
            "builders": [
                {"turn": spawn["turn"], "tile": list(spawn["tile"])}
                for _, spawn in sorted(spawns.items())
            ]
        },
    )

    strategy_root.mkdir(parents=True, exist_ok=True)
    if cleanup_stale:
        active_files = {f"{builder}.json" for builder in planners}
        for path in strategy_root.glob("*.json"):
            if path.name not in active_files:
                path.unlink()

    summary = {"builders": {}}
    for builder, planner in planners.items():
        payload = {"turns": planner.turns}
        write_json(strategy_root / f"{builder}.json", payload)
        summary["builders"][str(builder)] = {
            "turns": max((int(turn) for turn in planner.turns), default=0),
            "actions": sum(len(actions) for actions in planner.turns.values()),
            "final_builds": len(planner.built_final),
            "temp_roads_remaining": len(planner.temp_roads),
            "assigned_final_builds": len(assigned_by_builder[builder]),
            "temp_bounds": list(temp_bounds[builder]),
        }

    summary["final_tile_count"] = len(final_tiles)
    summary["planned_final_builds"] = sum(len(planner.built_final) for planner in planners.values())
    summary["config"] = {
        key: value
        for key, value in config.items()
        if not key.startswith("_")
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate feasible hardcoded pong builder strategies."
    )
    parser.add_argument(
        "--config",
        type=Path,
        help=(
            "Optional strategy config JSON. Defaults to strategy_config.json "
            "when that file exists."
        ),
    )
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    parser.add_argument("--map", type=Path, default=MAP_PATH)
    parser.add_argument("--spawns-out", type=Path, default=SPAWNS_PATH)
    parser.add_argument("--strategy-root", type=Path, default=STRATEGY_ROOT)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--no-cleanup-stale", action="store_true")
    args = parser.parse_args()

    config_path = args.config
    if config_path is None and CONFIG_PATH.exists():
        config_path = CONFIG_PATH
    raw_config = load_json(config_path) if config_path else None
    summary = generate(
        raw_config=raw_config,
        plan_path=args.plan,
        map_path=args.map,
        spawns_path=args.spawns_out,
        strategy_root=args.strategy_root,
        cleanup_stale=not args.no_cleanup_stale,
    )
    if args.summary_out:
        write_json(args.summary_out, summary)
    if not args.quiet:
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
