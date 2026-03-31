from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cambc import Direction, EntityType, Environment, Position, Team
from lib.map.constants import (
    INF_DIST,
    PASSABLE_TYPES,
    RESOURCE_TARGET_TYPES,
    SUPPLY_LINK_TYPES,
    WEAPON_TARGET_TYPES,
)

if TYPE_CHECKING:
    from lib.map import Map


DIRECTIONAL_ENTITY_TYPES = {
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
}
VISION_RADIUS_ENTITY_TYPES = {
    EntityType.GUNNER,
    EntityType.SENTINEL,
}
STORED_RESOURCE_TRACKED_ENTITY_TYPES = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
}


@dataclass
class TileBot:
    id: int | None
    entity_type: EntityType | None
    team: Team | None
    targets: list["Tile"]
    hp: int | None


@dataclass
class TileBuilding:
    id: int | None
    entity_type: EntityType | None
    prev_entity_type: EntityType | None
    team: Team | None
    targets: list["Tile"]
    prev_targets: list["Tile"]
    hp: int | None
    direction: Direction | None
    vision_radius_sq: int | None
    last_resource_onit_turn: int | None


class Tile:
    def __init__(self, position: Position, map: "Map") -> None:
        self.map: Map = map
        self.position: Position = position
        self.index: int = position.x * map.height + position.y

        self.environment: Environment | None = None
        self.is_passable: bool = False
        self.building: TileBuilding = TileBuilding(
            None,
            None,
            None,
            None,
            [],
            [],
            None,
            None,
            None,
            None,
        )
        self.bot: TileBot = TileBot(None, None, None, [], None)

        self.in_enemy_launcher_pickup_zone: int = 0
        self.in_enemy_attack_range: int = 0
        self.in_enemy_bot_action_range_turn: int = -1
        self.in_enemy_resource_range: int = 0

        self.in_own_launcher_pickup_zone: int = 0
        self.in_own_attack_range: int = 0
        self.in_own_bot_action_range_turn: int = -1
        self.in_own_resource_range: int = 0

        self.last_seen_turn: int = -1
        self.last_titanium_onit_turn: int = -1

    @property
    def own_core_dist(self) -> int:
        return self.map.own_core_dist_by_index[self.index]

    @own_core_dist.setter
    def own_core_dist(self, value: int) -> None:
        self.map.own_core_dist_by_index[self.index] = value

    @property
    def enemy_core_dist(self) -> int:
        return self.map.enemy_core_dist_by_index[self.index]

    @enemy_core_dist.setter
    def enemy_core_dist(self, value: int) -> None:
        self.map.enemy_core_dist_by_index[self.index] = value

    @property
    def dist_to_self(self) -> int:
        if self.map.dist_to_self_epoch_by_index[self.index] != self.map.dist_to_self_epoch:
            return INF_DIST
        return self.map.dist_to_self_by_index[self.index]

    @dist_to_self.setter
    def dist_to_self(self, value: int) -> None:
        self.map.dist_to_self_by_index[self.index] = value
        self.map.dist_to_self_epoch_by_index[self.index] = self.map.dist_to_self_epoch

    @property
    def is_enemy_turret_target_tile(self) -> int:
        return self.in_enemy_attack_range or self.in_enemy_launcher_pickup_zone

    def u_get_resource_targets(self) -> list["Tile"]:
        if self.building.entity_type in RESOURCE_TARGET_TYPES:
            return list(self.building.targets)
        return []

    def u_calc_intrinsic_passability(self) -> bool:
        building_type = self.building.entity_type
        if building_type is None:
            return self.environment != Environment.WALL
        if building_type == EntityType.CORE:
            return self.building.team == self.map.own_team
        return building_type in PASSABLE_TYPES

    def _is_intrinsically_passable(self) -> bool:
        return self.map.intrinsic_passable_by_index[self.index]

    def u_refresh_intrinsic_passability(self) -> None:
        intrinsic_passable = self.u_calc_intrinsic_passability()
        if intrinsic_passable == self.map.intrinsic_passable_by_index[self.index]:
            return
        self.map.intrinsic_passable_by_index[self.index] = intrinsic_passable
        # Any traversability change invalidates cached chokepoint answers.
        self.map.passability_epoch += 1
        self.map.core_distance_dirty_indices.add(self.index)

    def clear_bot(self) -> None:
        self.bot = TileBot(None, None, None, [], None)
        self.map.bot_present_by_index[self.index] = 0

    def clear_building(self) -> None:
        if self.building.entity_type is not None:
            self.update_target_zones_building_by(
                self.building.targets,
                self.building.entity_type,
                self.building.team,
                -1,
            )
        self.building = TileBuilding(
            None,
            None,
            None,
            None,
            [],
            [],
            None,
            None,
            None,
            self.building.last_resource_onit_turn,
        )
        self.u_refresh_intrinsic_passability()

    def update_attributes(self) -> None:
        ct = self.map.ct
        current_round = self.map.current_round
        if self.last_seen_turn == -1:
            self.map.newly_seen_tiles_in_vision.append(self)
        if self.environment is None:
            self.environment = ct.get_tile_env(self.position)
        if self.last_seen_turn == -1:
            # Frontier expansion cache: remember tiles first seen this turn.
            self.map.frontier_expand_newly_seen_indices.append(self.index)
        self.last_seen_turn = current_round

        if self.environment == Environment.ORE_TITANIUM:
            self.last_titanium_onit_turn = current_round

        bot_id = ct.get_tile_builder_bot_id(self.position)
        building_id = ct.get_tile_building_id(self.position)

        if bot_id != self.bot.id:
            if bot_id is None:
                self.clear_bot()
            else:
                self.bot.id = bot_id
                self.update_bot(id_changed=True)
        else:
            if bot_id is not None:
                self.update_bot(id_changed=False)
        self.map.bot_present_by_index[self.index] = 0 if bot_id is None else 1

        if building_id != self.building.id:
            if building_id is None:
                self.clear_building()
            else:
                if self.building.id is not None:
                    self.clear_building()
                self.building.id = building_id
                self.update_building(id_changed=True)
        else:
            if building_id is not None:
                self.update_building(id_changed=False)

        self.u_refresh_intrinsic_passability()
        self.is_passable = self._is_intrinsically_passable() and (
            self.bot.id is None or self.position == self.map.current_pos
        )

    def update_bot(self, id_changed: bool) -> None:
        ct = self.map.ct
        if id_changed:
            self.bot.entity_type = ct.get_entity_type(self.bot.id)
            self.bot.team = ct.get_team(self.bot.id)
            self.bot.targets = self.get_targets(self.bot.entity_type, self.bot.id)
        self.bot.hp = ct.get_hp(self.bot.id)
        self.update_target_zones_bot()

    def update_building(self, id_changed: bool) -> None:
        ct = self.map.ct
        if id_changed:
            prev_entity_type = self.building.entity_type
            prev_targets = self.building.targets.copy()
            prev_team = self.building.team
            self.building.prev_entity_type = self.building.entity_type
            self.building.prev_targets = self.building.targets.copy()
            self.building.entity_type = ct.get_entity_type(self.building.id)
            self.building.team = ct.get_team(self.building.id)

            if self.building.entity_type in DIRECTIONAL_ENTITY_TYPES:
                self.building.direction = ct.get_direction(self.building.id)
            else:
                self.building.direction = None

            if self.building.entity_type in VISION_RADIUS_ENTITY_TYPES:
                self.building.vision_radius_sq = ct.get_vision_radius_sq(
                    self.building.id
                )
            else:
                self.building.vision_radius_sq = None

            self.building.targets = self.get_targets(
                self.building.entity_type,
                self.building.id,
                direction=self.building.direction,
            )
            self.update_target_zones_building(
                prev_entity_type,
                prev_targets,
                prev_team,
            )
        else:
            if self.building.entity_type == EntityType.GUNNER:
                new_direction = ct.get_direction(self.building.id)
                if new_direction != self.building.direction:
                    prev_entity_type = self.building.entity_type
                    prev_targets = self.building.targets.copy()
                    prev_team = self.building.team
                    self.building.prev_entity_type = self.building.entity_type
                    self.building.prev_targets = self.building.targets.copy()
                    self.building.direction = new_direction
                    self.building.targets = self.get_targets(
                        self.building.entity_type,
                        self.building.id,
                        direction=self.building.direction,
                    )
                    self.update_target_zones_building(
                        prev_entity_type,
                        prev_targets,
                        prev_team,
                    )

        if id_changed or self.building.team != self.map.own_team:
            self.building.hp = ct.get_hp(self.building.id)
        if self.building.entity_type in STORED_RESOURCE_TRACKED_ENTITY_TYPES:
            stored_resource = ct.get_stored_resource(self.building.id)
            if stored_resource is not None:
                self.building.last_resource_onit_turn = self.map.current_round

    def get_targets(
        self,
        entity_type: EntityType,
        entity_id: int,
        direction: Direction | None = None,
    ) -> list["Tile"]:
        ct = self.map.ct
        tiles_by_index = self.map.tiles_by_index
        if direction is None and entity_type in DIRECTIONAL_ENTITY_TYPES:
            direction = ct.get_direction(entity_id)

        match entity_type:
            case EntityType.BUILDER_BOT:
                return [
                    tiles_by_index[idx]
                    for idx in self.map.builder_action_target_indices_by_index[
                        self.index
                    ]
                ]
            case EntityType.CORE:
                return [
                    tiles_by_index[idx]
                    for idx in self.map.core_footprint_target_indices_by_index[
                        self.index
                    ]
                ]
            case EntityType.HARVESTER | EntityType.FOUNDRY:
                return [
                    tiles_by_index[idx]
                    for idx in self.map.cardinal_neighbor_indices_by_index[self.index]
                ]
            case EntityType.CONVEYOR | EntityType.ARMOURED_CONVEYOR:
                if direction is None:
                    return []
                target_idx = self.map.neighbor_index_by_direction_by_index[
                    self.index
                ].get(direction)
                return [] if target_idx is None else [tiles_by_index[target_idx]]
            case EntityType.SPLITTER:
                if direction is None:
                    return []
                neighbor_idx_by_direction = self.map.neighbor_index_by_direction_by_index[
                    self.index
                ]
                return [
                    tiles_by_index[target_idx]
                    for output_direction in (
                        direction,
                        direction.rotate_left().rotate_left(),
                        direction.rotate_right().rotate_right(),
                    )
                    if (
                        target_idx := neighbor_idx_by_direction.get(output_direction)
                    )
                    is not None
                ]
            case EntityType.BRIDGE:
                target_pos = ct.get_bridge_target(entity_id)
                if not self.map.u_is_in_bounds(target_pos):
                    return []
                return [self.map.u_get_pos_tile(target_pos)]
            case EntityType.GUNNER:
                if direction is None:
                    return []
                return [
                    tiles_by_index[idx]
                    for idx in self.map.u_get_attackable_target_indices(
                        self.index,
                        EntityType.GUNNER,
                        direction,
                    )
                ]
            case EntityType.SENTINEL:
                if direction is None:
                    return []
                return [
                    tiles_by_index[idx]
                    for idx in self.map.u_get_attackable_target_indices(
                        self.index,
                        EntityType.SENTINEL,
                        direction,
                    )
                ]
            case EntityType.BREACH:
                if direction is None:
                    return []
                return [
                    tiles_by_index[idx]
                    for idx in self.map.u_get_attackable_target_indices(
                        self.index,
                        EntityType.BREACH,
                        direction,
                    )
                ]
            case EntityType.LAUNCHER:
                return [
                    tiles_by_index[idx]
                    for idx in self.map.u_get_attackable_target_indices(
                        self.index,
                        EntityType.LAUNCHER,
                        Direction.NORTH,
                    )
                ]
            case _:
                return []

    def update_target_zones_bot(self):
        current_round = self.map.current_round
        for target in self.bot.targets:
            if self.bot.team == self.map.own_team:
                target.in_own_bot_action_range_turn = current_round
            else:
                target.in_enemy_bot_action_range_turn = current_round

    def update_target_zones_building_by(
        self,
        targets: list["Tile"],
        entity_type: EntityType | None,
        team: Team | None,
        delta: int,
    ) -> None:
        if entity_type is None or team is None:
            return

        match entity_type:
            case _ if entity_type in RESOURCE_TARGET_TYPES:
                for target in targets:
                    if team == self.map.own_team:
                        target.in_own_resource_range += delta
                    else:
                        target.in_enemy_resource_range += delta
            case _ if entity_type in WEAPON_TARGET_TYPES - {EntityType.LAUNCHER}:
                for target in targets:
                    if team == self.map.own_team:
                        target.in_own_attack_range += delta
                    else:
                        target.in_enemy_attack_range += delta
                        target.map.enemy_turret_target_by_index[target.index] = int(
                            target.in_enemy_attack_range > 0
                            or target.in_enemy_launcher_pickup_zone > 0
                        )
            case EntityType.LAUNCHER:
                for target in self.map.u_get_launcher_pickup_positions(self.position):
                    if team == self.map.own_team:
                        target.in_own_launcher_pickup_zone += delta
                    else:
                        target.in_enemy_launcher_pickup_zone += delta
                        target.map.enemy_turret_target_by_index[target.index] = int(
                            target.in_enemy_attack_range > 0
                            or target.in_enemy_launcher_pickup_zone > 0
                        )

    def update_target_zones_building(
        self,
        prev_entity_type: EntityType | None,
        prev_targets: list["Tile"],
        prev_team: Team | None,
    ) -> None:
        if (
            self.building.entity_type == prev_entity_type
            and Counter(prev_targets) == Counter(self.building.targets)
            and self.building.team == prev_team
        ):
            return
        self.update_target_zones_building_by(
            prev_targets,
            prev_entity_type,
            prev_team,
            -1,
        )
        self.update_target_zones_building_by(
            self.building.targets,
            self.building.entity_type,
            self.building.team,
            1,
        )

    def update_supply_targets_in_vision(self) -> None:
        if self.in_enemy_resource_range > 0:
            if self not in self.map.enemy_supply_targets_in_vision:
                self.map.enemy_supply_targets_in_vision.append(self)
        elif self in self.map.enemy_supply_targets_in_vision:
            self.map.enemy_supply_targets_in_vision.remove(self)

        if self.in_own_resource_range > 0:
            if self not in self.map.own_supply_targets_in_vision:
                self.map.own_supply_targets_in_vision.append(self)
        elif self in self.map.own_supply_targets_in_vision:
            self.map.own_supply_targets_in_vision.remove(self)

    def is_core_of(self, team: Team) -> bool:
        return (
            self.building.entity_type == EntityType.CORE and self.building.team == team
        )

    def propagates_for_team(self, team: Team) -> bool:
        return (
            self.building.id is not None
            and self.building.team == team
            and self.building.entity_type in SUPPLY_LINK_TYPES
        )

    def is_targeted_by_supply_link_for_team(self, team: Team) -> bool:
        if team == self.map.own_team:
            supply_links_in_vision = self.map.own_supply_links_in_vision
        else:
            supply_links_in_vision = self.map.enemy_supply_links_in_vision

        return any(self in supply_link_tile.building.targets for supply_link_tile in supply_links_in_vision)

    def update_missing_links(self) -> None:
        if self.is_targeted_by_supply_link_for_team(self.map.own_team) and not (
            self.propagates_for_team(self.map.own_team)
            or self.is_core_of(self.map.own_team)
        ):
            if self not in self.map.own_missing_supply_links:
                self.map.own_missing_supply_links.append(self)

        if self.is_targeted_by_supply_link_for_team(self.map.enemy_team) and not (
            self.propagates_for_team(self.map.enemy_team)
            or self.is_core_of(self.map.enemy_team)
        ):
            if self not in self.map.enemy_missing_supply_links:
                self.map.enemy_missing_supply_links.append(self)
