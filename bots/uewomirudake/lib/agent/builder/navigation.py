import math
import time
from collections.abc import Callable

from cambc import Direction, EntityType, Environment, GameConstants, Position

from lib.agent.constants import (
    ATTACK_TURRET_FEEDER_TYPES,
    BRIDGE_PREFERRED_DIST,
    BUILDER_ACTION_RADIUS_SQ,
    CONVEYOR_ENTITY_TYPES,
    DISABLE_CONVEYORS_POINTING_AT_HARVESTERS,
    DIRECTIONAL_BUILDING_TYPES,
    ENEMY_TURRET_TYPES,
    HARD_AVOID_EXISTING_SUPPLY_CHAIN,
    NONDIRECTIONAL_BUILDING_TYPES,
)
from lib.map.constants import INF_DIST, SUPPLY_LINK_TYPES
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
_EMPTY_SOURCE_INDEX_SET = frozenset()


class BuilderNavigationMixin:
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

    def u_supply_chain_targets_core(self, resource: Environment) -> bool:
        return True

    def u_get_sentinel_orientation(self, pos: Position) -> Direction:
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

    def u_get_gunner_orientation(self, pos: Position) -> Direction:
        """
        Choose the gunner facing that best shoots down an open firing lane.

        If exactly one own feeder targets this tile, avoid facing back toward
        it. Among the remaining directions, prefer lanes that hit more enemy
        turrets before the first allied building, then lanes that can hit the
        enemy core, then lanes that hit more enemy buildings.
        """
        feeder_directions: list[Direction] = []
        enemy_core_tiles = (
            self.map.u_get_core_footprint_positions(self.map.enemy_core_center_pos)
            if self.map.enemy_core_center_pos is not None
            else []
        )

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

        direction_order = {
            direction: idx
            for idx, direction in enumerate(Direction)
            if direction != Direction.CENTRE
        }
        direction_scores: list[tuple[tuple[int, ...], Direction]] = []

        for direction in candidate_directions:
            visible_enemy_turrets = 0
            visible_enemy_buildings = 0
            can_target_enemy_core = False

            for target_tile in self.map.u_get_gunner_open_ray_tiles(pos, direction):
                if any(
                    core_tile.position == target_tile.position
                    for core_tile in enemy_core_tiles
                ):
                    can_target_enemy_core = True

                if (
                    target_tile.building.id is not None
                    and target_tile.building.team == self.map.enemy_team
                ):
                    visible_enemy_buildings += 1
                    if target_tile.building.entity_type in ENEMY_TURRET_TYPES:
                        visible_enemy_turrets += 1

                if self.round_stopwatch.check_overtime():
                    break

            direction_scores.append(
                (
                    (
                        -visible_enemy_turrets,
                        0 if can_target_enemy_core else 1,
                        -visible_enemy_buildings,
                        direction_order[direction],
                    ),
                    direction,
                )
            )

            if self.round_stopwatch.check_overtime():
                break

        if not direction_scores:
            return candidate_directions[0]

        return min(direction_scores, key=lambda item: item[0])[1]

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
        )
        bridge_target = self.u_best_bridge_target(pos, resource)

        if conveyor_direction is None and bridge_target is None:
            return (None, None)
        if conveyor_direction is None:
            return (EntityType.BRIDGE, bridge_target)
        if bridge_target is None:
            return (EntityType.CONVEYOR, conveyor_direction)

        source_tile = self.map.u_get_pos_tile(pos)
        conveyor_target_tile = self.map.u_get_pos_tile(pos.add(conveyor_direction))
        bridge_target_tile = self.map.u_get_pos_tile(bridge_target)
        conveyor_targets_existing_supply_chain = (
            conveyor_target_tile.building.entity_type in SUPPLY_LINK_TYPES
            and conveyor_target_tile.building.team == self.map.own_team
            and conveyor_target_tile.own_supply_chain_label != SupplyChainLabel.NONE
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
        if (
            conveyor_target_tile.environment in _RESOURCE_ENVIRONMENTS
            and bridge_target_tile.environment not in _RESOURCE_ENVIRONMENTS
        ):
            return (EntityType.BRIDGE, bridge_target)
        if (
            conveyor_targets_existing_supply_chain
            and not conveyor_targets_conveyor_feeding_harvester
            and not bridge_targets_existing_supply_chain
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
        incoming_supply_sources = (
            map.own_supply_link_source_indices_by_target_index_in_vision.get(
                source_idx,
                _EMPTY_SOURCE_INDEX_SET,
            )
        )
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
        best_key: tuple[int, int, int, int, int, int, int, int] | None = None
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
            neighbor_core_dist = neighbor_tile.own_core_dist
            if neighbor_core_dist > source_core_dist:
                continue
            if (
                neighbor_core_dist == source_core_dist
                and (
                    not HARD_AVOID_EXISTING_SUPPLY_CHAIN
                    or is_existing_supply_chain_tile
                )
            ):
                continue

            candidate_key = (
                1 if neighbor_tile.environment in _RESOURCE_ENVIRONMENTS else 0,
                1 if is_existing_supply_chain_tile else 0,
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
                target_key = (
                    resource_penalty,
                    0,
                    current_pos.distance_squared(target_tile.position),
                    target_tile.position.x,
                    target_tile.position.y,
                    0,
                    0,
                )
            else:
                category_rank = self.u_get_bridge_target_category_rank(
                    target_tile,
                    resource,
                )
                if category_rank is None:
                    continue
                target_key = (
                    resource_penalty,
                    1,
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
    ) -> bool:
        current_pos = self.map.current_pos
        if current_pos == pos:
            return False

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
            if next_direction is not None and self.ct.can_move(next_direction):
                self.u_move_with_target(next_direction, pos)
                return True
            if build_new_roads and self.ct.can_build_road(next_tile.position):
                adjacent_resource_tiles = []
                for adjacent_pos in self.map.u_iter_adjacent_cardinal_positions(
                    next_tile.position
                ):
                    adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
                    if adjacent_tile.environment == Environment.ORE_TITANIUM:
                        adjacent_resource_tiles.append(adjacent_tile)

                if allow_conveyor_building and adjacent_resource_tiles:
                    resource_candidates: list[Environment] = []
                    for adjacent_tile in adjacent_resource_tiles:
                        if (
                            adjacent_tile.building.team == self.map.own_team
                            and adjacent_tile.building.entity_type
                            == EntityType.HARVESTER
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
                    self.u_move_with_target(next_direction, pos)
                return True

        return False

    def u_attack_passable(
        self,
        pos: Position,
        move_towards: bool,
        destroy_condition: Callable[[Position], bool] | None = None,
        avoid_enemy_turrets: bool = True,
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
            if current_titanium - attack_titanium_cost < conveyor_titanium_cost:
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
        return self.u_move_to_astar(
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

        affordable = (
            self.map.titanium >= titanium_cost and self.map.axionite >= axionite_cost
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
            move_result = self.u_move_to_astar(
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
                can_build_method = getattr(self.ct, f"can_build_{building_type.value}")
                build_method = getattr(self.ct, f"build_{building_type.value}")
                log_step("build method lookup")
                if building_type in DIRECTIONAL_BUILDING_TYPES:
                    if facing_direction is None:
                        return finish(False, "reject missing facing direction")
                    if not can_build_method(pos, facing_direction):
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
                    build_method(pos, facing_direction)
                    self.last_built_entity_type = building_type
                    log_step("build directional")
                    if building_type in CONVEYOR_ENTITY_TYPES:
                        next_direction = self.map.u_get_direction_between(
                            current_pos,
                            pos,
                        )
                        if next_direction is not None and self.ct.can_move(
                            next_direction
                        ):
                            self.u_move_with_target(next_direction, pos)
                        output_pos = pos.add(facing_direction)
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
        move_result = self.u_move_to_astar(
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
    ) -> bool:
        current_pos = self.map.current_pos
        if current_pos.distance_squared(pos) <= BUILDER_ACTION_RADIUS_SQ:
            if not self.ct.can_heal(pos):
                return False
            self.ct.heal(pos)
            return True

        if not move_towards:
            return False
        return self.u_move_to_astar(
            pos,
            avoid_enemy_turrets=avoid_enemy_turrets,
        )
