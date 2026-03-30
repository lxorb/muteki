from collections import deque
from enum import Enum

from cambc import Controller, Direction, EntityType, GameConstants, Position, Team

from lib.map.tile import Tile


class SymmetryMode(Enum):
    ROTATION = "rotation"
    MIRROR_X = "mirror_x"
    MIRROR_Y = "mirror_y"


class Map:
    def __init__(self, ct: Controller):
        self.width = ct.get_map_width()
        self.height = ct.get_map_height()
        self.matrix: list[list[Tile]] = [
            [Tile(Position(x, y), self) for y in range(self.height)]
            for x in range(self.width)
        ]

        self.symmetry_mode: SymmetryMode | None = None
        self.symmetry_mode_candidates = [
            SymmetryMode.ROTATION,
            SymmetryMode.MIRROR_X,
            SymmetryMode.MIRROR_Y,
        ]
        self.core_center_pos: Position | None = None
        self.enemy_core_center_pos: Position | None = None
        self.enemy_core_center_pos_candidates: list[tuple[SymmetryMode, Position]] = []

        self.committed_path: list[Position] = []
        self.committed_path_allow_build_new_tiles = True
        self.committed_path_allow_enemy_tiles = True
        self.committed_path_destination: Position | None = None

        self.ct = ct
        self._reset_turn_state()

    def _get_resource_amount(self, resource_name: str) -> int:
        getter = getattr(self.ct, f"get_{resource_name}", None)
        if getter is None:
            return 0
        try:
            return int(getter())
        except Exception:
            return 0

    def _reset_turn_state(self) -> None:
        self.current_pos = self.ct.get_position()
        self.titanium = self._get_resource_amount("titanium")
        self.axionite = self._get_resource_amount("axionite")

        self.orthogonally_adjacent_tiles = list(
            self.u_iter_adjacent_positions(
                self.current_pos,
                consider_diagonal=False,
            )
        )
        self.diagonally_adjacent_tiles = [
            pos
            for pos in self.u_iter_adjacent_positions(self.current_pos)
            if pos not in self.orthogonally_adjacent_tiles
        ]

        self.has_enemy_bot_in_vision = False
        self.titanium_tiles_in_vision: list[Position] = []
        self.axionite_tiles_in_vision: list[Position] = []
        self.enemy_harvesters_in_sight: list[Position] = []
        self.own_harvesters_in_sight: list[Position] = []
        self.enemy_supply_targets_in_vision: list[Position] = []
        self.own_supply_targets_in_vision: list[Position] = []
        self.own_supply_links_in_sight: list[Position] = []
        self.buildings_in_vision: list[Position] = []
        self.own_missing_supply_links: list[Position] = []
        self.enemy_missing_supply_links: list[Position] = []

    @property
    def known_missing_supply_links(self) -> list[Position]:
        return self.own_missing_supply_links

    def u_get_pos_tile(self, pos: Position) -> Tile:
        return self.matrix[pos.x][pos.y]

    def _is_in_bounds(self, pos: Position) -> bool:
        return 0 <= pos.x < self.width and 0 <= pos.y < self.height

    def u_in_bounds(self, pos: Position) -> bool:
        return self._is_in_bounds(pos)

    def _in_bounds_positions(
        self,
        positions: list[Position] | tuple[Position, ...],
    ) -> list[Position]:
        seen: set[tuple[int, int]] = set()
        valid_positions: list[Position] = []
        for pos in positions:
            key = (pos.x, pos.y)
            if key in seen or not self._is_in_bounds(pos):
                continue
            seen.add(key)
            valid_positions.append(pos)
        return valid_positions

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
            if not self._is_in_bounds(next_pos):
                continue
            yield next_pos

    def u_is_on_facing_ray(
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
            self.u_is_on_facing_ray(turret_pos, direction, target_pos)
            and turret_pos.distance_squared(target_pos) <= radius_sq
        )

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
            if max(
                abs(target_pos.x - line_pos.x),
                abs(target_pos.y - line_pos.y),
            ) <= 1:
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

    def c_get_core_footprint_positions(self, center: Position) -> list[Position]:
        return self._in_bounds_positions(
            [
                Position(center.x + dx, center.y + dy)
                for dx in range(-1, 2)
                for dy in range(-1, 2)
            ]
        )

    def c_refresh_distance_field(
        self,
        seed_positions: list[Position] | tuple[Position, ...],
        attribute_name: str,
    ) -> None:
        queue: deque[Position] = deque()

        for seed_pos in self._in_bounds_positions(seed_positions):
            tile = self.matrix[seed_pos.x][seed_pos.y]
            setattr(tile, attribute_name, 0)
            queue.append(seed_pos)

        while queue:
            current_pos = queue.popleft()
            current_tile = self.matrix[current_pos.x][current_pos.y]
            current_dist = getattr(current_tile, attribute_name)

            for direction in Tile.DIRECTIONS:
                dx, dy = direction.delta()
                neighbor_pos = Position(current_pos.x + dx, current_pos.y + dy)
                if not self._is_in_bounds(neighbor_pos):
                    continue

                neighbor_tile = self.matrix[neighbor_pos.x][neighbor_pos.y]
                if not neighbor_tile._is_intrinsically_passable():
                    continue

                next_dist = current_dist + 1
                if next_dist >= getattr(neighbor_tile, attribute_name):
                    continue

                setattr(neighbor_tile, attribute_name, next_dist)
                queue.append(neighbor_pos)

    def c_refresh_core_distances(self) -> None:
        inf = 10**9
        for column in self.matrix:
            for tile in column:
                tile.own_core_dist = inf
                tile.enemy_core_dist = inf

        if self.core_center_pos is not None:
            self.c_refresh_distance_field(
                self.c_get_core_footprint_positions(self.core_center_pos),
                "own_core_dist",
            )

        if self.enemy_core_center_pos is not None:
            self.c_refresh_distance_field(
                self.c_get_core_footprint_positions(self.enemy_core_center_pos),
                "enemy_core_dist",
            )

    def u_get_core_relative_tile(self):
        if self.core_center_pos is None:
            return None

        delta_x = max(-1, min(1, self.current_pos.x - self.core_center_pos.x))
        delta_y = max(-1, min(1, self.current_pos.y - self.core_center_pos.y))
        return (delta_x, delta_y)

    def u_calc_core_center_pos(self):
        if self.core_center_pos is not None:
            return self.core_center_pos

        current_tile = self.u_get_pos_tile(self.current_pos)
        core_tile = current_tile
        if (
            core_tile.building.entity_type != EntityType.CORE
            or core_tile.building.team != self.own_team
        ):
            core_tile = None
            for building_pos in self.buildings_in_vision:
                candidate_tile = self.u_get_pos_tile(building_pos)
                if (
                    candidate_tile.building.entity_type == EntityType.CORE
                    and candidate_tile.building.team == self.own_team
                ):
                    core_tile = candidate_tile
                    break
            if core_tile is None:
                return None

        self.core_center_pos = self.ct.get_position(core_tile.building.id)
        if not self.enemy_core_center_pos_candidates:
            center = self.core_center_pos
            self.enemy_core_center_pos_candidates = [
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
        return self.core_center_pos

    def u_calc_enemy_core_center_candidates(self):
        return list(self.enemy_core_center_pos_candidates)

    def u_update_supply_information(
        self,
        visible_positions: list[Position] | None = None,
    ) -> None:
        if visible_positions is None:
            visible_positions = self.ct.get_nearby_tiles()
        for pos in visible_positions:
            tile = self.u_get_pos_tile(pos)
            tile.update_supply_targets_in_vision()
            tile.update_missing_links()

    def u_move_to(self, allow_build: bool = True):
        """
        This method is used to move to a new tile.
        If the tile is already walkable, then just move there.
        If not, you should in the base case just build a road and then walk on that tile.
        There is an attribute of the tile object that saves whether
        that tile is pointed on by a bridge or a conveyor. If that is the case,
        then instead of building a road, build either a conveyor or a bridge.
        To decide which one to build use the c_build_supplier method.
        """

    def u_build_supplier(self, pos: Position):
        """
        This method gets a position for a new supplier and is supposed to determine the target, which
        means it should determine first if a bridge or a conveyor or a splitter should be build and then
        it should determine where to point it at, i.e. where it's target should be.
        That is for conveyors an orthogonally adjacent field and for a bridge a tile with max distance not over
        the max target distance for the bridge.
        First, using the methods
        u_best_conveyor_orientation and u_best_bridge_target,
        determine the best locations for a potential bridge or conveyor
        If both are None, i.e. both do not make sense, don't build a supplier.
        If exactly one of them is none, build the other one with the corresponding target location.
        If both are not none, then you will have to decide which one makes more sense to build.
        For that purpose, you should introduce a global constant BRIDGE_PREFERRED_DIST = 5.
        If the difference of the core distance between the bridge and the bridge target is at least that high, then
        build a bridge, otherwise build a conveyor.
        """

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
        
    def u_update_vision(self):
        self._reset_turn_state()

        visible_positions = self.ct.get_nearby_tiles()
        for pos in visible_positions:
            tile = self.u_get_pos_tile(pos)
            tile.update_attributes()

        if self.core_center_pos is None:
            self.u_calc_core_center_pos()

        self.u_update_supply_information(visible_positions)
        self.c_refresh_core_distances()
