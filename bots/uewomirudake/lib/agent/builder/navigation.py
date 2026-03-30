from collections.abc import Callable

from cambc import Direction, EntityType, Environment, GameConstants, Position

from lib.agent.constants import (
    BRIDGE_PREFERRED_DIST,
    BUILDER_ACTION_RADIUS_SQ,
    CHOKEPOINT_MIN_DIST_INCREASE,
)

from .types import BuilderNavigationSelf


class BuilderNavigationMixin(BuilderNavigationSelf):
    def u_get_sentinel_orientation(self, pos: Position) -> Direction:
        """
        Assuming a sentinel should be placed on a specific tile, determine it's orientation.
        Most importantly, a sentinel should always be feeded with resources. (it can't be feeded from the direction it is pointing at).
        Then, it should point at the enemy core if possible.
        Then, it should point at enemy turrets if possible.
        Then, it should point at enemy bridges / conveyors.
        Make a priority ordering using this as the base idea.
        """

    def u_get_gunner_orientation(self):
        """
        Infer a similar priority ordering for the gunner based on the sentinel priority list.
        """

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
        conveyor_direction = self.map.u_best_conveyor_orientation(pos)
        bridge_target = self.map.u_best_bridge_target(pos)

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

    def u_is_enemy_turret_target_tile(self, pos: Position) -> bool:
        target_tile = self.map.u_get_pos_tile(pos)
        return (
            target_tile.in_enemy_attack_range
            or target_tile.in_enemy_launcher_pickup_zone
        )

    def u_move_to(
        self,
        pos: Position,
        avoid_enemy_turrets: bool = True,
    ) -> bool:
        current_pos = self.map.current_pos
        candidate_moves: list[tuple[int, int, Direction]] = []
        current_distance_sq = current_pos.distance_squared(pos)
        for direction in Direction:
            if direction == Direction.CENTRE:
                continue
            if not self.ct.can_move(direction):
                continue
            next_pos = current_pos.add(direction)
            if (
                avoid_enemy_turrets
                and self.u_is_enemy_turret_target_tile(next_pos)
            ):
                continue
            next_distance_sq = next_pos.distance_squared(pos)
            if next_distance_sq >= current_distance_sq:
                continue
            candidate_moves.append(
                (next_distance_sq, 0 if next_pos == pos else 1, direction)
            )

        if not candidate_moves:
            return False

        candidate_moves.sort(key=lambda move: move[:2])
        self.ct.move(candidate_moves[0][2])
        return True

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
                target_tile.building.hp
                <= GameConstants.BUILDER_BOT_ATTACK_DAMAGE
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

        if (
            avoid_enemy_turrets
            and self.u_is_enemy_turret_target_tile(pos)
        ):
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

        directional_buildings = {
            EntityType.CONVEYOR,
            EntityType.SPLITTER,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.GUNNER,
            EntityType.SENTINEL,
            EntityType.BREACH,
        }
        nondirectional_buildings = {
            EntityType.HARVESTER,
            EntityType.ROAD,
            EntityType.BARRIER,
            EntityType.FOUNDRY,
            EntityType.LAUNCHER,
        }

        if (
            current_pos.distance_squared(pos) <= BUILDER_ACTION_RADIUS_SQ
            and pos != current_pos
        ):
            if (
                target_tile.building.team == self.map.own_team
                and target_tile.building.entity_type in {EntityType.ROAD, EntityType.BARRIER}
                and target_tile.building.entity_type != building_type
                and self.ct.can_destroy(pos)
            ):
                self.ct.destroy(pos)
                return True

            if affordable:
                can_build_method = getattr(self.ct, f"can_build_{building_type.value}")
                build_method = getattr(self.ct, f"build_{building_type.value}")
                if building_type in directional_buildings:
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

                if building_type in nondirectional_buildings:
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
