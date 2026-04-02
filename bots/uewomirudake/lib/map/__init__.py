from array import array
from collections import deque
from collections.abc import Iterable
from enum import Enum
from heapq import heappop, heappush
import time

from cambc import (
    Controller,
    Direction,
    EntityType,
    Environment,
    GameConstants,
    Position,
    Team,
)

from lib.map.constants import (
    BUILDER_ACTION_OFFSETS,
    CHOKEPOINT_MIN_DIST_INCREASE,
    CORE_DIST_INF,
    DEEP_CHOKEPOINT_CHECKING,
    DIRECTIONS,
    DONT_INIT_CORE_DISTANCES_OUTSIDE_VISION,
    INF_DIST,
    OPPOSITE_ORE_SUPPLY_CHAIN_SEPARATION_INCLUDES_DIAGONALS,
    RESOURCE_TARGET_TYPES,
    SUPPLY_LINK_TYPES,
    TEMPORARY_TITANIUM_SUPPLY_AT_FOUNDRY_FIX,
)
from lib.map.tile import Tile
from lib.map.types import SupplyChainLabel

from lib.debug import Stopwatch


class SymmetryMode(Enum):
    ROTATION = "rotation"
    MIRROR_X = "mirror_x"
    MIRROR_Y = "mirror_y"


class Map:
    def __init__(self, ct: Controller):
        self.width = ct.get_map_width()
        self.height = ct.get_map_height()
        self.tile_count = self.width * self.height
        self.dist_to_self_by_index = array("H", [0]) * self.tile_count
        self.dist_to_self_epoch_by_index = array("I", [0]) * self.tile_count
        self.dist_to_self_epoch = 0
        self.last_dist_to_self_source_idx: int | None = None
        self.own_core_dist_by_index = array("H", [CORE_DIST_INF]) * self.tile_count
        self.enemy_core_dist_by_index = array("H", [CORE_DIST_INF]) * self.tile_count
        self.core_inf_distances_by_index = array("H", [CORE_DIST_INF]) * self.tile_count
        self.inf_distances_by_index = array("I", [INF_DIST]) * self.tile_count
        self.intrinsic_passable_by_index = [True] * self.tile_count
        self.bot_present_by_index = bytearray(self.tile_count)
        self.enemy_turret_target_by_index = bytearray(self.tile_count)
        # Bump whenever intrinsic traversability changes so chokepoint answers
        # can be reused safely until the passability graph changes again.
        self.passability_epoch = 0
        self.core_distance_dirty_indices: set[int] = set()
        self.core_distance_enqueued_by_index = bytearray(self.tile_count)
        self.own_core_source_indices: tuple[int, ...] = ()
        # Track own-core source changes separately from passability changes.
        self.own_core_source_epoch = 0
        self.enemy_core_source_indices: tuple[int, ...] = ()
        self.own_core_source_by_index = bytearray(self.tile_count)
        self.enemy_core_source_by_index = bytearray(self.tile_count)
        self.own_core_dist_initialized = False
        self.enemy_core_dist_initialized = False
        self.distance_queue_buffer_by_index: list[int] = []
        self.path_queue_buffer_by_index: list[int] = []
        self.visible_builder_bot_ids_by_index: dict[int, int] = {}
        self.visible_building_ids_by_index: dict[int, int] = {}
        self.own_supply_link_target_indices_in_vision: set[int] = set()
        self.enemy_supply_link_target_indices_in_vision: set[int] = set()
        self.own_supply_chain_labels_by_index = bytearray(self.tile_count)
        self.enemy_supply_chain_labels_by_index = bytearray(self.tile_count)
        # Dedicated chokepoint BFS buffers avoid per-call queue/list allocation.
        self.chokepoint_queue_buffer_by_index: list[int] = []
        self.path_seen_epoch_by_index = [0] * self.tile_count
        self.path_predecessor_by_index = [-1] * self.tile_count
        self.path_epoch = 0
        self.chokepoint_seen_epoch_by_index = [0] * self.tile_count
        self.chokepoint_dist_by_index = [0] * self.tile_count
        self.chokepoint_epoch = 0
        self.chokepoint_cache_by_index: dict[int, tuple[int, int, bool]] = {}
        self.matrix: list[list[Tile]] = [
            [Tile(Position(x, y), self) for y in range(self.height)]
            for x in range(self.width)
        ]
        self.tiles_by_index: list[Tile] = [
            self.matrix[x][y] for x in range(self.width) for y in range(self.height)
        ]
        self.neighbor_indices_by_index: list[tuple[int, ...]] = []
        self.cardinal_neighbor_indices_by_index: list[tuple[int, ...]] = []
        self.neighbor_index_by_direction_by_index: list[dict[Direction, int]] = []
        self.builder_action_target_indices_by_index: list[tuple[int, ...]] = []
        self.core_footprint_target_indices_by_index: list[tuple[int, ...]] = []
        self.attackable_target_indices_cache: dict[
            tuple[int, EntityType, Direction],
            tuple[int, ...],
        ] = {}
        for idx in range(self.tile_count):
            x = idx // self.height
            y = idx % self.height
            neighbors: list[int] = []
            cardinal_neighbors: list[int] = []
            neighbor_by_direction: dict[Direction, int] = {}
            for direction in DIRECTIONS:
                dx, dy = direction.delta()
                nx = x + dx
                ny = y + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    neighbor_idx = nx * self.height + ny
                    neighbors.append(neighbor_idx)
                    neighbor_by_direction[direction] = neighbor_idx
                    if dx == 0 or dy == 0:
                        cardinal_neighbors.append(neighbor_idx)
            self.neighbor_indices_by_index.append(tuple(neighbors))
            self.cardinal_neighbor_indices_by_index.append(tuple(cardinal_neighbors))
            self.neighbor_index_by_direction_by_index.append(neighbor_by_direction)

            builder_targets: list[int] = []
            for dx, dy in BUILDER_ACTION_OFFSETS:
                nx = x + dx
                ny = y + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    builder_targets.append(nx * self.height + ny)
            self.builder_action_target_indices_by_index.append(tuple(builder_targets))

            core_targets: list[int] = []
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    nx = x + dx
                    ny = y + dy
                    if 0 <= nx < self.width and 0 <= ny < self.height:
                        core_targets.append(nx * self.height + ny)
            self.core_footprint_target_indices_by_index.append(tuple(core_targets))

        self.ct = ct
        self.own_team = ct.get_team()
        self.enemy_team = next(team for team in Team if team != self.own_team)

        self.symmetry_mode: SymmetryMode | None = None
        self.symmetry_mode_candidates = [
            SymmetryMode.ROTATION,
            SymmetryMode.MIRROR_X,
            SymmetryMode.MIRROR_Y,
        ]
        self.own_core_center_pos: Position | None = None
        self.enemy_core_center_pos: Position | None = None
        self.enemy_core_center_pos_candidates: list[tuple[SymmetryMode, Position]] = []
        self.known_accessible_titanium_tiles: list[Tile] = []
        self.known_accessible_axionite_tiles: list[Tile] = []

        self.has_built_foundry: bool = False
        self.built_foundry_index: int = -1

        # Frontier expansion cache used by `s_frontier_expand_new`.
        self.frontier_expand_cached_unseen_indices: set[int] = set()
        self.frontier_expand_newly_seen_indices: list[int] = []
        self.known_own_supply_link_indices: set[int] = set()

        self.stopwatch = Stopwatch("Map")

        self._reset_turn_state()

    def _reset_turn_state(self) -> None:
        self.current_round = self.ct.get_current_round()
        self.current_pos = self.ct.get_position()
        self.titanium, self.axionite = self.ct.get_global_resources()

        self.has_enemy_bot_in_vision = False
        self.tiles_in_vision: list[Tile] = []
        self.newly_seen_tiles_in_vision: list[Tile] = []
        self.titanium_tiles_in_vision: list[Tile] = []
        self.axionite_tiles_in_vision: list[Tile] = []
        self.own_harvesters_in_vision: list[Tile] = []
        self.enemy_harvesters_in_vision: list[Tile] = []
        self.own_supply_targets_in_vision: list[Tile] = []
        self.enemy_supply_targets_in_vision: list[Tile] = []
        self.own_supply_links_in_vision: list[Tile] = []
        self.enemy_supply_links_in_vision: list[Tile] = []
        self.own_buildings_in_vision: list[Tile] = []
        self.enemy_buildings_in_vision: list[Tile] = []
        self.own_missing_supply_links: list[Tile] = []
        self.enemy_missing_supply_links: list[Tile] = []
        self.visible_builder_bot_ids_by_index = {}
        self.visible_building_ids_by_index = {}
        self.own_supply_link_target_indices_in_vision = set()
        self.enemy_supply_link_target_indices_in_vision = set()
        self.frontier_expand_newly_seen_indices = []

    def u_update_vision(self):
        self.stopwatch.start()

        self._reset_turn_state()

        self.tiles_in_vision = [
            self.u_get_pos_tile(pos) for pos in self.ct.get_nearby_tiles()
        ]

        for unit_id in self.ct.get_nearby_units():
            if self.ct.get_entity_type(unit_id) != EntityType.BUILDER_BOT:
                continue
            pos = self.ct.get_position(unit_id)
            if self.u_is_in_bounds(pos):
                self.visible_builder_bot_ids_by_index[pos.x * self.height + pos.y] = (
                    unit_id
                )

        for building_id in self.ct.get_nearby_buildings():
            pos = self.ct.get_position(building_id)
            if self.u_is_in_bounds(pos):
                self.visible_building_ids_by_index[pos.x * self.height + pos.y] = (
                    building_id
                )

        for tile in self.tiles_in_vision:
            tile.update_attributes()

        self.stopwatch.lap("Attributes")

        self.u_update_visible_map_caches()

        self.stopwatch.lap("Caches")

        if self.own_core_center_pos is None:
            self.u_calc_core_center_positions()

        self.stopwatch.lap("Core positions")

        self.u_update_supply_information()

        self.stopwatch.lap("Supply info")

        self.u_update_supply_patrol_indices()

        self.stopwatch.lap("Patrol indices")

        self.u_update_distances()

        self.stopwatch.lap("Distances")

        self.stopwatch.log()

    def u_get_attackable_target_indices(
        self,
        source_idx: int,
        turret_type: EntityType,
        direction: Direction,
    ) -> tuple[int, ...]:
        cache_key = (source_idx, turret_type, direction)
        cached_indices = self.attackable_target_indices_cache.get(cache_key)
        if cached_indices is not None:
            return cached_indices

        source_pos = self.tiles_by_index[source_idx].position
        target_indices = tuple(
            pos.x * self.height + pos.y
            for pos in self.ct.get_attackable_tiles_from(
                source_pos,
                direction,
                turret_type,
            )
            if self.u_is_in_bounds(pos)
        )
        self.attackable_target_indices_cache[cache_key] = target_indices
        return target_indices

    def u_update_visible_map_caches(self) -> None:
        self.u_update_symmetry_from_visible_tiles()

        known_accessible_titanium_indices = {
            tile.index for tile in self.known_accessible_titanium_tiles
        }
        known_accessible_axionite_indices = {
            tile.index for tile in self.known_accessible_axionite_tiles
        }

        for tile in self.tiles_in_vision:
            building = tile.building

            if tile.bot.id is not None and tile.bot.team != self.own_team:
                self.has_enemy_bot_in_vision = True

            if building.id is not None:
                if building.team == self.own_team:
                    self.own_buildings_in_vision.append(tile)
                else:
                    self.enemy_buildings_in_vision.append(tile)

                if building.entity_type in SUPPLY_LINK_TYPES:
                    if building.team == self.own_team:
                        self.own_supply_links_in_vision.append(tile)
                    else:
                        self.enemy_supply_links_in_vision.append(tile)

                if building.entity_type == EntityType.HARVESTER:
                    if building.team == self.own_team:
                        self.own_harvesters_in_vision.append(tile)
                    else:
                        self.enemy_harvesters_in_vision.append(tile)

            if tile.environment == Environment.ORE_TITANIUM:
                self.titanium_tiles_in_vision.append(tile)
                if building.id is None or (
                    building.team == self.own_team
                    and building.entity_type != EntityType.HARVESTER
                ):
                    known_accessible_titanium_indices.add(tile.index)
                else:
                    known_accessible_titanium_indices.discard(tile.index)
            else:
                known_accessible_titanium_indices.discard(tile.index)

            if tile.environment == Environment.ORE_AXIONITE:
                self.axionite_tiles_in_vision.append(tile)
                if building.id is None or (
                    building.team == self.own_team
                    and building.entity_type != EntityType.HARVESTER
                ):
                    known_accessible_axionite_indices.add(tile.index)
                else:
                    known_accessible_axionite_indices.discard(tile.index)
            else:
                known_accessible_axionite_indices.discard(tile.index)

        self.known_accessible_titanium_tiles = [
            self.tiles_by_index[idx]
            for idx in sorted(known_accessible_titanium_indices)
        ]
        self.known_accessible_axionite_tiles = [
            self.tiles_by_index[idx]
            for idx in sorted(known_accessible_axionite_indices)
        ]
        self.u_update_frontier_expand_cache()

    def u_update_frontier_expand_cache(self) -> None:
        if not self.frontier_expand_newly_seen_indices:
            return

        frontier_indices = self.frontier_expand_cached_unseen_indices
        tiles_by_index = self.tiles_by_index
        neighbor_indices_by_index = self.neighbor_indices_by_index

        for idx in self.frontier_expand_newly_seen_indices:
            frontier_indices.discard(idx)
            for neighbor_idx in neighbor_indices_by_index[idx]:
                if tiles_by_index[neighbor_idx].last_seen_turn == -1:
                    frontier_indices.add(neighbor_idx)

    def u_update_symmetry_from_visible_tiles(self) -> None:
        if self.symmetry_mode is not None:
            return

        if not self.newly_seen_tiles_in_vision:
            return

        rotation_possible = SymmetryMode.ROTATION in self.symmetry_mode_candidates
        mirror_x_possible = SymmetryMode.MIRROR_X in self.symmetry_mode_candidates
        mirror_y_possible = SymmetryMode.MIRROR_Y in self.symmetry_mode_candidates

        for tile in self.newly_seen_tiles_in_vision:
            x = tile.position.x
            y = tile.position.y
            tile_environment = tile.environment
            tile_is_core = tile.building.entity_type == EntityType.CORE

            rotation_tile = None
            mirror_x_tile = None
            mirror_y_tile = None
            has_known_symmetric_tile = False

            if rotation_possible:
                rotation_tile = self.matrix[self.width - 1 - x][self.height - 1 - y]
                has_known_symmetric_tile = rotation_tile.environment is not None

            if mirror_x_possible:
                mirror_x_tile = self.matrix[x][self.height - 1 - y]
                has_known_symmetric_tile = (
                    has_known_symmetric_tile or mirror_x_tile.environment is not None
                )

            if mirror_y_possible:
                mirror_y_tile = self.matrix[self.width - 1 - x][y]
                has_known_symmetric_tile = (
                    has_known_symmetric_tile or mirror_y_tile.environment is not None
                )

            if not has_known_symmetric_tile:
                continue

            if rotation_possible:
                if rotation_tile.environment is not None and (
                    tile_environment != rotation_tile.environment
                    or tile_is_core
                    != (rotation_tile.building.entity_type == EntityType.CORE)
                ):
                    rotation_possible = False

            if mirror_x_possible:
                if mirror_x_tile.environment is not None and (
                    tile_environment != mirror_x_tile.environment
                    or tile_is_core
                    != (mirror_x_tile.building.entity_type == EntityType.CORE)
                ):
                    mirror_x_possible = False

            if mirror_y_possible:
                if mirror_y_tile.environment is not None and (
                    tile_environment != mirror_y_tile.environment
                    or tile_is_core
                    != (mirror_y_tile.building.entity_type == EntityType.CORE)
                ):
                    mirror_y_possible = False

            if (
                int(rotation_possible) + int(mirror_x_possible) + int(mirror_y_possible)
                <= 1
            ):
                break

        new_symmetry_mode_candidates = []
        if rotation_possible:
            new_symmetry_mode_candidates.append(SymmetryMode.ROTATION)
        if mirror_x_possible:
            new_symmetry_mode_candidates.append(SymmetryMode.MIRROR_X)
        if mirror_y_possible:
            new_symmetry_mode_candidates.append(SymmetryMode.MIRROR_Y)

        if new_symmetry_mode_candidates == self.symmetry_mode_candidates:
            return

        self.symmetry_mode_candidates = new_symmetry_mode_candidates
        if len(self.symmetry_mode_candidates) == 1:
            self.symmetry_mode = self.symmetry_mode_candidates[0]

        self.enemy_core_center_pos_candidates = [
            (mode, symmetric_location)
            for mode, symmetric_location in self.enemy_core_center_pos_candidates
            if mode in self.symmetry_mode_candidates
        ]
        remaining_positions = {pos for _, pos in self.enemy_core_center_pos_candidates}
        if len(remaining_positions) == 1:
            self.enemy_core_center_pos = next(iter(remaining_positions))
            self.enemy_core_source_indices = self.u_cache_core_source_indices(
                self.enemy_core_center_pos,
                self.enemy_core_source_by_index,
            )
            self.enemy_core_dist_initialized = False

    def u_get_pos_tile(self, pos: Position) -> Tile:
        return self.matrix[pos.x][pos.y]

    def u_is_in_bounds(self, pos: Position) -> bool:
        return 0 <= pos.x < self.width and 0 <= pos.y < self.height

    def u_positions_to_tiles(
        self,
        positions: Iterable[Position],
    ) -> list[Tile]:
        seen: set[tuple[int, int]] = set()
        valid_tiles: list[Tile] = []
        for pos in positions:
            key = (pos.x, pos.y)
            if key in seen or not self.u_is_in_bounds(pos):
                continue
            seen.add(key)
            valid_tiles.append(self.u_get_pos_tile(pos))
        return valid_tiles

    def u_iter_adjacent_positions(self, pos: Position, consider_diagonal: bool = True):
        for direction in Direction:
            if direction == Direction.CENTRE:
                continue
            if not consider_diagonal and direction in {
                Direction.NORTHEAST,
                Direction.SOUTHEAST,
                Direction.SOUTHWEST,
                Direction.NORTHWEST,
            }:
                continue
            next_pos = pos.add(direction)
            if not self.u_is_in_bounds(next_pos):
                continue
            yield next_pos

    def u_is_adjacent_to_ore(
        self,
        pos: Position,
        ore_type: Environment,
        consider_diagonal: bool = OPPOSITE_ORE_SUPPLY_CHAIN_SEPARATION_INCLUDES_DIAGONALS,
    ) -> bool:
        for adjacent_pos in self.u_iter_adjacent_positions(
            pos,
            consider_diagonal=consider_diagonal,
        ):
            if self.u_get_pos_tile(adjacent_pos).environment == ore_type:
                return True
        return False

    def u_get_direction_between(
        self,
        source_pos: Position,
        target_pos: Position,
    ) -> Direction | None:
        delta_x = target_pos.x - source_pos.x
        delta_y = target_pos.y - source_pos.y
        step_x = 0 if delta_x == 0 else (1 if delta_x > 0 else -1)
        step_y = 0 if delta_y == 0 else (1 if delta_y > 0 else -1)

        for direction in Direction:
            if direction == Direction.CENTRE:
                continue
            if direction.delta() == (step_x, step_y):
                return direction
        return None

    def u_get_core_footprint_positions(self, center: Position) -> list[Tile]:
        return self.u_positions_to_tiles(
            [
                Position(center.x + dx, center.y + dy)
                for dx in range(-1, 2)
                for dy in range(-1, 2)
            ]
        )

    def u_cache_core_source_indices(
        self,
        center: Position | None,
        source_mask_by_index: bytearray,
    ) -> tuple[int, ...]:
        source_mask_by_index[:] = b"\x00" * self.tile_count
        if center is None:
            return ()

        source_indices = tuple(
            tile.index for tile in self.u_get_core_footprint_positions(center)
        )
        for idx in source_indices:
            source_mask_by_index[idx] = 1
        return source_indices

    def u_calc_core_center_positions(self) -> bool:
        if self.own_core_center_pos is not None:
            return True

        current_tile = self.u_get_pos_tile(self.current_pos)
        core_tile = current_tile
        if (
            core_tile.building.entity_type != EntityType.CORE
            or core_tile.building.team != self.own_team
        ):
            core_tile = None
            for candidate_tile in self.own_buildings_in_vision:
                if (
                    candidate_tile.building.entity_type == EntityType.CORE
                    and candidate_tile.building.team == self.own_team
                ):
                    core_tile = candidate_tile
                    break
            if core_tile is None:
                return False

        self.own_core_center_pos = self.ct.get_position(core_tile.building.id)
        self.own_core_source_indices = self.u_cache_core_source_indices(
            self.own_core_center_pos,
            self.own_core_source_by_index,
        )
        self.own_core_source_epoch += 1
        self.own_core_dist_initialized = False
        if not self.enemy_core_center_pos_candidates:
            center = self.own_core_center_pos
            all_enemy_core_center_pos_candidates = [
                (
                    SymmetryMode.ROTATION,
                    Position(self.width - 1 - center.x, self.height - 1 - center.y),
                ),
                (
                    SymmetryMode.MIRROR_X,
                    Position(center.x, self.height - 1 - center.y),
                ),
                (
                    SymmetryMode.MIRROR_Y,
                    Position(self.width - 1 - center.x, center.y),
                ),
            ]
            self.enemy_core_center_pos_candidates = [
                (mode, pos)
                for mode, pos in all_enemy_core_center_pos_candidates
                if mode in self.symmetry_mode_candidates
            ]
            remaining_positions = {
                pos for _, pos in self.enemy_core_center_pos_candidates
            }
            if len(remaining_positions) == 1:
                self.enemy_core_center_pos = next(iter(remaining_positions))
                self.enemy_core_source_indices = self.u_cache_core_source_indices(
                    self.enemy_core_center_pos,
                    self.enemy_core_source_by_index,
                )
                self.enemy_core_dist_initialized = False
        return True

    def u_is_enemy_bot_on_ally_tile(self, target_tile: Tile) -> bool:
        if target_tile.building.id is None:
            return False
        return target_tile.building.team == self.own_team

    def u_enemy_turret_targets_self(self, enemy_turret_id: int) -> bool:
        enemy_turret_pos = self.ct.get_position(enemy_turret_id)
        enemy_turret_tile = self.u_get_pos_tile(enemy_turret_pos)
        turret_type = enemy_turret_tile.building.entity_type
        target_pos = self.current_pos

        if turret_type == EntityType.GUNNER:
            return self.u_gunner_covers_target(
                enemy_turret_pos,
                enemy_turret_tile.building.direction,
                target_pos,
                enemy_turret_tile.building.vision_radius_sq,
            )
        if turret_type == EntityType.SENTINEL:
            return self.u_sentinel_covers_target(
                enemy_turret_pos,
                enemy_turret_tile.building.direction,
                target_pos,
                enemy_turret_tile.building.vision_radius_sq,
            )
        if turret_type == EntityType.BREACH:
            return self.u_breach_covers_target(
                enemy_turret_pos,
                enemy_turret_tile.building.direction,
                target_pos,
            )
        return False

    def u_is_on_gunner_facing_ray(
        self,
        source_pos: Position,
        direction: Direction,
        target_pos: Position,
    ) -> bool:
        if direction == Direction.CENTRE:
            return False

        delta_x = target_pos.x - source_pos.x
        delta_y = target_pos.y - source_pos.y
        dir_x, dir_y = direction.delta()

        if delta_x == 0 and delta_y == 0:
            return False
        if dir_x == 0:
            return delta_x == 0 and delta_y * dir_y > 0
        if dir_y == 0:
            return delta_y == 0 and delta_x * dir_x > 0

        return (
            delta_x * dir_y == delta_y * dir_x
            and delta_x * dir_x > 0
            and delta_y * dir_y > 0
        )

    def u_gunner_covers_target(
        self,
        turret_pos: Position,
        direction: Direction,
        target_pos: Position,
        radius_sq: int,
    ) -> bool:
        return (
            self.u_is_on_gunner_facing_ray(turret_pos, direction, target_pos)
            and turret_pos.distance_squared(target_pos) <= radius_sq
        )

    def u_get_gunner_ray_tiles(
        self,
        source_pos: Position,
        direction: Direction,
        radius_sq: int = GameConstants.GUNNER_VISION_RADIUS_SQ,
    ) -> list[Tile]:
        if direction == Direction.CENTRE:
            return []

        delta_x, delta_y = direction.delta()
        max_steps = max(self.width, self.height)
        tiles: list[Tile] = []

        for step in range(1, max_steps + 1):
            target_pos = Position(
                source_pos.x + delta_x * step,
                source_pos.y + delta_y * step,
            )
            if not self.u_is_in_bounds(target_pos):
                break
            if source_pos.distance_squared(target_pos) > radius_sq:
                break
            tiles.append(self.u_get_pos_tile(target_pos))

        return tiles

    def u_get_gunner_open_ray_tiles(
        self,
        source_pos: Position,
        direction: Direction,
        radius_sq: int = GameConstants.GUNNER_VISION_RADIUS_SQ,
    ) -> list[Tile]:
        open_tiles: list[Tile] = []
        for target_tile in self.u_get_gunner_ray_tiles(
            source_pos,
            direction,
            radius_sq,
        ):
            if (
                target_tile.building.id is not None
                and target_tile.building.team == self.own_team
            ):
                break
            open_tiles.append(target_tile)
        return open_tiles

    def u_sentinel_covers_target(
        self,
        turret_pos: Position,
        direction: Direction,
        target_pos: Position,
        radius_sq: int,
    ) -> bool:
        if direction == Direction.CENTRE:
            return False

        delta_x, delta_y = direction.delta()
        max_steps = max(self.width, self.height)

        for step in range(max_steps + 1):
            line_pos = Position(
                turret_pos.x + delta_x * step,
                turret_pos.y + delta_y * step,
            )
            if turret_pos.distance_squared(line_pos) > radius_sq:
                break
            if (
                max(
                    abs(target_pos.x - line_pos.x),
                    abs(target_pos.y - line_pos.y),
                )
                <= 1
            ):
                return True

        return False

    def u_breach_covers_target(
        self,
        turret_pos: Position,
        direction: Direction,
        target_pos: Position,
    ) -> bool:
        if direction == Direction.CENTRE:
            return False

        delta_x = target_pos.x - turret_pos.x
        delta_y = target_pos.y - turret_pos.y
        dir_x, dir_y = direction.delta()

        if delta_x == 0 and delta_y == 0:
            return False
        if (
            turret_pos.distance_squared(target_pos)
            > GameConstants.BREACH_ATTACK_RADIUS_SQ
        ):
            return False

        return (delta_x * dir_x) + (delta_y * dir_y) > 0

    def u_get_launcher_targets(self, source_pos: Position) -> list[Tile]:
        source_idx = source_pos.x * self.height + source_pos.y
        return [
            self.tiles_by_index[idx]
            for idx in self.u_get_attackable_target_indices(
                source_idx,
                EntityType.LAUNCHER,
                Direction.NORTH,
            )
        ]

    def u_get_launcher_pickup_positions(self, source_pos: Position) -> list[Tile]:
        source_idx = source_pos.x * self.height + source_pos.y
        return [
            self.tiles_by_index[idx]
            for idx in self.neighbor_indices_by_index[source_idx]
        ]

    def u_is_chokepoint(self, pos: Position) -> bool:
        if DEEP_CHOKEPOINT_CHECKING:
            return self.u_is_chokepoint_deep(pos)
        return self.u_is_chokepoint_light(pos)

    def u_is_chokepoint_light(self, pos: Position) -> bool:
        """
        Return whether this tile matches the simple orthogonal chokepoint pattern.
        """
        if not self.u_is_in_bounds(pos):
            return False

        center_idx = pos.x * self.height + pos.y
        if not self.intrinsic_passable_by_index[center_idx]:
            return False

        intrinsic_passable_by_index = self.intrinsic_passable_by_index

        def is_intrinsically_passable_or_in_bounds(x: int, y: int) -> bool:
            if x < 0 or x >= self.width or y < 0 or y >= self.height:
                return False
            return intrinsic_passable_by_index[x * self.height + y]

        left_right_blocked = not is_intrinsically_passable_or_in_bounds(
            pos.x - 1, pos.y
        ) and not is_intrinsically_passable_or_in_bounds(pos.x + 1, pos.y)
        up_down_open = is_intrinsically_passable_or_in_bounds(
            pos.x, pos.y - 1
        ) and is_intrinsically_passable_or_in_bounds(pos.x, pos.y + 1)
        up_down_blocked = not is_intrinsically_passable_or_in_bounds(
            pos.x, pos.y - 1
        ) and not is_intrinsically_passable_or_in_bounds(pos.x, pos.y + 1)
        left_right_open = is_intrinsically_passable_or_in_bounds(
            pos.x - 1, pos.y
        ) and is_intrinsically_passable_or_in_bounds(pos.x + 1, pos.y)

        return (left_right_blocked and up_down_open) or (
            up_down_blocked and left_right_open
        )

    def u_is_chokepoint_deep(self, pos: Position) -> bool:
        """
        Return whether blocking this tile would significantly lengthen a nearby route to the own core.
        """
        if not self.u_is_in_bounds(pos):
            return False

        blocked_idx = pos.x * self.height + pos.y
        if (
            not self.own_core_source_indices
            or self.own_core_source_by_index[blocked_idx]
        ):
            return False

        cache_entry = self.chokepoint_cache_by_index.get(blocked_idx)
        if cache_entry is not None:
            cached_passability_epoch, cached_core_epoch, cached_result = cache_entry
            if (
                cached_passability_epoch == self.passability_epoch
                and cached_core_epoch == self.own_core_source_epoch
            ):
                return cached_result

        # One weighted shortest-path search from the core with this tile
        # blocked gives the alternative path length for every adjacent tile,
        # which is much cheaper than rerunning the search once per neighbor.
        bfs_epoch = self.u_run_own_core_distance_bfs_avoiding_tile(blocked_idx)
        intrinsic_passable_by_index = self.intrinsic_passable_by_index
        own_core_dist_by_index = self.own_core_dist_by_index
        chokepoint_seen_epoch_by_index = self.chokepoint_seen_epoch_by_index
        chokepoint_dist_by_index = self.chokepoint_dist_by_index

        for adjacent_idx in self.neighbor_indices_by_index[blocked_idx]:
            if (
                own_core_dist_by_index[adjacent_idx] >= CORE_DIST_INF
                or not intrinsic_passable_by_index[adjacent_idx]
            ):
                continue

            alternative_dist = (
                chokepoint_dist_by_index[adjacent_idx]
                if chokepoint_seen_epoch_by_index[adjacent_idx] == bfs_epoch
                else INF_DIST
            )
            if (
                alternative_dist - own_core_dist_by_index[adjacent_idx]
                >= CHOKEPOINT_MIN_DIST_INCREASE
            ):
                self.chokepoint_cache_by_index[blocked_idx] = (
                    self.passability_epoch,
                    self.own_core_source_epoch,
                    True,
                )
                return True

        self.chokepoint_cache_by_index[blocked_idx] = (
            self.passability_epoch,
            self.own_core_source_epoch,
            False,
        )
        return False

    def u_run_own_core_distance_bfs_avoiding_tile(
        self,
        blocked_idx: int,
    ) -> int:
        # Epoch-stamped seen/dist arrays let us reuse the same storage without
        # clearing full-size lists on every chokepoint query.
        self.chokepoint_epoch += 1
        chokepoint_epoch = self.chokepoint_epoch
        heap: list[tuple[int, int]] = []
        seen_epoch_by_index = self.chokepoint_seen_epoch_by_index
        dist_by_index = self.chokepoint_dist_by_index
        own_core_source_indices = self.own_core_source_indices
        own_core_source_by_index = self.own_core_source_by_index
        intrinsic_passable_by_index = self.intrinsic_passable_by_index
        neighbor_indices_by_index = self.neighbor_indices_by_index

        for source_idx in own_core_source_indices:
            if source_idx == blocked_idx:
                continue
            seen_epoch_by_index[source_idx] = chokepoint_epoch
            dist_by_index[source_idx] = 0
            heappush(heap, (0, source_idx))

        while heap:
            current_dist, current_idx = heappop(heap)
            if (
                seen_epoch_by_index[current_idx] != chokepoint_epoch
                or current_dist != dist_by_index[current_idx]
            ):
                continue

            for neighbor_idx in neighbor_indices_by_index[current_idx]:
                if neighbor_idx == blocked_idx:
                    continue

                if (
                    not own_core_source_by_index[neighbor_idx]
                    and not intrinsic_passable_by_index[neighbor_idx]
                ):
                    continue

                next_dist = current_dist + self.u_get_core_distance_step_cost(
                    current_idx,
                    neighbor_idx,
                )
                if (
                    seen_epoch_by_index[neighbor_idx] == chokepoint_epoch
                    and next_dist >= dist_by_index[neighbor_idx]
                ):
                    continue

                seen_epoch_by_index[neighbor_idx] = chokepoint_epoch
                dist_by_index[neighbor_idx] = next_dist
                heappush(heap, (next_dist, neighbor_idx))

        return chokepoint_epoch

    def u_get_supply_chain_source_label(
        self,
        tile: Tile,
        team: Team,
    ) -> SupplyChainLabel:
        if tile.building.id is None or tile.building.team != team:
            return SupplyChainLabel.NONE

        if tile.building.entity_type == EntityType.HARVESTER:
            if tile.environment == Environment.ORE_TITANIUM:
                return SupplyChainLabel.TITANIUM
            if tile.environment == Environment.ORE_AXIONITE:
                return SupplyChainLabel.AXIONITE
            return SupplyChainLabel.NONE

        # TODO: More robust fix, don't just disable foundry supply label marking
        if not TEMPORARY_TITANIUM_SUPPLY_AT_FOUNDRY_FIX:
            if tile.building.entity_type == EntityType.FOUNDRY:
                return SupplyChainLabel.AXIONITE

        return SupplyChainLabel.NONE

    def u_get_supply_chain_output_label(
        self,
        tile: Tile,
        team: Team,
    ) -> SupplyChainLabel:
        if tile.building.id is None or tile.building.team != team:
            return SupplyChainLabel.NONE

        if tile.building.entity_type not in RESOURCE_TARGET_TYPES:
            return SupplyChainLabel.NONE

        if tile.building.entity_type == EntityType.FOUNDRY:
            return SupplyChainLabel.AXIONITE

        return tile.get_supply_chain_label(team)

    def u_can_preserve_visible_supply_chain_label(
        self,
        tile: Tile,
        team: Team,
    ) -> bool:
        supply_link_target_indices_in_vision = (
            self.own_supply_link_target_indices_in_vision
            if team == self.own_team
            else self.enemy_supply_link_target_indices_in_vision
        )
        if tile.environment == Environment.WALL:
            return False
        if tile.is_core_of(team):
            return True
        if tile.building.id is None:
            return tile.index in supply_link_target_indices_in_vision
        if tile.building.team == team and (
            tile.building.entity_type in RESOURCE_TARGET_TYPES
        ):
            return True
        if tile.building.entity_type in {EntityType.ROAD, EntityType.BARRIER}:
            return tile.index in supply_link_target_indices_in_vision
        return False

    def u_can_propagate_visible_supply_chain_label(
        self,
        tile: Tile,
        team: Team,
    ) -> bool:
        return (
            tile.last_seen_turn == self.current_round
            and tile.building.id is not None
            and tile.building.team == team
            and tile.building.entity_type in RESOURCE_TARGET_TYPES
        )

    def u_propagate_supply_chain_labels_for_team(
        self,
        queue: deque[Tile],
        team: Team,
        *,
        fill_only_unlabeled: bool,
    ) -> None:
        while queue:
            source_tile = queue.popleft()
            output_label = self.u_get_supply_chain_output_label(source_tile, team)
            if output_label == SupplyChainLabel.NONE:
                continue

            for target_tile in source_tile.u_get_resource_targets():
                if (
                    target_tile.last_seen_turn == self.current_round
                    and not self.u_can_preserve_visible_supply_chain_label(
                        target_tile,
                        team,
                    )
                ):
                    continue

                if fill_only_unlabeled:
                    if (
                        target_tile.get_supply_chain_label(team)
                        != SupplyChainLabel.NONE
                    ):
                        continue
                    target_tile.set_supply_chain_label(team, output_label)
                    label_changed = True
                else:
                    label_changed = target_tile.add_supply_chain_label(
                        team,
                        output_label,
                    )

                if not label_changed:
                    continue
                if self.u_can_propagate_visible_supply_chain_label(target_tile, team):
                    queue.append(target_tile)

    def u_update_supply_chain_labels_for_team(self, team: Team) -> None:
        fresh_queue: deque[Tile] = deque()
        remembered_queue: deque[Tile] = deque()
        remembered_labels: list[tuple[Tile, SupplyChainLabel]] = []

        for tile in self.tiles_in_vision:
            remembered_labels.append((tile, tile.get_supply_chain_label(team)))
            tile.set_supply_chain_label(team, SupplyChainLabel.NONE)

        for tile, _ in remembered_labels:
            source_label = self.u_get_supply_chain_source_label(tile, team)
            if source_label == SupplyChainLabel.NONE:
                continue
            tile.set_supply_chain_label(team, source_label)
            fresh_queue.append(tile)

        self.u_propagate_supply_chain_labels_for_team(
            fresh_queue,
            team,
            fill_only_unlabeled=False,
        )

        for tile, remembered_label in remembered_labels:
            if remembered_label == SupplyChainLabel.NONE:
                continue
            if tile.get_supply_chain_label(team) != SupplyChainLabel.NONE:
                continue
            if not self.u_can_preserve_visible_supply_chain_label(tile, team):
                continue

            tile.set_supply_chain_label(team, remembered_label)
            if self.u_can_propagate_visible_supply_chain_label(tile, team):
                remembered_queue.append(tile)

        self.u_propagate_supply_chain_labels_for_team(
            remembered_queue,
            team,
            fill_only_unlabeled=True,
        )

    def u_update_supply_chain_labels(self) -> None:
        self.u_update_supply_chain_labels_for_team(self.own_team)
        self.u_update_supply_chain_labels_for_team(self.enemy_team)

    def u_update_supply_information(self) -> None:
        self.own_supply_targets_in_vision = []
        self.enemy_supply_targets_in_vision = []
        self.own_missing_supply_links = []
        self.enemy_missing_supply_links = []
        self.own_supply_link_target_indices_in_vision = set()
        self.enemy_supply_link_target_indices_in_vision = set()

        for supply_link_tile in self.own_supply_links_in_vision:
            if self.u_is_own_supply_link_occupied_by_other_builder(supply_link_tile):
                continue
            self.own_supply_link_target_indices_in_vision.update(
                target.index for target in supply_link_tile.building.targets
            )

        for supply_link_tile in self.enemy_supply_links_in_vision:
            self.enemy_supply_link_target_indices_in_vision.update(
                target.index for target in supply_link_tile.building.targets
            )

        self.u_update_supply_chain_labels()

        for tile in self.tiles_in_vision:
            if tile.in_own_resource_range > 0:
                self.own_supply_targets_in_vision.append(tile)
            if tile.in_enemy_resource_range > 0:
                self.enemy_supply_targets_in_vision.append(tile)

            if tile.index in self.own_supply_link_target_indices_in_vision and not (
                tile.propagates_for_team(self.own_team)
                or tile.is_core_of(self.own_team)
                or (
                    tile.building.id is not None
                    and tile.building.team == self.own_team
                    and tile.building.entity_type
                    in {EntityType.HARVESTER, EntityType.FOUNDRY}
                )
            ):
                self.own_missing_supply_links.append(tile)

            if tile.index in self.enemy_supply_link_target_indices_in_vision and not (
                tile.propagates_for_team(self.enemy_team)
                or tile.is_core_of(self.enemy_team)
                or (
                    tile.building.id is not None
                    and tile.building.team == self.enemy_team
                    and tile.building.entity_type
                    in {EntityType.HARVESTER, EntityType.FOUNDRY}
                )
            ):
                self.enemy_missing_supply_links.append(tile)

    def u_is_own_supply_link_occupied_by_other_builder(self, tile: Tile) -> bool:
        return bool(
            tile.building.team == self.own_team
            and tile.building.entity_type in {EntityType.CONVEYOR, EntityType.BRIDGE}
            and tile.bot.id is not None
            and tile.bot.team == self.own_team
            and tile.bot.entity_type == EntityType.BUILDER_BOT
            and tile.position != self.current_pos
        )

    def u_update_supply_patrol_indices(self) -> None:
        """
        Refresh persistent knowledge of allied supply-link tiles.

        Known allied suppliers remain cached after they leave vision. When a
        previously known tile becomes visible again and is no longer an allied
        supplier, it is removed from the cache and its patrol marker is reset.
        """
        visible_supply_indices = {
            tile.index for tile in self.own_supply_links_in_vision
        }
        known_supply_indices = self.known_own_supply_link_indices
        known_supply_indices.update(visible_supply_indices)

        for tile in self.tiles_in_vision:
            if tile.index in visible_supply_indices:
                continue
            known_supply_indices.discard(tile.index)
            tile.last_patrolled_index = -1

    def u_run_distance_bfs(
        self,
        seed_indices: list[int] | tuple[int, ...],
        distance_by_index,
    ) -> None:
        queue = self.distance_queue_buffer_by_index
        queue.clear()
        queue.extend(seed_indices)
        queue_head = 0
        for seed_idx in seed_indices:
            distance_by_index[seed_idx] = 0

        neighbor_indices_by_index = self.neighbor_indices_by_index
        intrinsic_passable_by_index = self.intrinsic_passable_by_index

        while queue_head < len(queue):
            current_idx = queue[queue_head]
            queue_head += 1
            current_dist = distance_by_index[current_idx]

            for neighbor_idx in neighbor_indices_by_index[current_idx]:
                if not intrinsic_passable_by_index[neighbor_idx]:
                    continue

                next_dist = current_dist + 1
                if next_dist >= distance_by_index[neighbor_idx]:
                    continue

                distance_by_index[neighbor_idx] = next_dist
                queue.append(neighbor_idx)

    def u_get_core_distance_step_cost(
        self,
        source_idx: int,
        target_idx: int,
    ) -> int:
        source_x = source_idx // self.height
        source_y = source_idx % self.height
        target_x = target_idx // self.height
        target_y = target_idx % self.height
        if abs(source_x - target_x) + abs(source_y - target_y) == 1:
            return 1
        return 2

    def u_enqueue_core_distance_index(
        self,
        idx: int,
        queue: list[int],
    ) -> None:
        if self.core_distance_enqueued_by_index[idx]:
            return
        self.core_distance_enqueued_by_index[idx] = 1
        queue.append(idx)

    def u_update_core_distance_field_incremental(
        self,
        source_indices: list[int] | tuple[int, ...],
        source_by_index: bytearray,
        distance_by_index,
        dirty_indices: list[int] | tuple[int, ...],
    ) -> None:
        if not source_indices:
            return

        queue = self.distance_queue_buffer_by_index
        queue.clear()
        queue_head = 0
        neighbor_indices_by_index = self.neighbor_indices_by_index
        intrinsic_passable_by_index = self.intrinsic_passable_by_index

        for idx in source_indices:
            self.u_enqueue_core_distance_index(idx, queue)

        for idx in dirty_indices:
            self.u_enqueue_core_distance_index(idx, queue)
            for neighbor_idx in neighbor_indices_by_index[idx]:
                self.u_enqueue_core_distance_index(neighbor_idx, queue)

        while queue_head < len(queue):
            idx = queue[queue_head]
            queue_head += 1
            self.core_distance_enqueued_by_index[idx] = 0

            if source_by_index[idx]:
                updated_dist = 0
            elif not intrinsic_passable_by_index[idx]:
                updated_dist = CORE_DIST_INF
            else:
                best_neighbor_dist = CORE_DIST_INF
                for neighbor_idx in neighbor_indices_by_index[idx]:
                    neighbor_dist = distance_by_index[neighbor_idx]
                    if neighbor_dist >= CORE_DIST_INF:
                        continue
                    neighbor_dist += self.u_get_core_distance_step_cost(
                        idx,
                        neighbor_idx,
                    )
                    if neighbor_dist < best_neighbor_dist:
                        best_neighbor_dist = neighbor_dist
                updated_dist = best_neighbor_dist

            if updated_dist == distance_by_index[idx]:
                continue

            distance_by_index[idx] = updated_dist
            for neighbor_idx in neighbor_indices_by_index[idx]:
                self.u_enqueue_core_distance_index(neighbor_idx, queue)

    def u_initialize_core_distance_field(
        self,
        source_indices: list[int] | tuple[int, ...],
        distance_by_index,
    ) -> None:
        if not source_indices:
            return

        distance_by_index[:] = self.core_inf_distances_by_index
        heap: list[tuple[int, int]] = []
        for source_idx in source_indices:
            distance_by_index[source_idx] = 0
            heappush(heap, (0, source_idx))

        neighbor_indices_by_index = self.neighbor_indices_by_index
        intrinsic_passable_by_index = self.intrinsic_passable_by_index

        if DONT_INIT_CORE_DISTANCES_OUTSIDE_VISION:
            vision_radius_sq = self.ct.get_vision_radius_sq()

        while heap:
            current_dist, current_idx = heappop(heap)
            if current_dist != distance_by_index[current_idx]:
                continue

            for neighbor_idx in neighbor_indices_by_index[current_idx]:
                if not intrinsic_passable_by_index[neighbor_idx]:
                    continue

                if DONT_INIT_CORE_DISTANCES_OUTSIDE_VISION:
                    neighbor_pos = self.tiles_by_index[current_idx].position
                    if (
                        self.own_core_center_pos.distance_squared(neighbor_pos)
                        > vision_radius_sq
                    ):
                        continue

                next_dist = current_dist + self.u_get_core_distance_step_cost(
                    current_idx,
                    neighbor_idx,
                )
                if next_dist >= distance_by_index[neighbor_idx]:
                    continue

                distance_by_index[neighbor_idx] = next_dist
                heappush(heap, (next_dist, neighbor_idx))

    def u_refresh_dist_to_self(self) -> None:
        source_idx = self.current_pos.x * self.height + self.current_pos.y
        if (
            self.last_dist_to_self_source_idx == source_idx
            and self.dist_to_self_epoch != 0
        ):
            return

        self.dist_to_self_epoch += 1
        dist_to_self_epoch = self.dist_to_self_epoch
        self.last_dist_to_self_source_idx = source_idx
        queue = self.distance_queue_buffer_by_index
        queue.clear()
        queue.append(source_idx)
        queue_head = 0
        self.dist_to_self_epoch_by_index[source_idx] = dist_to_self_epoch
        self.dist_to_self_by_index[source_idx] = 0
        neighbor_indices_by_index = self.neighbor_indices_by_index
        intrinsic_passable_by_index = self.intrinsic_passable_by_index
        dist_to_self_by_index = self.dist_to_self_by_index
        dist_to_self_epoch_by_index = self.dist_to_self_epoch_by_index

        while queue_head < len(queue):
            current_idx = queue[queue_head]
            queue_head += 1
            current_dist = dist_to_self_by_index[current_idx]

            for neighbor_idx in neighbor_indices_by_index[current_idx]:
                if (
                    not intrinsic_passable_by_index[neighbor_idx]
                    or dist_to_self_epoch_by_index[neighbor_idx] == dist_to_self_epoch
                ):
                    continue

                dist_to_self_epoch_by_index[neighbor_idx] = dist_to_self_epoch
                dist_to_self_by_index[neighbor_idx] = current_dist + 1
                queue.append(neighbor_idx)

    def u_calculate_shortest_path(
        self,
        source_pos: Position,
        target_pos: Position,
        avoid_enemy_turrets: bool = True,
        avoid_other_builder_bots: bool = True,
    ) -> list[Tile]:
        if not self.u_is_in_bounds(source_pos) or not self.u_is_in_bounds(target_pos):
            return []

        source_tile = self.u_get_pos_tile(source_pos)
        target_tile = self.u_get_pos_tile(target_pos)
        source_idx = source_tile.index
        target_idx = target_tile.index
        tiles_by_index = self.tiles_by_index
        neighbor_indices_by_index = self.neighbor_indices_by_index
        intrinsic_passable_by_index = self.intrinsic_passable_by_index
        dist_to_self_by_index = self.dist_to_self_by_index
        dist_to_self_epoch_by_index = self.dist_to_self_epoch_by_index
        own_core_dist_by_index = self.own_core_dist_by_index
        enemy_turret_target_by_index = self.enemy_turret_target_by_index
        bot_present_by_index = self.bot_present_by_index
        if source_pos == target_pos:
            return [source_tile]

        if (
            source_pos == self.current_pos
            and dist_to_self_epoch_by_index[target_idx] == self.dist_to_self_epoch
        ):
            current_idx = target_idx
            path = [tiles_by_index[current_idx]]

            while current_idx != source_idx:
                next_dist_to_self = dist_to_self_by_index[current_idx] - 1
                best_candidate_idx: int | None = None
                best_candidate_score: tuple[int, int, int] | None = None

                for adjacent_idx in neighbor_indices_by_index[current_idx]:
                    if (
                        dist_to_self_epoch_by_index[adjacent_idx]
                        != self.dist_to_self_epoch
                        or dist_to_self_by_index[adjacent_idx] != next_dist_to_self
                    ):
                        continue
                    if (
                        avoid_enemy_turrets
                        and adjacent_idx != source_idx
                        and enemy_turret_target_by_index[adjacent_idx]
                    ):
                        continue
                    if (
                        avoid_other_builder_bots
                        and adjacent_idx != source_idx
                        and adjacent_idx != target_idx
                        and bot_present_by_index[adjacent_idx]
                    ):
                        continue
                    candidate_score = (
                        own_core_dist_by_index[adjacent_idx],
                        adjacent_idx // self.height,
                        adjacent_idx % self.height,
                    )
                    if (
                        best_candidate_score is None
                        or candidate_score < best_candidate_score
                    ):
                        best_candidate_score = candidate_score
                        best_candidate_idx = adjacent_idx

                if best_candidate_idx is None:
                    break

                current_idx = best_candidate_idx
                path.append(tiles_by_index[current_idx])

            if path[-1].index == source_idx:
                path.reverse()
                return path

        self.path_epoch += 1
        path_epoch = self.path_epoch
        seen_epoch_by_index = self.path_seen_epoch_by_index
        predecessor_by_index = self.path_predecessor_by_index
        seen_epoch_by_index[source_idx] = path_epoch
        predecessor_by_index[source_idx] = source_idx
        queue = self.path_queue_buffer_by_index
        queue.clear()
        queue.append(source_idx)
        queue_head = 0

        while queue_head < len(queue):
            current_idx = queue[queue_head]
            queue_head += 1
            for adjacent_idx in neighbor_indices_by_index[current_idx]:
                if seen_epoch_by_index[adjacent_idx] == path_epoch:
                    continue

                if (
                    avoid_enemy_turrets
                    and adjacent_idx != target_idx
                    and enemy_turret_target_by_index[adjacent_idx]
                ):
                    continue
                if (
                    avoid_other_builder_bots
                    and adjacent_idx != source_idx
                    and adjacent_idx != target_idx
                    and bot_present_by_index[adjacent_idx]
                ):
                    continue
                if (
                    adjacent_idx != target_idx
                    and not intrinsic_passable_by_index[adjacent_idx]
                ):
                    continue

                predecessor_by_index[adjacent_idx] = current_idx
                seen_epoch_by_index[adjacent_idx] = path_epoch
                if adjacent_idx == target_idx:
                    path = [target_tile]
                    walk_idx = adjacent_idx

                    while walk_idx != source_idx:
                        previous_idx = predecessor_by_index[walk_idx]
                        if previous_idx == -1:
                            break
                        path.append(tiles_by_index[previous_idx])
                        walk_idx = previous_idx

                    path.reverse()
                    return path

                queue.append(adjacent_idx)

        return []

    def u_update_distances(self) -> None:
        sw = Stopwatch("Map distances")
        sw.start()

        self.u_refresh_dist_to_self()
        dirty_indices = tuple(self.core_distance_dirty_indices)

        sw.lap("Init")

        if self.own_core_source_indices and (
            dirty_indices or not self.own_core_dist_initialized
        ):
            if not self.own_core_dist_initialized:
                self.u_initialize_core_distance_field(
                    self.own_core_source_indices,
                    self.own_core_dist_by_index,
                )
            else:
                self.u_update_core_distance_field_incremental(
                    self.own_core_source_indices,
                    self.own_core_source_by_index,
                    self.own_core_dist_by_index,
                    dirty_indices,
                )
            self.own_core_dist_initialized = True

        sw.lap("Own distance field")

        if self.enemy_core_source_indices and (
            dirty_indices or not self.enemy_core_dist_initialized
        ):
            if not self.enemy_core_dist_initialized:
                self.u_initialize_core_distance_field(
                    self.enemy_core_source_indices,
                    self.enemy_core_dist_by_index,
                )
            else:
                self.u_update_core_distance_field_incremental(
                    self.enemy_core_source_indices,
                    self.enemy_core_source_by_index,
                    self.enemy_core_dist_by_index,
                    dirty_indices,
                )
            self.enemy_core_dist_initialized = True

        sw.lap("Enemy distance field")

        self.core_distance_dirty_indices.clear()

        sw.log()
