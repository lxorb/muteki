from collections.abc import Callable

from cambc import Direction, EntityType, Environment, GameConstants, Position

from lib.agent.constants import (
    BRIDGE_PREFERRED_DIST,
    BUILDER_ACTION_RADIUS_SQ,
    ENEMY_TURRET_TYPES,
    ATTACK_TURRET_FEEDER_TYPES,
    OWN_SUPPLIER_TYPES,
    DIRECTIONAL_BUILDING_TYPES,
    NONDIRECTIONAL_BUILDING_TYPES,
)
from lib.map.constants import SUPPLY_LINK_TYPES
from lib.map.types import SupplyChainLabel


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

    def u_get_core_splitter_foundry_plan(
        self,
    ) -> tuple[Position, Direction, Position] | None:
        """
        TODO: AI code, NOT REVIEWED (needs review)
        """
        if (
            self.map.own_core_center_pos is None
            and not self.map.u_calc_core_center_positions()
        ):
            return None

        own_core_center_pos = self.map.own_core_center_pos
        if own_core_center_pos is None:
            return None

        own_team = self.map.own_team
        built_splitter_index = (
            self.map.built_splitter_index if self.map.has_built_splitter else -1
        )
        core_tiles = self.map.u_get_core_footprint_positions(own_core_center_pos)
        core_tile_indices = {tile.index for tile in core_tiles}
        candidate_plans: list[tuple[tuple[int, ...], Position, Direction, Position]] = []

        for core_tile in core_tiles:
            for splitter_pos in self.map.u_iter_adjacent_positions(
                core_tile.position,
                consider_diagonal=False,
            ):
                splitter_tile = self.map.u_get_pos_tile(splitter_pos)
                splitter_building = splitter_tile.building
                if (
                    splitter_tile.index in core_tile_indices
                    or splitter_building.team != own_team
                ):
                    continue

                splitter_direction = self.map.u_get_direction_between(
                    splitter_pos,
                    core_tile.position,
                )
                if splitter_direction is None:
                    continue

                if splitter_building.entity_type == EntityType.SPLITTER:
                    if splitter_building.direction != splitter_direction:
                        continue
                elif splitter_building.entity_type in SUPPLY_LINK_TYPES:
                    if not (
                        splitter_tile.own_supply_chain_label
                        & SupplyChainLabel.TITANIUM
                    ):
                        continue
                    if not any(
                        target.position == core_tile.position
                        for target in splitter_building.targets
                    ):
                        continue
                else:
                    continue

                dir_x, dir_y = splitter_direction.delta()
                back_pos = Position(
                    splitter_pos.x - dir_x,
                    splitter_pos.y - dir_y,
                )
                if not self.map.u_is_in_bounds(back_pos):
                    continue

                back_tile = self.map.u_get_pos_tile(back_pos)
                if not (
                    back_tile.building.team == own_team
                    and back_tile.building.entity_type in SUPPLY_LINK_TYPES
                    and back_tile.own_supply_chain_label & SupplyChainLabel.TITANIUM
                    and any(
                        target.position == splitter_pos
                        for target in back_tile.building.targets
                    )
                ):
                    continue

                side_directions = (
                    splitter_direction.rotate_left().rotate_left(),
                    splitter_direction.rotate_right().rotate_right(),
                )
                for foundry_direction, spill_direction in (
                    (side_directions[0], side_directions[1]),
                    (side_directions[1], side_directions[0]),
                ):
                    foundry_pos = splitter_pos.add(foundry_direction)
                    if not self.map.u_is_in_bounds(foundry_pos):
                        continue

                    foundry_tile = self.map.u_get_pos_tile(foundry_pos)
                    if (
                        foundry_tile.index in core_tile_indices
                        or not any(
                            (
                                (
                                    neighbor_tile := self.map.u_get_pos_tile(
                                        neighbor_pos
                                    )
                                ).building.entity_type
                                == EntityType.CORE
                                and neighbor_tile.building.team == own_team
                            )
                            for neighbor_pos in self.map.u_iter_adjacent_positions(
                                foundry_pos,
                                consider_diagonal=False,
                            )
                        )
                    ):
                        continue
                    if not self.u_can_host_foundry_site(foundry_pos):
                        continue
                    if (
                        foundry_tile.building.entity_type != EntityType.FOUNDRY
                        and foundry_tile.own_supply_chain_label
                        & SupplyChainLabel.TITANIUM
                    ):
                        continue
                    if (
                        foundry_tile.building.entity_type != EntityType.FOUNDRY
                        and self.map.u_is_chokepoint(foundry_pos)
                    ):
                        continue

                    spill_pos = splitter_pos.add(spill_direction)
                    if not self.map.u_is_in_bounds(spill_pos):
                        continue
                    if not self.u_is_harmless_core_splitter_side_tile(spill_pos):
                        continue

                    splitter_rank = 0
                    if splitter_tile.index != built_splitter_index:
                        splitter_rank = (
                            1
                            if splitter_building.entity_type == EntityType.SPLITTER
                            else 2
                        )
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
                        if foundry_tile.own_supply_chain_label
                        & SupplyChainLabel.AXIONITE
                        else 1
                    )
                    candidate_plans.append(
                        (
                            (
                                splitter_rank,
                                foundry_rank,
                                label_rank,
                                foundry_tile.position.x,
                                foundry_tile.position.y,
                                splitter_tile.position.x,
                                splitter_tile.position.y,
                            ),
                            splitter_pos,
                            splitter_direction,
                            foundry_pos,
                        )
                    )

        if not candidate_plans:
            return None

        candidate_plans.sort(key=lambda item: item[0])
        _, splitter_pos, splitter_direction, foundry_pos = candidate_plans[0]
        return (splitter_pos, splitter_direction, foundry_pos)

    def u_get_supply_chain_progress_key(
        self,
        pos: Position,
        resource: Environment,
    ) -> tuple[int, int]:
        """
        TODO: AI code, NOT REVIEWED (needs review)
        """
        target_tile = self.map.u_get_pos_tile(pos)
        if resource == Environment.ORE_AXIONITE:
            core_plan = self.u_get_core_splitter_foundry_plan()
            if core_plan is not None:
                foundry_pos = core_plan[2]
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
                avoidance_ore is not None
                and self.map.u_is_adjacent_to_ore(pos, avoidance_ore)
            )
        )

    def u_get_sentinel_orientation(self, pos: Position) -> Direction:
        """
        Choose the sentinel facing that best covers high-value targets.

        If exactly one own supplier or harvester currently feeds this tile, do
        not face back toward that feeder. Among the remaining directions,
        prefer facings that can cover the enemy core, then more enemy turrets,
        then more own conveyors or bridges, then more enemy buildings.
        """
        feeder_directions: list[Direction] = []
        enemy_turret_tiles = []
        own_supplier_tiles = []
        enemy_building_tiles = []

        enemy_core_tiles = []
        if self.map.enemy_core_center_pos is not None:
            enemy_core_tiles = self.map.u_get_core_footprint_positions(
                self.map.enemy_core_center_pos
            )

        for building_tile in self.map.own_buildings_in_vision:
            building_type = building_tile.building.entity_type

            if building_type in ATTACK_TURRET_FEEDER_TYPES and any(
                target_tile.position == pos
                for target_tile in building_tile.building.targets
            ):
                feeder_direction = self.map.u_get_direction_between(
                    building_tile.position,
                    pos,
                )
                if feeder_direction is not None:
                    feeder_directions.append(feeder_direction)
            if building_type in OWN_SUPPLIER_TYPES:
                own_supplier_tiles.append(building_tile)

        for building_tile in self.map.enemy_buildings_in_vision:
            building_type = building_tile.building.entity_type
            enemy_building_tiles.append(building_tile)
            if building_type in ENEMY_TURRET_TYPES:
                enemy_turret_tiles.append(building_tile)

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
        direction_scores = [
            self.u_get_sentinel_direction_score(
                pos,
                direction,
                enemy_core_tiles,
                enemy_turret_tiles,
                own_supplier_tiles,
                enemy_building_tiles,
                direction_order,
            )
            for direction in candidate_directions
        ]

        direction_scores.sort(key=lambda item: item[0])
        return direction_scores[0][1]

    def u_get_sentinel_direction_score(
        self,
        pos: Position,
        direction: Direction,
        enemy_core_tiles,
        enemy_turret_tiles,
        own_supplier_tiles,
        enemy_building_tiles,
        direction_order: dict[Direction, int],
    ) -> tuple[tuple[int, ...], Direction]:
        can_target_enemy_core = any(
            self.map.u_sentinel_covers_target(
                pos,
                direction,
                target_tile.position,
                GameConstants.SENTINEL_VISION_RADIUS_SQ,
            )
            for target_tile in enemy_core_tiles
        )
        enemy_turret_count = sum(
            1
            for target_tile in enemy_turret_tiles
            if self.map.u_sentinel_covers_target(
                pos,
                direction,
                target_tile.position,
                GameConstants.SENTINEL_VISION_RADIUS_SQ,
            )
        )
        own_supplier_count = sum(
            1
            for target_tile in own_supplier_tiles
            if self.map.u_sentinel_covers_target(
                pos,
                direction,
                target_tile.position,
                GameConstants.SENTINEL_VISION_RADIUS_SQ,
            )
        )
        enemy_building_count = sum(
            1
            for target_tile in enemy_building_tiles
            if self.map.u_sentinel_covers_target(
                pos,
                direction,
                target_tile.position,
                GameConstants.SENTINEL_VISION_RADIUS_SQ,
            )
        )
        return (
            (
                0 if can_target_enemy_core else 1,
                -enemy_turret_count,
                -own_supplier_count,
                -enemy_building_count,
                direction_order[direction],
            ),
            direction,
        )

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

        direction_scores.sort(key=lambda item: item[0])
        return direction_scores[0][1]

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
        core_plan = self.u_get_core_splitter_foundry_plan()
        if (
            resource == Environment.ORE_AXIONITE
            and core_plan is not None
            and pos == core_plan[2]
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
    ) -> Direction | None:
        """
        Return the best cardinal output direction for a conveyor at this tile.
        """
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
            if (
                neighbor_tile.building.entity_type == EntityType.CORE
                and neighbor_tile.building.team == self.map.own_team
            ):
                if self.u_supply_chain_targets_core(resource):
                    return direction
                continue
            if (
                self.u_get_supply_chain_progress_key(neighbor_pos, resource)
                >= source_progress_key
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
        if self.u_is_supply_tile_forbidden(target_tile.position, resource):
            return None
        if (
            target_tile.building.entity_type in SUPPLY_LINK_TYPES
            and target_tile.building.team == own_team
        ):
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
        candidate_tiles = []

        for column in self.map.matrix:
            for target_tile in column:
                target_pos = target_tile.position
                if target_pos == pos:
                    continue
                if (
                    pos.distance_squared(target_pos)
                    > GameConstants.BRIDGE_TARGET_RADIUS_SQ
                ):
                    continue
                if abs(target_pos.x - pos.x) + abs(target_pos.y - pos.y) == 1:
                    continue
                if (
                    target_tile.building.entity_type == EntityType.CORE
                    and target_tile.building.team == self.map.own_team
                    and not self.u_supply_chain_targets_core(resource)
                ):
                    continue
                if (
                    self.u_get_supply_chain_progress_key(target_pos, resource)
                    >= source_progress_key
                ):
                    continue
                candidate_tiles.append(target_tile)

        if not candidate_tiles:
            return None

        if self.u_supply_chain_targets_core(resource):
            core_tiles = [
                tile
                for tile in candidate_tiles
                if (
                    tile.building.entity_type == EntityType.CORE
                    and tile.building.team == self.map.own_team
                )
            ]
            if core_tiles:
                core_tiles.sort(
                    key=lambda tile: (
                        pos.distance_squared(tile.position),
                        tile.position.x,
                        tile.position.y,
                    )
                )
                return core_tiles[0].position

        categorized_tiles: list[tuple[int, object]] = []
        for target_tile in candidate_tiles:
            category_rank = self.u_get_bridge_target_category_rank(
                target_tile,
                resource,
            )
            if category_rank is None:
                continue
            categorized_tiles.append((category_rank, target_tile))

        if not categorized_tiles:
            return None

        best_category_rank = min(
            category_rank for category_rank, _ in categorized_tiles
        )
        candidate_tiles = [
            target_tile
            for category_rank, target_tile in categorized_tiles
            if category_rank == best_category_rank
        ]
        candidate_tiles.sort(
            key=lambda tile: (
                *self.u_get_supply_chain_progress_key(
                    tile.position,
                    resource,
                ),
                (
                    0
                    if current_pos.distance_squared(tile.position)
                    <= BUILDER_ACTION_RADIUS_SQ
                    else 1
                ),
                tile.position.x,
                tile.position.y,
            )
        )
        return candidate_tiles[0].position

    def u_get_bridge_target_category_rank(
        self,
        target_tile,
        resource: Environment = Environment.ORE_TITANIUM,
    ) -> int | None:
        own_team = self.map.own_team
        if self.u_is_supply_tile_forbidden(target_tile.position, resource):
            return None
        if self.u_is_empty_ore_tile(target_tile.position):
            return None
        if (
            target_tile.building.entity_type in SUPPLY_LINK_TYPES
            and target_tile.building.team == own_team
        ):
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
                target_tile.building.entity_type == EntityType.BARRIER
                and building_type != EntityType.BARRIER
            )
        )
        if hold and can_hold_build_target and not affordable:
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
                    return True

                if building_type == EntityType.BRIDGE:
                    if target_pos is None:
                        return False
                    if self.u_is_empty_ore_tile(target_pos):
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
