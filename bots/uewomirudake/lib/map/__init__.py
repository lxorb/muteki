from collections import deque
from collections.abc import Iterable
from enum import Enum
import time

from cambc import Controller, Direction, EntityType, GameConstants, Position, Team

from lib.map.constants import CHOKEPOINT_MIN_DIST_INCREASE, DIRECTIONS, INF_DIST
from lib.map.tile import Tile


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
        self.matrix: list[list[Tile]] = [
            [Tile(Position(x, y), self) for y in range(self.height)]
            for x in range(self.width)
        ]
        self.tiles_by_index: list[Tile] = [
            self.matrix[x][y]
            for x in range(self.width)
            for y in range(self.height)
        ]
        self.neighbor_indices_by_index: list[tuple[int, ...]] = []
        for idx in range(self.tile_count):
            x = idx // self.height
            y = idx % self.height
            neighbors: list[int] = []
            for direction in DIRECTIONS:
                dx, dy = direction.delta()
                nx = x + dx
                ny = y + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    neighbors.append(nx * self.height + ny)
            self.neighbor_indices_by_index.append(tuple(neighbors))

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

        self._reset_turn_state()

    def _reset_turn_state(self) -> None:
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

    def u_update_vision(self):
        t_start = time.perf_counter_ns()
        self._reset_turn_state()

        self.tiles_in_vision = [
            self.u_get_pos_tile(pos) for pos in self.ct.get_nearby_tiles()
        ]

        t_update_attributes_start = time.perf_counter_ns()
        for tile in self.tiles_in_vision:
            tile.update_attributes()
        update_attributes_time_mus = (
            time.perf_counter_ns() - t_update_attributes_start
        ) // 1_000

        if self.own_core_center_pos is None:
            self.u_calc_core_center_positions()

        self.u_update_supply_information()

        t_update_distances_start = time.perf_counter_ns()
        self.u_update_distances()
        update_distances_time_mus = (
            time.perf_counter_ns() - t_update_distances_start
        ) // 1_000
        update_vision_time_mus = (time.perf_counter_ns() - t_start) // 1_000
        print(f"Map update attributes time: {update_attributes_time_mus} mus")
        print(f"Map update distances time: {update_distances_time_mus} mus")
        print(f"Map update vision time: {update_vision_time_mus} mus")

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
        tiles: list[Tile] = []

        for x in range(self.width):
            for y in range(self.height):
                pos = Position(x, y)
                if pos == source_pos:
                    continue
                if (
                    source_pos.distance_squared(pos)
                    <= GameConstants.LAUNCHER_VISION_RADIUS_SQ
                ):
                    tiles.append(self.u_get_pos_tile(pos))

        return tiles

    def u_get_launcher_pickup_positions(self, source_pos: Position) -> list[Tile]:
        return self.u_positions_to_tiles(
            [source_pos.add(direction) for direction in DIRECTIONS]
        )

    def u_is_chokepoint(self, pos: Position) -> bool:
        """
        Return whether blocking this tile would significantly lengthen a nearby route to the own core.
        """
        if self.own_core_center_pos is None or not self.u_is_in_bounds(pos):
            return False

        blocked_key = (pos.x, pos.y)
        own_core_tiles = self.u_get_core_footprint_positions(self.own_core_center_pos)
        own_core_keys = {
            (core_tile.position.x, core_tile.position.y)
            for core_tile in own_core_tiles
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
        queue: deque[tuple[Position, int]] = deque([(source_pos, 0)])
        seen = {(source_pos.x, source_pos.y), blocked_key}

        while queue:
            current_pos, current_dist = queue.popleft()
            current_key = (current_pos.x, current_pos.y)
            if current_key in own_core_keys:
                return current_dist

            for neighbor_pos in self.u_iter_adjacent_positions(current_pos):
                neighbor_key = (neighbor_pos.x, neighbor_pos.y)
                if neighbor_key in seen:
                    continue

                neighbor_tile = self.u_get_pos_tile(neighbor_pos)
                if (
                    neighbor_key not in own_core_keys
                    and not neighbor_tile._is_intrinsically_passable()
                ):
                    continue

                seen.add(neighbor_key)
                queue.append((neighbor_pos, current_dist + 1))

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
        queue: deque[int] = deque(seed_indices)
        for seed_idx in seed_indices:
            distance_by_index[seed_idx] = 0

        tiles_by_index = self.tiles_by_index
        neighbor_indices_by_index = self.neighbor_indices_by_index

        while queue:
            current_idx = queue.popleft()
            current_dist = distance_by_index[current_idx]

            for neighbor_idx in neighbor_indices_by_index[current_idx]:
                neighbor_tile = tiles_by_index[neighbor_idx]
                if not neighbor_tile._is_intrinsically_passable():
                    continue

                next_dist = current_dist + 1
                if next_dist >= distance_by_index[neighbor_idx]:
                    continue

                distance_by_index[neighbor_idx] = next_dist
                queue.append(neighbor_idx)

    def u_refresh_dist_to_self(self) -> None:
        self.u_run_distance_bfs(
            (self.u_get_pos_tile(self.current_pos).index,),
            self.dist_to_self_by_index,
        )

    def u_refresh_own_core_dist(self) -> None:
        if self.own_core_center_pos is None:
            return
        self.u_run_distance_bfs(
            tuple(
                tile.index
                for tile in self.u_get_core_footprint_positions(
                    self.own_core_center_pos
                )
            ),
            self.own_core_dist_by_index,
        )

    def u_refresh_enemy_core_dist(self) -> None:
        if self.enemy_core_center_pos is None:
            return
        self.u_run_distance_bfs(
            tuple(
                tile.index
                for tile in self.u_get_core_footprint_positions(
                    self.enemy_core_center_pos
                )
            ),
            self.enemy_core_dist_by_index,
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
        if source_pos == target_pos:
            return [source_tile]

        if source_pos == self.current_pos and target_tile.dist_to_self < INF_DIST:
            current_tile = target_tile
            path = [current_tile]

            while current_tile.position != source_pos:
                next_dist_to_self = current_tile.dist_to_self - 1
                candidate_tiles: list[Tile] = []

                for adjacent_pos in self.u_iter_adjacent_positions(current_tile.position):
                    adjacent_tile = self.u_get_pos_tile(adjacent_pos)
                    if adjacent_tile.dist_to_self != next_dist_to_self:
                        continue
                    if (
                        avoid_enemy_turrets
                        and adjacent_pos != source_pos
                        and adjacent_tile.is_enemy_turret_target_tile
                    ):
                        continue
                    if (
                        avoid_other_builder_bots
                        and adjacent_pos != source_pos
                        and adjacent_pos != target_pos
                        and adjacent_tile.bot.id is not None
                    ):
                        continue
                    candidate_tiles.append(adjacent_tile)

                if not candidate_tiles:
                    break

                candidate_tiles.sort(
                    key=lambda tile: (
                        tile.own_core_dist,
                        tile.position.x,
                        tile.position.y,
                    )
                )
                current_tile = candidate_tiles[0]
                path.append(current_tile)

            if path[-1].position == source_pos:
                path.reverse()
                return path

        source_key = (source_pos.x, source_pos.y)
        target_key = (target_pos.x, target_pos.y)
        predecessor_by_key: dict[tuple[int, int], Tile | None] = {source_key: None}
        queue: deque[Tile] = deque([source_tile])

        while queue:
            current_tile = queue.popleft()
            for adjacent_pos in self.u_iter_adjacent_positions(current_tile.position):
                adjacent_key = (adjacent_pos.x, adjacent_pos.y)
                if adjacent_key in predecessor_by_key:
                    continue

                adjacent_tile = self.u_get_pos_tile(adjacent_pos)
                if (
                    avoid_enemy_turrets
                    and adjacent_pos != target_pos
                    and adjacent_tile.is_enemy_turret_target_tile
                ):
                    continue
                if (
                    avoid_other_builder_bots
                    and adjacent_pos != source_pos
                    and adjacent_pos != target_pos
                    and adjacent_tile.bot.id is not None
                ):
                    continue
                if (
                    adjacent_pos != target_pos
                    and not adjacent_tile._is_intrinsically_passable()
                ):
                    continue

                predecessor_by_key[adjacent_key] = current_tile
                if adjacent_key == target_key:
                    path = [target_tile]
                    walk_key = adjacent_key

                    while walk_key != source_key:
                        previous_tile = predecessor_by_key[walk_key]
                        if previous_tile is None:
                            break
                        path.append(previous_tile)
                        walk_key = (
                            previous_tile.position.x,
                            previous_tile.position.y,
                        )

                    path.reverse()
                    return path

                queue.append(adjacent_tile)

        return []

    def u_update_distances(self) -> None:
        self.dist_to_self_by_index[:] = self.inf_distances_by_index
        self.own_core_dist_by_index[:] = self.inf_distances_by_index
        self.enemy_core_dist_by_index[:] = self.inf_distances_by_index

        self.u_refresh_dist_to_self()
        self.u_refresh_own_core_dist()
        self.u_refresh_enemy_core_dist()
