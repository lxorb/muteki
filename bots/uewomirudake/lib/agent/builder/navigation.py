from collections.abc import Callable

from cambc import Direction, EntityType, Environment, GameConstants, Position

from lib.agent.constants import (
    BRIDGE_PREFERRED_DIST,
    BUILDER_ACTION_RADIUS_SQ,
    CHOKEPOINT_MIN_DIST_INCREASE,
    ENEMY_TURRET_TYPES,
    ATTACK_TURRET_FEEDER_TYPES,
    OWN_SUPPLIER_TYPES,
    DIRECTIONAL_BUILDING_TYPES,
    NONDIRECTIONAL_BUILDING_TYPES,
)

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

    # TODO
    def u_is_chokepoint(
        self,
        pos: Position,
        min_dist_increase: int = CHOKEPOINT_MIN_DIST_INCREASE,
    ) -> bool:
        pass

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

    # TODO
    def u_best_conveyor_orientation(self, pos: Position):
        """
        Assuming that on the given position a conveyor should be build,
        return the best direction for the conveyor to point at or None, if it does not make
        sense to build a conveyor here.
        There are four possible tiles where the conveyor can point at. You should prioritze them as follows, ordered by precedence (descending, highest first):

        - if one of the neighbors is a core tile, early exist and return the corresponding orientation
        - filter out all neigbor tiles that would not decrease distance to the own core
        - then it should be prioritzed by tiles that already have a supply chain element (bridge /conveyor / splitter) on them
        -> if there are such tiles, just consider these
        -> if there are no such tiles, prioritize by tiles that are own barriers, then own roads, then empty tiles, then enemy roads (in this order)
        -> if there are none of these tiles, then return None
        - keep only the best of the beforementioned categories
        - if there are multiple tiles left, sort them by distance and pick the one with the lowest distance to the own core
        - if there are still multiple left, prioritize the ones that are in action radius of the current builder bot
        -

        This prioritizing should be written in a modular way so that is easily adjustable.

        """

    # TODO
    def u_best_bridge_target(self, pos: Position):
        """
        Assuming that on the given position a bridge should be build,
        return the best direction for the bridge to point at or None, if it does not make
        sense to build a bridge here.
        Consider all tiles that the bridge can point at (see the docs for information on which these are).

        - filter out all tiles that are orthogonally adjacent to the source pos
        - filter out all tiles that would not decrease distance to the own core
        - then if one of the remaining possible target tiles is a core tile, then simply return the core tile with the smallest distance to the current tile
        - if that was not the case it should be prioritzed by tiles that already have a supply chain element (bridge /conveyor / splitter) on them
        -> if there are such tiles, just consider these
        -> if there are no such tiles, prioritize by tiles that are of the own team and either barriers / roads or empty >> then enemy roads
        -> if there are none of these tiles, then return None
        - keep only the best of the beforementioned categories
        - if there are multiple tiles left, sort them by distance and pick the one with the lowest distance to the own core
        - if there are still multiple left, prioritize the ones that are in action radius of the current builder bot


        This prioritizing should be written in a modular way so that is easily adjustable.

        """

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
