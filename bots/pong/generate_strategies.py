from __future__ import annotations

import heapq
import json
from pathlib import Path
from typing import Any


BOT_ROOT = Path(__file__).resolve().parent
PLAN_PATH = BOT_ROOT / "plan.json"
MAP_PATH = BOT_ROOT / "pong_map.json"
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


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


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
    ) -> None:
        self.builder = builder
        self.pos = spawn
        self.rows = rows
        self.final_tiles = final_tiles
        self.owner = owner
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
        min_x, max_x, min_y, max_y = TEMP_BOUNDS[self.builder]
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
                if best is None or candidate < best:
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


def owner_for(pos: tuple[int, int]) -> int:
    x, y = pos
    if x <= 36 or (x <= 40 and 10 <= y <= 13):
        return 1
    if x >= 43:
        return 2
    return 3


def target_phase(
    pos: tuple[int, int],
    spec: Any,
    rows: list[list[int]],
    flow_distances: dict[tuple[int, int], int],
    titanium_supply_tiles: set[tuple[int, int]],
    titanium_harvester_distances: dict[tuple[int, int], int],
) -> tuple[int, int, int, int]:
    kind = spec_type(spec)
    terrain = rows[pos[1]][pos[0]]
    core_distance = abs(pos[0] - 41) + abs(pos[1] - 8)
    flow_distance = flow_distances.get(pos, core_distance + 100)
    if kind in WALKABLE_TYPES and pos in titanium_supply_tiles:
        phase = flow_distance * 2
    elif kind == "harvester" and terrain == 2:
        phase = titanium_harvester_distances.get(pos, 500) * 2 + 1
    elif kind in WALKABLE_TYPES:
        phase = 1000 + flow_distance
    elif kind == "bridge":
        phase = 1100 + core_distance
    elif kind == "foundry":
        phase = 1800 + core_distance
    elif kind == "harvester":
        phase = 2000 + core_distance
    else:
        phase = 3000 + core_distance
    return phase, flow_distance, pos[1], pos[0]


def choose_next_target(
    planner: BuilderPlan,
    targets: list[tuple[int, int]],
) -> tuple[int, int]:
    best_target = targets[0]
    best_score = 1_000_000
    for target in targets:
        goals = planner.stand_goals_for(target)
        path = planner.path_to_any(goals)
        if path is None:
            continue
        score = len(path) * 10 + abs(target[0] - planner.pos[0]) + abs(target[1] - planner.pos[1])
        if score < best_score:
            best_score = score
            best_target = target
    return best_target


def generate() -> dict[str, Any]:
    plan = load_json(PLAN_PATH)
    map_data = load_json(MAP_PATH)
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

    owner = {pos: owner_for(pos) for pos in final_tiles}
    planners = {
        builder: BuilderPlan(builder, spawn["tile"], rows, final_tiles, owner)
        for builder, spawn in SPAWNS.items()
    }

    for builder, planner in planners.items():
        assigned = [pos for pos in final_tiles if owner[pos] == builder]
        phases = sorted(
            {
                target_phase(
                    pos,
                    final_tiles[pos],
                    rows,
                    flow_distances,
                    titanium_supply_tiles,
                    titanium_harvester_distances,
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
                )
            )
            while phase_targets:
                target = choose_next_target(planner, phase_targets)
                planner.build_target(target)
                phase_targets.remove(target)
        planner.cleanup_temp_roads()

    write_json(
        SPAWNS_PATH,
        {
            "builders": [
                {"turn": spawn["turn"], "tile": list(spawn["tile"])}
                for _, spawn in sorted(SPAWNS.items())
            ]
        },
    )

    STRATEGY_ROOT.mkdir(parents=True, exist_ok=True)
    summary = {"builders": {}}
    for builder, planner in planners.items():
        payload = {"turns": planner.turns}
        write_json(STRATEGY_ROOT / f"{builder}.json", payload)
        summary["builders"][str(builder)] = {
            "turns": max((int(turn) for turn in planner.turns), default=0),
            "actions": sum(len(actions) for actions in planner.turns.values()),
            "final_builds": len(planner.built_final),
            "temp_roads_remaining": len(planner.temp_roads),
        }

    summary["final_tile_count"] = len(final_tiles)
    summary["planned_final_builds"] = sum(len(planner.built_final) for planner in planners.values())
    return summary


def main() -> int:
    print(json.dumps(generate(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
