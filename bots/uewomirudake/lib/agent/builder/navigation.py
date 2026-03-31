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

from .types import BuilderNavigationSelf


class BuilderNavigationMixin(BuilderNavigationSelf):
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

            if (
                building_type in ATTACK_TURRET_FEEDER_TYPES
                and any(target_tile.position == pos for target_tile in building_tile.building.targets)
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
                and any(target_tile.position == pos for target_tile in building_tile.building.targets)
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
                if any(core_tile.position == target_tile.position for core_tile in enemy_core_tiles):
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
    ) -> tuple[EntityType | None, Direction | Position | None]:
        """
        Return the supplier type to build at one tile plus its chosen target.

        Delegates candidate selection to the conveyor- and bridge-planning map
        helpers. If both plans exist, prefer the bridge only when it skips at
        least `BRIDGE_PREFERRED_DIST` cached core-distance steps.
        """
        conveyor_direction = self.u_best_conveyor_orientation(pos)
        bridge_target = self.u_best_bridge_target(pos)

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

    def u_best_conveyor_orientation(self, pos: Position) -> Direction | None:
        """
        Return the best cardinal output direction for a conveyor at this tile.
        """
        current_pos = self.map.current_pos
        source_tile = self.map.u_get_pos_tile(pos)
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
                return direction
            if neighbor_tile.own_core_dist >= source_tile.own_core_dist:
                continue

            category_rank = self.u_get_supplier_tile_category_rank(neighbor_tile)
            if category_rank is None:
                continue

            candidate_tiles.append((direction, neighbor_tile, category_rank))

        if not candidate_tiles:
            return None

        best_category_rank = min(category_rank for _, _, category_rank in candidate_tiles)
        candidate_tiles = [
            (direction, neighbor_tile)
            for direction, neighbor_tile, category_rank in candidate_tiles
            if category_rank == best_category_rank
        ]
        candidate_tiles.sort(
            key=lambda item: (
                item[1].own_core_dist,
                0
                if current_pos.distance_squared(item[1].position)
                <= BUILDER_ACTION_RADIUS_SQ
                else 1,
                item[1].position.x,
                item[1].position.y,
            )
        )
        return candidate_tiles[0][0]

    def u_get_supplier_tile_category_rank(self, target_tile) -> int | None:
        own_team = self.map.own_team
        if target_tile.building.entity_type in SUPPLY_LINK_TYPES:
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

    def u_best_bridge_target(self, pos: Position) -> Position | None:
        """
        Return the best bridge target tile reachable from this source tile.
        """
        current_pos = self.map.current_pos
        source_tile = self.map.u_get_pos_tile(pos)
        candidate_tiles = []

        for column in self.map.matrix:
            for target_tile in column:
                target_pos = target_tile.position
                if target_pos == pos:
                    continue
                if pos.distance_squared(target_pos) > GameConstants.BRIDGE_TARGET_RADIUS_SQ:
                    continue
                if (
                    abs(target_pos.x - pos.x) + abs(target_pos.y - pos.y) == 1
                ):
                    continue
                if target_tile.own_core_dist >= source_tile.own_core_dist:
                    continue
                candidate_tiles.append(target_tile)

        if not candidate_tiles:
            return None

        core_tiles = [
            tile
            for tile in candidate_tiles
            if tile.building.entity_type == EntityType.CORE
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
            category_rank = self.u_get_bridge_target_category_rank(target_tile)
            if category_rank is None:
                continue
            categorized_tiles.append((category_rank, target_tile))

        if not categorized_tiles:
            return None

        best_category_rank = min(category_rank for category_rank, _ in categorized_tiles)
        candidate_tiles = [
            target_tile
            for category_rank, target_tile in categorized_tiles
            if category_rank == best_category_rank
        ]
        candidate_tiles.sort(
            key=lambda tile: (
                tile.own_core_dist,
                0
                if current_pos.distance_squared(tile.position)
                <= BUILDER_ACTION_RADIUS_SQ
                else 1,
                tile.position.x,
                tile.position.y,
            )
        )
        return candidate_tiles[0].position

    def u_get_bridge_target_category_rank(self, target_tile) -> int | None:
        own_team = self.map.own_team
        if target_tile.building.entity_type in SUPPLY_LINK_TYPES:
            return 0
        if target_tile.building.id is None or (
            target_tile.building.team == own_team
            and target_tile.building.entity_type in {EntityType.BARRIER, EntityType.ROAD}
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
        build_new_roads: bool = False,
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

        if (
            current_pos.distance_squared(pos) <= BUILDER_ACTION_RADIUS_SQ
            and pos != current_pos
        ):
            if (
                target_tile.building.team == self.map.own_team
                and target_tile.building.entity_type
                in {EntityType.ROAD, EntityType.BARRIER}
                and target_tile.building.entity_type != building_type
                and self.ct.can_destroy(pos)
            ):
                self.ct.destroy(pos)
                return True

            if affordable:
                can_build_method = getattr(self.ct, f"can_build_{building_type.value}")
                build_method = getattr(self.ct, f"build_{building_type.value}")
                if building_type in DIRECTIONAL_BUILDING_TYPES:
                    if facing_direction is None:
                        return False
                    if not can_build_method(pos, facing_direction):
                        return False
                    build_method(pos, facing_direction)
                    return True

                if building_type == EntityType.BRIDGE:
                    if target_pos is None:
                        return False
                    if not can_build_method(pos, target_pos):
                        return False
                    build_method(pos, target_pos)
                    return True

                if building_type in NONDIRECTIONAL_BUILDING_TYPES:
                    if not can_build_method(pos):
                        return False
                    build_method(pos)
                    return True

                raise ValueError(f"Unsupported builder target type: {building_type}")

        if (
            attack_enemy_passable
            and target_tile.is_passable
            and target_tile.building.team != self.map.own_team
        ):
            return self.u_attack_passable(
                pos,
                move_towards=False,
                destroy_condition=lambda _: True,
                avoid_enemy_turrets=avoid_enemy_turrets,
            )

        if not move_towards:
            return False
        return self.u_move_to(
            pos,
            avoid_enemy_turrets=avoid_enemy_turrets,
        )
