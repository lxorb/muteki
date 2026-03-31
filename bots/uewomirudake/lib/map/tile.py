from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cambc import Direction, EntityType, Environment, GameConstants, Position, Team
from lib.map.constants import (
    BUILDER_ACTION_OFFSETS,
    CARDINAL_DIRECTIONS,
    DIRECTIONS,
    INF_DIST,
    PASSABLE_TYPES,
    RESOURCE_TARGET_TYPES,
    SUPPLY_LINK_TYPES,
    WEAPON_TARGET_TYPES,
)

if TYPE_CHECKING:
    from lib.map import Map


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

        self.own_core_dist: int = INF_DIST
        self.enemy_core_dist: int = INF_DIST
        self.dist_to_self: int = INF_DIST

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
    def is_enemy_turret_target_tile(self) -> int:
        return self.in_enemy_attack_range or self.in_enemy_launcher_pickup_zone

    def u_get_resource_targets(self) -> list["Tile"]:
        if self.building.entity_type in RESOURCE_TARGET_TYPES:
            return list(self.building.targets)
        return []

    def u_offset_position(self, direction: Direction) -> Position:
        dx, dy = direction.delta()
        return Position(self.position.x + dx, self.position.y + dy)

    def u_get_adjacent_positions(self, directions: tuple[Direction, ...]) -> list["Tile"]:
        return self.map.u_positions_to_tiles(
            [self.u_offset_position(direction) for direction in directions]
        )

    def _is_intrinsically_passable(self) -> bool:
        building_type = self.building.entity_type
        if building_type is None:
            return self.environment != Environment.WALL
        if building_type == EntityType.CORE:
            return self.building.team == self.map.own_team
        return building_type in PASSABLE_TYPES

    def clear_bot(self) -> None:
        self.bot = TileBot(None, None, None, [], None)

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

    def update_attributes(self) -> None:
        current_round = self.map.ct.get_current_round()
        self.environment = self.map.ct.get_tile_env(self.position)
        self.is_passable = self.map.ct.is_tile_passable(self.position)
        self.last_seen_turn = current_round

        if self.environment == Environment.ORE_TITANIUM:
            self.last_titanium_onit_turn = current_round

        bot_id = self.map.ct.get_tile_builder_bot_id(self.position)
        building_id = self.map.ct.get_tile_building_id(self.position)

        if bot_id is None:
            self.clear_bot()
        else:
            self.bot.id = bot_id
            self.update_bot()

        if building_id is None:
            self.clear_building()
        else:
            self.building.id = building_id
            self.update_building()

        self.update_map_values()

    def update_bot(self) -> None:
        self.bot.entity_type = self.map.ct.get_entity_type(self.bot.id)
        self.bot.team = self.map.ct.get_team(self.bot.id)
        self.bot.hp = self.map.ct.get_hp(self.bot.id)
        self.bot.targets = self.get_targets(self.bot.entity_type, self.bot.id)
        self.update_target_zones_bot()

    def update_building(self) -> None:
        prev_entity_type = self.building.entity_type
        prev_targets = self.building.targets.copy()
        prev_team = self.building.team
        self.building.prev_entity_type = self.building.entity_type
        self.building.prev_targets = self.building.targets.copy()
        self.building.entity_type = self.map.ct.get_entity_type(self.building.id)
        self.building.team = self.map.ct.get_team(self.building.id)
        self.building.hp = self.map.ct.get_hp(self.building.id)
        try:
            self.building.direction = self.map.ct.get_direction(self.building.id)
        except Exception:
            self.building.direction = None
        try:
            self.building.vision_radius_sq = self.map.ct.get_vision_radius_sq(
                self.building.id
            )
        except Exception:
            self.building.vision_radius_sq = None
        try:
            stored_resource = self.map.ct.get_stored_resource(self.building.id)
        except Exception:
            stored_resource = None
        if stored_resource is not None:
            self.building.last_resource_onit_turn = self.map.ct.get_current_round()
        self.building.targets = self.get_targets(
            self.building.entity_type, self.building.id
        )
        self.update_target_zones_building(prev_entity_type, prev_targets, prev_team)

    def get_targets(self, entity_type: EntityType, entity_id: int) -> list["Tile"]:
        direction: Direction | None = None
        try:
            direction = self.map.ct.get_direction(entity_id)
        except Exception:
            direction = None

        match entity_type:
            case EntityType.BUILDER_BOT:
                positions = [
                    Position(self.position.x + dx, self.position.y + dy)
                    for dx, dy in BUILDER_ACTION_OFFSETS
                ]
            case EntityType.CORE:
                positions = [
                    Position(self.position.x + dx, self.position.y + dy)
                    for dx in range(-1, 2)
                    for dy in range(-1, 2)
                ]
            case EntityType.HARVESTER | EntityType.FOUNDRY:
                positions = self.u_get_adjacent_positions(CARDINAL_DIRECTIONS)
            case EntityType.CONVEYOR | EntityType.ARMOURED_CONVEYOR:
                if direction is None:
                    return []
                positions = [self.u_offset_position(direction)]
            case EntityType.SPLITTER:
                if direction is None:
                    return []
                positions = [
                    self.u_offset_position(output_direction)
                    for output_direction in (
                        direction,
                        direction.rotate_left().rotate_left(),
                        direction.rotate_right().rotate_right(),
                    )
                ]
            case EntityType.BRIDGE:
                positions = [self.map.ct.get_bridge_target(entity_id)]
            case EntityType.GUNNER:
                if direction is None:
                    return []
                positions = self.map.u_get_gunner_ray_tiles(self.position, direction)
            case EntityType.SENTINEL:
                if direction is None:
                    return []
                positions = [
                    tile
                    for column in self.map.matrix
                    for tile in column
                    if self.map.u_sentinel_covers_target(
                        self.position,
                        direction,
                        tile.position,
                        self.building.vision_radius_sq or 0,
                    )
                ]
            case EntityType.BREACH:
                if direction is None:
                    return []
                positions = [
                    tile
                    for column in self.map.matrix
                    for tile in column
                    if self.map.u_breach_covers_target(
                        self.position,
                        direction,
                        tile.position,
                    )
                ]
            case EntityType.LAUNCHER:
                positions = self.map.u_get_launcher_targets(self.position)
            case _:
                positions = []

        if positions and isinstance(positions[0], Tile):
            return list(positions)
        return self.map.u_positions_to_tiles(positions)

    def update_target_zones_bot(self):
        current_round = self.map.ct.get_current_round()
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
            case EntityType.LAUNCHER:
                for target in self.map.u_get_launcher_pickup_positions(self.position):
                    if team == self.map.own_team:
                        target.in_own_launcher_pickup_zone += delta
                    else:
                        target.in_enemy_launcher_pickup_zone += delta

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

    def update_map_values(self) -> None:
        self.map_update_symmetry_mode()

        if self.bot.id is not None and self.bot.team != self.map.own_team:
            self.map.has_enemy_bot_in_vision = True

        self.map_update_buildings_in_vision()
        self.map_update_supply_links()
        self.map_update_in_vision_ores()
        self.map_update_harvesters()
        self.map_update_accessible_ores()

    def map_update_symmetry_mode(self) -> None:
        from lib.map import SymmetryMode

        if self.map.symmetry_mode is not None:
            return

        candidate_modes_to_remove = set()
        symmetric_locations = {
            SymmetryMode.ROTATION: Position(
                self.map.width - 1 - self.position.x,
                self.map.height - 1 - self.position.y,
            ),
            SymmetryMode.MIRROR_X: Position(
                self.position.x,
                self.map.height - 1 - self.position.y,
            ),
            SymmetryMode.MIRROR_Y: Position(
                self.map.width - 1 - self.position.x,
                self.position.y,
            ),
        }

        for symmetry_mode, symmetric_location in symmetric_locations.items():
            if symmetry_mode not in self.map.symmetry_mode_candidates:
                continue

            symmetric_tile = self.map.matrix[symmetric_location.x][symmetric_location.y]
            self_is_core = self.building.entity_type == EntityType.CORE
            symmetric_is_core = symmetric_tile.building.entity_type == EntityType.CORE

            if symmetric_tile.environment is not None and (
                self.environment != symmetric_tile.environment
                or self_is_core != symmetric_is_core
            ):
                candidate_modes_to_remove.add(symmetry_mode)

        self.map.symmetry_mode_candidates = [
            mode
            for mode in self.map.symmetry_mode_candidates
            if mode not in candidate_modes_to_remove
        ]
        if len(self.map.symmetry_mode_candidates) == 1:
            self.map.symmetry_mode = self.map.symmetry_mode_candidates[0]

        self.map.enemy_core_center_pos_candidates = [
            (mode, symmetric_location)
            for mode, symmetric_location in self.map.enemy_core_center_pos_candidates
            if mode in self.map.symmetry_mode_candidates
        ]
        remaining_positions = {
            pos for _, pos in self.map.enemy_core_center_pos_candidates
        }
        if len(remaining_positions) == 1:
            self.map.enemy_core_center_pos = next(iter(remaining_positions))

    def map_update_buildings_in_vision(self) -> None:
        if self.building.id is not None:
            if self.building.team == self.map.own_team:
                if self not in self.map.own_buildings_in_vision:
                    self.map.own_buildings_in_vision.append(self)
            elif self.building.team == self.map.enemy_team:
                if self not in self.map.enemy_buildings_in_vision:
                    self.map.enemy_buildings_in_vision.append(self)

    def map_update_supply_links(self) -> None:
        if (
            self.building.id is not None
            and self.building.entity_type in SUPPLY_LINK_TYPES
        ):
            if self.building.team == self.map.own_team:
                if self not in self.map.own_supply_links_in_vision:
                    self.map.own_supply_links_in_vision.append(self)
            elif self.building.team == self.map.enemy_team:
                if self not in self.map.enemy_supply_links_in_vision:
                    self.map.enemy_supply_links_in_vision.append(self)

    def map_update_in_vision_ores(self) -> None:
        if self.environment == Environment.ORE_TITANIUM:
            if self not in self.map.titanium_tiles_in_vision:
                self.map.titanium_tiles_in_vision.append(self)
        elif self.environment == Environment.ORE_AXIONITE:
            if self not in self.map.axionite_tiles_in_vision:
                self.map.axionite_tiles_in_vision.append(self)

    def map_update_accessible_ores(self) -> None:
        if self.environment == Environment.ORE_TITANIUM:
            if self.building.id is None or (
                self.building.team == self.map.own_team
                and self.building.entity_type != EntityType.HARVESTER
            ):
                if self not in self.map.known_accessible_titanium_tiles:
                    self.map.known_accessible_titanium_tiles.append(self)
            elif self in self.map.known_accessible_titanium_tiles:
                self.map.known_accessible_titanium_tiles.remove(self)
        elif self in self.map.known_accessible_titanium_tiles:
            self.map.known_accessible_titanium_tiles.remove(self)

        if self.environment == Environment.ORE_AXIONITE:
            if self.building.id is None or (
                self.building.team == self.map.own_team
                and self.building.entity_type != EntityType.HARVESTER
            ):
                if self not in self.map.known_accessible_axionite_tiles:
                    self.map.known_accessible_axionite_tiles.append(self)
            elif self in self.map.known_accessible_axionite_tiles:
                self.map.known_accessible_axionite_tiles.remove(self)
        elif self in self.map.known_accessible_axionite_tiles:
            self.map.known_accessible_axionite_tiles.remove(self)

    def map_update_harvesters(self) -> None:
        if self.building.entity_type == EntityType.HARVESTER:
            if self.building.team == self.map.own_team:
                if self not in self.map.own_harvesters_in_vision:
                    self.map.own_harvesters_in_vision.append(self)
            else:
                if self not in self.map.enemy_harvesters_in_vision:
                    self.map.enemy_harvesters_in_vision.append(self)

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
