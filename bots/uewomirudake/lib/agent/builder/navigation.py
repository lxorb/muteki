import math
import time
from array import array
from collections.abc import Callable
from heapq import heappop, heappush

from cambc import Direction, EntityType, Environment, GameConstants, Position

from lib.agent.constants import (
    ATTACK_TURRET_TYPES,
    ATTACK_TURRET_FEEDER_TYPES,
    BUILD_ACTION_MIN_TITANIUM_BASE,
    BRIDGE_PREFERRED_DIST,
    BUILDER_ACTION_RADIUS_SQ,
    CONVEYOR_ENTITY_TYPES,
    DISABLE_CONVEYORS_POINTING_AT_HARVESTERS,
    DIRECTIONAL_BUILDING_TYPES,
    ENEMY_TURRET_TYPES,
    HARASSMENT_STRATEGY_ID,
    HARD_AVOID_EXISTING_SUPPLY_CHAIN,
    NONDIRECTIONAL_BUILDING_TYPES,
    REPLACE_ATTACKED_CONVEYOR_MAX_HP,
)
from lib.map.constants import DIRECTIONS, INF_DIST, SUPPLY_LINK_TYPES
from lib.map.types import SupplyChainLabel

_BRIDGE_R = int(GameConstants.BRIDGE_TARGET_RADIUS_SQ**0.5) + 1
_BRIDGE_TARGET_OFFSETS: tuple[tuple[int, int], ...] = tuple(
    (dx, dy)
    for dx in range(-_BRIDGE_R, _BRIDGE_R + 1)
    for dy in range(-_BRIDGE_R, _BRIDGE_R + 1)
    if 0 < dx * dx + dy * dy <= GameConstants.BRIDGE_TARGET_RADIUS_SQ
    and abs(dx) + abs(dy) != 1
)
_RESOURCE_ENVIRONMENTS = frozenset(
    (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE)
)
_CARDINAL_DIRECTIONS = tuple(
    direction
    for direction in Direction
    if direction != Direction.CENTRE and sum(abs(delta) for delta in direction.delta()) == 1
)
_ADJACENT_DIRECTION_CANDIDATES_BY_DIRECTION = {
    direction: (
        direction,
        DIRECTIONS[(idx - 1) % len(DIRECTIONS)],
        DIRECTIONS[(idx + 1) % len(DIRECTIONS)],
    )
    for idx, direction in enumerate(DIRECTIONS)
}
_EMPTY_SOURCE_INDEX_SET = frozenset()
_INCREMENTAL_PATH_INF = 0x3FFFFFFF
_INCREMENTAL_OVERTIME_CHECK_INTERVAL = 16
_INCREMENTAL_QUEUE_REBUILD_FACTOR = 8


def _u_chebyshev_dist_by_index(
    left_idx: int,
    right_idx: int,
    index_x_by_index,
    index_y_by_index,
) -> int:
    dx = index_x_by_index[left_idx] - index_x_by_index[right_idx]
    if dx < 0:
        dx = -dx
    dy = index_y_by_index[left_idx] - index_y_by_index[right_idx]
    if dy < 0:
        dy = -dy
    return dx if dx >= dy else dy


class _IncrementalShortestPathState:
    __slots__ = (
        "use_d_star_lite",
        "tile_count",
        "target_idx",
        "avoid_enemy_turrets",
        "reach_builder_action_range",
        "last_source_idx",
        "km",
        "queue",
        "inf_cost_by_index",
        "g_by_index",
        "rhs_by_index",
        "passable_mask_by_index",
        "goal_mask_by_index",
    )

    def __init__(self, use_d_star_lite: bool):
        self.use_d_star_lite = use_d_star_lite
        self.tile_count = 0
        self.target_idx = -1
        self.avoid_enemy_turrets = True
        self.reach_builder_action_range = False
        self.last_source_idx = -1
        self.km = 0
        self.queue: list[tuple[int, int, int]] = []
        self.inf_cost_by_index = array("I")
        self.g_by_index = array("I")
        self.rhs_by_index = array("I")
        self.passable_mask_by_index = bytearray()
        self.goal_mask_by_index = bytearray()

    def u_ensure_capacity(self, tile_count: int) -> None:
        if self.tile_count == tile_count:
            return
        self.tile_count = tile_count
        self.inf_cost_by_index = array("I", [_INCREMENTAL_PATH_INF]) * tile_count
        self.g_by_index = array("I", self.inf_cost_by_index)
        self.rhs_by_index = array("I", self.inf_cost_by_index)
        self.passable_mask_by_index = bytearray(tile_count)
        self.goal_mask_by_index = bytearray(tile_count)
        self.queue = []

    def u_calculate_key(
        self,
        source_idx: int,
        idx: int,
        index_x_by_index,
        index_y_by_index,
    ) -> tuple[int, int]:
        best_cost = self.g_by_index[idx]
        rhs_cost = self.rhs_by_index[idx]
        if rhs_cost < best_cost:
            best_cost = rhs_cost
        heuristic = _u_chebyshev_dist_by_index(
            source_idx,
            idx,
            index_x_by_index,
            index_y_by_index,
        )
        if self.use_d_star_lite:
            heuristic += self.km
        return (best_cost + heuristic, best_cost)

    def u_push_inconsistent(
        self,
        source_idx: int,
        idx: int,
        index_x_by_index,
        index_y_by_index,
    ) -> None:
        if self.g_by_index[idx] == self.rhs_by_index[idx]:
            return
        key_1, key_2 = self.u_calculate_key(
            source_idx,
            idx,
            index_x_by_index,
            index_y_by_index,
        )
        heappush(self.queue, (key_1, key_2, idx))

    def u_reset(
        self,
        source_idx: int,
        target_idx: int,
        avoid_enemy_turrets: bool,
        reach_builder_action_range: bool,
        passable_mask_by_index: bytearray,
        goal_mask_by_index: bytearray,
        index_x_by_index,
        index_y_by_index,
    ) -> None:
        self.target_idx = target_idx
        self.avoid_enemy_turrets = avoid_enemy_turrets
        self.reach_builder_action_range = reach_builder_action_range
        self.last_source_idx = source_idx
        self.km = 0
        self.g_by_index[:] = self.inf_cost_by_index
        self.rhs_by_index[:] = self.inf_cost_by_index
        self.passable_mask_by_index[:] = passable_mask_by_index
        self.goal_mask_by_index[:] = goal_mask_by_index
        self.queue.clear()
        for idx in range(self.tile_count):
            if not goal_mask_by_index[idx]:
                continue
            self.rhs_by_index[idx] = 0
            self.u_push_inconsistent(
                source_idx,
                idx,
                index_x_by_index,
                index_y_by_index,
            )

    def u_update_vertex(
        self,
        map,
        source_idx: int,
        idx: int,
        index_x_by_index,
        index_y_by_index,
    ) -> None:
        if self.goal_mask_by_index[idx]:
            self.rhs_by_index[idx] = 0
        elif not self.passable_mask_by_index[idx]:
            self.rhs_by_index[idx] = _INCREMENTAL_PATH_INF
        else:
            best_cost = _INCREMENTAL_PATH_INF
            neighbor_base = idx * map.MAX_NEIGHBOR_COUNT
            neighbor_count = map.neighbor_count_by_index[idx]
            for offset in range(neighbor_count):
                neighbor_idx = map.neighbor_indices_by_index[neighbor_base + offset]
                if not self.passable_mask_by_index[neighbor_idx]:
                    continue
                candidate_cost = self.g_by_index[neighbor_idx] + 1
                if candidate_cost < best_cost:
                    best_cost = candidate_cost
            self.rhs_by_index[idx] = best_cost
        self.u_push_inconsistent(
            source_idx,
            idx,
            index_x_by_index,
            index_y_by_index,
        )

    def u_rebuild_queue(
        self,
        source_idx: int,
        index_x_by_index,
        index_y_by_index,
    ) -> None:
        self.queue.clear()
        for idx in range(self.tile_count):
            if self.g_by_index[idx] == self.rhs_by_index[idx]:
                continue
            self.u_push_inconsistent(
                source_idx,
                idx,
                index_x_by_index,
                index_y_by_index,
            )

    def u_apply_graph_changes(
        self,
        map,
        source_idx: int,
        passable_mask_by_index: bytearray,
        goal_mask_by_index: bytearray,
        index_x_by_index,
        index_y_by_index,
    ) -> None:
        changed_indices: list[int] = []
        current_passable_mask_by_index = self.passable_mask_by_index
        current_goal_mask_by_index = self.goal_mask_by_index
        for idx in range(self.tile_count):
            if (
                current_passable_mask_by_index[idx] == passable_mask_by_index[idx]
                and current_goal_mask_by_index[idx] == goal_mask_by_index[idx]
            ):
                continue
            current_passable_mask_by_index[idx] = passable_mask_by_index[idx]
            current_goal_mask_by_index[idx] = goal_mask_by_index[idx]
            changed_indices.append(idx)

        if not changed_indices:
            return

        for idx in changed_indices:
            self.u_update_vertex(
                map,
                source_idx,
                idx,
                index_x_by_index,
                index_y_by_index,
            )
            neighbor_base = idx * map.MAX_NEIGHBOR_COUNT
            neighbor_count = map.neighbor_count_by_index[idx]
            for offset in range(neighbor_count):
                neighbor_idx = map.neighbor_indices_by_index[neighbor_base + offset]
                if not map.active_mask_by_index[neighbor_idx]:
                    continue
                self.u_update_vertex(
                    map,
                    source_idx,
                    neighbor_idx,
                    index_x_by_index,
                    index_y_by_index,
                )

    def u_compute_shortest_path(
        self,
        map,
        source_idx: int,
        index_x_by_index,
        index_y_by_index,
    ) -> bool:
        check_overtime_interval = map.round_stopwatch.check_overtime_interval
        overtime_check_countdown = _INCREMENTAL_OVERTIME_CHECK_INTERVAL

        while self.queue:
            source_key = self.u_calculate_key(
                source_idx,
                source_idx,
                index_x_by_index,
                index_y_by_index,
            )
            queue_key_1, queue_key_2, idx = self.queue[0]
            if (
                (queue_key_1, queue_key_2) >= source_key
                and self.rhs_by_index[source_idx] == self.g_by_index[source_idx]
            ):
                break

            overtime_check_countdown -= 1
            if overtime_check_countdown == 0:
                if check_overtime_interval():
                    return False
                overtime_check_countdown = _INCREMENTAL_OVERTIME_CHECK_INTERVAL

            old_key_1, old_key_2, idx = heappop(self.queue)
            new_key = self.u_calculate_key(
                source_idx,
                idx,
                index_x_by_index,
                index_y_by_index,
            )
            if (old_key_1, old_key_2) < new_key:
                heappush(self.queue, (new_key[0], new_key[1], idx))
                continue

            if self.g_by_index[idx] > self.rhs_by_index[idx]:
                self.g_by_index[idx] = self.rhs_by_index[idx]
            else:
                self.g_by_index[idx] = _INCREMENTAL_PATH_INF
                self.u_update_vertex(
                    map,
                    source_idx,
                    idx,
                    index_x_by_index,
                    index_y_by_index,
                )

            neighbor_base = idx * map.MAX_NEIGHBOR_COUNT
            neighbor_count = map.neighbor_count_by_index[idx]
            for offset in range(neighbor_count):
                neighbor_idx = map.neighbor_indices_by_index[neighbor_base + offset]
                if not map.active_mask_by_index[neighbor_idx]:
                    continue
                self.u_update_vertex(
                    map,
                    source_idx,
                    neighbor_idx,
                    index_x_by_index,
                    index_y_by_index,
                )

            if len(self.queue) > self.tile_count * _INCREMENTAL_QUEUE_REBUILD_FACTOR:
                self.u_rebuild_queue(
                    source_idx,
                    index_x_by_index,
                    index_y_by_index,
                )

        return True


class BuilderNavigationMixin:
    def u_get_required_build_titanium_reserve(self) -> int:
        if BUILD_ACTION_MIN_TITANIUM_BASE <= 0:
            return 0

        harvester_titanium_cost, _ = self.ct.get_harvester_cost()
        return math.ceil(
            BUILD_ACTION_MIN_TITANIUM_BASE * harvester_titanium_cost / 20
        )

    def u_can_spend_titanium_without_falling_below_reserve(
        self,
        titanium_cost: int,
    ) -> bool:
        return (
            self.map.titanium - titanium_cost
            >= self.u_get_required_build_titanium_reserve()
        )

    def u_should_respect_titanium_reserve_for_road_build(
        self,
        respect_titanium_reserve_for_road_build: bool,
    ) -> bool:
        return (
            respect_titanium_reserve_for_road_build
            or self.strategy == HARASSMENT_STRATEGY_ID
        )

    def u_move_target_reached(
        self,
        current_pos: Position,
        target_pos: Position,
        reach_builder_action_range: bool,
    ) -> bool:
        if reach_builder_action_range:
            return current_pos.distance_squared(target_pos) <= BUILDER_ACTION_RADIUS_SQ
        return current_pos == target_pos

    def u_try_progress_move_step(
        self,
        next_tile,
        next_direction: Direction | None,
        target_pos: Position,
        build_new_roads: bool,
        allow_conveyor_building: bool,
        respect_titanium_reserve_for_road_build: bool,
    ) -> bool:
        current_pos = self.map.current_pos
        if next_direction is not None and self.ct.can_move(next_direction):
            self.u_move_with_target(next_direction, target_pos)
            return True

        respect_titanium_reserve_for_road_build = (
            self.u_should_respect_titanium_reserve_for_road_build(
                respect_titanium_reserve_for_road_build
            )
        )
        road_titanium_cost, _ = self.ct.get_road_cost()
        can_build_road = (
            build_new_roads
            and self.ct.can_build_road(next_tile.position)
            and (
                not respect_titanium_reserve_for_road_build
                or self.u_can_spend_titanium_without_falling_below_reserve(
                    road_titanium_cost
                )
            )
        )
        if not can_build_road:
            return False

        adjacent_resource_tiles = []
        for adjacent_pos in self.map.u_iter_adjacent_cardinal_positions(next_tile.position):
            adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
            if adjacent_tile.environment == Environment.ORE_TITANIUM:
                adjacent_resource_tiles.append(adjacent_tile)

        if allow_conveyor_building and adjacent_resource_tiles:
            resource_candidates: list[Environment] = []
            for adjacent_tile in adjacent_resource_tiles:
                if (
                    adjacent_tile.building.team == self.map.own_team
                    and adjacent_tile.building.entity_type == EntityType.HARVESTER
                    and adjacent_tile.environment not in resource_candidates
                ):
                    resource_candidates.append(adjacent_tile.environment)
            for adjacent_tile in adjacent_resource_tiles:
                if adjacent_tile.environment not in resource_candidates:
                    resource_candidates.append(adjacent_tile.environment)

            for resource in resource_candidates:
                facing_direction = self.u_best_conveyor_orientation(
                    next_tile.position,
                    resource,
                )
                if facing_direction is None:
                    continue
                if self.u_build_at(
                    next_tile.position,
                    EntityType.CONVEYOR,
                    hold=False,
                    move_towards=False,
                    attack_enemy_passable=False,
                    facing_direction=facing_direction,
                    allow_conveyor_building=allow_conveyor_building,
                ):
                    return True
            return False

        self.ct.build_road(next_tile.position)
        if next_direction is not None and self.ct.can_move(next_direction):
            self.u_move_with_target(next_direction, target_pos)
        return True

    def u_try_greedy_manhattan_move_toward(
        self,
        target_pos: Position,
        avoid_enemy_turrets: bool = True,
    ) -> bool:
        current_pos = self.map.current_pos
        current_dist = (
            abs(current_pos.x - target_pos.x)
            + abs(current_pos.y - target_pos.y)
        )
        best_direction: Direction | None = None
        best_score: tuple[int, int, int] | None = None

        for direction in DIRECTIONS:
            if direction == Direction.CENTRE:
                continue
            if not self.ct.can_move(direction):
                continue

            next_pos = current_pos.add(direction)
            if not self.map.u_is_in_bounds(next_pos):
                continue
            next_idx = self.map.u_to_index(next_pos)
            if (
                avoid_enemy_turrets
                and self.map.enemy_turret_target_by_index[next_idx]
            ):
                continue
            next_dist = abs(next_pos.x - target_pos.x) + abs(next_pos.y - target_pos.y)
            if next_dist >= current_dist:
                continue

            score = (
                next_dist,
                self.map.u_get_own_core_dist_by_index(next_idx),
                next_idx,
            )
            if best_score is None or score < best_score:
                best_score = score
                best_direction = direction

        if best_direction is None:
            return False

        self.u_move_with_target(best_direction, target_pos)
        return True

    def u_move_to(
        self,
        pos: Position,
        avoid_enemy_turrets: bool = True,
        build_new_roads: bool = True,
        allow_conveyor_building: bool = True,
        reach_builder_action_range: bool = False,
        respect_titanium_reserve_for_road_build: bool = False,
    ) -> bool:
        current_pos = self.map.current_pos
        if self.u_move_target_reached(current_pos, pos, reach_builder_action_range):
            return False
        if not self.map.u_is_in_bounds(pos):
            return False
        target_idx = self.map.u_to_index(pos)
        target_is_vision_reachable = self.map.u_is_vision_reachable_by_index(target_idx)
        if not reach_builder_action_range and target_is_vision_reachable:
            next_tile = self.map.u_get_next_step_towards_vision_reachable(pos)
            if next_tile is not None:
                next_direction = self.map.u_get_direction_between(
                    current_pos,
                    next_tile.position,
                )
                if next_direction is not None and self.ct.can_move(next_direction):
                    self.u_move_with_target(next_direction, pos)
                    return True
                return False
        if self.map.is_caged and not target_is_vision_reachable:
            return self.u_try_greedy_manhattan_move_toward(
                pos,
                avoid_enemy_turrets=avoid_enemy_turrets,
            )
        respect_titanium_reserve_for_road_build = (
            self.u_should_respect_titanium_reserve_for_road_build(
                respect_titanium_reserve_for_road_build
            )
        )
        return self.u_move_to_astar(
            pos,
            avoid_enemy_turrets=avoid_enemy_turrets,
            build_new_roads=build_new_roads,
            allow_conveyor_building=allow_conveyor_building,
            reach_builder_action_range=reach_builder_action_range,
            respect_titanium_reserve_for_road_build=(
                respect_titanium_reserve_for_road_build
            ),
        )

    def _u_get_incremental_path_state(
        self,
        attribute_name: str,
        use_d_star_lite: bool,
    ) -> _IncrementalShortestPathState:
        planner_states_by_builder_id = getattr(self, attribute_name, None)
        if planner_states_by_builder_id is None:
            planner_states_by_builder_id = {}
            setattr(self, attribute_name, planner_states_by_builder_id)

        current_tile = self.map.u_get_pos_tile(self.map.current_pos)
        builder_id = current_tile.bot.id
        if builder_id is None:
            builder_id = -1

        planner_state = planner_states_by_builder_id.get(builder_id)
        if planner_state is None:
            planner_state = _IncrementalShortestPathState(use_d_star_lite)
            planner_states_by_builder_id[builder_id] = planner_state
        return planner_state

    def _u_build_incremental_path_masks(
        self,
        source_idx: int,
        target_idx: int,
        avoid_enemy_turrets: bool,
        reach_builder_action_range: bool,
    ) -> tuple[bytearray, bytearray, bool]:
        map = self.map
        tile_count = map.tile_count
        passable_mask_by_index = bytearray(tile_count)
        goal_mask_by_index = bytearray(tile_count)
        active_mask_by_index = map.active_mask_by_index
        intrinsic_passable_by_index = map.intrinsic_passable_by_index
        enemy_turret_target_by_index = map.enemy_turret_target_by_index
        bot_present_by_index = map.bot_present_by_index

        if not active_mask_by_index[source_idx]:
            return (passable_mask_by_index, goal_mask_by_index, False)

        for idx in range(tile_count):
            if not active_mask_by_index[idx]:
                continue
            if idx == source_idx:
                passable_mask_by_index[idx] = 1
                continue
            if idx == target_idx and not reach_builder_action_range:
                passable_mask_by_index[idx] = int(intrinsic_passable_by_index[idx])
                continue
            if not intrinsic_passable_by_index[idx]:
                continue
            if avoid_enemy_turrets and enemy_turret_target_by_index[idx]:
                continue
            if idx != target_idx and bot_present_by_index[idx]:
                continue
            passable_mask_by_index[idx] = 1

        has_goal = False
        if not reach_builder_action_range:
            if passable_mask_by_index[target_idx]:
                goal_mask_by_index[target_idx] = 1
                has_goal = True
            return (passable_mask_by_index, goal_mask_by_index, has_goal)

        goal_base = target_idx * map.MAX_BUILDER_ACTION_TARGET_COUNT
        goal_count = map.builder_action_target_count_by_index[target_idx]
        goal_indices_by_index = map.builder_action_target_indices_by_index
        for offset in range(goal_count):
            goal_idx = goal_indices_by_index[goal_base + offset]
            if not passable_mask_by_index[goal_idx]:
                continue
            goal_mask_by_index[goal_idx] = 1
            has_goal = True

        return (passable_mask_by_index, goal_mask_by_index, has_goal)

    def _u_move_to_incremental_shortest_path(
        self,
        pos: Position,
        planner_attribute_name: str,
        use_d_star_lite: bool,
        avoid_enemy_turrets: bool = True,
        build_new_roads: bool = True,
        allow_conveyor_building: bool = True,
        reach_builder_action_range: bool = False,
        respect_titanium_reserve_for_road_build: bool = False,
    ) -> bool:
        map = self.map
        current_pos = map.current_pos
        if not map.u_is_in_bounds(pos):
            return False
        if self.u_move_target_reached(current_pos, pos, reach_builder_action_range):
            return False

        print("Move to target:", pos)

        respect_titanium_reserve_for_road_build = (
            self.u_should_respect_titanium_reserve_for_road_build(
                respect_titanium_reserve_for_road_build
            )
        )

        source_idx = map.u_to_index(current_pos)
        target_idx = map.u_to_index(pos)
        planner_state = self._u_get_incremental_path_state(
            planner_attribute_name,
            use_d_star_lite,
        )
        planner_state.u_ensure_capacity(map.tile_count)

        passable_mask_by_index, goal_mask_by_index, has_goal = (
            self._u_build_incremental_path_masks(
                source_idx,
                target_idx,
                avoid_enemy_turrets,
                reach_builder_action_range,
            )
        )
        if not has_goal:
            return False

        index_x_by_index = map.index_x_by_index
        index_y_by_index = map.index_y_by_index
        requires_reset = (
            planner_state.target_idx != target_idx
            or planner_state.avoid_enemy_turrets != avoid_enemy_turrets
            or planner_state.reach_builder_action_range != reach_builder_action_range
            or planner_state.last_source_idx == -1
            or (not use_d_star_lite and planner_state.last_source_idx != source_idx)
        )

        if requires_reset:
            planner_state.u_reset(
                source_idx,
                target_idx,
                avoid_enemy_turrets,
                reach_builder_action_range,
                passable_mask_by_index,
                goal_mask_by_index,
                index_x_by_index,
                index_y_by_index,
            )
        else:
            if planner_state.last_source_idx != source_idx:
                planner_state.km += _u_chebyshev_dist_by_index(
                    planner_state.last_source_idx,
                    source_idx,
                    index_x_by_index,
                    index_y_by_index,
                )
                planner_state.last_source_idx = source_idx
            planner_state.u_apply_graph_changes(
                map,
                source_idx,
                passable_mask_by_index,
                goal_mask_by_index,
                index_x_by_index,
                index_y_by_index,
            )

        if not planner_state.u_compute_shortest_path(
            map,
            source_idx,
            index_x_by_index,
            index_y_by_index,
        ):
            return False

        best_next_idx: int | None = None
        best_next_score: tuple[int, int, int, int, int] | None = None
        tiles_by_index = map.tiles_by_index
        get_own_core_dist = map.u_get_own_core_dist_by_index
        neighbor_base = source_idx * map.MAX_NEIGHBOR_COUNT
        neighbor_count = map.neighbor_count_by_index[source_idx]
        neighbor_indices_by_index = map.neighbor_indices_by_index

        for offset in range(neighbor_count):
            neighbor_idx = neighbor_indices_by_index[neighbor_base + offset]
            if not planner_state.passable_mask_by_index[neighbor_idx]:
                continue
            neighbor_cost = planner_state.g_by_index[neighbor_idx]
            if neighbor_cost >= _INCREMENTAL_PATH_INF:
                continue
            neighbor_tile = tiles_by_index[neighbor_idx]
            candidate_score = (
                neighbor_cost + 1,
                int(neighbor_tile.building.id is None),
                get_own_core_dist(neighbor_idx),
                index_x_by_index[neighbor_idx],
                index_y_by_index[neighbor_idx],
            )
            if best_next_score is None or candidate_score < best_next_score:
                best_next_score = candidate_score
                best_next_idx = neighbor_idx

        if best_next_idx is None:
            return False

        next_tile = tiles_by_index[best_next_idx]
        next_direction = map.u_get_direction_between(
            current_pos,
            next_tile.position,
        )
        return self.u_try_progress_move_step(
            next_tile,
            next_direction,
            pos,
            build_new_roads=build_new_roads,
            allow_conveyor_building=allow_conveyor_building,
            respect_titanium_reserve_for_road_build=(
                respect_titanium_reserve_for_road_build
            ),
        )

    def u_move_to_d_star_lite(
        self,
        pos: Position,
        avoid_enemy_turrets: bool = True,
        build_new_roads: bool = True,
        allow_conveyor_building: bool = True,
        reach_builder_action_range: bool = False,
        respect_titanium_reserve_for_road_build: bool = False,
    ) -> bool:
        return self._u_move_to_incremental_shortest_path(
            pos,
            "_d_star_lite_states_by_builder_id",
            use_d_star_lite=True,
            avoid_enemy_turrets=avoid_enemy_turrets,
            build_new_roads=build_new_roads,
            allow_conveyor_building=allow_conveyor_building,
            reach_builder_action_range=reach_builder_action_range,
            respect_titanium_reserve_for_road_build=(
                respect_titanium_reserve_for_road_build
            ),
        )

    def u_move_to_lpa_star(
        self,
        pos: Position,
        avoid_enemy_turrets: bool = True,
        build_new_roads: bool = True,
        allow_conveyor_building: bool = True,
        reach_builder_action_range: bool = False,
        respect_titanium_reserve_for_road_build: bool = False,
    ) -> bool:
        return self._u_move_to_incremental_shortest_path(
            pos,
            "_lpa_star_states_by_builder_id",
            use_d_star_lite=False,
            avoid_enemy_turrets=avoid_enemy_turrets,
            build_new_roads=build_new_roads,
            allow_conveyor_building=allow_conveyor_building,
            reach_builder_action_range=reach_builder_action_range,
            respect_titanium_reserve_for_road_build=(
                respect_titanium_reserve_for_road_build
            ),
        )

    def u_move_with_target(
        self,
        direction: Direction,
        target_pos: Position,
    ) -> None:
        print(
            "Move target:",
            target_pos,
            "via",
            direction,
            "to",
            self.map.current_pos.add(direction),
        )
        self.ct.move(direction)

    def u_get_supply_chain_progress_key_to_target(
        self,
        pos: Position,
        target_pos: Position,
    ) -> tuple[int, int]:
        target_tile = self.map.u_get_pos_tile(pos)
        return (
            pos.distance_squared(target_pos),
            target_tile.own_core_dist,
        )

    def u_is_supply_branch_target_usable(
        self,
        pos: Position,
        target_pos: Position,
        resource: Environment,
        blocked_indices: set[int],
    ) -> bool:
        if pos == target_pos:
            return True

        target_tile = self.map.u_get_pos_tile(pos)
        if target_tile.index in blocked_indices:
            return False
        if target_tile.environment == Environment.WALL:
            return False
        if (
            target_tile.building.entity_type in SUPPLY_LINK_TYPES
            and target_tile.building.team == self.map.own_team
        ):
            return False
        if (
            target_tile.building.entity_type == EntityType.BARRIER
            and target_tile.building.team == self.map.own_team
        ):
            return True
        if (
            target_tile.building.entity_type == EntityType.ROAD
            and target_tile.building.team == self.map.own_team
        ):
            return True
        if target_tile.building.id is None:
            return True
        return False

    def u_can_route_supply_chain_to_target(
        self,
        start_pos: Position,
        target_pos: Position,
        resource: Environment,
        blocked_indices: set[int],
    ) -> bool:
        if start_pos == target_pos:
            return True
        if not self.map.u_is_in_bounds(start_pos):
            return False
        if not self.u_is_supply_branch_target_usable(
            start_pos,
            target_pos,
            resource,
            blocked_indices,
        ):
            return False

        tiles_by_index = self.map.tiles_by_index
        queue = [start_pos]
        seen_indices = {self.map.u_get_pos_tile(start_pos).index}
        queue_idx = 0

        while queue_idx < len(queue):
            current_pos = queue[queue_idx]
            queue_idx += 1
            current_progress_key = self.u_get_supply_chain_progress_key_to_target(
                current_pos,
                target_pos,
            )

            for direction in Direction:
                if direction == Direction.CENTRE:
                    continue
                dx, dy = direction.delta()
                if abs(dx) + abs(dy) != 1:
                    continue

                next_pos = current_pos.add(direction)
                if not self.map.u_is_in_bounds(next_pos):
                    continue
                if (
                    self.u_get_supply_chain_progress_key_to_target(
                        next_pos,
                        target_pos,
                    )
                    >= current_progress_key
                ):
                    continue
                if next_pos == target_pos:
                    return True
                if not self.u_is_supply_branch_target_usable(
                    next_pos,
                    target_pos,
                    resource,
                    blocked_indices,
                ):
                    continue

                next_idx = self.map.u_get_pos_tile(next_pos).index
                if next_idx in seen_indices:
                    continue
                seen_indices.add(next_idx)
                queue.append(next_pos)

            for target_idx in self.map.u_iter_active_tile_indices():
                target_tile = tiles_by_index[target_idx]
                target_pos_candidate = target_tile.position
                if target_pos_candidate == current_pos:
                    continue
                if (
                    current_pos.distance_squared(target_pos_candidate)
                    > GameConstants.BRIDGE_TARGET_RADIUS_SQ
                ):
                    continue
                if (
                    abs(target_pos_candidate.x - current_pos.x)
                    + abs(target_pos_candidate.y - current_pos.y)
                    == 1
                ):
                    continue
                if (
                    self.u_get_supply_chain_progress_key_to_target(
                        target_pos_candidate,
                        target_pos,
                    )
                    >= current_progress_key
                ):
                    continue
                if target_pos_candidate == target_pos:
                    return True
                if not self.u_is_supply_branch_target_usable(
                    target_pos_candidate,
                    target_pos,
                    resource,
                    blocked_indices,
                ):
                    continue

                target_idx = target_tile.index
                if target_idx in seen_indices:
                    continue
                seen_indices.add(target_idx)
                queue.append(target_pos_candidate)

                if self.round_stopwatch.check_overtime():
                    break

            if self.round_stopwatch.check_overtime():
                break

        return False

    def u_get_supply_chain_label_for_resource(
        self,
        resource: Environment,
    ) -> SupplyChainLabel:
        if resource == Environment.ORE_TITANIUM:
            return SupplyChainLabel.TITANIUM
        if resource == Environment.ORE_AXIONITE:
            return SupplyChainLabel.AXIONITE
        return SupplyChainLabel.NONE

    def u_get_transport_supply_chain_policy(
        self,
        supply_chain_label: SupplyChainLabel,
    ) -> tuple[bool, bool, bool]:
        is_pure_axionite_supply_chain = supply_chain_label == SupplyChainLabel.AXIONITE
        return (
            not is_pure_axionite_supply_chain,
            is_pure_axionite_supply_chain,
            is_pure_axionite_supply_chain,
        )

    def u_get_transport_supplier_build_plan_for_supply_chain(
        self,
        pos: Position,
        resource: Environment,
        supply_chain_label: SupplyChainLabel,
    ) -> tuple[EntityType | None, Direction | Position | None]:
        (
            prefer_bridge_when_conveyor_targets_existing_chain,
            avoid_core,
            prefer_join_existing_supply_chain,
        ) = self.u_get_transport_supply_chain_policy(supply_chain_label)
        return self.u_get_transport_supplier_build_plan(
            pos,
            resource,
            prefer_bridge_when_conveyor_targets_existing_chain=(
                prefer_bridge_when_conveyor_targets_existing_chain
            ),
            avoid_core=avoid_core,
            prefer_join_existing_supply_chain=prefer_join_existing_supply_chain,
            supply_chain_label=supply_chain_label,
        )

    def u_supply_chain_targets_core(self, resource: Environment) -> bool:
        return True

    def u_can_afford_sentinel(self, respect_titanium_reserve: bool = False) -> bool:
        sentinel_titanium_cost, sentinel_axionite_cost = self.ct.get_sentinel_cost()
        return (
            (
                not respect_titanium_reserve
                or self.u_can_spend_titanium_without_falling_below_reserve(
                    sentinel_titanium_cost
                )
            )
            and self.map.titanium >= sentinel_titanium_cost
            and self.map.axionite >= sentinel_axionite_cost
        )

    def u_can_afford_gunner(self, respect_titanium_reserve: bool = False) -> bool:
        gunner_titanium_cost, gunner_axionite_cost = self.ct.get_gunner_cost()
        return (
            (
                not respect_titanium_reserve
                or self.u_can_spend_titanium_without_falling_below_reserve(
                    gunner_titanium_cost
                )
            )
            and self.map.titanium >= gunner_titanium_cost
            and self.map.axionite >= gunner_axionite_cost
        )

    def u_get_direction_toward_enemy_core_center(self, pos: Position) -> Direction:
        enemy_core_center_pos = self.map.enemy_core_center_pos
        if enemy_core_center_pos is None and self.map.enemy_core_center_pos_candidates:
            enemy_core_center_pos = min(
                (candidate_pos for _, candidate_pos in self.map.enemy_core_center_pos_candidates),
                key=lambda candidate_pos: (
                    pos.distance_squared(candidate_pos),
                    candidate_pos.x,
                    candidate_pos.y,
                ),
            )

        if enemy_core_center_pos is None:
            return Direction.NORTH

        direction = self.map.u_get_direction_between(pos, enemy_core_center_pos)
        if direction is None or direction == Direction.CENTRE:
            return Direction.NORTH
        return direction

    def u_get_sentinel_orientation(self, pos: Position) -> Direction:
        enemy_core_center_pos = self.map.enemy_core_center_pos
        if enemy_core_center_pos is not None:
            base_direction = self.map.u_get_direction_between(pos, enemy_core_center_pos)
        else:
            own_core_center_pos = self.map.own_core_center_pos
            if own_core_center_pos is None:
                self.map.u_calc_core_center_positions()
                own_core_center_pos = self.map.own_core_center_pos
            if own_core_center_pos is None:
                base_direction = Direction.NORTH
            else:
                base_direction = self.map.u_get_direction_between(own_core_center_pos, pos)

        if base_direction is None or base_direction == Direction.CENTRE:
            base_direction = Direction.NORTH

        source_idx = self.map.u_to_index(pos)
        current_round = self.map.current_round
        enemy_team = self.map.enemy_team
        best_direction = base_direction
        best_key = None

        for candidate_order, direction in enumerate(
            _ADJACENT_DIRECTION_CANDIDATES_BY_DIRECTION[base_direction]
        ):
            enemy_turret_count = 0
            can_target_enemy_core = 0
            enemy_harvester_count = 0
            enemy_supply_chain_count = 0
            other_enemy_building_count = 0

            for target_idx in self.map.u_get_attackable_target_indices(
                source_idx,
                EntityType.SENTINEL,
                direction,
            ):
                target_tile = self.map.tiles_by_index[target_idx]
                if target_tile.is_core_of(enemy_team):
                    can_target_enemy_core = 1
                    continue
                if (
                    target_tile.last_seen_turn != current_round
                    or target_tile.building.team != enemy_team
                ):
                    continue

                target_type = target_tile.building.entity_type
                if target_type in ENEMY_TURRET_TYPES:
                    enemy_turret_count += 1
                elif target_type == EntityType.HARVESTER:
                    enemy_harvester_count += 1
                elif target_type in SUPPLY_LINK_TYPES:
                    enemy_supply_chain_count += 1
                elif target_type is not None:
                    other_enemy_building_count += 1

            key = (
                -enemy_turret_count,
                -can_target_enemy_core,
                -enemy_harvester_count,
                -enemy_supply_chain_count,
                -other_enemy_building_count,
                candidate_order,
            )
            if best_key is None or key < best_key:
                best_key = key
                best_direction = direction

            if self.round_stopwatch.check_overtime():
                break

        return best_direction

    def _u_tile_is_targeted_by_supply_chain(
        self,
        tile_idx: int,
    ) -> bool:
        return bool(
            self.map.own_supply_link_source_indices_by_target_index_in_vision.get(
                tile_idx,
                _EMPTY_SOURCE_INDEX_SET,
            )
            or self.map.enemy_supply_link_source_indices_by_target_index_in_vision.get(
                tile_idx,
                _EMPTY_SOURCE_INDEX_SET,
            )
        )

    def _u_supply_tile_transports_titanium(self, tile) -> bool:
        if tile.building.entity_type not in SUPPLY_LINK_TYPES:
            return False
        if tile.building.entity_type == EntityType.SPLITTER:
            return tile.building.last_titanium_onit_turn == self.map.current_round
        if tile.building.team is None:
            return False
        return self.map.u_supply_chain_has_titanium(
            tile.index,
            tile.building.team,
        )

    def _u_tile_is_useful_harvester_adjacent_turret_target(self, tile) -> bool:
        enemy_team = self.map.enemy_team
        if tile.is_core_of(enemy_team):
            return True
        if tile.building.team != enemy_team:
            return False
        return tile.building.entity_type in (
            *ATTACK_TURRET_TYPES,
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.BRIDGE,
            EntityType.SPLITTER,
            EntityType.FOUNDRY,
            EntityType.LAUNCHER,
            EntityType.HARVESTER,
        )

    def _u_gunner_can_target_useful_harvester_adjacent_enemy(
        self,
        pos: Position,
        direction: Direction,
    ) -> bool:
        return any(
            self._u_tile_is_useful_harvester_adjacent_turret_target(target_tile)
            for target_tile in self.map.u_get_gunner_shootable_tiles(pos, direction)
        )

    def _u_sentinel_can_target_useful_harvester_adjacent_enemy(
        self,
        pos: Position,
        direction: Direction,
    ) -> bool:
        source_idx = self.map.u_to_index(pos)
        for target_idx in self.map.u_get_attackable_target_indices(
            source_idx,
            EntityType.SENTINEL,
            direction,
        ):
            if self._u_tile_is_useful_harvester_adjacent_turret_target(
                self.map.tiles_by_index[target_idx]
            ):
                return True
        return False

    def _u_get_harvester_adjacent_turret_substitution(
        self,
        pos: Position,
        respect_titanium_reserve: bool,
        require_affordable: bool = True,
    ) -> tuple[EntityType, Direction] | None:
        if (
            not require_affordable
            or self.u_can_afford_gunner(respect_titanium_reserve)
        ):
            gunner_direction = self.u_get_gunner_orientation(pos)
            if self._u_gunner_can_target_useful_harvester_adjacent_enemy(
                pos,
                gunner_direction,
            ):
                return (EntityType.GUNNER, gunner_direction)

        if (
            not require_affordable
            or self.u_can_afford_sentinel(respect_titanium_reserve)
        ):
            sentinel_direction = self.u_get_sentinel_orientation(pos)
            if self._u_sentinel_can_target_useful_harvester_adjacent_enemy(
                pos,
                sentinel_direction,
            ):
                return (EntityType.SENTINEL, sentinel_direction)

        return None

    def u_get_useful_sentinel_direction(self, pos: Position) -> Direction | None:
        sentinel_direction = self.u_get_sentinel_orientation(pos)
        enemy_team = self.map.enemy_team
        sentinel_target_indices = self.map.u_get_attackable_target_indices(
            self.map.u_get_pos_tile(pos).index,
            EntityType.SENTINEL,
            sentinel_direction,
        )
        for sentinel_target_idx in sentinel_target_indices:
            sentinel_target_tile = self.map.tiles_by_index[sentinel_target_idx]
            if sentinel_target_tile.is_core_of(enemy_team):
                return sentinel_direction
            if sentinel_target_tile.building.team != enemy_team:
                continue
            if sentinel_target_tile.building.entity_type in (
                EntityType.HARVESTER,
                EntityType.FOUNDRY,
                EntityType.LAUNCHER,
            ) or sentinel_target_tile.building.entity_type in ENEMY_TURRET_TYPES:
                return sentinel_direction
        return None

    def u_get_gunner_orientation(self, pos: Position) -> Direction:
        current_round = self.map.current_round
        enemy_team = self.map.enemy_team
        source_idx = self.map.u_to_index(pos)
        direction_order = {
            direction: idx
            for idx, direction in enumerate(Direction)
            if direction != Direction.CENTRE
        }
        candidate_entries: list[dict[str, object]] = []

        def tile_points_at_self(tile) -> bool:
            return any(target_tile.index == source_idx for target_tile in tile.building.targets)

        def is_visible_enemy_tile(tile) -> bool:
            if tile.is_core_of(enemy_team):
                return True
            if tile.last_seen_turn != current_round:
                return False
            if tile.bot.id is not None and tile.bot.team == enemy_team:
                return True
            return tile.building.id is not None and tile.building.team == enemy_team

        def is_visible_enemy_supply_tile(tile) -> bool:
            return (
                tile.last_seen_turn == current_round
                and tile.building.team == enemy_team
                and tile.building.entity_type in SUPPLY_LINK_TYPES
            )

        def first_tile_health(tile) -> int:
            if tile.bot.id is not None and tile.bot.team == enemy_team:
                return tile.bot.hp if tile.bot.hp is not None else INF_DIST
            if tile.is_core_of(enemy_team) or tile.building.team == enemy_team:
                return tile.building.hp if tile.building.hp is not None else INF_DIST
            return INF_DIST

        def filter_candidates(predicate: Callable[[dict[str, object]], bool]) -> None:
            nonlocal candidate_entries
            filtered_entries = [
                candidate_entry
                for candidate_entry in candidate_entries
                if predicate(candidate_entry)
            ]
            if filtered_entries:
                candidate_entries = filtered_entries

        for direction in Direction:
            if direction == Direction.CENTRE:
                continue

            shootable_tiles = self.map.u_get_gunner_shootable_tiles(pos, direction)
            if not shootable_tiles:
                continue

            if not any(is_visible_enemy_tile(target_tile) for target_tile in shootable_tiles):
                continue

            if any(
                target_tile.last_seen_turn == current_round
                and target_tile.building.team == enemy_team
                and target_tile.building.entity_type in CONVEYOR_ENTITY_TYPES
                and tile_points_at_self(target_tile)
                for target_tile in shootable_tiles
            ):
                continue

            first_tile = shootable_tiles[0]
            if (
                first_tile.last_seen_turn == current_round
                and first_tile.building.team == enemy_team
                and first_tile.building.entity_type == EntityType.BRIDGE
                and tile_points_at_self(first_tile)
            ):
                continue

            candidate_entries.append(
                {
                    "direction": direction,
                    "shootable_tiles": shootable_tiles,
                    "first_tile": first_tile,
                    "direction_order": direction_order[direction],
                    "first_tile_health": first_tile_health(first_tile),
                }
            )

            if self.round_stopwatch.check_overtime():
                break

        if not candidate_entries:
            return self.u_get_direction_toward_enemy_core_center(pos)

        filter_candidates(
            lambda candidate_entry: (
                candidate_entry["first_tile"].last_seen_turn == current_round
                and candidate_entry["first_tile"].building.team == enemy_team
                and candidate_entry["first_tile"].building.entity_type == EntityType.GUNNER
                and self._u_tile_is_targeted_by_titanium_supply_chain(
                    candidate_entry["first_tile"].index
                )
            )
        )
        filter_candidates(
            lambda candidate_entry: (
                candidate_entry["first_tile"].last_seen_turn == current_round
                and candidate_entry["first_tile"].building.team == enemy_team
                and candidate_entry["first_tile"].building.entity_type
                == EntityType.SENTINEL
                and self._u_tile_is_targeted_by_titanium_supply_chain(
                    candidate_entry["first_tile"].index
                )
            )
        )
        filter_candidates(
            lambda candidate_entry: (
                candidate_entry["first_tile"].last_seen_turn == current_round
                and candidate_entry["first_tile"].building.team == enemy_team
                and candidate_entry["first_tile"].building.entity_type == EntityType.BREACH
                and self._u_tile_is_targeted_by_supply_chain(
                    candidate_entry["first_tile"].index
                )
            )
        )
        filter_candidates(
            lambda candidate_entry: any(
                target_tile.last_seen_turn == current_round
                and target_tile.building.team == enemy_team
                and target_tile.building.entity_type == EntityType.GUNNER
                and self._u_tile_is_targeted_by_titanium_supply_chain(target_tile.index)
                for target_tile in candidate_entry["shootable_tiles"][1:]
            )
        )
        filter_candidates(
            lambda candidate_entry: any(
                target_tile.last_seen_turn == current_round
                and target_tile.building.team == enemy_team
                and target_tile.building.entity_type == EntityType.SENTINEL
                and self._u_tile_is_targeted_by_titanium_supply_chain(target_tile.index)
                for target_tile in candidate_entry["shootable_tiles"][1:]
            )
        )
        filter_candidates(
            lambda candidate_entry: any(
                target_tile.last_seen_turn == current_round
                and target_tile.building.team == enemy_team
                and target_tile.building.entity_type == EntityType.BREACH
                and self._u_tile_is_targeted_by_supply_chain(target_tile.index)
                for target_tile in candidate_entry["shootable_tiles"][1:]
            )
        )
        filter_candidates(
            lambda candidate_entry: any(
                is_visible_enemy_supply_tile(target_tile)
                and self._u_supply_tile_transports_titanium(target_tile)
                for target_tile in candidate_entry["shootable_tiles"]
            )
        )
        filter_candidates(
            lambda candidate_entry: candidate_entry["first_tile"].is_core_of(enemy_team)
        )
        filter_candidates(
            lambda candidate_entry: any(
                target_tile.is_core_of(enemy_team)
                for target_tile in candidate_entry["shootable_tiles"][1:]
            )
        )

        return min(
            candidate_entries,
            key=lambda candidate_entry: (
                candidate_entry["first_tile_health"],
                candidate_entry["direction_order"],
            ),
        )["direction"]

    def _u_get_adjacent_enemy_turret_gunner_direction(
        self,
        pos: Position,
    ) -> Direction | None:
        current_round = self.map.current_round
        enemy_team = self.map.enemy_team
        pos_tile = self.map.u_get_pos_tile(pos)
        pos_idx = pos_tile.index
        adjacent_enemy_turret_present = False

        for adjacent_idx in self.map.u_iter_neighbor_indices(pos_idx):
            adjacent_tile = self.map.tiles_by_index[adjacent_idx]
            if (
                adjacent_tile.last_seen_turn == current_round
                and adjacent_tile.building.team == enemy_team
                and adjacent_tile.building.entity_type in ATTACK_TURRET_TYPES
            ):
                adjacent_enemy_turret_present = True
                break

            if self.round_stopwatch.check_overtime():
                break

        if not adjacent_enemy_turret_present:
            return None

        feeder_directions: list[Direction] = []
        for building_tile in self.map.own_buildings_in_vision:
            if (
                building_tile.building.entity_type in ATTACK_TURRET_FEEDER_TYPES
                and any(
                    target_tile.position == pos
                    for target_tile in building_tile.building.targets
                )
            ):
                feeder_direction = self.map.u_get_direction_between(
                    building_tile.position,
                    pos,
                )
                if feeder_direction is not None:
                    feeder_directions.append(feeder_direction)

            if self.round_stopwatch.check_overtime():
                break

        blocked_direction = (
            feeder_directions[0] if len(feeder_directions) == 1 else None
        )
        candidate_directions = [
            direction
            for direction in Direction
            if direction != Direction.CENTRE and direction != blocked_direction
        ]
        if not candidate_directions:
            return None

        direction_order = {
            direction: idx
            for idx, direction in enumerate(Direction)
            if direction != Direction.CENTRE
        }
        build_source_indices = (
            self.map.enemy_supply_link_source_indices_by_target_index_in_vision.get(
                pos_idx,
                (),
            )
        )
        direction_scores: list[tuple[tuple[int, int, int, int, int], Direction]] = []

        for direction in candidate_directions:
            best_target_key = None
            for target_tile in self.map.u_get_gunner_shootable_tiles(pos, direction):
                if (
                    target_tile.last_seen_turn != current_round
                    or target_tile.building.team != enemy_team
                ):
                    continue

                target_type = target_tile.building.entity_type
                if target_type not in {EntityType.GUNNER, EntityType.SENTINEL}:
                    continue

                target_source_indices = (
                    self.map.enemy_supply_link_source_indices_by_target_index_in_vision.get(
                        target_tile.index,
                        (),
                    )
                )
                target_is_fed = bool(target_source_indices)
                source_targets_own_gunner = bool(build_source_indices) and any(
                    source_idx in build_source_indices
                    for source_idx in target_source_indices
                )

                priority_rank = 5
                if (
                    target_type == EntityType.GUNNER
                    and target_is_fed
                    and source_targets_own_gunner
                ):
                    priority_rank = 0
                elif target_type == EntityType.GUNNER and target_is_fed:
                    priority_rank = 1
                elif target_type == EntityType.SENTINEL and target_is_fed:
                    priority_rank = 2
                elif target_type == EntityType.GUNNER:
                    priority_rank = 3
                elif target_type == EntityType.SENTINEL:
                    priority_rank = 4

                target_hp = (
                    target_tile.building.hp
                    if target_tile.building.hp is not None
                    else INF_DIST
                )
                target_key = (
                    priority_rank,
                    target_hp,
                    pos.distance_squared(target_tile.position),
                    target_tile.position.x,
                    target_tile.position.y,
                )
                if best_target_key is None or target_key < best_target_key:
                    best_target_key = target_key

                if self.round_stopwatch.check_overtime():
                    break

            if best_target_key is None:
                continue

            direction_scores.append(
                (
                    (*best_target_key, direction_order[direction]),
                    direction,
                )
            )

            if self.round_stopwatch.check_overtime():
                break

        if not direction_scores:
            return self.u_get_gunner_orientation(pos)

        return min(direction_scores, key=lambda item: item[0])[1]

    def u_get_turret_build_plan(
        self,
        pos: Position,
    ) -> tuple[EntityType, Direction]:
        gunner_direction = self._u_get_adjacent_enemy_turret_gunner_direction(pos)
        if gunner_direction is not None:
            return (EntityType.GUNNER, gunner_direction)

        current_round = self.map.current_round
        enemy_team = self.map.enemy_team
        pos_idx = self.map.u_to_index(pos)

        def has_harvester_adjacent_gunner_lane() -> bool:
            for neighbor_idx in self.map.u_iter_neighbor_indices(pos_idx):
                neighbor_tile = self.map.tiles_by_index[neighbor_idx]
                if neighbor_tile.last_seen_turn != current_round:
                    continue

                building = neighbor_tile.building
                if building.id is None:
                    if neighbor_tile.environment != Environment.EMPTY:
                        continue
                elif (
                    building.team == enemy_team
                    and building.entity_type == EntityType.ROAD
                ):
                    pass
                elif (
                    building.team == enemy_team
                    and building.entity_type in CONVEYOR_ENTITY_TYPES
                    and neighbor_tile.conveyor_targets_harvester
                ):
                    pass
                else:
                    continue

                for adjacent_pos in self.map.u_iter_adjacent_cardinal_positions(
                    neighbor_tile.position
                ):
                    adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
                    if (
                        adjacent_tile.last_seen_turn == current_round
                        and adjacent_tile.environment == Environment.ORE_TITANIUM
                        and adjacent_tile.building.team == enemy_team
                        and adjacent_tile.building.entity_type == EntityType.HARVESTER
                    ):
                        return True

                    if self.round_stopwatch.check_overtime():
                        break

                if self.round_stopwatch.check_overtime():
                    break

            return False

        sentinel_titanium_cost, sentinel_axionite_cost = self.ct.get_sentinel_cost()
        gunner_titanium_cost, gunner_axionite_cost = self.ct.get_gunner_cost()
        can_afford_sentinel = (
            self.map.titanium >= sentinel_titanium_cost
            and self.map.axionite >= sentinel_axionite_cost
        )
        can_afford_gunner = (
            self.map.titanium >= gunner_titanium_cost
            and self.map.axionite >= gunner_axionite_cost
        )
        if has_harvester_adjacent_gunner_lane():
            return (EntityType.GUNNER, self.u_get_gunner_orientation(pos))
        if not can_afford_sentinel and can_afford_gunner:
            return (EntityType.GUNNER, self.u_get_gunner_orientation(pos))

        return (
            EntityType.SENTINEL,
            self.u_get_sentinel_orientation(pos),
        )

    def u_build_turret(
        self,
        pos: Position,
        hold: bool,
        move_towards: bool,
        attack_enemy_passable: bool,
        avoid_enemy_turrets: bool = True,
        respect_titanium_reserve: bool = False,
    ) -> bool:
        building_type, facing_direction = self.u_get_turret_build_plan(pos)
        return self.u_build_at(
            pos,
            building_type,
            hold=hold,
            move_towards=move_towards,
            attack_enemy_passable=attack_enemy_passable,
            facing_direction=facing_direction,
            avoid_enemy_turrets=avoid_enemy_turrets,
            respect_titanium_reserve=respect_titanium_reserve,
        )

    def _u_tile_is_targeted_by_titanium_supply_chain(
        self,
        tile_idx: int,
    ) -> bool:
        for source_idx in self.map.own_supply_link_source_indices_by_target_index_in_vision.get(
            tile_idx,
            _EMPTY_SOURCE_INDEX_SET,
        ):
            if self.map.u_supply_chain_has_titanium(source_idx, self.map.own_team):
                return True

        for source_idx in self.map.enemy_supply_link_source_indices_by_target_index_in_vision.get(
            tile_idx,
            _EMPTY_SOURCE_INDEX_SET,
        ):
            if self.map.u_supply_chain_has_titanium(source_idx, self.map.enemy_team):
                return True

        return False

    def u_get_supplier_build_plan(
        self,
        pos: Position,
        resource: Environment = Environment.ORE_TITANIUM,
    ) -> tuple[EntityType | None, Direction | Position | None]:
        """
        Return the supplier type to build for `resource` at one tile plus its
        chosen target.

        Delegates candidate selection to the conveyor- and bridge-planning
        helpers. If both plans exist, prefer the bridge only when it skips at
        least `BRIDGE_PREFERRED_DIST` cached core-distance steps.
        """
        conveyor_direction = self.u_best_conveyor_orientation(pos, resource)
        bridge_target = self.u_best_bridge_target(pos, resource)

        if conveyor_direction is None and bridge_target is None:
            return (None, None)
        if conveyor_direction is None:
            return (EntityType.BRIDGE, bridge_target)
        if bridge_target is None:
            return (EntityType.CONVEYOR, conveyor_direction)

        source_tile = self.map.u_get_pos_tile(pos)
        conveyor_target_pos = pos.add(conveyor_direction)
        conveyor_target_tile = self.map.u_get_pos_tile(conveyor_target_pos)
        bridge_target_tile = self.map.u_get_pos_tile(bridge_target)
        if (
            conveyor_target_tile.environment in _RESOURCE_ENVIRONMENTS
            and bridge_target_tile.environment not in _RESOURCE_ENVIRONMENTS
        ):
            return (EntityType.BRIDGE, bridge_target)

        bridge_dist_covered = (
            source_tile.own_core_dist - bridge_target_tile.own_core_dist
        )
        if bridge_dist_covered >= BRIDGE_PREFERRED_DIST:
            return (EntityType.BRIDGE, bridge_target)
        return (EntityType.CONVEYOR, conveyor_direction)

    def u_get_transport_supplier_build_plan(
        self,
        pos: Position,
        resource: Environment = Environment.ORE_TITANIUM,
        prefer_bridge_when_conveyor_targets_existing_chain: bool = True,
        avoid_core: bool = False,
        prefer_join_existing_supply_chain: bool = False,
        supply_chain_label: SupplyChainLabel = SupplyChainLabel.NONE,
    ) -> tuple[EntityType | None, Direction | Position | None]:
        """
        Return the normal transport-oriented supplier plan for `resource` at `pos`.

        Unlike the surround-aware supplier planning, this never intentionally
        points a conveyor into an adjacent resource tile or harvester. It only
        considers transport-oriented conveyor directions plus the normal bridge
        candidate logic.
        """
        conveyor_direction = self.u_best_conveyor_orientation(
            pos,
            resource,
            allow_adjacent_resource_sink=False,
            avoid_core=avoid_core,
            prefer_join_existing_supply_chain=prefer_join_existing_supply_chain,
        )
        bridge_target = self.u_best_bridge_target(
            pos,
            resource,
            avoid_core=avoid_core,
            prefer_join_existing_supply_chain=prefer_join_existing_supply_chain,
        )

        if conveyor_direction is None and bridge_target is None:
            return (None, None)
        if conveyor_direction is None:
            return (EntityType.BRIDGE, bridge_target)
        if bridge_target is None:
            return (EntityType.CONVEYOR, conveyor_direction)

        source_tile = self.map.u_get_pos_tile(pos)
        conveyor_target_tile = self.map.u_get_pos_tile(pos.add(conveyor_direction))
        bridge_target_tile = self.map.u_get_pos_tile(bridge_target)
        is_pure_axionite_supply_chain = supply_chain_label == SupplyChainLabel.AXIONITE
        conveyor_targets_existing_supply_chain = (
            conveyor_target_tile.building.entity_type in SUPPLY_LINK_TYPES
            and conveyor_target_tile.building.team == self.map.own_team
            and conveyor_target_tile.own_supply_chain_label != SupplyChainLabel.NONE
        )
        conveyor_targets_joinable_supply_chain = (
            conveyor_targets_existing_supply_chain
            and self.map.u_supply_chain_is_joinable(
                conveyor_target_tile.index,
                self.map.own_team,
            )
        )
        conveyor_targets_conveyor_feeding_harvester = (
            conveyor_target_tile.building.entity_type in CONVEYOR_ENTITY_TYPES
            and conveyor_target_tile.building.team == self.map.own_team
            and conveyor_target_tile.conveyor_targets_harvester
        )
        bridge_targets_existing_supply_chain = (
            bridge_target_tile.building.entity_type in SUPPLY_LINK_TYPES
            and bridge_target_tile.building.team == self.map.own_team
            and bridge_target_tile.own_supply_chain_label != SupplyChainLabel.NONE
        )
        conveyor_targets_titanium_supply_chain = (
            conveyor_targets_existing_supply_chain
            and bool(
                conveyor_target_tile.own_supply_chain_label
                & SupplyChainLabel.TITANIUM
            )
        )
        bridge_targets_titanium_supply_chain = (
            bridge_targets_existing_supply_chain
            and bool(
                bridge_target_tile.own_supply_chain_label
                & SupplyChainLabel.TITANIUM
            )
        )
        if (
            conveyor_target_tile.environment in _RESOURCE_ENVIRONMENTS
            and bridge_target_tile.environment not in _RESOURCE_ENVIRONMENTS
        ):
            return (EntityType.BRIDGE, bridge_target)
        if (
            is_pure_axionite_supply_chain
            and bridge_targets_titanium_supply_chain
            and not conveyor_targets_titanium_supply_chain
        ):
            return (EntityType.BRIDGE, bridge_target)
        if (
            conveyor_targets_existing_supply_chain
            and not conveyor_targets_joinable_supply_chain
            and not conveyor_targets_conveyor_feeding_harvester
            and not bridge_targets_existing_supply_chain
            and prefer_bridge_when_conveyor_targets_existing_chain
            and not is_pure_axionite_supply_chain
        ):
            return (EntityType.BRIDGE, bridge_target)
        bridge_dist_covered = (
            source_tile.own_core_dist - bridge_target_tile.own_core_dist
        )
        if bridge_dist_covered >= BRIDGE_PREFERRED_DIST:
            return (EntityType.BRIDGE, bridge_target)
        return (EntityType.CONVEYOR, conveyor_direction)

    def u_best_conveyor_orientation(
        self,
        pos: Position,
        resource: Environment = Environment.ORE_TITANIUM,
        surround_target_pos: Position | None = None,
        allow_adjacent_resource_sink: bool = True,
        avoid_core: bool = False,
        prefer_join_existing_supply_chain: bool = False,
    ) -> Direction | None:
        """
        Return the best cardinal output direction for a conveyor at this tile.
        """
        map = self.map
        own_team = map.own_team
        current_pos = map.current_pos
        source_tile = map.u_get_pos_tile(pos)
        source_idx = source_tile.index
        source_core_dist = source_tile.own_core_dist
        tiles_by_index = map.tiles_by_index
        hard_avoid_existing_supply_chain = (
            HARD_AVOID_EXISTING_SUPPLY_CHAIN
            and not prefer_join_existing_supply_chain
        )
        incoming_supply_sources = (
            map.own_supply_link_source_indices_by_target_index_in_vision.get(
                source_idx,
                _EMPTY_SOURCE_INDEX_SET,
            )
        )
        joinable_existing_supply_chain_cache: dict[int, bool] = {}

        def is_joinable_existing_supply_chain(target_idx: int, target_tile) -> bool:
            if not (
                target_tile.building.entity_type in SUPPLY_LINK_TYPES
                and target_tile.building.team == own_team
                and target_tile.own_supply_chain_label != SupplyChainLabel.NONE
            ):
                return False

            root_idx = map.u_get_supply_chain_id_by_index(target_idx, own_team)
            if root_idx is None:
                return False

            is_joinable = joinable_existing_supply_chain_cache.get(root_idx)
            if is_joinable is None:
                is_joinable = map.u_supply_chain_is_joinable(target_idx, own_team)
                joinable_existing_supply_chain_cache[root_idx] = is_joinable
            return is_joinable

        if allow_adjacent_resource_sink:
            saw_adjacent_resource = False
            all_adjacent_resources_have_own_conveyor = True
            best_adjacent_harvester_direction = None
            best_adjacent_harvester_key = None
            surround_direction = None

            for direction in _CARDINAL_DIRECTIONS:
                adjacent_idx = map.u_get_neighbor_index_by_direction(source_idx, direction)
                if adjacent_idx is None:
                    continue
                adjacent_tile = tiles_by_index[adjacent_idx]
                if adjacent_tile.environment != resource:
                    continue

                saw_adjacent_resource = True
                has_adjacent_own_conveyor = False
                for neighbor_idx in map.u_iter_cardinal_neighbor_indices(adjacent_idx):
                    neighbor_tile = tiles_by_index[neighbor_idx]
                    if (
                        neighbor_tile.building.team == own_team
                        and neighbor_tile.building.entity_type in CONVEYOR_ENTITY_TYPES
                    ):
                        has_adjacent_own_conveyor = True
                        break
                if not has_adjacent_own_conveyor:
                    all_adjacent_resources_have_own_conveyor = False

                if (
                    adjacent_tile.building.team == own_team
                    and adjacent_tile.building.entity_type == EntityType.HARVESTER
                ):
                    adjacent_key = (
                        adjacent_tile.position.x,
                        adjacent_tile.position.y,
                    )
                    if (
                        best_adjacent_harvester_key is None
                        or adjacent_key < best_adjacent_harvester_key
                    ):
                        best_adjacent_harvester_key = adjacent_key
                        best_adjacent_harvester_direction = direction

                if (
                    surround_target_pos is not None
                    and adjacent_tile.position == surround_target_pos
                ):
                    surround_direction = direction

            if saw_adjacent_resource and all_adjacent_resources_have_own_conveyor:
                if (
                    best_adjacent_harvester_direction is not None
                    and not DISABLE_CONVEYORS_POINTING_AT_HARVESTERS
                ):
                    return best_adjacent_harvester_direction
                if surround_direction is not None:
                    return surround_direction

        best_direction = None
        best_key: tuple[int, int, int, int, int, int, int, int, int] | None = None
        for direction in _CARDINAL_DIRECTIONS:
            neighbor_idx = map.u_get_neighbor_index_by_direction(source_idx, direction)
            if neighbor_idx is None:
                continue

            neighbor_tile = tiles_by_index[neighbor_idx]
            if (
                neighbor_tile.last_seen_turn == map.current_round
                and neighbor_tile.building.team == own_team
                and neighbor_tile.building.entity_type in SUPPLY_LINK_TYPES
            ):
                if neighbor_idx in incoming_supply_sources:
                    continue
            elif any(target.position == pos for target in neighbor_tile.building.targets):
                continue
            if neighbor_tile.is_core_of(own_team):
                if avoid_core:
                    continue
                return direction

            category_rank = self.u_get_supplier_tile_category_rank(
                neighbor_tile,
                resource,
            )
            if category_rank is None:
                continue

            is_existing_supply_chain_tile = (
                neighbor_tile.building.entity_type in SUPPLY_LINK_TYPES
                and neighbor_tile.building.team == own_team
                and neighbor_tile.own_supply_chain_label != SupplyChainLabel.NONE
            )
            is_joinable_existing_supply_chain_tile = (
                is_existing_supply_chain_tile
                and is_joinable_existing_supply_chain(neighbor_idx, neighbor_tile)
            )
            neighbor_core_dist = neighbor_tile.own_core_dist
            if neighbor_core_dist > source_core_dist:
                continue
            if (
                neighbor_core_dist == source_core_dist
                and (
                    not hard_avoid_existing_supply_chain
                    or is_existing_supply_chain_tile
                )
            ):
                continue

            candidate_key = (
                1 if neighbor_tile.environment in _RESOURCE_ENVIRONMENTS else 0,
                0 if is_joinable_existing_supply_chain_tile else 1,
                (
                    0
                    if (
                        is_existing_supply_chain_tile
                        == prefer_join_existing_supply_chain
                    )
                    else 1
                ),
                1 if neighbor_core_dist == source_core_dist else 0,
                category_rank,
                neighbor_core_dist,
                0
                if current_pos.distance_squared(neighbor_tile.position)
                <= BUILDER_ACTION_RADIUS_SQ
                else 1,
                neighbor_tile.position.x,
                neighbor_tile.position.y,
            )
            if best_key is None or candidate_key < best_key:
                best_key = candidate_key
                best_direction = direction

        return best_direction

    def u_get_supplier_tile_category_rank(
        self,
        target_tile,
        resource: Environment = Environment.ORE_TITANIUM,
    ) -> int | None:
        own_team = self.map.own_team
        if target_tile.environment == Environment.WALL:
            return None
        if (
            target_tile.building.entity_type in SUPPLY_LINK_TYPES
            and target_tile.building.team == own_team
        ):
            if target_tile.own_supply_chain_label == SupplyChainLabel.NONE:
                return None
            return 0
        if (
            target_tile.building.entity_type == EntityType.BARRIER
            and target_tile.building.team == own_team
        ):
            return 1
        if (
            target_tile.building.entity_type == EntityType.ROAD
            and target_tile.building.team == own_team
        ):
            return 2
        if target_tile.building.id is None:
            return 3
        if (
            target_tile.building.entity_type == EntityType.ROAD
            and target_tile.building.team != own_team
        ):
            return 4
        return None

    def u_best_bridge_target(
        self,
        pos: Position,
        resource: Environment = Environment.ORE_TITANIUM,
        avoid_core: bool = False,
        prefer_join_existing_supply_chain: bool = False,
    ) -> Position | None:
        """
        Return the best bridge target tile reachable from this source tile.
        """
        map = self.map
        current_pos = map.current_pos
        source_tile = map.u_get_pos_tile(pos)
        source_idx = source_tile.index
        source_core_dist = source_tile.own_core_dist
        own_team = map.own_team
        map_width = map.width
        map_height = map.height
        active_mask = map.active_mask_by_index
        tiles_by_index = map.tiles_by_index
        pos_x = pos.x
        pos_y = pos.y
        incoming_supply_sources = (
            map.own_supply_link_source_indices_by_target_index_in_vision.get(
                source_idx,
                _EMPTY_SOURCE_INDEX_SET,
            )
        )
        joinable_existing_supply_chain_cache: dict[int, bool] = {}

        def is_joinable_existing_supply_chain(target_idx: int, target_tile) -> bool:
            if not (
                target_tile.building.entity_type in SUPPLY_LINK_TYPES
                and target_tile.building.team == own_team
                and target_tile.own_supply_chain_label != SupplyChainLabel.NONE
            ):
                return False

            root_idx = map.u_get_supply_chain_id_by_index(target_idx, own_team)
            if root_idx is None:
                return False

            is_joinable = joinable_existing_supply_chain_cache.get(root_idx)
            if is_joinable is None:
                is_joinable = map.u_supply_chain_is_joinable(target_idx, own_team)
                joinable_existing_supply_chain_cache[root_idx] = is_joinable
            return is_joinable

        best_target_pos = None
        best_target_key = None
        for dx, dy in _BRIDGE_TARGET_OFFSETS:
            nx = pos_x + dx
            ny = pos_y + dy
            if nx < 0 or ny < 0 or nx >= map_width or ny >= map_height:
                continue
            target_idx = map.u_to_index_xy(nx, ny)
            if not active_mask[target_idx]:
                continue
            target_tile = tiles_by_index[target_idx]
            if (
                target_tile.last_seen_turn == map.current_round
                and target_tile.building.team == own_team
                and target_tile.building.entity_type in SUPPLY_LINK_TYPES
            ):
                if target_idx in incoming_supply_sources:
                    continue
            elif any(target.position == pos for target in target_tile.building.targets):
                continue
            if target_tile.own_core_dist >= source_core_dist:
                continue
            resource_penalty = (
                1 if target_tile.environment in _RESOURCE_ENVIRONMENTS else 0
            )
            if target_tile.is_core_of(own_team):
                if avoid_core:
                    continue
                target_key = (
                    resource_penalty,
                    0,
                    0,
                    0,
                    0,
                    current_pos.distance_squared(target_tile.position),
                    target_tile.position.x,
                    target_tile.position.y,
                    0,
                )
            else:
                is_existing_supply_chain_tile = (
                    target_tile.building.entity_type in SUPPLY_LINK_TYPES
                    and target_tile.building.team == own_team
                    and target_tile.own_supply_chain_label != SupplyChainLabel.NONE
                )
                is_joinable_existing_supply_chain_tile = (
                    is_existing_supply_chain_tile
                    and is_joinable_existing_supply_chain(target_idx, target_tile)
                )
                category_rank = self.u_get_bridge_target_category_rank(
                    target_tile,
                    resource,
                )
                if category_rank is None:
                    continue
                target_key = (
                    resource_penalty,
                    1,
                    0 if is_joinable_existing_supply_chain_tile else 1,
                    (
                        0
                        if (
                            is_existing_supply_chain_tile
                            == prefer_join_existing_supply_chain
                        )
                        else 1
                    ),
                    category_rank,
                    target_tile.own_core_dist,
                    0
                    if current_pos.distance_squared(target_tile.position)
                    <= BUILDER_ACTION_RADIUS_SQ
                    else 1,
                    target_tile.position.x,
                    target_tile.position.y,
                )
            if best_target_key is None or target_key < best_target_key:
                best_target_key = target_key
                best_target_pos = target_tile.position
            if self.round_stopwatch.check_overtime():
                break

        return best_target_pos

    def u_get_bridge_target_category_rank(
        self,
        target_tile,
        resource: Environment = Environment.ORE_TITANIUM,
    ) -> int | None:
        own_team = self.map.own_team
        if target_tile.environment == Environment.WALL:
            return None
        if target_tile.building.id is None or (
            target_tile.building.team == own_team
            and target_tile.building.entity_type
            in {EntityType.BARRIER, EntityType.ROAD}
        ):
            return 0
        if (
            target_tile.building.entity_type in SUPPLY_LINK_TYPES
            and target_tile.building.team == own_team
        ):
            if target_tile.own_supply_chain_label == SupplyChainLabel.NONE:
                return None
            return 1
        if (
            target_tile.building.entity_type == EntityType.ROAD
            and target_tile.building.team != own_team
        ):
            return 2
        return None

    def u_move_to_astar(
        self,
        pos: Position,
        avoid_enemy_turrets: bool = True,
        build_new_roads: bool = True,
        allow_conveyor_building: bool = True,
        reach_builder_action_range: bool = False,
        respect_titanium_reserve_for_road_build: bool = False,
    ) -> bool:
        current_pos = self.map.current_pos
        if current_pos == pos:
            return False
        respect_titanium_reserve_for_road_build = (
            self.u_should_respect_titanium_reserve_for_road_build(
                respect_titanium_reserve_for_road_build
            )
        )

        print("Move to target:", pos)

        if reach_builder_action_range:
            next_tile = self.map.u_get_next_step_to_builder_action_range_astar(
                current_pos,
                pos,
                avoid_enemy_turrets=avoid_enemy_turrets,
            )
        else:
            next_tile = self.map.u_get_next_step_towards_astar(
                current_pos,
                pos,
                avoid_enemy_turrets=avoid_enemy_turrets,
            )
        if next_tile is not None:
            next_direction = self.map.u_get_direction_between(
                current_pos,
                next_tile.position,
            )
            return self.u_try_progress_move_step(
                next_tile,
                next_direction,
                pos,
                build_new_roads=build_new_roads,
                allow_conveyor_building=allow_conveyor_building,
                respect_titanium_reserve_for_road_build=(
                    respect_titanium_reserve_for_road_build
                ),
            )

        return False

    def u_attack_passable(
        self,
        pos: Position,
        move_towards: bool,
        destroy_condition: Callable[[Position], bool] | None = None,
        avoid_enemy_turrets: bool = True,
        ignore_conveyor_reserve_if_target_damaged: bool = False,
    ) -> bool:
        current_pos = self.map.current_pos
        target_tile = self.map.u_get_pos_tile(pos)

        if current_pos == pos:
            if target_tile.building.id is None:
                return False
            if not self.ct.can_fire(current_pos):
                return False

            current_titanium, _ = self.ct.get_global_resources()
            conveyor_titanium_cost, _ = self.ct.get_conveyor_cost()
            attack_titanium_cost = int(
                math.ceil(
                    GameConstants.BUILDER_BOT_ATTACK_COST[0]
                    * max(0.0001, self.ct.get_scale_percent() / 100.0)
                )
            )
            target_is_damaged = target_tile.building.hp < self.ct.get_max_hp(
                target_tile.building.id
            )
            if (
                not (
                    ignore_conveyor_reserve_if_target_damaged and target_is_damaged
                )
                and current_titanium - attack_titanium_cost < conveyor_titanium_cost
            ):
                return False

            would_destroy = (
                target_tile.building.hp <= GameConstants.BUILDER_BOT_ATTACK_DAMAGE
            )
            if (
                would_destroy
                and destroy_condition is not None
                and not destroy_condition(pos)
            ):
                return False

            self.ct.fire(current_pos)
            return True

        if not move_towards:
            return False
        return self.u_move_to(
            pos,
            avoid_enemy_turrets=avoid_enemy_turrets,
        )

    def u_build_at(
        self,
        pos: Position,
        building_type: EntityType,
        hold: bool,
        move_towards: bool,
        attack_enemy_passable: bool,
        facing_direction: Direction | None = None,
        target_pos: Position | None = None,
        avoid_enemy_turrets: bool = True,
        allow_conveyor_building: bool = True,
        respect_titanium_reserve: bool = False,
        allow_sentinel_next_to_harvester_instead_conveyor: bool = True,
        safety_conveyor: bool = False,
    ) -> bool:
        total_start_ns = time.perf_counter_ns()
        last_step_ns = total_start_ns

        def log_step(label: str) -> None:
            nonlocal last_step_ns
            now_ns = time.perf_counter_ns()
            print(
                "Build_at timing:",
                label,
                f"{(now_ns - last_step_ns) / 1_000_000:.3f} ms",
            )
            last_step_ns = now_ns

        def finish(result: bool, label: str) -> bool:
            log_step(label)
            print(
                "Build_at timing: total",
                f"{(time.perf_counter_ns() - total_start_ns) / 1_000_000:.3f} ms",
            )
            return result

        current_pos = self.map.current_pos
        target_tile = self.map.u_get_pos_tile(pos)
        self.last_built_entity_type = None

        if building_type == EntityType.CONVEYOR:
            armoured_titanium_cost, armoured_axionite_cost = (
                self.ct.get_armoured_conveyor_cost()
            )
            adjacent_to_own_harvester = any(
                adjacent_tile.building.team == self.map.own_team
                and adjacent_tile.building.entity_type == EntityType.HARVESTER
                for adjacent_tile in (
                    self.map.u_get_pos_tile(adjacent_pos)
                    for adjacent_pos in self.map.u_iter_adjacent_cardinal_positions(
                        pos
                    )
                )
            )
            conveyor_targets_own_turret = False
            if facing_direction is not None and facing_direction != Direction.CENTRE:
                conveyor_output_pos = pos.add(facing_direction)
                if self.map.u_is_in_bounds(conveyor_output_pos):
                    conveyor_output_tile = self.map.u_get_pos_tile(conveyor_output_pos)
                    conveyor_targets_own_turret = (
                        conveyor_output_tile.building.team == self.map.own_team
                        and conveyor_output_tile.building.entity_type
                        in ATTACK_TURRET_TYPES
                    )
            if (
                self.map.titanium >= armoured_titanium_cost
                and self.map.axionite >= armoured_axionite_cost
                and self.map.axionite - armoured_axionite_cost >= 1
                and (
                    adjacent_to_own_harvester
                    or conveyor_targets_own_turret
                )
            ):
                building_type = EntityType.ARMOURED_CONVEYOR

        if building_type in CONVEYOR_ENTITY_TYPES and not allow_conveyor_building:
            return finish(False, "reject conveyor build")
        print(
            "Build target:",
            building_type,
            "at",
            pos,
            "facing",
            facing_direction,
            "target",
            target_pos,
        )
        log_step("setup")
        can_build_on_own_tile = building_type in {
            EntityType.ARMOURED_CONVEYOR,
            EntityType.BRIDGE,
            EntityType.CONVEYOR,
            EntityType.ROAD,
        }

        if avoid_enemy_turrets and target_tile.is_enemy_turret_target_tile:
            return finish(False, "reject enemy turret tile")

        titanium_cost, axionite_cost = getattr(
            self.ct, f"get_{building_type.value}_cost"
        )()
        log_step("cost lookup")

        meets_titanium_reserve = (
            not respect_titanium_reserve
            or self.u_can_spend_titanium_without_falling_below_reserve(titanium_cost)
        )
        affordable = (
            meets_titanium_reserve
            and self.map.titanium >= titanium_cost
            and self.map.axionite >= axionite_cost
        )
        can_hold_build_target = (
            target_tile.building.id is None
            or (
                target_tile.building.entity_type == EntityType.ROAD
                and target_tile.building.team == self.map.own_team
            )
            or (
                building_type == EntityType.HARVESTER
                and target_tile.building.entity_type in CONVEYOR_ENTITY_TYPES
                and target_tile.building.team == self.map.own_team
                and target_tile.conveyor_targets_harvester
            )
            or (
                target_tile.building.entity_type == EntityType.BARRIER
                and building_type != EntityType.BARRIER
            )
        )
        log_step("affordability and hold checks")
        if (
            hold
            and can_hold_build_target
            and not affordable
            and current_pos.distance_squared(pos) <= BUILDER_ACTION_RADIUS_SQ
        ):
            return finish(True, "hold affordable wait in range")
        if not affordable:
            if not hold:
                return finish(False, "reject unaffordable without hold")
            if not move_towards:
                return finish(False, "reject unaffordable without move")
            log_step("pre astar unaffordable")
            move_result = self.u_move_to(
                pos,
                avoid_enemy_turrets=avoid_enemy_turrets,
                reach_builder_action_range=True,
            )
            log_step("astar unaffordable")
            return finish(move_result, "return unaffordable move")

        if current_pos.distance_squared(pos) <= BUILDER_ACTION_RADIUS_SQ and (
            pos != current_pos or can_build_on_own_tile
        ):
            destroyed_replaceable_blocker = False
            should_try_attack_enemy_passable = (
                attack_enemy_passable
                and target_tile.is_passable
                and target_tile.building.team != self.map.own_team
            )
            adjacent_tiles = tuple(
                self.map.u_get_pos_tile(adjacent_pos)
                for adjacent_pos in self.map.u_iter_adjacent_cardinal_positions(pos)
            )
            adjacent_to_own_harvester = any(
                adjacent_tile.building.team == self.map.own_team
                and adjacent_tile.building.entity_type == EntityType.HARVESTER
                for adjacent_tile in adjacent_tiles
            )
            adjacent_to_own_titanium_harvester = any(
                adjacent_tile.building.team == self.map.own_team
                and adjacent_tile.building.entity_type == EntityType.HARVESTER
                and adjacent_tile.environment == Environment.ORE_TITANIUM
                for adjacent_tile in adjacent_tiles
            )
            conveyor_like_feeds_own_harvester = False
            conveyor_like_feeds_own_titanium_harvester = False
            if (
                building_type in CONVEYOR_ENTITY_TYPES
                and facing_direction is not None
                and pos != current_pos
            ):
                conveyor_output_pos = pos.add(facing_direction)
                if self.map.u_is_in_bounds(conveyor_output_pos):
                    conveyor_output_tile = self.map.u_get_pos_tile(conveyor_output_pos)
                    conveyor_output_is_cardinal_neighbor = (
                        abs(conveyor_output_pos.x - pos.x)
                        + abs(conveyor_output_pos.y - pos.y)
                        == 1
                    )
                    conveyor_like_feeds_own_harvester = (
                        conveyor_output_is_cardinal_neighbor
                        and conveyor_output_tile.building.team == self.map.own_team
                        and conveyor_output_tile.building.entity_type
                        == EntityType.HARVESTER
                    )
                    conveyor_like_feeds_own_titanium_harvester = (
                        conveyor_like_feeds_own_harvester
                        and adjacent_to_own_titanium_harvester
                        and conveyor_output_tile.environment == Environment.ORE_TITANIUM
                    )
            barrier_adjacent_to_own_harvester = (
                building_type == EntityType.BARRIER
                and adjacent_to_own_harvester
            )
            barrier_adjacent_to_own_titanium_harvester = (
                building_type == EntityType.BARRIER
                and adjacent_to_own_titanium_harvester
            )
            sentinel_substitution_candidate = (
                conveyor_like_feeds_own_harvester
                or safety_conveyor
                or barrier_adjacent_to_own_harvester
            )
            sentinel_substitution_targets_titanium_harvester = (
                conveyor_like_feeds_own_titanium_harvester
                or (
                    (safety_conveyor or barrier_adjacent_to_own_harvester)
                    and adjacent_to_own_titanium_harvester
                )
            )

            preferred_building_type = building_type
            preferred_facing_direction = facing_direction
            if (
                allow_sentinel_next_to_harvester_instead_conveyor
                and pos != current_pos
            ):
                should_try_turret_substitution = (
                    barrier_adjacent_to_own_titanium_harvester
                    or (
                        building_type in CONVEYOR_ENTITY_TYPES
                        and sentinel_substitution_candidate
                        and sentinel_substitution_targets_titanium_harvester
                    )
                )
                if should_try_turret_substitution:
                    turret_substitution = (
                        self._u_get_harvester_adjacent_turret_substitution(
                            pos,
                            respect_titanium_reserve,
                        )
                    )
                    if turret_substitution is not None:
                        preferred_building_type, preferred_facing_direction = (
                            turret_substitution
                        )
            log_step("in range prebuild")
            if (
                target_tile.building.team == self.map.own_team
                and target_tile.building.entity_type
                in {EntityType.ROAD, EntityType.BARRIER}
                and target_tile.building.entity_type != building_type
                and self.ct.can_destroy(pos)
            ):
                self.ct.destroy(pos)
                destroyed_replaceable_blocker = True
                log_step("destroy replaceable blocker")
            elif (
                building_type == EntityType.HARVESTER
                and target_tile.building.team == self.map.own_team
                and target_tile.building.entity_type in CONVEYOR_ENTITY_TYPES
                and target_tile.conveyor_targets_harvester
                and self.ct.can_destroy(pos)
            ):
                self.ct.destroy(pos)
                destroyed_replaceable_blocker = True
                log_step("destroy harvester feeder conveyor")

            if affordable:
                actual_building_type = preferred_building_type
                actual_facing_direction = preferred_facing_direction
                can_build_method = getattr(self.ct, f"can_build_{actual_building_type.value}")
                build_method = getattr(self.ct, f"build_{actual_building_type.value}")
                log_step("build method lookup")
                if actual_building_type in DIRECTIONAL_BUILDING_TYPES:
                    if actual_facing_direction is None:
                        return finish(False, "reject missing facing direction")
                    can_build_directional = can_build_method(
                        pos,
                        actual_facing_direction,
                    )
                    if (
                        not can_build_directional
                        and actual_building_type != building_type
                    ):
                        actual_building_type = building_type
                        actual_facing_direction = facing_direction
                        can_build_method = getattr(
                            self.ct,
                            f"can_build_{actual_building_type.value}",
                        )
                        build_method = getattr(
                            self.ct,
                            f"build_{actual_building_type.value}",
                        )
                        if actual_facing_direction is None:
                            return finish(False, "reject missing fallback facing direction")
                        can_build_directional = can_build_method(
                            pos,
                            actual_facing_direction,
                        )
                    if not can_build_directional:
                        log_step("can_build directional")
                        if should_try_attack_enemy_passable:
                            attack_result = self.u_attack_passable(
                                pos,
                                move_towards=move_towards,
                                destroy_condition=lambda _: True,
                                avoid_enemy_turrets=avoid_enemy_turrets,
                            )
                            log_step("attack fallback directional")
                            return finish(
                                attack_result,
                                "return attack fallback directional",
                            )
                        return finish(False, "reject can_build directional")
                    log_step("can_build directional")
                    build_method(pos, actual_facing_direction)
                    self.last_built_entity_type = actual_building_type
                    log_step("build directional")
                    if actual_building_type in CONVEYOR_ENTITY_TYPES:
                        next_direction = self.map.u_get_direction_between(
                            current_pos,
                            pos,
                        )
                        if next_direction is not None and self.ct.can_move(
                            next_direction
                        ):
                            self.u_move_with_target(next_direction, pos)
                        output_pos = pos.add(actual_facing_direction)
                        if self.map.u_is_in_bounds(output_pos):
                            output_tile = self.map.u_get_pos_tile(output_pos)
                            if (
                                output_tile.building.team == self.map.own_team
                                and output_tile.building.entity_type
                                in CONVEYOR_ENTITY_TYPES
                                and output_tile.conveyor_targets_harvester
                                and self.ct.can_destroy(output_pos)
                            ):
                                self.ct.destroy(output_pos)
                                output_tile.clear_building()
                        log_step("conveyor post build")
                    return finish(True, "return directional build")

                if building_type == EntityType.BRIDGE:
                    if target_pos is None:
                        return finish(False, "reject missing bridge target")
                    if not can_build_method(pos, target_pos):
                        log_step("can_build bridge")
                        if should_try_attack_enemy_passable:
                            attack_result = self.u_attack_passable(
                                pos,
                                move_towards=move_towards,
                                destroy_condition=lambda _: True,
                                avoid_enemy_turrets=avoid_enemy_turrets,
                            )
                            log_step("attack fallback bridge")
                            return finish(
                                attack_result,
                                "return attack fallback bridge",
                            )
                        return finish(False, "reject can_build bridge")
                    log_step("can_build bridge")
                    build_method(pos, target_pos)
                    self.last_built_entity_type = building_type
                    log_step("build bridge")
                    return finish(True, "return bridge build")

                if building_type in NONDIRECTIONAL_BUILDING_TYPES:
                    if not can_build_method(pos):
                        log_step("can_build nondirectional")
                        if should_try_attack_enemy_passable:
                            attack_result = self.u_attack_passable(
                                pos,
                                move_towards=move_towards,
                                destroy_condition=lambda _: True,
                                avoid_enemy_turrets=avoid_enemy_turrets,
                            )
                            log_step("attack fallback nondirectional")
                            return finish(
                                attack_result,
                                "return attack fallback nondirectional",
                            )
                        return finish(False, "reject can_build nondirectional")
                    log_step("can_build nondirectional")
                    build_method(pos)
                    self.last_built_entity_type = building_type
                    log_step("build nondirectional")
                    return finish(True, "return nondirectional build")

                raise ValueError(f"Unsupported builder target type: {building_type}")

            if destroyed_replaceable_blocker:
                return finish(True, "return destroyed blocker")

        if (
            attack_enemy_passable
            and target_tile.is_passable
            and target_tile.building.team != self.map.own_team
        ):
            log_step("pre attack fallback")
            attack_result = self.u_attack_passable(
                pos,
                move_towards=move_towards,
                destroy_condition=lambda _: True,
                avoid_enemy_turrets=avoid_enemy_turrets,
            )
            log_step("attack fallback")
            return finish(attack_result, "return attack fallback")

        if not move_towards:
            return finish(False, "reject without move")
        log_step("pre astar move")
        move_result = self.u_move_to(
            pos,
            avoid_enemy_turrets=avoid_enemy_turrets,
            reach_builder_action_range=True,
        )
        log_step("astar move")
        return finish(move_result, "return move")

    def u_heal_at(
        self,
        pos: Position,
        move_towards: bool,
        avoid_enemy_turrets: bool = True,
        allow_low_hp_building_replacement: bool = False,
    ) -> bool:
        current_pos = self.map.current_pos
        if current_pos.distance_squared(pos) <= BUILDER_ACTION_RADIUS_SQ:
            target_tile = self.map.u_get_pos_tile(pos)
            if (
                allow_low_hp_building_replacement
                and target_tile.building.team == self.map.own_team
                and target_tile.building.hp is not None
            ):
                replacement_entity_type = None
                replacement_facing_direction = target_tile.building.direction
                targeted_by_titanium_supply_chain = (
                    target_tile.building.entity_type
                    in {EntityType.GUNNER, EntityType.SENTINEL}
                    and self._u_tile_is_targeted_by_titanium_supply_chain(
                        target_tile.index
                    )
                )

                if (
                    target_tile.building.entity_type == EntityType.CONVEYOR
                    and target_tile.building.hp <= REPLACE_ATTACKED_CONVEYOR_MAX_HP
                ):
                    conveyor_titanium_cost, conveyor_axionite_cost = (
                        self.ct.get_conveyor_cost()
                    )
                    if (
                        self.map.titanium >= conveyor_titanium_cost
                        and self.map.axionite >= conveyor_axionite_cost
                        and replacement_facing_direction is not None
                        and replacement_facing_direction != Direction.CENTRE
                    ):
                        replacement_entity_type = EntityType.CONVEYOR
                elif (
                    target_tile.building.entity_type == EntityType.GUNNER
                    and target_tile.building.hp <= REPLACE_ATTACKED_CONVEYOR_MAX_HP
                    and targeted_by_titanium_supply_chain
                ):
                    gunner_titanium_cost, gunner_axionite_cost = self.ct.get_gunner_cost()
                    if (
                        self.map.titanium >= gunner_titanium_cost
                        and self.map.axionite >= gunner_axionite_cost
                        and replacement_facing_direction is not None
                        and replacement_facing_direction != Direction.CENTRE
                    ):
                        replacement_entity_type = EntityType.GUNNER
                elif (
                    target_tile.building.entity_type == EntityType.SENTINEL
                    and target_tile.building.hp <= REPLACE_ATTACKED_CONVEYOR_MAX_HP
                    and targeted_by_titanium_supply_chain
                ):
                    replacement_facing_direction = (
                        self._u_get_adjacent_enemy_turret_gunner_direction(pos)
                    )
                    if replacement_facing_direction is not None:
                        gunner_titanium_cost, gunner_axionite_cost = (
                            self.ct.get_gunner_cost()
                        )
                        if (
                            self.map.titanium >= gunner_titanium_cost
                            and self.map.axionite >= gunner_axionite_cost
                            and replacement_facing_direction != Direction.CENTRE
                        ):
                            replacement_entity_type = EntityType.GUNNER

                if (
                    replacement_entity_type is not None
                    and self.ct.can_destroy(pos)
                ):
                    self.ct.destroy(pos)
                    target_tile.clear_building()
                    can_build_method = getattr(
                        self.ct,
                        f"can_build_{replacement_entity_type.value}",
                    )
                    build_method = getattr(
                        self.ct,
                        f"build_{replacement_entity_type.value}",
                    )
                    if can_build_method(pos, replacement_facing_direction):
                        build_method(pos, replacement_facing_direction)
                        self.last_built_entity_type = replacement_entity_type
                        return True
                    return False

            if not self.ct.can_heal(pos):
                return False
            self.ct.heal(pos)
            return True

        if not move_towards:
            return False
        return self.u_move_to(
            pos,
            avoid_enemy_turrets=avoid_enemy_turrets,
        )
