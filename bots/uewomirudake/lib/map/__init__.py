from collections import deque
from collections.abc import Iterable
from enum import Enum
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
    DIRECTIONS,
    INF_DIST,
    SUPPLY_LINK_TYPES,
)
from lib.map.tile import Tile

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
        self.dist_to_self_by_index = [INF_DIST] * self.tile_count
        self.own_core_dist_by_index = [INF_DIST] * self.tile_count
        self.enemy_core_dist_by_index = [INF_DIST] * self.tile_count
        self.inf_distances_by_index = [INF_DIST] * self.tile_count
        self.intrinsic_passable_by_index = [True] * self.tile_count
        self.core_distance_dirty_indices: set[int] = set()
        self.core_distance_enqueued_by_index = bytearray(self.tile_count)
        self.own_core_source_indices: tuple[int, ...] = ()
        self.enemy_core_source_indices: tuple[int, ...] = ()
        self.own_core_source_by_index = bytearray(self.tile_count)
        self.enemy_core_source_by_index = bytearray(self.tile_count)
        self.own_core_dist_initialized = False
        self.enemy_core_dist_initialized = False
        self.distance_queue_buffer_by_index: list[int] = []
        self.path_queue_buffer_by_index: list[int] = []
        self.path_seen_epoch_by_index = [0] * self.tile_count
        self.path_predecessor_by_index = [-1] * self.tile_count
        self.path_epoch = 0
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

        # Frontier expansion cache used by `s_frontier_expand_new`.
        self.frontier_expand_cached_unseen_indices: set[int] = set()
        self.frontier_expand_newly_seen_indices: list[int] = []

        self.stopwatch = Stopwatch("Map")

        self._reset_turn_state()

    def _reset_turn_state(self) -> None:
        self.current_round = self.ct.get_current_round()
        self.current_pos = self.ct.get_position()
        self.titanium, self.axionite = self.ct.get_global_resources()

        self.has_enemy_bot_in_vision = False
        self.tiles_in_vision: list[Tile] = []
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
        self.frontier_expand_newly_seen_indices = []

    def u_update_vision(self):
        self.stopwatch.start()

        self._reset_turn_state()

        self.tiles_in_vision = [
            self.u_get_pos_tile(pos) for pos in self.ct.get_nearby_tiles()
        ]

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

        candidate_modes_to_remove = set()

        for tile in self.tiles_in_vision:
            x = tile.position.x
            y = tile.position.y
            symmetric_locations = {
                SymmetryMode.ROTATION: (self.width - 1 - x, self.height - 1 - y),
                SymmetryMode.MIRROR_X: (x, self.height - 1 - y),
                SymmetryMode.MIRROR_Y: (self.width - 1 - x, y),
            }

            for symmetry_mode, (sx, sy) in symmetric_locations.items():
                if symmetry_mode not in self.symmetry_mode_candidates:
                    continue

                symmetric_tile = self.matrix[sx][sy]
                if symmetric_tile.environment is None:
                    continue

                tile_is_core = tile.building.entity_type == EntityType.CORE
                symmetric_is_core = (
                    symmetric_tile.building.entity_type == EntityType.CORE
                )
                if (
                    tile.environment != symmetric_tile.environment
                    or tile_is_core != symmetric_is_core
                ):
                    candidate_modes_to_remove.add(symmetry_mode)

        if not candidate_modes_to_remove:
            return

        self.symmetry_mode_candidates = [
            mode
            for mode in self.symmetry_mode_candidates
            if mode not in candidate_modes_to_remove
        ]
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
        """
        Return whether blocking this tile would significantly lengthen a nearby route to the own core.
        """
        if self.own_core_center_pos is None or not self.u_is_in_bounds(pos):
            return False

        blocked_key = (pos.x, pos.y)
        own_core_tiles = self.u_get_core_footprint_positions(self.own_core_center_pos)
        own_core_keys = {
            (core_tile.position.x, core_tile.position.y) for core_tile in own_core_tiles
        }
        if blocked_key in own_core_keys:
            return False

        for adjacent_pos in self.u_iter_adjacent_positions(pos):
            adjacent_tile = self.u_get_pos_tile(adjacent_pos)
            if (
                adjacent_tile.own_core_dist >= INF_DIST
                or not adjacent_tile._is_intrinsically_passable()
            ):
                continue

            alternative_dist = self.u_get_own_core_dist_avoiding_tile(
                adjacent_pos,
                blocked_key,
                own_core_keys,
            )
            if (
                alternative_dist - adjacent_tile.own_core_dist
                >= CHOKEPOINT_MIN_DIST_INCREASE
            ):
                return True

        return False

    def u_get_own_core_dist_avoiding_tile(
        self,
        source_pos: Position,
        blocked_key: tuple[int, int],
        own_core_keys: set[tuple[int, int]],
    ) -> int:
        source_idx = source_pos.x * self.height + source_pos.y
        blocked_idx = blocked_key[0] * self.height + blocked_key[1]
        own_core_indices = [False] * self.tile_count
        for core_key in own_core_keys:
            own_core_indices[core_key[0] * self.height + core_key[1]] = True

        queue = self.path_queue_buffer_by_index
        queue.clear()
        queue.append(source_idx)
        queue_head = 0
        seen = [False] * self.tile_count
        seen[source_idx] = True
        seen[blocked_idx] = True
        dist_by_index = [INF_DIST] * self.tile_count
        dist_by_index[source_idx] = 0
        neighbor_indices_by_index = self.neighbor_indices_by_index
        intrinsic_passable_by_index = self.intrinsic_passable_by_index

        while queue_head < len(queue):
            current_idx = queue[queue_head]
            queue_head += 1
            current_dist = dist_by_index[current_idx]
            if own_core_indices[current_idx]:
                return current_dist

            for neighbor_idx in neighbor_indices_by_index[current_idx]:
                if seen[neighbor_idx]:
                    continue

                if (
                    not own_core_indices[neighbor_idx]
                    and not intrinsic_passable_by_index[neighbor_idx]
                ):
                    continue

                seen[neighbor_idx] = True
                dist_by_index[neighbor_idx] = current_dist + 1
                queue.append(neighbor_idx)

        return INF_DIST

    def u_update_supply_information(self) -> None:
        for tile in self.tiles_in_vision:
            tile.update_supply_targets_in_vision()
            tile.update_missing_links()

    def u_run_distance_bfs(
        self,
        seed_indices: list[int] | tuple[int, ...],
        distance_by_index: list[int],
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
        distance_by_index: list[int],
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
                updated_dist = INF_DIST
            else:
                best_neighbor_dist = INF_DIST
                for neighbor_idx in neighbor_indices_by_index[idx]:
                    neighbor_dist = distance_by_index[neighbor_idx]
                    if neighbor_dist < best_neighbor_dist:
                        best_neighbor_dist = neighbor_dist
                updated_dist = (
                    INF_DIST
                    if best_neighbor_dist >= INF_DIST
                    else best_neighbor_dist + 1
                )

            if updated_dist == distance_by_index[idx]:
                continue

            distance_by_index[idx] = updated_dist
            for neighbor_idx in neighbor_indices_by_index[idx]:
                self.u_enqueue_core_distance_index(neighbor_idx, queue)

    def u_refresh_dist_to_self(self) -> None:
        self.u_run_distance_bfs(
            (self.current_pos.x * self.height + self.current_pos.y,),
            self.dist_to_self_by_index,
        )

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
        own_core_dist_by_index = self.own_core_dist_by_index
        if source_pos == target_pos:
            return [source_tile]

        if (
            source_pos == self.current_pos
            and dist_to_self_by_index[target_idx] < INF_DIST
        ):
            current_idx = target_idx
            path = [tiles_by_index[current_idx]]

            while current_idx != source_idx:
                next_dist_to_self = dist_to_self_by_index[current_idx] - 1
                best_candidate_idx: int | None = None
                best_candidate_score: tuple[int, int, int] | None = None

                for adjacent_idx in neighbor_indices_by_index[current_idx]:
                    adjacent_tile = tiles_by_index[adjacent_idx]
                    if dist_to_self_by_index[adjacent_idx] != next_dist_to_self:
                        continue
                    if (
                        avoid_enemy_turrets
                        and adjacent_idx != source_idx
                        and adjacent_tile.is_enemy_turret_target_tile
                    ):
                        continue
                    if (
                        avoid_other_builder_bots
                        and adjacent_idx != source_idx
                        and adjacent_idx != target_idx
                        and adjacent_tile.bot.id is not None
                    ):
                        continue
                    candidate_score = (
                        own_core_dist_by_index[adjacent_idx],
                        adjacent_tile.position.x,
                        adjacent_tile.position.y,
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

                adjacent_tile = tiles_by_index[adjacent_idx]
                if (
                    avoid_enemy_turrets
                    and adjacent_idx != target_idx
                    and adjacent_tile.is_enemy_turret_target_tile
                ):
                    continue
                if (
                    avoid_other_builder_bots
                    and adjacent_idx != source_idx
                    and adjacent_idx != target_idx
                    and adjacent_tile.bot.id is not None
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

        self.dist_to_self_by_index[:] = self.inf_distances_by_index

        self.u_refresh_dist_to_self()
        dirty_indices = tuple(self.core_distance_dirty_indices)

        sw.lap("Init")

        if self.own_core_source_indices and (
            dirty_indices or not self.own_core_dist_initialized
        ):
            if not self.own_core_dist_initialized:
                self.own_core_dist_by_index[:] = self.inf_distances_by_index
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
                self.enemy_core_dist_by_index[:] = self.inf_distances_by_index
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
