import math
from collections.abc import Callable

from cambc import Direction, EntityType, Environment, GameConstants, Position

from lib.agent.constants import (
    AVOID_EMPTY_ORE_BRIDGE_TARGETS,
    AVOID_OTHER_SUPPLY_LABEL_ORES,
    BRIDGE_PREFERRED_DIST,
    BUILDER_ACTION_RADIUS_SQ,
    ATTACK_TURRET_FEEDER_TYPES,
    DIRECTIONAL_BUILDING_TYPES,
    ENEMY_TURRET_TYPES,
    FOUNDRY_WAIT_RADIUS_SQ,
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


class BuilderNavigationMixin:
    def u_is_empty_ore_tile(self, pos: Position) -> bool:
        target_tile = self.map.u_get_pos_tile(pos)
        return target_tile.building.id is None and target_tile.environment in {
            Environment.ORE_TITANIUM,
            Environment.ORE_AXIONITE,
        }

    def u_can_host_foundry_site(self, pos: Position) -> bool:
        target_tile = self.map.u_get_pos_tile(pos)
        if (
            target_tile.building.entity_type == EntityType.FOUNDRY
            and target_tile.building.team == self.map.own_team
        ):
            return True
        if target_tile.building.id is None:
            return True
        return (
            target_tile.building.team == self.map.own_team
            and target_tile.building.entity_type
            in {EntityType.ROAD, EntityType.BARRIER}
        )

    def u_is_harmless_core_splitter_side_tile(self, pos: Position) -> bool:
        target_tile = self.map.u_get_pos_tile(pos)
        return target_tile.building.id is None or (
            target_tile.building.team == self.map.own_team
            and target_tile.building.entity_type
            in {EntityType.ROAD, EntityType.BARRIER}
        )

    def u_get_core_foundry_plan(self) -> Position | None:
        # TODO: Redo foundry logic efficiently and disable foundry logic properly for non-foundry bots
        return None

        if (
            self.map.own_core_center_pos is None
            and not self.map.u_calc_core_center_positions()
        ):
            return None

        own_core_center_pos = self.map.own_core_center_pos
        if own_core_center_pos is None:
            return None

        own_team = self.map.own_team
        planned_foundry_index = self.map.built_foundry_index
        core_tiles = self.map.u_get_core_footprint_positions(own_core_center_pos)
        core_tile_indices = {tile.index for tile in core_tiles}
        candidate_plans: list[tuple[tuple[int, ...], Position]] = []
        seen_foundry_indices: set[int] = set()

        for core_tile in core_tiles:
            for foundry_pos in self.map.u_iter_adjacent_cardinal_positions(
                core_tile.position,
            ):
                foundry_tile = self.map.u_get_pos_tile(foundry_pos)
                if (
                    foundry_tile.index in core_tile_indices
                    or foundry_tile.index in seen_foundry_indices
                ):
                    continue
                seen_foundry_indices.add(foundry_tile.index)

                if not self.u_can_host_foundry_site(foundry_pos):
                    continue
                if (
                    foundry_tile.building.entity_type != EntityType.FOUNDRY
                    and foundry_tile.own_supply_chain_label & SupplyChainLabel.TITANIUM
                ):
                    continue
                if (
                    foundry_tile.building.entity_type != EntityType.FOUNDRY
                    and self.map.u_is_chokepoint(foundry_pos)
                ):
                    continue

                planned_rank = 0 if foundry_tile.index == planned_foundry_index else 1
                foundry_rank = 0
                if (
                    foundry_tile.building.entity_type != EntityType.FOUNDRY
                    or foundry_tile.building.team != own_team
                ):
                    if foundry_tile.building.id is None:
                        foundry_rank = 1
                    elif foundry_tile.building.entity_type == EntityType.ROAD:
                        foundry_rank = 2
                    else:
                        foundry_rank = 3
                label_rank = (
                    0
                    if foundry_tile.own_supply_chain_label & SupplyChainLabel.AXIONITE
                    else 1
                )
                bot_dist_rank = foundry_tile.dist_to_self
                candidate_plans.append(
                    (
                        (
                            planned_rank,
                            foundry_rank,
                            label_rank,
                            bot_dist_rank,
                            foundry_tile.position.x,
                            foundry_tile.position.y,
                        ),
                        foundry_pos,
                    )
                )

        if not candidate_plans:
            return None

        return min(candidate_plans, key=lambda item: item[0])[1]

    def u_get_visible_titanium_core_chain_candidates(
        self,
    ) -> list[tuple[Position, Direction]]:
        own_team = self.map.own_team
        visible_titanium_tiles_by_index = {
            tile.index: tile
            for tile in self.map.own_supply_links_in_vision
            if tile.own_supply_chain_label & SupplyChainLabel.TITANIUM
        }
        if not visible_titanium_tiles_by_index:
            return []

        reverse_edges_by_index: dict[int, list[tuple[int, Direction]]] = {}
        coreward_directions_by_index: dict[int, set[Direction]] = {}

        for tile in visible_titanium_tiles_by_index.values():
            if self.map.u_is_own_supply_link_occupied_by_other_builder(tile):
                continue
            for target_tile in tile.building.targets:
                target_direction = self.map.u_get_direction_between(
                    tile.position,
                    target_tile.position,
                )
                if target_direction is None:
                    continue

                if target_tile.is_core_of(own_team):
                    coreward_directions_by_index.setdefault(tile.index, set()).add(
                        target_direction
                    )
                    continue

                if target_tile.index not in visible_titanium_tiles_by_index:
                    continue

                reverse_edges_by_index.setdefault(target_tile.index, []).append(
                    (tile.index, target_direction)
                )

            if self.round_stopwatch.check_overtime():
                break

        queue = list(coreward_directions_by_index)
        queue_idx = 0
        while queue_idx < len(queue):
            target_idx = queue[queue_idx]
            queue_idx += 1

            for source_idx, source_direction in reverse_edges_by_index.get(
                target_idx,
                [],
            ):
                source_directions = coreward_directions_by_index.setdefault(
                    source_idx,
                    set(),
                )
                if source_direction in source_directions:
                    continue
                source_directions.add(source_direction)
                queue.append(source_idx)

            if self.round_stopwatch.check_overtime():
                break

        candidate_plans: list[tuple[Position, Direction]] = []
        for tile_idx, directions in coreward_directions_by_index.items():
            tile = visible_titanium_tiles_by_index[tile_idx]
            for direction in directions:
                candidate_plans.append((tile.position, direction))

            if self.round_stopwatch.check_overtime():
                break

        return candidate_plans

    def u_get_core_splitter_foundry_plan(
        self,
    ) -> tuple[Position, Direction, Position] | None:
        own_team = self.map.own_team
        planned_foundry_pos = self.u_get_core_foundry_plan()
        if planned_foundry_pos is None:
            return None

        current_pos = self.map.current_pos
        visible_titanium_chain_indices = {
            tile.index
            for tile in self.map.own_supply_links_in_vision
            if tile.own_supply_chain_label & SupplyChainLabel.TITANIUM
        }
        candidate_plans: list[tuple[tuple[int, ...], Position, Direction, Position]] = (
            []
        )

        for (
            splitter_pos,
            splitter_direction,
        ) in self.u_get_visible_titanium_core_chain_candidates():
            if self.round_stopwatch.check_overtime():
                break
            splitter_tile = self.map.u_get_pos_tile(splitter_pos)
            splitter_building = splitter_tile.building
            if (
                splitter_building.team != own_team
                or splitter_building.entity_type not in SUPPLY_LINK_TYPES
            ):
                continue

            side_positions = [
                splitter_pos.add(direction)
                for direction in (
                    splitter_direction.rotate_left().rotate_left(),
                    splitter_direction.rotate_right().rotate_right(),
                )
            ]
            if not all(
                self.map.u_is_in_bounds(side_pos)
                and (
                    side_pos == planned_foundry_pos
                    or self.u_is_harmless_core_splitter_side_tile(side_pos)
                )
                for side_pos in side_positions
            ):
                continue
            if not any(
                self.u_can_route_supply_chain_to_target(
                    side_pos,
                    planned_foundry_pos,
                    Environment.ORE_TITANIUM,
                    visible_titanium_chain_indices,
                )
                for side_pos in side_positions
            ):
                continue

            splitter_rank = 1
            if (
                splitter_building.entity_type == EntityType.SPLITTER
                and splitter_building.direction == splitter_direction
            ):
                splitter_rank = 0

            candidate_plans.append(
                (
                    (
                        current_pos.distance_squared(splitter_pos),
                        splitter_tile.own_core_dist,
                        splitter_rank,
                        splitter_tile.position.x,
                        splitter_tile.position.y,
                    ),
                    splitter_pos,
                    splitter_direction,
                    planned_foundry_pos,
                )
            )

        if not candidate_plans:
            return None

        _, splitter_pos, splitter_direction, foundry_pos = min(candidate_plans, key=lambda item: item[0])
        return (splitter_pos, splitter_direction, foundry_pos)

    def u_get_foundry_wait_position(self, foundry_pos: Position) -> Position | None:
        own_team = self.map.own_team
        current_pos = self.map.current_pos
        candidate_tiles: list[tuple[tuple[int, ...], Position]] = []

        for tile_idx in self.map.u_iter_active_tile_indices():
            if self.round_stopwatch.check_overtime():
                break
            tile = self.map.tiles_by_index[tile_idx]
            tile_pos = tile.position
            if (
                tile_pos == foundry_pos
                or tile_pos.distance_squared(foundry_pos) > FOUNDRY_WAIT_RADIUS_SQ
            ):
                continue
            if tile.dist_to_self >= INF_DIST:
                continue
            if tile.is_core_of(own_team):
                continue
            if tile.bot.id is not None and tile_pos != current_pos:
                continue
            if tile.environment in {
                Environment.ORE_TITANIUM,
                Environment.ORE_AXIONITE,
            }:
                continue
            if (
                tile.own_supply_chain_label != SupplyChainLabel.NONE
                or tile.enemy_supply_chain_label != SupplyChainLabel.NONE
            ):
                continue
            if (
                tile.index in self.map.own_supply_link_target_indices_in_vision
                or tile.index in self.map.enemy_supply_link_target_indices_in_vision
            ):
                continue
            if self.map.u_is_chokepoint(tile_pos):
                continue
            if tile.building.id is None:
                tile_kind_rank = 0 if tile.environment == Environment.EMPTY else 1
            elif (
                tile.building.entity_type == EntityType.ROAD
                and tile.building.team == own_team
            ):
                tile_kind_rank = 2
            else:
                continue
            if tile_pos != current_pos and not tile.is_passable:
                continue

            is_foundry_cardinal = (
                abs(tile_pos.x - foundry_pos.x) + abs(tile_pos.y - foundry_pos.y) == 1
            )
            is_core_adjacent = any(
                self.map.u_get_pos_tile(neighbor_pos).is_core_of(own_team)
                for neighbor_pos in self.map.u_iter_adjacent_cardinal_positions(
                    tile_pos,
                )
            )
            candidate_tiles.append(
                (
                    (
                        1 if is_foundry_cardinal else 0,
                        1 if is_core_adjacent else 0,
                        tile_kind_rank,
                        tile_pos.distance_squared(foundry_pos),
                        tile.dist_to_self,
                        tile_pos.x,
                        tile_pos.y,
                    ),
                    tile_pos,
                )
            )

        if not candidate_tiles:
            return None

        return min(candidate_tiles, key=lambda item: item[0])[1]

    def u_foundry_site_has_visible_axionite_supply(
        self,
        foundry_pos: Position,
    ) -> bool:
        foundry_tile = self.map.u_get_pos_tile(foundry_pos)
        if (
            foundry_tile.last_seen_turn != self.map.current_round
            or foundry_tile.index
            not in self.map.own_supply_link_target_indices_in_vision
        ):
            return False

        for neighbor_pos in self.map.u_iter_adjacent_cardinal_positions(
            foundry_pos,
        ):
            neighbor_tile = self.map.u_get_pos_tile(neighbor_pos)
            if not (
                neighbor_tile.building.team == self.map.own_team
                and neighbor_tile.building.entity_type in SUPPLY_LINK_TYPES
                and not self.map.u_is_own_supply_link_occupied_by_other_builder(
                    neighbor_tile
                )
                and neighbor_tile.own_supply_chain_label & SupplyChainLabel.AXIONITE
                and any(
                    target.index == foundry_tile.index
                    for target in neighbor_tile.building.targets
                )
            ):
                continue
            return True

        return False

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
        via_bridge: bool,
    ) -> bool:
        if pos == target_pos:
            return True

        target_tile = self.map.u_get_pos_tile(pos)
        if target_tile.index in blocked_indices:
            return False
        if target_tile.environment == Environment.WALL:
            return False
        if self.u_is_supply_tile_forbidden(pos, resource):
            return False
        if (
            target_tile.building.entity_type in SUPPLY_LINK_TYPES
            and target_tile.building.team == self.map.own_team
        ):
            return False
        if (
            via_bridge
            and AVOID_EMPTY_ORE_BRIDGE_TARGETS
            and self.u_is_empty_ore_tile(pos)
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
            via_bridge=False,
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
                    via_bridge=False,
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
                    via_bridge=True,
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

    def u_get_supply_chain_progress_key(
        self,
        pos: Position,
        resource: Environment,
    ) -> tuple[int, int]:
        target_tile = self.map.u_get_pos_tile(pos)
        if resource == Environment.ORE_AXIONITE:
            foundry_pos = self.u_get_core_foundry_plan()
            if foundry_pos is not None:
                return (
                    pos.distance_squared(foundry_pos),
                    target_tile.own_core_dist,
                )
        return (target_tile.own_core_dist, 0)

    def u_get_supply_chain_label_for_resource(
        self,
        resource: Environment,
    ) -> SupplyChainLabel:
        if resource == Environment.ORE_TITANIUM:
            return SupplyChainLabel.TITANIUM
        if resource == Environment.ORE_AXIONITE:
            return SupplyChainLabel.AXIONITE
        return SupplyChainLabel.NONE

    def u_get_supply_chain_avoidance_label(
        self,
        resource: Environment,
    ) -> SupplyChainLabel:
        avoidance_ore = self.u_get_supply_chain_avoidance_ore(resource)
        if avoidance_ore is None:
            return SupplyChainLabel.NONE
        return self.u_get_supply_chain_label_for_resource(avoidance_ore)

    def u_get_supply_chain_avoidance_ore(
        self,
        resource: Environment,
    ) -> Environment | None:
        if resource == Environment.ORE_TITANIUM:
            return Environment.ORE_AXIONITE
        if resource == Environment.ORE_AXIONITE:
            return Environment.ORE_TITANIUM
        return None

    def u_supply_chain_targets_core(self, resource: Environment) -> bool:
        return resource == Environment.ORE_TITANIUM

    def u_is_axionite_foundry_target(
        self,
        pos: Position,
        resource: Environment,
    ) -> bool:
        if resource != Environment.ORE_AXIONITE:
            return False

        foundry_pos = self.u_get_core_foundry_plan()
        return foundry_pos is not None and pos == foundry_pos

    def u_can_wrap_axionite_chain_around_core(
        self,
        source_pos: Position,
        target_pos: Position,
        resource: Environment,
    ) -> bool:
        if resource != Environment.ORE_AXIONITE:
            return False

        source_tile = self.map.u_get_pos_tile(source_pos)
        if source_tile.own_core_dist != 1:
            return False

        foundry_pos = self.u_get_core_foundry_plan()
        if foundry_pos is None:
            return False

        return target_pos.distance_squared(foundry_pos) < source_pos.distance_squared(
            foundry_pos
        )

    def u_is_supply_tile_forbidden(
        self,
        pos: Position,
        resource: Environment,
    ) -> bool:
        target_tile = self.map.u_get_pos_tile(pos)
        avoidance_label = self.u_get_supply_chain_avoidance_label(resource)
        avoidance_ore = self.u_get_supply_chain_avoidance_ore(resource)
        return bool(
            (
                avoidance_label != SupplyChainLabel.NONE
                and target_tile.own_supply_chain_label & avoidance_label
            )
            or (
                AVOID_EMPTY_ORE_BRIDGE_TARGETS
                and avoidance_ore is not None
                and self.map.u_is_adjacent_to_ore(pos, avoidance_ore)
            )
        )

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
        foundry_pos = self.u_get_core_foundry_plan()
        if (
            resource == Environment.ORE_AXIONITE
            and foundry_pos is not None
            and pos == foundry_pos
        ):
            return (None, None)
        if self.u_is_supply_tile_forbidden(pos, resource):
            return (None, None)

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
        if self.u_is_axionite_foundry_target(
            conveyor_target_pos,
            resource,
        ):
            return (EntityType.CONVEYOR, conveyor_direction)
        if self.u_is_axionite_foundry_target(
            bridge_target,
            resource,
        ):
            return (EntityType.BRIDGE, bridge_target)
        if self.u_can_wrap_axionite_chain_around_core(
            pos,
            conveyor_target_pos,
            resource,
        ) or self.u_can_wrap_axionite_chain_around_core(
            pos,
            bridge_target,
            resource,
        ):
            foundry_pos = self.u_get_core_foundry_plan()
            if foundry_pos is not None:
                if bridge_target.distance_squared(
                    foundry_pos
                ) < conveyor_target_pos.distance_squared(foundry_pos):
                    return (EntityType.BRIDGE, bridge_target)
            return (EntityType.CONVEYOR, conveyor_direction)

        bridge_target_tile = self.map.u_get_pos_tile(bridge_target)
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
        foundry_pos = self.u_get_core_foundry_plan()
        if (
            resource == Environment.ORE_AXIONITE
            and foundry_pos is not None
            and pos == foundry_pos
        ):
            return (None, None)
        if self.u_is_supply_tile_forbidden(pos, resource):
            return (None, None)

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
        conveyor_target_pos = pos.add(conveyor_direction)
        if self.u_is_axionite_foundry_target(
            conveyor_target_pos,
            resource,
        ):
            return (EntityType.CONVEYOR, conveyor_direction)
        if self.u_is_axionite_foundry_target(
            bridge_target,
            resource,
        ):
            return (EntityType.BRIDGE, bridge_target)
        if self.u_can_wrap_axionite_chain_around_core(
            pos,
            conveyor_target_pos,
            resource,
        ) or self.u_can_wrap_axionite_chain_around_core(
            pos,
            bridge_target,
            resource,
        ):
            foundry_pos = self.u_get_core_foundry_plan()
            if foundry_pos is not None:
                if bridge_target.distance_squared(
                    foundry_pos
                ) < conveyor_target_pos.distance_squared(foundry_pos):
                    return (EntityType.BRIDGE, bridge_target)
            return (EntityType.CONVEYOR, conveyor_direction)

        bridge_target_tile = self.map.u_get_pos_tile(bridge_target)
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
        own_team = self.map.own_team

        adjacent_resource_tiles = []
        for adjacent_pos in self.map.u_iter_adjacent_cardinal_positions(pos):
            adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
            if adjacent_tile.environment == resource:
                adjacent_resource_tiles.append(adjacent_tile)

        if allow_adjacent_resource_sink and adjacent_resource_tiles:
            def has_adjacent_own_conveyor(tile) -> bool:
                for neighbor_pos in self.map.u_iter_adjacent_cardinal_positions(
                    tile.position
                ):
                    neighbor_tile = self.map.u_get_pos_tile(neighbor_pos)
                    if (
                        neighbor_tile.building.team == own_team
                        and neighbor_tile.building.entity_type == EntityType.CONVEYOR
                    ):
                        return True
                return False

            if all(
                has_adjacent_own_conveyor(resource_tile)
                for resource_tile in adjacent_resource_tiles
            ):
                adjacent_harvesters = [
                    resource_tile
                    for resource_tile in adjacent_resource_tiles
                    if (
                        resource_tile.building.team == own_team
                        and resource_tile.building.entity_type == EntityType.HARVESTER
                    )
                ]
                if adjacent_harvesters:
                    target_tile = min(
                        adjacent_harvesters,
                        key=lambda tile: (tile.position.x, tile.position.y),
                    )
                    return self.map.u_get_direction_between(pos, target_tile.position)

                if surround_target_pos is not None:
                    for resource_tile in adjacent_resource_tiles:
                        if resource_tile.position == surround_target_pos:
                            return self.map.u_get_direction_between(
                                pos,
                                surround_target_pos,
                            )

        current_pos = self.map.current_pos
        source_progress_key = self.u_get_supply_chain_progress_key(pos, resource)
        candidate_tiles: list[tuple[Direction, object, int]] = []

        for direction in Direction:
            if direction == Direction.CENTRE:
                continue
            dx, dy = direction.delta()
            if abs(dx) + abs(dy) != 1:
                continue

            neighbor_pos = pos.add(direction)
            if not self.map.u_is_in_bounds(neighbor_pos):
                continue

            neighbor_tile = self.map.u_get_pos_tile(neighbor_pos)
            if neighbor_tile.is_core_of(self.map.own_team):
                if self.u_supply_chain_targets_core(resource):
                    return direction
                continue
            if self.u_get_supply_chain_progress_key(
                neighbor_pos, resource
            ) >= source_progress_key and not self.u_can_wrap_axionite_chain_around_core(
                pos,
                neighbor_pos,
                resource,
            ):
                continue

            category_rank = self.u_get_supplier_tile_category_rank(
                neighbor_tile,
                resource,
            )
            if category_rank is None:
                continue

            candidate_tiles.append((direction, neighbor_tile, category_rank))

        if not candidate_tiles:
            return None

        best_category_rank = min(
            category_rank for _, _, category_rank in candidate_tiles
        )
        candidate_tiles = [
            (direction, neighbor_tile)
            for direction, neighbor_tile, category_rank in candidate_tiles
            if category_rank == best_category_rank
        ]
        candidate_tiles.sort(
            key=lambda item: (
                *self.u_get_supply_chain_progress_key(
                    item[1].position,
                    resource,
                ),
                (
                    0
                    if current_pos.distance_squared(item[1].position)
                    <= BUILDER_ACTION_RADIUS_SQ
                    else 1
                ),
                item[1].position.x,
                item[1].position.y,
            )
        )
        return candidate_tiles[0][0]

    def u_get_supplier_tile_category_rank(
        self,
        target_tile,
        resource: Environment = Environment.ORE_TITANIUM,
    ) -> int | None:
        own_team = self.map.own_team
        if target_tile.environment == Environment.WALL:
            return None
        if self.u_is_supply_tile_forbidden(target_tile.position, resource):
            return None
        if self.u_is_axionite_foundry_target(target_tile.position, resource):
            if self.u_can_host_foundry_site(target_tile.position):
                return -1
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
        current_pos = self.map.current_pos
        source_progress_key = self.u_get_supply_chain_progress_key(pos, resource)
        map_width = self.map.width
        map_height = self.map.height
        active_mask = self.map.active_mask_by_index
        tiles_by_index = self.map.tiles_by_index
        pos_x = pos.x
        pos_y = pos.y

        # Filter candidates, caching progress keys to avoid recomputing them later.
        candidates: list[tuple[object, tuple[int, int]]] = []
        for dx, dy in _BRIDGE_TARGET_OFFSETS:
            nx = pos_x + dx
            ny = pos_y + dy
            if nx < 0 or ny < 0 or nx >= map_width or ny >= map_height:
                continue
            target_idx = self.map.u_to_index_xy(nx, ny)
            if not active_mask[target_idx]:
                continue
            target_tile = tiles_by_index[target_idx]
            target_pos = target_tile.position
            if target_tile.is_core_of(
                self.map.own_team
            ) and not self.u_supply_chain_targets_core(resource):
                continue
            target_progress_key = self.u_get_supply_chain_progress_key(
                target_pos, resource
            )
            if (
                target_progress_key >= source_progress_key
                and not self.u_can_wrap_axionite_chain_around_core(
                    pos,
                    target_pos,
                    resource,
                )
            ):
                continue
            candidates.append((target_tile, target_progress_key))

        if not candidates:
            return None

        if self.u_supply_chain_targets_core(resource):
            core_tiles = [
                tile for tile, _ in candidates if tile.is_core_of(self.map.own_team)
            ]
            if core_tiles:
                return min(
                    core_tiles,
                    key=lambda tile: (
                        pos.distance_squared(tile.position),
                        tile.position.x,
                        tile.position.y,
                    ),
                ).position

        # Single pass: find best tile using composite key (rank, progress, distance, pos).
        # Avoids a separate categorize loop, a min-rank scan, a filter, and a second min.
        best_tile = None
        best_key: tuple | None = None
        for target_tile, target_progress_key in candidates:
            if self.round_stopwatch.check_overtime():
                break
            category_rank = self.u_get_bridge_target_category_rank(
                target_tile,
                resource,
            )
            if category_rank is None:
                continue
            dist_bucket = (
                0
                if current_pos.distance_squared(target_tile.position)
                <= BUILDER_ACTION_RADIUS_SQ
                else 1
            )
            key = (
                category_rank,
                *target_progress_key,
                dist_bucket,
                target_tile.position.x,
                target_tile.position.y,
            )
            if best_key is None or key < best_key:
                best_key = key
                best_tile = target_tile

        return best_tile.position if best_tile is not None else None

    def u_get_bridge_target_category_rank(
        self,
        target_tile,
        resource: Environment = Environment.ORE_TITANIUM,
    ) -> int | None:
        own_team = self.map.own_team
        if target_tile.environment == Environment.WALL:
            return None
        if self.u_is_supply_tile_forbidden(target_tile.position, resource):
            return None
        if AVOID_EMPTY_ORE_BRIDGE_TARGETS and self.u_is_empty_ore_tile(
            target_tile.position
        ):
            return None
        if self.u_is_axionite_foundry_target(target_tile.position, resource):
            if self.u_can_host_foundry_site(target_tile.position):
                return -1
        if (
            target_tile.building.entity_type in SUPPLY_LINK_TYPES
            and target_tile.building.team == own_team
        ):
            if target_tile.own_supply_chain_label == SupplyChainLabel.NONE:
                return None
            return 0
        if target_tile.building.id is None or (
            target_tile.building.team == own_team
            and target_tile.building.entity_type
            in {EntityType.BARRIER, EntityType.ROAD}
        ):
            return 1
        if (
            target_tile.building.entity_type == EntityType.ROAD
            and target_tile.building.team != own_team
        ):
            return 2
        return None

    def u_move_to(
        self,
        pos: Position,
        avoid_enemy_turrets: bool = True,
        build_new_roads: bool = True,
    ) -> bool:
        current_pos = self.map.current_pos
        if current_pos == pos:
            return False

        shortest_path = self.map.u_calculate_shortest_path(
            current_pos,
            pos,
            avoid_enemy_turrets=avoid_enemy_turrets,
        )
        if len(shortest_path) >= 2:
            next_tile = shortest_path[1]
            next_direction = self.map.u_get_direction_between(
                current_pos,
                next_tile.position,
            )
            if next_direction is not None and self.ct.can_move(next_direction):
                self.ct.move(next_direction)
                return True
            if build_new_roads and self.ct.can_build_road(next_tile.position):
                adjacent_resource_tiles = []
                for adjacent_pos in self.map.u_iter_adjacent_cardinal_positions(
                    next_tile.position
                ):
                    adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
                    if adjacent_tile.environment == Environment.ORE_TITANIUM:
                        adjacent_resource_tiles.append(adjacent_tile)

                if adjacent_resource_tiles:
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
                        if self.ct.can_build_conveyor(
                            next_tile.position,
                            facing_direction,
                        ):
                            self.ct.build_conveyor(
                                next_tile.position,
                                facing_direction,
                            )
                            if next_direction is not None and self.ct.can_move(
                                next_direction
                            ):
                                self.ct.move(next_direction)
                            return True
                    return False

                self.ct.build_road(next_tile.position)
                if next_direction is not None and self.ct.can_move(next_direction):
                    self.ct.move(next_direction)
                return True

        return False

    def u_move_to_astar(
        self,
        pos: Position,
        avoid_enemy_turrets: bool = True,
        build_new_roads: bool = True,
    ) -> bool:
        current_pos = self.map.current_pos
        if current_pos == pos:
            return False

        shortest_path = self.map.u_calculate_shortest_path_astar(
            current_pos,
            pos,
            avoid_enemy_turrets=avoid_enemy_turrets,
        )
        if len(shortest_path) >= 2:
            next_tile = shortest_path[1]
            next_direction = self.map.u_get_direction_between(
                current_pos,
                next_tile.position,
            )
            if next_direction is not None and self.ct.can_move(next_direction):
                self.ct.move(next_direction)
                return True
            if build_new_roads and self.ct.can_build_road(next_tile.position):
                adjacent_resource_tiles = []
                for adjacent_pos in self.map.u_iter_adjacent_cardinal_positions(
                    next_tile.position
                ):
                    adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
                    if adjacent_tile.environment == Environment.ORE_TITANIUM:
                        adjacent_resource_tiles.append(adjacent_tile)

                if adjacent_resource_tiles:
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
                        if self.ct.can_build_conveyor(
                            next_tile.position,
                            facing_direction,
                        ):
                            self.ct.build_conveyor(
                                next_tile.position,
                                facing_direction,
                            )
                            if next_direction is not None and self.ct.can_move(
                                next_direction
                            ):
                                self.ct.move(next_direction)
                            return True
                    return False

                self.ct.build_road(next_tile.position)
                if next_direction is not None and self.ct.can_move(next_direction):
                    self.ct.move(next_direction)
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
    ) -> bool:
        current_pos = self.map.current_pos
        target_tile = self.map.u_get_pos_tile(pos)
        self.last_built_entity_type = None
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
        can_build_on_own_tile = building_type in {
            EntityType.ARMOURED_CONVEYOR,
            EntityType.BRIDGE,
            EntityType.CONVEYOR,
            EntityType.ROAD,
        }

        if avoid_enemy_turrets and target_tile.is_enemy_turret_target_tile:
            return False

        titanium_cost, axionite_cost = getattr(
            self.ct, f"get_{building_type.value}_cost"
        )()

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
                and target_tile.building.entity_type == EntityType.CONVEYOR
                and target_tile.building.team == self.map.own_team
                and target_tile.conveyor_targets_harvester
            )
            or (
                target_tile.building.entity_type == EntityType.BARRIER
                and building_type != EntityType.BARRIER
            )
        )
        if (
            hold
            and can_hold_build_target
            and not affordable
            and current_pos.distance_squared(pos) <= BUILDER_ACTION_RADIUS_SQ
        ):
            return True

        if current_pos.distance_squared(pos) <= BUILDER_ACTION_RADIUS_SQ and (
            pos != current_pos or can_build_on_own_tile
        ):
            destroyed_replaceable_blocker = False
            should_try_attack_enemy_passable = (
                attack_enemy_passable
                and target_tile.is_passable
                and target_tile.building.team != self.map.own_team
            )
            if (
                target_tile.building.team == self.map.own_team
                and target_tile.building.entity_type
                in {EntityType.ROAD, EntityType.BARRIER}
                and target_tile.building.entity_type != building_type
                and self.ct.can_destroy(pos)
            ):
                self.ct.destroy(pos)
                destroyed_replaceable_blocker = True
            elif (
                building_type == EntityType.HARVESTER
                and target_tile.building.team == self.map.own_team
                and target_tile.building.entity_type == EntityType.CONVEYOR
                and target_tile.conveyor_targets_harvester
                and self.ct.can_destroy(pos)
            ):
                self.ct.destroy(pos)
                destroyed_replaceable_blocker = True

            if affordable:
                can_build_method = getattr(self.ct, f"can_build_{building_type.value}")
                build_method = getattr(self.ct, f"build_{building_type.value}")
                if building_type in DIRECTIONAL_BUILDING_TYPES:
                    if facing_direction is None:
                        return False
                    if not can_build_method(pos, facing_direction):
                        if should_try_attack_enemy_passable:
                            return self.u_attack_passable(
                                pos,
                                move_towards=move_towards,
                                destroy_condition=lambda _: True,
                                avoid_enemy_turrets=avoid_enemy_turrets,
                            )
                        return False
                    build_method(pos, facing_direction)
                    self.last_built_entity_type = building_type
                    if building_type == EntityType.CONVEYOR:
                        next_direction = self.map.u_get_direction_between(
                            current_pos,
                            pos,
                        )
                        if next_direction is not None and self.ct.can_move(
                            next_direction
                        ):
                            self.ct.move(next_direction)
                    return True

                if building_type == EntityType.BRIDGE:
                    if target_pos is None:
                        return False
                    if AVOID_EMPTY_ORE_BRIDGE_TARGETS and self.u_is_empty_ore_tile(
                        target_pos
                    ):
                        return False
                    if not can_build_method(pos, target_pos):
                        if should_try_attack_enemy_passable:
                            return self.u_attack_passable(
                                pos,
                                move_towards=move_towards,
                                destroy_condition=lambda _: True,
                                avoid_enemy_turrets=avoid_enemy_turrets,
                            )
                        return False
                    build_method(pos, target_pos)
                    self.last_built_entity_type = building_type
                    return True

                if building_type in NONDIRECTIONAL_BUILDING_TYPES:
                    if not can_build_method(pos):
                        if should_try_attack_enemy_passable:
                            return self.u_attack_passable(
                                pos,
                                move_towards=move_towards,
                                destroy_condition=lambda _: True,
                                avoid_enemy_turrets=avoid_enemy_turrets,
                            )
                        return False
                    build_method(pos)
                    self.last_built_entity_type = building_type
                    return True

                raise ValueError(f"Unsupported builder target type: {building_type}")

            if destroyed_replaceable_blocker:
                return True

        if (
            attack_enemy_passable
            and target_tile.is_passable
            and target_tile.building.team != self.map.own_team
        ):
            return self.u_attack_passable(
                pos,
                move_towards=move_towards,
                destroy_condition=lambda _: True,
                avoid_enemy_turrets=avoid_enemy_turrets,
            )

        if not move_towards:
            return False
        return self.u_move_to(
            pos,
            avoid_enemy_turrets=avoid_enemy_turrets,
        )

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
        return self.u_move_to(
            pos,
            avoid_enemy_turrets=avoid_enemy_turrets,
        )
