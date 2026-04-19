from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cambc import Direction, EntityType, Environment, Position, ResourceType, Team
from lib.agent.constants import ENABLE_PRINTING
from lib.map.constants import (
    CORE_DIST_INF,
    INF_DIST,
    PASSABLE_TYPES,
    RESOURCE_TARGET_TYPES,
    SUPPLY_LINK_TYPES,
    WEAPON_TARGET_TYPES,
)
from lib.map.types import SupplyChainLabel

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
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
}
LAZY_WEAPON_TARGET_TYPES = {
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.LAUNCHER,
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
    prev_team: Team | None
    targets: list["Tile"]
    prev_targets: list["Tile"]
    hp: int | None
    direction: Direction | None
    vision_radius_sq: int | None
    last_resource_onit_turn: int | None
    last_titanium_onit_turn: int | None
    last_raw_axionite_onit_turn: int | None
    last_refined_axionite_onit_turn: int | None


class Tile:
    def __init__(self, position: Position, map: "Map") -> None:
        self.map: Map = map
        self.position: Position = position
        self.index: int = map.u_to_index(position)

        self.environment: Environment | None = None
        self.is_passable: bool = False
        self.is_walkable: bool = False
        self.building: TileBuilding = TileBuilding(
            None,
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

        self.last_patrolled_index: int = -1

        self.has_marker = False

    @property
    def own_core_dist(self) -> int:
        return self.map.u_get_own_core_dist_by_index(self.index)

    @own_core_dist.setter
    def own_core_dist(self, value: int) -> None:
        self.map.own_core_dist_by_index[self.index] = (
            CORE_DIST_INF if value >= INF_DIST else value
        )

    @property
    def dist_to_self(self) -> int:
        if (
            not self.map.compute_dist_to_self
            or self.map.dist_to_self_epoch == 0
            or self.map.dist_to_self_epoch_by_index[self.index]
            != self.map.dist_to_self_epoch
        ):
            return self.map.u_get_estimated_dist_to_self_by_index(self.index)
        return self.map.dist_to_self_by_index[self.index]

    @dist_to_self.setter
    def dist_to_self(self, value: int) -> None:
        self.map.dist_to_self_by_index[self.index] = value
        self.map.dist_to_self_epoch_by_index[self.index] = self.map.dist_to_self_epoch

    @property
    def own_supply_chain_label(self) -> SupplyChainLabel:
        return SupplyChainLabel(self.map.own_supply_chain_labels_by_index[self.index])

    @own_supply_chain_label.setter
    def own_supply_chain_label(self, value: SupplyChainLabel | int) -> None:
        self.map.own_supply_chain_labels_by_index[self.index] = int(value)

    @property
    def enemy_supply_chain_label(self) -> SupplyChainLabel:
        return SupplyChainLabel(self.map.enemy_supply_chain_labels_by_index[self.index])

    @enemy_supply_chain_label.setter
    def enemy_supply_chain_label(self, value: SupplyChainLabel | int) -> None:
        self.map.enemy_supply_chain_labels_by_index[self.index] = int(value)

    def get_supply_chain_label(self, team: Team) -> SupplyChainLabel:
        if team == self.map.own_team:
            return self.own_supply_chain_label
        if team == self.map.enemy_team:
            return self.enemy_supply_chain_label
        return SupplyChainLabel.NONE

    def set_supply_chain_label(
        self,
        team: Team,
        value: SupplyChainLabel | int,
    ) -> None:
        if team == self.map.own_team:
            self.own_supply_chain_label = value
        elif team == self.map.enemy_team:
            self.enemy_supply_chain_label = value

    def add_supply_chain_label(
        self,
        team: Team,
        value: SupplyChainLabel | int,
    ) -> bool:
        current_label = self.get_supply_chain_label(team)
        updated_label = current_label | SupplyChainLabel(value)
        if updated_label == current_label:
            return False
        self.set_supply_chain_label(team, updated_label)
        return True

    @property
    def is_enemy_turret_target_tile(self) -> int:
        return self.in_enemy_attack_range or self.in_enemy_launcher_pickup_zone

    @property
    def conveyor_targets_harvester(self) -> bool:
        return bool(self.map.conveyor_targets_harvester_by_index[self.index])

    def u_get_resource_targets(self) -> list["Tile"]:
        if self.building.entity_type in RESOURCE_TARGET_TYPES:
            return self.building.targets
        return []

    def u_calc_intrinsic_passability(self) -> bool:
        if self.is_core_of(self.map.enemy_team):
            return False
        if self.is_core_of(self.map.own_team):
            return True
        building_type = self.building.entity_type
        if building_type is None:
            return self.environment != Environment.WALL
        if building_type == EntityType.CORE:
            return self.building.team == self.map.own_team
        return building_type in PASSABLE_TYPES

    def u_calc_core_distance_passability(self) -> bool:
        if self.is_core_of(self.map.enemy_team):
            return False
        if self.is_core_of(self.map.own_team):
            return True
        building_type = self.building.entity_type
        if building_type == EntityType.CORE:
            return self.building.team == self.map.own_team
        return self.environment != Environment.WALL

    def u_refresh_core_distance_passability(self) -> None:
        core_distance_passable = self.u_calc_core_distance_passability()
        if core_distance_passable == bool(
            self.map.core_distance_passable_by_index[self.index]
        ):
            return
        self.map.core_distance_passable_by_index[self.index] = (
            1 if core_distance_passable else 0
        )
        self.map.core_distance_dirty_indices.add(self.index)

    def _is_intrinsically_passable(self) -> bool:
        return self.map.intrinsic_passable_by_index[self.index]

    def u_refresh_intrinsic_passability(self) -> None:
        intrinsic_passable = self.u_calc_intrinsic_passability()
        if intrinsic_passable == self.map.intrinsic_passable_by_index[self.index]:
            return
        self.map.intrinsic_passable_by_index[self.index] = intrinsic_passable

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
        self.map.conveyor_targets_harvester_by_index[self.index] = 0
        self.building = TileBuilding(
            None,
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
            self.building.last_titanium_onit_turn,
            self.building.last_raw_axionite_onit_turn,
            self.building.last_refined_axionite_onit_turn,
        )
        self.u_refresh_core_distance_passability()
        self.u_refresh_intrinsic_passability()

    def u_apply_core_building_state(
        self,
        team: Team,
        building_id: int | None,
        hp: int | None,
    ) -> None:
        if self.building.entity_type not in {None, EntityType.CORE}:
            self.clear_building()

        self.building.id = building_id
        self.building.entity_type = EntityType.CORE
        self.building.team = team
        self.building.direction = None
        self.building.vision_radius_sq = None
        self.building.targets = []
        self.building.hp = hp
        self.u_refresh_core_distance_passability()
        self.u_refresh_intrinsic_passability()
        self.is_passable = self._is_intrinsically_passable() and (
            self.bot.id is None or self.position == self.map.current_pos
        )
        

    def u_clear_core_building_state(self, team: Team) -> None:
        if self.building.entity_type == EntityType.CORE and self.building.team == team:
            self.clear_building()
            self.is_passable = self._is_intrinsically_passable() and (
                self.bot.id is None or self.position == self.map.current_pos
            )

    def update_attributes(self) -> None:
        ct = self.map.ct
        current_round = self.map.current_round
        if self.last_seen_turn == -1:
            self.map.newly_seen_tiles_in_vision.append(self)
        if self.environment is None:
            self.environment = ct.get_tile_env(self.position)
        self.u_refresh_core_distance_passability()
        if self.last_seen_turn == -1:
            # Frontier expansion cache: remember tiles first seen this turn.
            self.map.frontier_expand_newly_seen_indices.append(self.index)
        self.last_seen_turn = current_round

        bot_id = self.map.visible_builder_bot_ids_by_index.get(self.index)
        building_id = self.map.visible_building_ids_by_index.get(self.index)

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

        self.u_refresh_core_distance_passability()
        self.u_refresh_intrinsic_passability()
        self.is_passable = self._is_intrinsically_passable() and (
            self.bot.id is None or self.position == self.map.current_pos
        )

        self.is_walkable = self.building.entity_type in PASSABLE_TYPES or self.is_core_of(self.map.own_team)  
        if self.map.is_launcher:
            self.update_launcher_targets()
    
    def update_launcher_targets(self):
        if self.bot.id is not None:
            return
        if self.building.entity_type in PASSABLE_TYPES:
            self.map.launcher_own_reachable.append(self)
            self.map.launcher_enemy_reachable.append(self)
        elif self.building.entity_type == EntityType.CORE:
            if self.building.team == self.map.own_team:
                self.map.launcher_own_reachable.append(self)
            else:
                self.map.launcher_enemy_reachable.append(self)

    def update_bot(self, id_changed: bool) -> None:
        ct = self.map.ct
        # if self.bot.id == 972:
        #     raise ValueError(f"spotted bot here: {self.map.ct.get_position()} in round {self.map.ct.get_current_round()}")
        if id_changed:
            self.bot.entity_type = ct.get_entity_type(self.bot.id)
            self.bot.team = ct.get_team(self.bot.id)
            self.bot.targets = self.get_targets(self.bot.entity_type, self.bot.id)
        self.bot.hp = ct.get_hp(self.bot.id)
        if self.map.is_launcher and self in self.map.launcher_action_radius:
            self.map.launcher_action_radius_bots.append(self)
        self.update_target_zones_bot()
        if self.map.is_launcher:
            if self.bot.id not in self.map.launcher_known_buddies:
                self.map.launcher_newcomer_buddies.add(self.bot.id)
        if self.bot.team == self.map.own_team:
            self.map.visible_own_builder_bot_count += 1
        else:
            self.map.visible_enemy_builder_bot_count = 0
    
    def handle_marker(self, marker_id):
        self.has_marker = True
        self.building.id = None
        self.building.entity_type = None
        self.building.team = None
        symmetry_mode, own_id, current_round, target_x, target_y = self.map.read_marker(self.map.ct.get_marker_value(marker_id))
        #print("read symmetry_mode from position", self.position, "is", symmetry_mode)
        if self.map.symmetry_mode is None and symmetry_mode is not None:
            self.update_symmetry_information(symmetry_mode)
        if self.map.is_launcher:
            self.map.seen_markers_for_debugging.append(self)
            if not own_id in self.map.id_to_target_pos_round or self.map.id_to_target_pos_round[own_id][1] < current_round:
                self.map.id_to_target_pos_round[own_id] = (Position(target_x, target_y), current_round)

    def update_symmetry_information(self, symmetry_mode):
        self.map.symmetry_mode = symmetry_mode
        self.map.symmetry_mode_candidates = [symmetry_mode]
        self.map.enemy_core_center_pos_candidates = [
            (mode, pos) for mode, pos in self.map.enemy_core_center_pos_candidates
            if mode == symmetry_mode
        ]
        if ENABLE_PRINTING: print(self.map.enemy_core_center_pos_candidates)
        remaining_positions = {pos for _, pos in self.map.enemy_core_center_pos_candidates}
        if ENABLE_PRINTING: print(remaining_positions)
        if len(remaining_positions) == 1:
            self.map.enemy_core_center_pos = next(iter(remaining_positions))
            self.map.enemy_core_source_indices = self.map.u_set_core_source_indices(
                self.map.enemy_team,
                self.map.enemy_core_center_pos,
            )

    def update_building(self, id_changed: bool) -> None:
        ct = self.map.ct
                
        if id_changed:
            self.building.prev_entity_type = self.building.entity_type
            self.building.prev_targets = self.building.targets.copy()
            self.building.prev_team = self.building.team
            self.building.entity_type = ct.get_entity_type(self.building.id)
            self.building.team = ct.get_team(self.building.id)
            tracks_targets = self.u_tracks_building_targets()

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

            self.building.targets = (
                self.get_targets(
                    self.building.entity_type,
                    self.building.id,
                    direction=self.building.direction,
                )
                if tracks_targets
                else []
            )
            self.update_target_zones_building()

        
        if (self.building.entity_type == EntityType.MARKER):
            self.handle_marker(self.building.id)


        else:
            if self.building.entity_type == EntityType.GUNNER:
                new_direction = ct.get_direction(self.building.id)
                if new_direction != self.building.direction:
                    tracks_targets = self.u_tracks_building_targets()
                    if tracks_targets:
                        self.building.prev_entity_type = self.building.entity_type
                        self.building.prev_targets = self.building.targets.copy()
                        self.building.prev_team = self.building.team
                    self.building.direction = new_direction
                    if tracks_targets:
                        self.building.targets = self.get_targets(
                            self.building.entity_type,
                            self.building.id,
                            direction=self.building.direction,
                        )
                        self.update_target_zones_building()

        self.building.hp = ct.get_hp(self.building.id)
        if self.building.entity_type in STORED_RESOURCE_TRACKED_ENTITY_TYPES:
            stored_resource = ct.get_stored_resource(self.building.id)
            if stored_resource is not None:
                self.building.last_resource_onit_turn = self.map.current_round
                if stored_resource == ResourceType.TITANIUM:
                    self.building.last_titanium_onit_turn = self.map.current_round
                elif stored_resource == ResourceType.RAW_AXIONITE:
                    self.building.last_raw_axionite_onit_turn = self.map.current_round
                elif stored_resource == ResourceType.REFINED_AXIONITE:
                    self.building.last_refined_axionite_onit_turn = (
                        self.map.current_round
                    )

    def u_tracks_building_targets(self) -> bool:
        if self.building.entity_type in RESOURCE_TARGET_TYPES:
            return True
        return (
            self.building.team != self.map.own_team
            and self.building.entity_type in LAZY_WEAPON_TARGET_TYPES
        )

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
                    for idx in self.map.u_iter_builder_action_target_indices(self.index)
                ]
            case EntityType.CORE:
                return [
                    tiles_by_index[idx]
                    for idx in self.map.u_iter_core_footprint_target_indices(self.index)
                ]
            case EntityType.HARVESTER | EntityType.FOUNDRY:
                return [
                    tiles_by_index[idx]
                    for idx in self.map.u_iter_cardinal_neighbor_indices(self.index)
                ]
            case EntityType.CONVEYOR | EntityType.ARMOURED_CONVEYOR:
                if direction is None:
                    return []
                target_idx = self.map.u_get_neighbor_index_by_direction(
                    self.index,
                    direction,
                )
                return [] if target_idx is None else [tiles_by_index[target_idx]]
            case EntityType.SPLITTER:
                if direction is None:
                    return []
                return [
                    tiles_by_index[target_idx]
                    for output_direction in (
                        direction,
                        direction.rotate_left().rotate_left(),
                        direction.rotate_right().rotate_right(),
                    )
                    if (
                        target_idx := self.map.u_get_neighbor_index_by_direction(
                            self.index,
                            output_direction,
                        )
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
                        if self.map.is_launcher and target in self.map.launcher_visible_tiles and target not in self.map.launcher_killer_zone_tiles:
                            self.map.launcher_killer_zone_tiles.append(target)
                    else:
                        target.in_enemy_attack_range += delta
                        target.map.enemy_turret_target_by_index[target.index] = int(
                            target.in_enemy_attack_range > 0
                            or target.in_enemy_launcher_pickup_zone > 0
                        )
                        if self.map.is_launcher and target in self.map.launcher_safe_zone_tiles:
                            self.map.launcher_safe_zone_tiles.remove(target)
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
                        if self.map.is_launcher and target in self.map.launcher_safe_zone_tiles:
                            self.map.launcher_safe_zone_tiles.remove(target)

    def update_target_zones_building( self
    ) -> None:
        if (
            self.building.entity_type == self.building.prev_entity_type
            and Counter(self.building.prev_targets) == Counter(self.building.targets)
            and self.building.team == self.building.prev_team
        ):
            return
        self.update_target_zones_building_by(
            self.building.prev_targets,
            self.building.prev_entity_type,
            self.building.prev_team,
            -1,
        )
        self.update_target_zones_building_by(
            self.building.targets,
            self.building.entity_type,
            self.building.team,
            1,
        )

    def is_core_of(self, team: Team) -> bool:
        if self.building.entity_type == EntityType.CORE and self.building.team == team:
            return True
        if team == self.map.own_team:
            return bool(self.map.own_core_source_by_index[self.index])
        if team == self.map.enemy_team:
            return bool(self.map.enemy_core_source_by_index[self.index])
        return False

    def propagates_for_team(self, team: Team) -> bool:
        return (
            self.building.id is not None
            and self.building.team == team
            and self.building.entity_type in SUPPLY_LINK_TYPES
        )

    def is_targeted_by_supply_link_for_team(self, team: Team) -> bool:
        if team == self.map.own_team:
            return self.index in self.map.own_supply_link_target_indices_in_vision
        return self.index in self.map.enemy_supply_link_target_indices_in_vision

