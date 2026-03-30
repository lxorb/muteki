from collections import Counter
from dataclasses import dataclass

from cambc import Direction, EntityType, Environment, Position, Team


@dataclass
class TileBot:
    id: int | None
    entity_type: EntityType | None
    team: Team | None
    targets: list[Position]
    hp: int | None


@dataclass
class TileBuilding:
    id: int | None
    entity_type: EntityType | None
    prev_entity_type: EntityType | None
    team: Team | None
    targets: list[Position]
    prev_targets: list[Position]
    hp: int | None
    direction: Direction | None
    vision_radius_sq: int | None
    last_resource_onit_turn: int | None


class Tile:
    DIRECTIONS = tuple(direction for direction in Direction if direction != Direction.CENTRE)
    CARDINAL_DIRECTIONS = tuple(
        direction
        for direction in DIRECTIONS
        if sum(abs(delta) for delta in direction.delta()) == 1
    )
    BUILDER_ACTION_OFFSETS = tuple(
        (dx, dy)
        for dx in range(-1, 2)
        for dy in range(-1, 2)
        if dx * dx + dy * dy <= 2
    )
    SENTINEL_COVER_OFFSETS = tuple(
        (dx, dy) for dx in range(-1, 2) for dy in range(-1, 2)
    )

    TYPES_WITH_RESOURCE_TARGET = {
        EntityType.CONVEYOR,
        EntityType.SPLITTER,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.BRIDGE,
        EntityType.HARVESTER,
        EntityType.FOUNDRY,
    }

    TYPES_WITH_WEAPON_TARGET = {
        EntityType.GUNNER,
        EntityType.SENTINEL,
        EntityType.BREACH,
        EntityType.LAUNCHER,
    }

    TYPES_PASSABLE = {
        EntityType.CONVEYOR,
        EntityType.SPLITTER,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.ROAD,
        EntityType.BRIDGE,
    }

    SUPPLY_LINK_TYPES = {
        EntityType.CONVEYOR,
        EntityType.SPLITTER,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.BRIDGE,
    }

    def __init__(self, position: Position, map):
        self.map = map
        self.position = position

        self.own_core_dist = 10**9
        self.enemy_core_dist = 10**9
        self.dist_to_self = 10**9

        self.environment: Environment | None = None
        self.is_passable = False
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
            None,
        )
        self.bot = TileBot(None, None, None, [], None)

        self.in_enemy_launcher_pickup_zone = 0
        self.in_enemy_attack_range = 0
        self.in_enemy_bot_action_range_turn = -1
        self.in_enemy_resource_range = 0

        self.in_own_launcher_pickup_zone = 0
        self.in_own_attack_range = 0
        self.in_own_bot_action_range_turn = -1
        self.in_own_resource_range = 0

        self.last_seen_turn = -1
        self.last_titanium_onit_turn = -1
        self.known_missing_supply_links: list[Position] = []

    def u_get_resource_targets(self) -> list[Position]:
        if self.building.entity_type in self.TYPES_WITH_RESOURCE_TARGET:
            return list(self.building.targets)
        return []

    def _append_unique(self, positions: list[Position], pos: Position) -> None:
        if pos not in positions:
            positions.append(pos)

    def _offset_position(self, direction: Direction) -> Position:
        dx, dy = direction.delta()
        return Position(self.position.x + dx, self.position.y + dy)

    def _adjacent_positions(self, directions: tuple[Direction, ...]) -> list[Position]:
        return [self._offset_position(direction) for direction in directions]

    def _get_gunner_targets(self, direction: Direction) -> list[Position]:
        if direction == Direction.CENTRE:
            return []
        delta_x, delta_y = direction.delta()
        max_steps = max(self.map.width, self.map.height)
        positions: list[Position] = []

        for step in range(1, max_steps + 1):
            target_pos = Position(
                self.position.x + delta_x * step,
                self.position.y + delta_y * step,
            )
            if not self.map._is_in_bounds(target_pos):
                break
            if self.position.distance_squared(target_pos) > 13:
                break
            positions.append(target_pos)

        return positions

    def _get_sentinel_targets(self, direction: Direction) -> list[Position]:
        if direction == Direction.CENTRE:
            return []

        delta_x, delta_y = direction.delta()
        max_steps = max(self.map.width, self.map.height)
        positions: list[Position] = []

        for step in range(max_steps + 1):
            line_pos = Position(
                self.position.x + delta_x * step,
                self.position.y + delta_y * step,
            )
            if self.position.distance_squared(line_pos) > 32:
                break
            if not self.map._is_in_bounds(line_pos):
                break

            for off_x, off_y in self.SENTINEL_COVER_OFFSETS:
                positions.append(Position(line_pos.x + off_x, line_pos.y + off_y))

        return self.map._in_bounds_positions(positions)

    def _get_breach_targets(self, direction: Direction) -> list[Position]:
        if direction == Direction.CENTRE:
            return []

        dir_x, dir_y = direction.delta()
        positions: list[Position] = []

        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if dx == 0 and dy == 0:
                    continue
                if dx * dx + dy * dy > 5:
                    continue
                if dx * dir_x + dy * dir_y < 0:
                    continue
                positions.append(Position(self.position.x + dx, self.position.y + dy))

        return self.map._in_bounds_positions(positions)

    def _get_launcher_targets(self) -> list[Position]:
        positions: list[Position] = []

        for x in range(self.map.width):
            for y in range(self.map.height):
                pos = Position(x, y)
                if pos == self.position:
                    continue
                if self.position.distance_squared(pos) <= 26:
                    positions.append(pos)

        return positions

    def _get_launcher_pickup_positions(self) -> list[Position]:
        return self.map._in_bounds_positions(self._adjacent_positions(self.DIRECTIONS))

    def _is_intrinsically_passable(self) -> bool:
        building_type = self.building.entity_type
        if building_type is None:
            return True
        if building_type == EntityType.CORE:
            return self.building.team == self.map.own_team
        return building_type in self.TYPES_PASSABLE

    def update_distances(self):
        self.dist_to_self = self.position.distance_squared(self.map.ct.get_position())

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

    def update_attributes(self):
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

        self.update_distances()
        self.update_map_values()

    def update_bot(self):
        self.bot.entity_type = self.map.ct.get_entity_type(self.bot.id)
        self.bot.team = self.map.ct.get_team(self.bot.id)
        self.bot.hp = self.map.ct.get_hp(self.bot.id)
        self.bot.targets = self.get_targets(self.bot.entity_type, self.bot.id)
        self.update_target_zones_bot()

    def update_building(self):
        prev_entity_type = self.building.entity_type
        prev_targets = self.building.targets.copy()
        prev_team = self.building.team
        self.building.prev_entity_type = self.building.entity_type
        self.building.prev_targets = self.building.targets.copy()
        self.building.entity_type = self.map.ct.get_entity_type(self.building.id)
        self.building.team = self.map.ct.get_team(self.building.id)
        self.building.hp = self.map.ct.get_hp(self.building.id)
        self.building.targets = self.get_targets(self.building.entity_type, self.building.id)
        try:
            self.building.direction = self.map.ct.get_direction(self.building.id)
        except Exception:
            self.building.direction = None
        try:
            self.building.vision_radius_sq = self.map.ct.get_vision_radius_sq(self.building.id)
        except Exception:
            self.building.vision_radius_sq = None
        try:
            stored_resource = self.map.ct.get_stored_resource(self.building.id)
        except Exception:
            stored_resource = None
        if stored_resource is not None:
            self.building.last_resource_onit_turn = self.map.ct.get_current_round()
        self.update_target_zones_building(prev_entity_type, prev_targets, prev_team)

    def update_target_zones_bot(self):
        current_round = self.map.ct.get_current_round()
        for target in self.bot.targets:
            if self.bot.team == self.map.own_team:
                self.map.matrix[target.x][target.y].in_own_bot_action_range_turn = current_round
            else:
                self.map.matrix[target.x][target.y].in_enemy_bot_action_range_turn = current_round

    def update_target_zones_building_by(
        self,
        targets: list[Position],
        entity_type: EntityType | None,
        team: Team | None,
        delta: int,
    ):
        if entity_type is None or team is None:
            return

        match entity_type:
            case _ if entity_type in self.TYPES_WITH_RESOURCE_TARGET:
                for target in targets:
                    if team == self.map.own_team:
                        self.map.matrix[target.x][target.y].in_own_resource_range += delta
                    else:
                        self.map.matrix[target.x][target.y].in_enemy_resource_range += delta
            case _ if entity_type in self.TYPES_WITH_WEAPON_TARGET - {EntityType.LAUNCHER}:
                for target in targets:
                    if team == self.map.own_team:
                        self.map.matrix[target.x][target.y].in_own_attack_range += delta
                    else:
                        self.map.matrix[target.x][target.y].in_enemy_attack_range += delta
            case EntityType.LAUNCHER:
                for target in self._get_launcher_pickup_positions():
                    if team == self.map.own_team:
                        self.map.matrix[target.x][target.y].in_own_launcher_pickup_zone += delta
                    else:
                        self.map.matrix[target.x][target.y].in_enemy_launcher_pickup_zone += delta

    def update_target_zones_building(
        self,
        prev_entity_type: EntityType | None,
        prev_targets: list[Position],
        prev_team: Team | None,
    ):
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

    def get_targets(self, entity_type: EntityType, entity_id: int) -> list[Position]:
        direction: Direction | None = None
        try:
            direction = self.map.ct.get_direction(entity_id)
        except Exception:
            direction = None

        match entity_type:
            case EntityType.BUILDER_BOT:
                positions = [
                    Position(self.position.x + dx, self.position.y + dy)
                    for dx, dy in self.BUILDER_ACTION_OFFSETS
                ]
            case EntityType.CORE:
                positions = [
                    Position(self.position.x + dx, self.position.y + dy)
                    for dx in range(-1, 2)
                    for dy in range(-1, 2)
                ]
            case EntityType.HARVESTER | EntityType.FOUNDRY:
                positions = self._adjacent_positions(self.CARDINAL_DIRECTIONS)
            case EntityType.CONVEYOR | EntityType.ARMOURED_CONVEYOR:
                if direction is None:
                    return []
                positions = [self._offset_position(direction)]
            case EntityType.SPLITTER:
                if direction is None:
                    return []
                positions = [
                    self._offset_position(output_direction)
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
                positions = self._get_gunner_targets(direction)
            case EntityType.SENTINEL:
                if direction is None:
                    return []
                positions = self._get_sentinel_targets(direction)
            case EntityType.BREACH:
                if direction is None:
                    return []
                positions = self._get_breach_targets(direction)
            case EntityType.LAUNCHER:
                positions = self._get_launcher_targets()
            case _:
                positions = []

        return self.map._in_bounds_positions(positions)

    def update_map_values(self):
        self.map_update_symmetry_mode()

        if self.bot.id is not None and self.bot.team != self.map.own_team:
            self.map.has_enemy_bot_in_vision = True

        self.map_update_buildings_in_vision()
        self.map_update_supply_links()
        self.map_update_in_vision_ores()
        self.map_update_harvesters()
        self.map_update_accessible_ores()

    def map_update_buildings_in_vision(self):
        if self.building.id is not None:
            self._append_unique(self.map.buildings_in_vision, self.position)

    def map_update_supply_links(self):
        if (
            self.building.id is not None
            and self.building.team == self.map.own_team
            and self.building.entity_type in self.SUPPLY_LINK_TYPES
        ):
            self._append_unique(self.map.own_supply_links_in_sight, self.position)

    def map_update_accessible_ores(self):
        if self.environment == Environment.ORE_TITANIUM:
            if self.building.id is None or (
                self.building.team == self.map.own_team
                and self.building.entity_type != EntityType.HARVESTER
            ):
                self._append_unique(self.map.known_accessible_titanium_tiles, self.position)
            elif self.position in self.map.known_accessible_titanium_tiles:
                self.map.known_accessible_titanium_tiles.remove(self.position)
        elif self.position in self.map.known_accessible_titanium_tiles:
            self.map.known_accessible_titanium_tiles.remove(self.position)

        if self.environment == Environment.ORE_AXIONITE:
            if self.building.id is None or (
                self.building.team == self.map.own_team
                and self.building.entity_type != EntityType.HARVESTER
            ):
                self._append_unique(self.map.known_accessible_axionite_tiles, self.position)
            elif self.position in self.map.known_accessible_axionite_tiles:
                self.map.known_accessible_axionite_tiles.remove(self.position)
        elif self.position in self.map.known_accessible_axionite_tiles:
            self.map.known_accessible_axionite_tiles.remove(self.position)

    def map_update_in_vision_ores(self):
        if self.environment == Environment.ORE_TITANIUM:
            self._append_unique(self.map.titanium_tiles_in_vision, self.position)
        elif self.environment == Environment.ORE_AXIONITE:
            self._append_unique(self.map.axionite_tiles_in_vision, self.position)

    def map_update_harvesters(self):
        if self.building.entity_type == EntityType.HARVESTER:
            if self.building.team == self.map.own_team:
                self._append_unique(self.map.own_harvesters_in_sight, self.position)
            else:
                self._append_unique(self.map.enemy_harvesters_in_sight, self.position)

    def map_update_symmetry_mode(self):
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

    def update_supply_targets_in_vision(self):
        if self.in_enemy_resource_range > 0:
            self._append_unique(self.map.enemy_supply_targets_in_vision, self.position)
        elif self.position in self.map.enemy_supply_targets_in_vision:
            self.map.enemy_supply_targets_in_vision.remove(self.position)

        if self.in_own_resource_range > 0:
            self._append_unique(self.map.own_supply_targets_in_vision, self.position)
        elif self.position in self.map.own_supply_targets_in_vision:
            self.map.own_supply_targets_in_vision.remove(self.position)

    def update_missing_links(self):
        if self.in_own_resource_range and not (
            self.propagates_for_team(self.map.own_team)
            or self.is_core_of(self.map.own_team)
        ):
            self._append_unique(self.map.own_missing_supply_links, self.position)

        if self.in_enemy_resource_range and not (
            self.propagates_for_team(self.map.enemy_team)
            or self.is_core_of(self.map.enemy_team)
        ):
            self._append_unique(self.map.enemy_missing_supply_links, self.position)

    def is_core_of(self, team: Team) -> bool:
        return self.building.entity_type == EntityType.CORE and self.building.team == team

    def propagates_for_team(self, team: Team) -> bool:
        return (
            self.building.id is not None
            and self.building.team == team
            and self.building.entity_type in self.SUPPLY_LINK_TYPES
        )
