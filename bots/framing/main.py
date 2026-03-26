import atexit
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
import heapq
import os
import random
import time
from cambc import Controller, Direction, EntityType, Environment, Position, Team

INFINITE_DISTANCE = 10**9
DEBUG_OUTPUT = False
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
CARDINAL_DIRECTIONS = [
    direction
    for direction in DIRECTIONS
    if sum(abs(delta) for delta in direction.delta()) == 1
]
FLOOD_FILL_SHIFTS = [direction.delta() for direction in DIRECTIONS]
REPAIR_MIN_TITANIUM_THRESHOLD = 10
HARVESTER_BRIDGE_MIN_TITANIUM_THRESHOLD = 100
CHAIN_BRIDGE_MIN_TITANIUM_THRESHOLD = 100
HARVESTER_MIN_TITANIUM_THRESHOLD = 300
ENEMY_HARVESTER_SENTINEL_MIN_TITANIUM_THRESHOLD = 300
SCAVENGER_ACTIVE_TITANIUM_THRESHOLD = 200
HARASSMENT_SPAWN_BASE_TITANIUM_THRESHOLD = 1500
HARASSMENT_SPAWN_TITANIUM_STEP = 100
HARASSMENT_ATTACK_MIN_TITANIUM_THRESHOLD = 160
CORE_PROXIMITY_DIST = 3
LAUNCHER_DEFEND_MIN_TITANIUM_THRESHOLD = 70
BRIDGE_LONG_JUMP_CORE_DISTANCE_GAIN = 5
BUILDER_ACTION_RADIUS_SQ = 2
BB_EXPAND_TARGET_REUSE_ROUNDS = 8
BB_EXPAND_MAX_POP_ATTEMPTS = 40
BUILDER_ACTION_OFFSETS = [
    (dx, dy)
    for dx in range(-1, 2)
    for dy in range(-1, 2)
    if dx * dx + dy * dy <= BUILDER_ACTION_RADIUS_SQ
]
BUILDER_STAGING_OFFSETS = [
    (dx, dy)
    for dx, dy in BUILDER_ACTION_OFFSETS
    if not (dx == 0 and dy == 0)
]
SENTINEL_COVER_OFFSETS = [(dx, dy) for dx in range(-1, 2) for dy in range(-1, 2)]
MAX_BOTS = 999
MAX_HARVESTORS = 999
SURRENDER_AT_TURN = 3000

SENTINEL_TARGET_PRIORITY = [
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.CORE,
    EntityType.BUILDER_BOT,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.LAUNCHER,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.ROAD,
    EntityType.BARRIER,
    EntityType.MARKER,
    EntityType.FOUNDRY,
]
GUNNER_TARGET_PRIORITY = [
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.CORE,
    EntityType.BUILDER_BOT,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.LAUNCHER,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.ROAD,
    EntityType.BARRIER,
    EntityType.MARKER,
    EntityType.FOUNDRY,
]
BREACH_TARGET_PRIORITY = [
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.CORE,
    EntityType.BUILDER_BOT,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.LAUNCHER,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.ROAD,
    EntityType.BARRIER,
    EntityType.MARKER,
    EntityType.FOUNDRY,
]
HARASSMENT_ENEMY_TILE_TYPE_PRIORITY = [
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
]
HARASSMENT_ENEMY_TILE_SPECIAL_PRIORITY = [
    "feeds_enemy_turret",
    "targets_enemy_core",
    "adjacent_enemy_harvester",
    "default",
]
HARASSMENT_ENEMY_TILE_TYPE_RANK = {
    entity_type: idx
    for idx, entity_type in enumerate(HARASSMENT_ENEMY_TILE_TYPE_PRIORITY)
}
HARASSMENT_ENEMY_TILE_SPECIAL_RANK = {
    name: idx
    for idx, name in enumerate(HARASSMENT_ENEMY_TILE_SPECIAL_PRIORITY)
}
ENEMY_TURRET_TYPES = {
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
}
SUPPLY_LINK_TYPES = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
}
WALKABLE_BUILDING_TYPES = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
    EntityType.BRIDGE,
    EntityType.ROAD,
}

_PROFILE_DIR = os.environ.get("FRAMING_PROFILE_DIR")
if _PROFILE_DIR:
    import cProfile

    _PROFILE = cProfile.Profile()
    _PROFILE.enable()

    def _dump_framing_profile() -> None:
        os.makedirs(_PROFILE_DIR, exist_ok=True)
        profile_tag = os.environ.get("FRAMING_PROFILE_TAG", "framing")
        profile_path = os.path.join(
            _PROFILE_DIR,
            f"{profile_tag}_{os.getpid()}.prof",
        )
        _PROFILE.dump_stats(profile_path)

    atexit.register(_dump_framing_profile)


class BotAction(Enum):
    NONE = auto()
    SPAWN_BUILDER = auto()
    ATTACK_ENEMY_HARVESTER = auto()
    ATTACK_ENEMY_WALKABLE = auto()
    REPAIR_IF_DAMAGED = auto()
    MAINTAINER_PATROL = auto()
    HARASSMENT_SCOUT = auto()
    GUNNER_ATTACK = auto()
    COMPLETE_SUPPLY_CHAIN = auto()
    SENTINEL_ATTACK = auto()
    BREACH_ATTACK = auto()
    BUILD_HARVESTER_BRIDGE = auto()
    HOLD_BUILD_HARVESTER_BRIDGE = auto()
    BUILD_MISSING_BRIDGE = auto()
    HOLD_MISSING_BRIDGE = auto()
    DESTROY_HIJACKED_RESCHAIN = auto()
    DEFEND_CORE_PROX = auto()
    PROTECT_HARVESTER = auto()
    HOLD_PROTECT_HARVESTER = auto()
    BUILD_HARVESTER = auto()
    HOLD_TITANIUM = auto()
    BB_SCOUT = auto()
    PATROL_SUPPLY_CHAINS = auto()
    SCAVENGER_PATROL_SUPPLY_CHAINS = auto()
    LAUNCHER_DEFEND = auto()
    LAUNCHER_THROW = auto()


class CoreSpawnEvent(Enum):
    FIRST_RESOURCE_INCREASE = auto()
    ENEMY_BOT_IN_CORE_VISION = auto()


@dataclass(frozen=True, slots=True)
class CoreSpawnTurnEvent:
    turn: int


@dataclass(slots=True)
class Tile:
    position: Position
    environment: Environment
    distance_to_core: int
    building_id: int | None = None
    building_type: EntityType | None = None
    building_team: Team | None = None
    builder_bot_id: int | None = None
    builder_bot_team: Team | None = None
    is_passable: bool = True
    last_seen_round: int = -1
    last_patrolled_index: int = -1

class Map:
    def __init__(self, ct: Controller):
        """
        Create a map cache for a single bot instance.

        The map stores the latest controller, allocates tile and distance
        matrices for the full board, starts with an unknown core position, and
        remembers the friendly harvester ids that have been seen so far.
        """
        self.ct = ct
        self.width = ct.get_map_width()
        self.height = ct.get_map_height()
        self.matrix: list[list[Tile | None]] = self._create_empty_matrix()
        self.distance_matrix: list[list[int]] = self._create_distance_matrix()
        self.core_center_pos: Position | None = None
        self.known_harvester_ids: set[int] = set()
        self.known_harvesters_built = 0
        self.known_positions: list[tuple[int, int]] = []
        self.newly_known_positions: list[tuple[int, int]] = []
        self.knowledge_revision = 0
        self.supply_link_positions: set[tuple[int, int]] = set()
        self._initialise_bfs_buffers()

    def update_controller(self, ct: Controller) -> None:
        """
        Replace the controller used by this map cache.

        If the map dimensions changed, the cached matrices are rebuilt so the
        stored state matches the new board shape before future updates.
        """
        self.ct = ct

        width = ct.get_map_width()
        height = ct.get_map_height()
        if width == self.width and height == self.height:
            return

        self.width = width
        self.height = height
        self.matrix = self._create_empty_matrix()
        self.distance_matrix = self._create_distance_matrix()
        self.core_center_pos = None
        self.known_harvester_ids.clear()
        self.known_harvesters_built = 0
        self.known_positions = []
        self.newly_known_positions = []
        self.knowledge_revision += 1
        self.supply_link_positions.clear()
        self._initialise_bfs_buffers()

    def update_vision(
        self,
        visible_positions: list[Position],
        nearby_building_infos: list[tuple[int, EntityType, Team, Position]],
        nearby_unit_infos: list[tuple[int, EntityType, Team, Position]],
        current_round: int,
        own_team: Team,
    ) -> None:
        """
        Merge currently visible map information into the cache.

        Visible tiles are created or refreshed in place, and the cached
        distance-to-core values are recomputed when the known wall layout or
        visible core position changes. Friendly harvester ids seen in vision
        are remembered so the bot can track how many harvesters are known to
        have been built so far.
        """
        ct = self.ct
        matrix = self.matrix
        known_positions = self.known_positions
        known_harvester_ids = self.known_harvester_ids
        supply_link_positions = self.supply_link_positions
        get_tile_env = ct.get_tile_env
        distance_dirty = self._update_core_center_pos(nearby_building_infos, own_team)
        knowledge_changed = distance_dirty
        newly_known_positions: list[tuple[int, int]] = []
        building_at_pos: dict[tuple[int, int], tuple[int, EntityType, Team]] = {}
        builder_at_pos: dict[tuple[int, int], tuple[int, Team]] = {}

        for building_id, building_type, building_team, building_pos in nearby_building_infos:
            if building_type == EntityType.CORE:
                for dx in range(-1, 2):
                    for dy in range(-1, 2):
                        core_x = building_pos.x + dx
                        core_y = building_pos.y + dy
                        if self._is_in_bounds(core_x, core_y):
                            building_at_pos[(core_x, core_y)] = (
                                building_id,
                                building_type,
                                building_team,
                            )
                continue

            building_at_pos[(building_pos.x, building_pos.y)] = (
                building_id,
                building_type,
                building_team,
            )

        for unit_id, unit_type, unit_team, unit_pos in nearby_unit_infos:
            if unit_type != EntityType.BUILDER_BOT:
                continue
            builder_at_pos[(unit_pos.x, unit_pos.y)] = (unit_id, unit_team)

        for pos in visible_positions:
            x = pos.x
            y = pos.y
            tile = matrix[x][y]

            if tile is None:
                environment = get_tile_env(pos)
                tile = Tile(
                    position=pos,
                    environment=environment,
                    distance_to_core=INFINITE_DISTANCE,
                )
                matrix[x][y] = tile
                known_positions.append((x, y))
                newly_known_positions.append((x, y))
                knowledge_changed = True
                if environment == Environment.WALL:
                    distance_dirty = True
            tile.last_seen_round = current_round

            building_info = building_at_pos.get((x, y))
            if building_info is None:
                tile.building_id = None
                tile.building_type = None
                tile.building_team = None
            else:
                tile.building_id = building_info[0]
                tile.building_type = building_info[1]
                tile.building_team = building_info[2]

            builder_info = builder_at_pos.get((x, y))
            if builder_info is None:
                tile.builder_bot_id = None
                tile.builder_bot_team = None
            else:
                tile.builder_bot_id = builder_info[0]
                tile.builder_bot_team = builder_info[1]

            tile.is_passable = (
                tile.environment != Environment.WALL
                and (
                    tile.building_type in WALKABLE_BUILDING_TYPES
                    or (
                        tile.building_type == EntityType.CORE
                        and tile.building_team == own_team
                    )
                )
            )
            if (
                tile.building_id is not None
                and tile.building_type == EntityType.HARVESTER
                and tile.building_team == own_team
            ):
                known_harvester_ids.add(tile.building_id)

            coord = (x, y)
            if (
                tile.building_id is not None
                and tile.building_team == own_team
                and tile.building_type in SUPPLY_LINK_TYPES
            ):
                supply_link_positions.add(coord)
            else:
                supply_link_positions.discard(coord)

        self.known_harvesters_built = len(known_harvester_ids)
        self.newly_known_positions = newly_known_positions
        if knowledge_changed:
            self.knowledge_revision += 1

        if distance_dirty:
            self._refresh_distance_matrix()
            self._apply_distances_to_known_tiles()
            return

        for pos in visible_positions:
            tile = matrix[pos.x][pos.y]
            if tile is not None:
                tile.distance_to_core = self._get_distance_for_tile(tile, pos.x, pos.y)

    def _create_empty_matrix(self) -> list[list[Tile | None]]:
        """
        Build an empty tile matrix for the whole map.

        Unknown tiles are represented as `None` so the bot can distinguish
        between unseen space and a seen tile with concrete information.
        """
        return [[None for _ in range(self.height)] for _ in range(self.width)]

    def _create_distance_matrix(self) -> list[list[int]]:
        """
        Build a distance matrix initialised to infinity.

        The matrix mirrors the board dimensions and uses the shared infinite
        sentinel until flood-fill distances from the core are computed.
        """
        return [
            [INFINITE_DISTANCE for _ in range(self.height)] for _ in range(self.width)
        ]

    def _initialise_bfs_buffers(self) -> None:
        """
        Allocate reusable arrays for pathfinding traversals.

        The BFS helpers reuse these arrays each call, which avoids repeated
        large set/dict allocations in the hottest movement code paths.
        """
        cell_count = self.width * self.height
        self._bfs_token = 0
        self._bfs_seen = [0] * cell_count
        self._bfs_parent = [-1] * cell_count
        self._bfs_goal = [0] * cell_count
        self._bfs_queue = [0] * cell_count

    def _next_bfs_token(self) -> int:
        """
        Return a fresh traversal token for reusable BFS arrays.

        Tokens let the BFS helpers treat the shared arrays as logically cleared
        without paying the cost of resetting them on every call.
        """
        self._bfs_token += 1
        if self._bfs_token >= 2_000_000_000:
            self._bfs_seen = [0] * (self.width * self.height)
            self._bfs_goal = [0] * (self.width * self.height)
            self._bfs_token = 1
        return self._bfs_token

    def _to_index(self, x: int, y: int) -> int:
        """
        Flatten one map coordinate into the reusable BFS array index space.
        """
        return y * self.width + x

    def _update_core_center_pos(
        self,
        nearby_building_infos: list[tuple[int, EntityType, Team, Position]],
        own_team: Team,
    ) -> bool:
        """
        Refresh the cached allied core centre if it is currently visible.

        The method returns whether the cached value changed, which lets callers
        decide whether dependent distance information needs to be recomputed.
        """
        if self.core_center_pos is not None:
            return False
        for _, building_type, building_team, building_pos in nearby_building_infos:
            if building_type != EntityType.CORE or building_team != own_team:
                continue
            self.core_center_pos = building_pos
            return True
        return False

    def _refresh_distance_matrix(self) -> None:
        """
        Recompute flood-fill distances from the allied core.

        The fill starts from all nine core tiles and treats only permanent wall
        tiles as blocked, leaving every other known or unknown tile passable.
        """
        width = self.width
        height = self.height
        matrix = self.matrix
        distance_matrix = self._create_distance_matrix()
        self.distance_matrix = distance_matrix
        core_pos = self.core_center_pos
        if core_pos is None:
            return

        queue: deque[tuple[int, int]] = deque()
        core_x = core_pos.x
        core_y = core_pos.y
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                x = core_x + dx
                y = core_y + dy
                if x < 0 or x >= width or y < 0 or y >= height:
                    continue
                tile = matrix[x][y]
                if tile is not None and tile.environment == Environment.WALL:
                    continue

                distance_matrix[x][y] = 0
                queue.append((x, y))

        while queue:
            x, y = queue.popleft()
            next_distance = distance_matrix[x][y] + 1

            for shift_x, shift_y in FLOOD_FILL_SHIFTS:
                new_x = x + shift_x
                new_y = y + shift_y
                if new_x < 0 or new_x >= width or new_y < 0 or new_y >= height:
                    continue

                next_tile = matrix[new_x][new_y]
                if next_tile is not None and next_tile.environment == Environment.WALL:
                    continue
                if next_distance >= distance_matrix[new_x][new_y]:
                    continue

                distance_matrix[new_x][new_y] = next_distance
                queue.append((new_x, new_y))

    def _get_core_tiles(self) -> list[tuple[int, int]]:
        """
        Return the in-bounds footprint tiles of the allied core.

        The footprint is the 3x3 square centred on the cached core position, or
        an empty list if the core position is not currently known.
        """
        if self.core_center_pos is None:
            return []

        core_tiles: list[tuple[int, int]] = []
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                x = self.core_center_pos.x + dx
                y = self.core_center_pos.y + dy
                if self._is_in_bounds(x, y):
                    core_tiles.append((x, y))

        return core_tiles

    def _apply_distances_to_known_tiles(self) -> None:
        """
        Copy cached flood-fill distances onto known tile objects.

        Every seen tile receives the latest distance value so later logic can
        rely on `Tile.distance_to_core` directly without consulting the matrix.
        """
        for x, y in self.known_positions:
            tile = self.matrix[x][y]
            if tile is not None:
                tile.distance_to_core = self._get_distance_for_tile(tile, x, y)

    def _get_distance_for_tile(self, tile: Tile, x: int, y: int) -> int:
        """
        Return the effective distance-to-core for one tile.

        Permanent walls always report infinity, while every other tile uses the
        cached flood-fill distance from the distance matrix.
        """
        if tile.environment == Environment.WALL:
            return INFINITE_DISTANCE
        return self.distance_matrix[x][y]

    def _is_wall(self, x: int, y: int) -> bool:
        """
        Check whether a cached tile is a permanent wall.

        Unknown tiles are treated as non-walls so the flood fill can continue
        through unseen areas until those tiles are observed.
        """
        tile = self.matrix[x][y]
        return tile is not None and tile.environment == Environment.WALL

    def _is_in_bounds(self, x: int, y: int) -> bool:
        """
        Check whether coordinates lie inside the map bounds.

        The method uses the cached map dimensions so callers can guard matrix
        accesses without repeating the same boundary logic.
        """
        return 0 <= x < self.width and 0 <= y < self.height

    def _is_known_walkable_for_path(self, x: int, y: int, own_builder_id: int) -> bool:
        """
        Return whether a tile is currently traversable for cached-path routing.

        Unknown tiles are treated as traversable so routing can cross unseen
        space. Known walls and known non-passable building tiles are blocked.
        Builder-bot occupancy is only treated as blocking when the occupancy
        was observed in the current round, which avoids stale out-of-vision
        unit snapshots locking whole routes.
        """
        tile = self.matrix[x][y]
        if tile is None:
            return True
        if tile.environment == Environment.WALL:
            return False
        if tile.building_id is not None and not tile.is_passable:
            return False
        if (
            tile.last_seen_round == self.ct.get_current_round()
            and tile.builder_bot_id is not None
            and tile.builder_bot_id != own_builder_id
        ):
            return False
        return True

    def _is_known_currently_walkable_for_move(
        self,
        x: int,
        y: int,
        own_builder_id: int,
    ) -> bool:
        """
        Return whether a tile is a known current move tile without new roads.

        Unlike the more permissive cached path helper, this variant requires
        the tile to be known already and currently passable, so callers can use
        it for movement routines that must stay on existing walkable
        infrastructure instead of planning through future road placements.
        """
        tile = self.matrix[x][y]
        if tile is None:
            return False
        if tile.environment == Environment.WALL:
            return False
        if not tile.is_passable:
            return False
        if (
            tile.last_seen_round == self.ct.get_current_round()
            and tile.builder_bot_id is not None
            and tile.builder_bot_id != own_builder_id
        ):
            return False
        return True

    def get_next_field_for_target(self, target_pos: Position) -> Position | None:
        """
        Return the next path step toward a target tile over the cached world map.

        The search runs a grid BFS from the current bot position stored in this
        map's controller and treats unknown tiles as passable. Known walls and
        known non-passable structure tiles are blocked. The method returns the
        first tile on the shortest discovered path to `target_pos`, or `None`
        when no path can currently be found or the target lies outside the map.
        """
        start_pos = self.ct.get_position()
        start_x = start_pos.x
        start_y = start_pos.y
        target_x = target_pos.x
        target_y = target_pos.y
        own_builder_id = self.ct.get_id()
        current_round = self.ct.get_current_round()
        width = self.width
        height = self.height
        matrix = self.matrix

        if not (0 <= start_x < width and 0 <= start_y < height):
            return None
        if not (0 <= target_x < width and 0 <= target_y < height):
            return None
        if start_x == target_x and start_y == target_y:
            return start_pos

        target_tile = matrix[target_x][target_y]
        if target_tile is not None:
            if target_tile.environment == Environment.WALL:
                return None
            if target_tile.building_id is not None and not target_tile.is_passable:
                return None
            if (
                target_tile.last_seen_round == current_round
                and target_tile.builder_bot_id is not None
                and target_tile.builder_bot_id != own_builder_id
            ):
                return None

        token = self._next_bfs_token()
        seen = self._bfs_seen
        parent = self._bfs_parent
        queue = self._bfs_queue
        start_idx = start_y * width + start_x
        target_idx = target_y * width + target_x
        head = 0
        tail = 1
        queue[0] = start_idx
        seen[start_idx] = token
        parent[start_idx] = -1

        found = False
        while head < tail:
            idx = queue[head]
            head += 1
            if idx == target_idx:
                found = True
                break

            x = idx % width
            y = idx // width
            for shift_x, shift_y in FLOOD_FILL_SHIFTS:
                new_x = x + shift_x
                new_y = y + shift_y
                if new_x < 0 or new_x >= width or new_y < 0 or new_y >= height:
                    continue

                next_idx = new_y * width + new_x
                if seen[next_idx] == token:
                    continue

                next_tile = matrix[new_x][new_y]
                if next_tile is not None:
                    if next_tile.environment == Environment.WALL:
                        continue
                    if next_tile.building_id is not None and not next_tile.is_passable:
                        continue
                    if (
                        next_tile.last_seen_round == current_round
                        and next_tile.builder_bot_id is not None
                        and next_tile.builder_bot_id != own_builder_id
                    ):
                        continue

                seen[next_idx] = token
                parent[next_idx] = idx
                queue[tail] = next_idx
                tail += 1

        if not found:
            return None

        step_idx = target_idx
        while parent[step_idx] != -1 and parent[step_idx] != start_idx:
            step_idx = parent[step_idx]

        if parent[step_idx] == -1:
            return None

        return Position(step_idx % width, step_idx // width)

    def get_next_known_walkable_field_for_target(
        self,
        target_pos: Position,
    ) -> Position | None:
        """
        Return the next step toward a target using only known move-ready tiles.

        The search is restricted to cached tiles that are already passable right
        now, which makes it suitable for low-resource movement where the bot
        must not rely on building new roads. Unknown tiles are excluded.
        """
        start_pos = self.ct.get_position()
        start_x = start_pos.x
        start_y = start_pos.y
        target_x = target_pos.x
        target_y = target_pos.y
        own_builder_id = self.ct.get_id()
        current_round = self.ct.get_current_round()
        width = self.width
        height = self.height
        matrix = self.matrix

        if not (0 <= start_x < width and 0 <= start_y < height):
            return None
        if not (0 <= target_x < width and 0 <= target_y < height):
            return None
        if start_x == target_x and start_y == target_y:
            return start_pos

        target_tile = matrix[target_x][target_y]
        if target_tile is None:
            return None
        if target_tile.environment == Environment.WALL:
            return None
        if not target_tile.is_passable:
            return None
        if (
            target_tile.last_seen_round == current_round
            and target_tile.builder_bot_id is not None
            and target_tile.builder_bot_id != own_builder_id
        ):
            return None

        token = self._next_bfs_token()
        seen = self._bfs_seen
        parent = self._bfs_parent
        queue = self._bfs_queue
        start_idx = start_y * width + start_x
        target_idx = target_y * width + target_x
        head = 0
        tail = 1
        queue[0] = start_idx
        seen[start_idx] = token
        parent[start_idx] = -1

        found = False
        while head < tail:
            idx = queue[head]
            head += 1
            if idx == target_idx:
                found = True
                break

            x = idx % width
            y = idx // width
            for shift_x, shift_y in FLOOD_FILL_SHIFTS:
                new_x = x + shift_x
                new_y = y + shift_y
                if new_x < 0 or new_x >= width or new_y < 0 or new_y >= height:
                    continue

                next_idx = new_y * width + new_x
                if seen[next_idx] == token:
                    continue

                next_tile = matrix[new_x][new_y]
                if next_tile is None:
                    continue
                if next_tile.environment == Environment.WALL:
                    continue
                if not next_tile.is_passable:
                    continue
                if (
                    next_tile.last_seen_round == current_round
                    and next_tile.builder_bot_id is not None
                    and next_tile.builder_bot_id != own_builder_id
                ):
                    continue

                seen[next_idx] = token
                parent[next_idx] = idx
                queue[tail] = next_idx
                tail += 1

        if not found:
            return None

        step_idx = target_idx
        while parent[step_idx] != -1 and parent[step_idx] != start_idx:
            step_idx = parent[step_idx]

        if parent[step_idx] == -1:
            return None

        return Position(step_idx % width, step_idx // width)

    def get_next_field_for_action_range(
        self,
        target_pos: Position,
        action_radius_sq: int = 2,
    ) -> Position | None:
        """
        Return the next path step toward any tile that can act on a target.

        The search runs a grid BFS from the current bot position across the
        cached map and stops at the closest reachable tile whose distance to
        `target_pos` is within the given action radius. The target tile itself
        is excluded as a staging tile so callers can stay in range without
        stepping onto the build tile.
        """
        start_pos = self.ct.get_position()
        start_x = start_pos.x
        start_y = start_pos.y
        target_x = target_pos.x
        target_y = target_pos.y
        own_builder_id = self.ct.get_id()
        current_round = self.ct.get_current_round()
        width = self.width
        height = self.height
        matrix = self.matrix

        if not (0 <= start_x < width and 0 <= start_y < height):
            return None
        if not (0 <= target_x < width and 0 <= target_y < height):
            return None

        target_tile = matrix[target_x][target_y]
        if target_tile is not None:
            if target_tile.environment == Environment.WALL:
                return None
            if target_tile.building_id is not None and not target_tile.is_passable:
                return None
            if (
                target_tile.last_seen_round == current_round
                and target_tile.builder_bot_id is not None
                and target_tile.builder_bot_id != own_builder_id
            ):
                return None

        token = self._next_bfs_token()
        goal = self._bfs_goal
        seen = self._bfs_seen
        parent = self._bfs_parent
        queue = self._bfs_queue
        target_idx = target_y * width + target_x
        limit = int(action_radius_sq**0.5) + 1
        goal_count = 0
        for dx in range(-limit, limit + 1):
            for dy in range(-limit, limit + 1):
                if dx == 0 and dy == 0:
                    continue
                if dx * dx + dy * dy > action_radius_sq:
                    continue
                goal_x = target_x + dx
                goal_y = target_y + dy
                if goal_x < 0 or goal_x >= width or goal_y < 0 or goal_y >= height:
                    continue

                goal_tile = matrix[goal_x][goal_y]
                if goal_tile is not None:
                    if goal_tile.environment == Environment.WALL:
                        continue
                    if goal_tile.building_id is not None and not goal_tile.is_passable:
                        continue
                    if (
                        goal_tile.last_seen_round == current_round
                        and goal_tile.builder_bot_id is not None
                        and goal_tile.builder_bot_id != own_builder_id
                    ):
                        continue

                goal_idx = goal_y * width + goal_x
                goal[goal_idx] = token
                goal_count += 1

        if goal_count == 0:
            return None

        start_idx = start_y * width + start_x
        if goal[start_idx] == token:
            return start_pos

        head = 0
        tail = 1
        queue[0] = start_idx
        seen[start_idx] = token
        parent[start_idx] = -1
        goal_idx = -1

        while head < tail:
            idx = queue[head]
            head += 1
            x = idx % width
            y = idx // width

            for shift_x, shift_y in FLOOD_FILL_SHIFTS:
                new_x = x + shift_x
                new_y = y + shift_y
                if new_x < 0 or new_x >= width or new_y < 0 or new_y >= height:
                    continue

                next_idx = new_y * width + new_x
                if next_idx == target_idx or seen[next_idx] == token:
                    continue

                next_tile = matrix[new_x][new_y]
                if next_tile is not None:
                    if next_tile.environment == Environment.WALL:
                        continue
                    if next_tile.building_id is not None and not next_tile.is_passable:
                        continue
                    if (
                        next_tile.last_seen_round == current_round
                        and next_tile.builder_bot_id is not None
                        and next_tile.builder_bot_id != own_builder_id
                    ):
                        continue

                seen[next_idx] = token
                parent[next_idx] = idx
                if goal[next_idx] == token:
                    goal_idx = next_idx
                    head = tail
                    break

                queue[tail] = next_idx
                tail += 1

        if goal_idx == -1:
            return None

        step_idx = goal_idx
        while parent[step_idx] != -1 and parent[step_idx] != start_idx:
            step_idx = parent[step_idx]

        if parent[step_idx] == -1:
            return None

        return Position(step_idx % width, step_idx // width)

    def get_prox_dist(self) -> int:
        """
        Return the fixed core-proximity radius for local defense decisions.

        The radius is configured globally and is intentionally constant so core
        defense behavior stays predictable across maps.
        """
        return CORE_PROXIMITY_DIST

    def is_inside_core_proximity(
        self,
        pos: Position,
        core_center_pos: Position | None = None,
    ) -> bool:
        """
        Check whether a position lies inside the chosen core proximity radius.

        The check uses Chebyshev distance to the given core center (or the
        cached allied core center when omitted) and the radius returned
        by `get_prox_dist`.
        """
        core_pos = core_center_pos or self.core_center_pos
        if core_pos is None:
            return False

        prox_dist = self.get_prox_dist()
        return (
            max(abs(pos.x - core_pos.x), abs(pos.y - core_pos.y))
            <= prox_dist
        )

    def get_sector(self, pos: Position) -> str:
        """
        Return the map sector of a tile relative to the allied core centre.

        The map is split into `NE`, `SE`, `SW`, and `NW` sectors around the
        core centre. Axis ties follow fixed rules so every tile has exactly one
        sector: directly above -> `NE`, right -> `SE`, below -> `SW`,
        and left -> `NW`.
        """
        core_pos = self.core_center_pos
        if core_pos is None:
            core_pos = Position(self.width // 2, self.height // 2)

        dx = pos.x - core_pos.x
        dy = pos.y - core_pos.y

        if dx == 0 and dy == 0:
            return "NE"
        if dx == 0:
            return "NE" if dy < 0 else "SW"
        if dy == 0:
            return "SE" if dx > 0 else "NW"
        if dx > 0 and dy < 0:
            return "NE"
        if dx > 0 and dy > 0:
            return "SE"
        if dx < 0 and dy > 0:
            return "SW"
        return "NW"


class Bot:
    # Builder lifecycle and role selection

    def __init__(self):
        """
        Initialise persistent per-unit bot state.

        The bot stores controller-linked helpers, builder-role state, and the
        cached allied core position so this information survives across rounds.
        """
        self.core_bbs_spawned = 0  # number of builder bots spawned so far (core)
        self.core_harassment_bbs_spawned = 0
        self.core_spawn_plan_index = 0
        self.core_completed_spawn_events: set[CoreSpawnEvent] = set()
        self.core_previous_resources: tuple[int, int] | None = None
        self.ct: Controller | None = None
        self.map: Map | None = None
        self.bb_handler = None
        self.core_center_pos: Position | None = None
        self.enemy_core_pos: Position | None = None
        self.enemy_core_pos_candidates: list[Position] = []
        self.harassment_scout_target: Position | None = None
        self.init_resource_chain_complete = False
        self.init_res_scout_radius = 2
        self.init_res_scout_clockwise = True
        self.core_prox_defend_target: tuple[int, int] | None = None
        self.missing_supply_blocker_target: tuple[int, int] | None = None
        self.missing_supply_target: tuple[int, int] | None = None
        self.supply_patrol_index = 0
        self.bb_last_turn_completed = True
        self._bb_resume_from_incomplete_turn = False
        self.bb_strategy_plan_key: str | None = None
        self.bb_last_completed_strategy_index = -1
        self.bb_last_completed_strategy_method: str | None = None
        self.previous_action = BotAction.NONE
        self.last_action = BotAction.NONE
        self.turn_map_width = 0
        self.turn_map_height = 0
        self.turn_id = -1
        self.turn_round = -1
        self.turn_team: Team | None = None
        self.turn_position: Position | None = None
        self.turn_resources: tuple[int, int] = (0, 0)
        self.turn_nearby_tiles: list[Position] = []
        self.turn_nearby_buildings: list[int] = []
        self.turn_nearby_units: list[int] = []
        self.turn_nearby_building_infos: list[
            tuple[int, EntityType, Team, Position]
        ] = []
        self.turn_allied_supply_link_infos: list[
            tuple[int, EntityType, Position, Position | None]
        ] = []
        self.turn_allied_supply_output_keys: set[tuple[int, int]] = set()
        self.turn_allied_harvester_adjacent_keys: set[tuple[int, int]] = set()
        self.turn_nearby_unit_infos: list[
            tuple[int, EntityType, Team, Position]
        ] = []
        self.turn_has_enemy_bot_in_vision = False
        self.turn_type_name = "unknown"
        self._harvester_protection_cache_round = -1
        self._harvester_protection_cache: list[
            tuple[tuple[int, int, int, int, int, int, int], Position, bool]
        ] = []
        self._enemy_threat_cache_round = -1
        self._enemy_builder_action_tiles: set[tuple[int, int]] = set()
        self._enemy_turret_range_tiles: set[tuple[int, int]] = set()
        self._spatial_cache_round = -1
        self._spatial_unknown_prefix: list[list[int]] = []
        self._spatial_owned_prefix: list[list[int]] = []
        self._expand_heap: list[tuple[int, int, int, int, int]] = []
        self._expand_candidate_revision: dict[tuple[int, int], int] = {}
        self._expand_known_candidates: set[tuple[int, int]] = set()
        self._expand_frontier_candidates: set[tuple[int, int]] = set()
        self._expand_revision_counter = 0
        self._expand_cached_map_size: tuple[int, int] | None = None
        self._expand_target_coord: tuple[int, int] | None = None
        self._expand_target_round = -1
        self._enemy_core_inference_round = -1
        self._enemy_core_knowledge_revision = -1
        self._enemy_core_symmetry_modes: set[str] | None = None

    def _debug_print(self, message: str) -> None:
        """
        Print debug information only when verbose output is enabled.

        Ladder play is sensitive to output overhead, so all non-essential logs
        are routed through this helper and disabled by default.
        """
        if DEBUG_OUTPUT:
            print(message)

    def _get_entity_type_name(self, entity_type: EntityType) -> str:
        """
        Return a readable unit-type label for per-turn logging.

        Builder bots use a more specific role name elsewhere; this helper
        covers the generic entity-level names.
        """
        return entity_type.name.lower().replace("_", " ")

    def _get_action_name(self) -> str:
        """
        Return the last recorded action as a readable lowercase label.
        """
        return self.last_action.name.lower().replace("_", " ")

    def _refresh_turn_cache(self) -> None:
        """
        Cache the current turn's nearby controller data for repeated use.

        Heavy builder turns query nearby tiles, buildings, units, and resource
        totals many times. Caching those snapshots once per turn avoids a large
        amount of repeated controller traffic in hot decision methods.
        """
        ct = self.ct
        get_entity_type = ct.get_entity_type
        get_team = ct.get_team
        get_position = ct.get_position

        self.turn_round = ct.get_current_round()
        self.turn_id = ct.get_id()
        self.turn_team = ct.get_team()
        self.turn_position = ct.get_position()
        self.turn_map_width = ct.get_map_width()
        self.turn_map_height = ct.get_map_height()
        self.turn_resources = ct.get_global_resources()
        self.turn_nearby_tiles = list(ct.get_nearby_tiles())
        self.turn_nearby_buildings = list(ct.get_nearby_buildings())
        self.turn_nearby_units = list(ct.get_nearby_units())

        building_infos: list[tuple[int, EntityType, Team, Position]] = []
        building_infos_append = building_infos.append
        for building_id in self.turn_nearby_buildings:
            building_infos_append(
                (
                    building_id,
                    get_entity_type(building_id),
                    get_team(building_id),
                    get_position(building_id),
                )
            )
        self.turn_nearby_building_infos = building_infos
        allied_supply_link_infos: list[
            tuple[int, EntityType, Position, Position | None]
        ] = []
        allied_supply_output_keys: set[tuple[int, int]] = set()
        allied_harvester_adjacent_keys: set[tuple[int, int]] = set()
        turn_team = self.turn_team
        for building_id, building_type, building_team, building_pos in building_infos:
            if building_team != turn_team:
                continue
            if building_type == EntityType.HARVESTER:
                for direction in CARDINAL_DIRECTIONS:
                    neighbor_pos = building_pos.add(direction)
                    if (
                        neighbor_pos.x < 0
                        or neighbor_pos.x >= self.turn_map_width
                        or neighbor_pos.y < 0
                        or neighbor_pos.y >= self.turn_map_height
                    ):
                        continue
                    allied_harvester_adjacent_keys.add(
                        (neighbor_pos.x, neighbor_pos.y)
                    )
            if building_type not in SUPPLY_LINK_TYPES:
                continue
            output_pos = self._get_supply_link_output_pos_from_info(
                building_id,
                building_type,
                building_pos,
            )
            allied_supply_link_infos.append(
                (
                    building_id,
                    building_type,
                    building_pos,
                    output_pos,
                )
            )
            if output_pos is None:
                continue
            if (
                output_pos.x < 0
                or output_pos.x >= self.turn_map_width
                or output_pos.y < 0
                or output_pos.y >= self.turn_map_height
            ):
                continue
            allied_supply_output_keys.add((output_pos.x, output_pos.y))
        self.turn_allied_supply_link_infos = allied_supply_link_infos
        self.turn_allied_supply_output_keys = allied_supply_output_keys
        self.turn_allied_harvester_adjacent_keys = allied_harvester_adjacent_keys

        unit_infos: list[tuple[int, EntityType, Team, Position]] = []
        unit_infos_append = unit_infos.append
        for unit_id in self.turn_nearby_units:
            unit_infos_append(
                (
                    unit_id,
                    get_entity_type(unit_id),
                    get_team(unit_id),
                    get_position(unit_id),
                )
            )
        self.turn_nearby_unit_infos = unit_infos
        self._update_enemy_bot_in_vision_flag()
        self._enemy_threat_cache_round = -1
        self._spatial_cache_round = -1

    def _update_enemy_bot_in_vision_flag(self) -> None:
        """
        Cache whether at least one enemy builder bot is currently visible.

        The value is reused by multiple builder decisions (for example
        harvester holding) so that those methods can read one stable per-turn
        boolean instead of rescanning visible units repeatedly.
        """
        own_team = self.turn_team if self.turn_team is not None else self.ct.get_team()
        self.turn_has_enemy_bot_in_vision = any(
            unit_team != own_team and unit_type == EntityType.BUILDER_BOT
            for _, unit_type, unit_team, _ in self.turn_nearby_unit_infos
        )

    def _ensure_enemy_threat_cache(self) -> None:
        """
        Build O(1) enemy-threat lookup sets for the current turn.

        Bridge-targeting logic asks whether many candidate tiles are threatened
        by enemy builders or turrets. Precomputing those covered tiles once per
        turn avoids repeatedly rescanning visible enemies per candidate.
        """
        current_round = self.ct.get_current_round()
        if self._enemy_threat_cache_round == current_round:
            return

        builder_tiles: set[tuple[int, int]] = set()
        turret_tiles: set[tuple[int, int]] = set()
        own_team = self.turn_team if self.turn_team is not None else self.ct.get_team()

        for _, unit_type, unit_team, unit_pos in self.turn_nearby_unit_infos:
            if unit_team == own_team or unit_type != EntityType.BUILDER_BOT:
                continue
            for dx, dy in BUILDER_ACTION_OFFSETS:
                target_pos = Position(unit_pos.x + dx, unit_pos.y + dy)
                if self._is_in_bounds(target_pos):
                    builder_tiles.add((target_pos.x, target_pos.y))

        max_steps = max(self.ct.get_map_width(), self.ct.get_map_height())
        for building_id, building_type, building_team, building_pos in self.turn_nearby_building_infos:
            if building_team == own_team:
                continue

            if building_type == EntityType.BREACH:
                radius_sq = self.ct.get_vision_radius_sq(building_id)
                limit = int(radius_sq**0.5)
                for dx in range(-limit, limit + 1):
                    for dy in range(-limit, limit + 1):
                        if dx * dx + dy * dy > radius_sq:
                            continue
                        target_pos = Position(building_pos.x + dx, building_pos.y + dy)
                        if self._is_in_bounds(target_pos):
                            turret_tiles.add((target_pos.x, target_pos.y))
                continue

            if building_type == EntityType.GUNNER:
                direction = self.ct.get_direction(building_id)
                delta_x, delta_y = direction.delta()
                if direction == Direction.CENTRE:
                    continue
                radius_sq = self.ct.get_vision_radius_sq(building_id)
                for step in range(1, max_steps + 1):
                    target_pos = Position(
                        building_pos.x + delta_x * step,
                        building_pos.y + delta_y * step,
                    )
                    if not self._is_in_bounds(target_pos):
                        break
                    if building_pos.distance_squared(target_pos) > radius_sq:
                        break
                    turret_tiles.add((target_pos.x, target_pos.y))
                continue

            if building_type == EntityType.SENTINEL:
                direction = self.ct.get_direction(building_id)
                delta_x, delta_y = direction.delta()
                if direction == Direction.CENTRE:
                    continue
                for step in range(max_steps + 1):
                    line_pos = Position(
                        building_pos.x + delta_x * step,
                        building_pos.y + delta_y * step,
                    )
                    if building_pos.distance_squared(line_pos) > 32:
                        break
                    if not self._is_in_bounds(line_pos):
                        break
                    for off_x, off_y in SENTINEL_COVER_OFFSETS:
                        target_pos = Position(line_pos.x + off_x, line_pos.y + off_y)
                        if self._is_in_bounds(target_pos):
                            turret_tiles.add((target_pos.x, target_pos.y))

        self._enemy_builder_action_tiles = builder_tiles
        self._enemy_turret_range_tiles = turret_tiles
        self._enemy_threat_cache_round = current_round

    def _ensure_spatial_scan_cache(self) -> bool:
        """
        Build prefix sums for unknown space and owned infrastructure this turn.

        The scavenger scout repeatedly scores map positions by local unknown
        area and friendly build density. Prefix sums turn those radius queries
        into O(1) operations instead of nested per-tile neighborhood scans.
        """
        if self.map is None:
            return False

        current_round = self.ct.get_current_round()
        if self._spatial_cache_round == current_round:
            return True

        own_team = self.turn_team if self.turn_team is not None else self.ct.get_team()
        width = self.map.width
        height = self.map.height
        matrix = self.map.matrix
        unknown_prefix = [[0] * (width + 1) for _ in range(height + 1)]
        owned_prefix = [[0] * (width + 1) for _ in range(height + 1)]

        for y in range(height):
            row_unknown = 0
            row_owned = 0
            unknown_row = unknown_prefix[y + 1]
            owned_row = owned_prefix[y + 1]
            prev_unknown_row = unknown_prefix[y]
            prev_owned_row = owned_prefix[y]
            for x in range(width):
                tile = matrix[x][y]
                row_unknown += 1 if tile is None else 0
                row_owned += 1 if (
                    tile is not None
                    and (
                        tile.building_team == own_team
                        or tile.builder_bot_team == own_team
                    )
                ) else 0
                unknown_row[x + 1] = prev_unknown_row[x + 1] + row_unknown
                owned_row[x + 1] = prev_owned_row[x + 1] + row_owned

        self._spatial_unknown_prefix = unknown_prefix
        self._spatial_owned_prefix = owned_prefix
        self._spatial_cache_round = current_round
        return True

    def _query_prefix_sum(
        self,
        prefix: list[list[int]],
        center_pos: Position,
        radius: int,
    ) -> int:
        """
        Return the inclusive square-prefix sum around a centre position.
        """
        if self.map is None:
            return 0

        min_x = max(0, center_pos.x - radius)
        min_y = max(0, center_pos.y - radius)
        max_x = min(self.map.width - 1, center_pos.x + radius)
        max_y = min(self.map.height - 1, center_pos.y + radius)
        return (
            prefix[max_y + 1][max_x + 1]
            - prefix[min_y][max_x + 1]
            - prefix[max_y + 1][min_x]
            + prefix[min_y][min_x]
        )

    def initialize_bb(self):
        """
        Initialise builder-specific cached state on its first turn.

        This creates the builder-local map cache, performs an immediate vision
        update, and adopts the cached core position when it is available.
        """
        self.map = Map(self.ct)
        self.map.update_vision(
            self.turn_nearby_tiles,
            self.turn_nearby_building_infos,
            self.turn_nearby_unit_infos,
            self.turn_round,
            self.turn_team if self.turn_team is not None else self.ct.get_team(),
        )
        if self.map.core_center_pos is not None:
            self.core_center_pos = self.map.core_center_pos

    def update_bb_map(self):
        """
        Refresh the builder-local map cache for the current turn.

        The method initialises the cache on first use, otherwise swaps in the
        latest controller and updates visible map information in place. It also
        refreshes the cached enemy-bot-in-vision flag at the start of map
        fetching and prints the time spent on the map update for this unit and
        turn.
        """
        map_update_start = time.perf_counter_ns()
        self._update_enemy_bot_in_vision_flag()
        if self.map is None:
            self.initialize_bb()
        else:
            self.map.update_controller(self.ct)
            self.map.update_vision(
                self.turn_nearby_tiles,
                self.turn_nearby_building_infos,
                self.turn_nearby_unit_infos,
                self.turn_round,
                self.turn_team if self.turn_team is not None else self.ct.get_team(),
            )
        if self.map.core_center_pos is not None:
            self.core_center_pos = self.map.core_center_pos
        map_update_elapsed = time.perf_counter_ns() - map_update_start
        self._debug_print(
            f"Unit {self.ct.get_id()} map update took {map_update_elapsed / 1000}mus"
        )

    def get_initial_bb_handler(self):
        """
        Choose the builder's initial role handler.

        The builder infers its initial role from the core-footprint tile it was
        spawned on. If that mapping cannot be resolved (for example after an
        unusual reset state), the method falls back to round-based
        initialisation using callable entries from `INITIAL_BB`, with
        scavenger as the final default.
        """
        if self.core_center_pos is None:
            self.find_core_center()
        if self.core_center_pos is not None:
            current_pos = self.ct.get_position()
            offset = (
                current_pos.x - self.core_center_pos.x,
                current_pos.y - self.core_center_pos.y,
            )
            assigned_handler = CORE_TILE_BB_ROLE.get(offset)
            if callable(assigned_handler):
                return assigned_handler.__get__(self, type(self))

        initial_builder_handlers = [entry for entry in INITIAL_BB if callable(entry)]
        round_index = self.ct.get_current_round() - 1
        if 0 <= round_index < len(initial_builder_handlers):
            return initial_builder_handlers[round_index].__get__(self, type(self))
        return Bot.run_bb_scavenger.__get__(self, type(self))

    def get_bb_handler_name(self) -> str:
        """
        Return the current builder role as a short human-readable label.

        The method maps the active bound handler to the role name used in logs
        so builder turns can announce whether they are acting as maintainers,
        scavengers, harassment units, and so on.
        """
        if self.bb_handler is None:
            return "scavenger"

        handler_func = getattr(self.bb_handler, "__func__", self.bb_handler)
        handler_names = {
            Bot.run_bb_init_res: "init resource",
            Bot.run_bb_scavenger: "scavenger",
            Bot.run_bb_harassment: "harassment",
            Bot.run_bb_defender: "defender",
        }
        return handler_names.get(handler_func, handler_func.__name__)

    def _reset_bb_strategy_progress(self, plan_key: str | None = None) -> None:
        """
        Reset stored progress for ordered builder strategy execution.

        The progress marker tracks which strategy method was last completed so
        a builder can resume from the next entry after a timed-out turn.
        """
        self.bb_strategy_plan_key = plan_key
        self.bb_last_completed_strategy_index = -1
        self.bb_last_completed_strategy_method = None

    def _run_bb_strategy_plan(self, plan_key: str, steps) -> bool:
        """
        Execute ordered builder strategy steps with timeout-resume support.

        Steps are `(name, callable)` pairs. If the previous turn ended before
        the role handler returned, the executor resumes at the step after the
        last completed one; otherwise it starts from the beginning.
        """
        if self.bb_strategy_plan_key != plan_key:
            self._reset_bb_strategy_progress(plan_key)

        if not steps:
            self._reset_bb_strategy_progress(plan_key)
            return False

        start_index = 0
        if self._bb_resume_from_incomplete_turn:
            start_index = self.bb_last_completed_strategy_index + 1

        if start_index < 0 or start_index >= len(steps):
            start_index = 0

        for index in range(start_index, len(steps)):
            step_name, step_func = steps[index]
            acted = bool(step_func())
            self.bb_last_completed_strategy_index = index
            self.bb_last_completed_strategy_method = step_name
            if acted:
                return True

        return False

    def find_core_center(self) -> Position | None:
        """
        Locate and cache the allied core centre.

        The lookup prefers the builder-local map cache and falls back to nearby
        controller queries when the cache has not learned the core position yet.
        """
        if self.map is not None and self.map.core_center_pos is not None:
            self.core_center_pos = self.map.core_center_pos
            return self.core_center_pos

        current_pos = self.ct.get_position()
        building_id = self.ct.get_tile_building_id(current_pos)
        if (
            building_id is not None
            and self.ct.get_entity_type(building_id) == EntityType.CORE
            and self.ct.get_team(building_id) == self.ct.get_team()
        ):
            self.core_center_pos = self.ct.get_position(building_id)
            return self.core_center_pos

        for building_id in self.ct.get_nearby_buildings():
            if (
                self.ct.get_entity_type(building_id) == EntityType.CORE
                and self.ct.get_team(building_id) == self.ct.get_team()
            ):
                self.core_center_pos = self.ct.get_position(building_id)
                return self.core_center_pos

        return None

    def get_ns_elapsed(self):
        """
        Return the nanoseconds spent so far in the current turn.

        The value is measured from the timestamp captured at the start of
        `run`, which makes it useful for lightweight runtime instrumentation.
        """
        return time.perf_counter_ns() - self.t_start

    def get_ns_remaining(self):
        """
        Estimate the remaining local nanosecond budget for the turn.

        The estimate is based on a 2 ms target and the same per-turn start time
        used by the elapsed-time helper.
        """
        return 2_000_000 - time.perf_counter_ns() + self.t_start


    # Turn entrypoints

    def run(self, ct: Controller) -> None:
        """
        Execute one turn for the current unit.

        The method stores the current controller, checks the development
        surrender hook, and dispatches to the unit-type-specific handler.
        """
        self.ct = ct
        self.t_start = time.perf_counter_ns()
        self._refresh_turn_cache()
        etype = self.ct.get_entity_type()
        self.turn_type_name = self._get_entity_type_name(etype)
        self.previous_action = self.last_action
        self.last_action = BotAction.NONE

        try:
            if self.surrender():
                return

            match etype:
                case EntityType.CORE:
                    self.run_core()
                case EntityType.BUILDER_BOT:
                    self.run_bb()
                case EntityType.GUNNER:
                    self.run_gunner()
                case EntityType.SENTINEL:
                    self.run_sentinel()
                case EntityType.BREACH:
                    self.run_breach()
                case EntityType.LAUNCHER:
                    self.run_launcher()
        finally:
            elapsed_mus = self.get_ns_elapsed() / 1000
            if etype == EntityType.BUILDER_BOT:
                print(
                    f"Unit {self.ct.get_id()} type: {self.turn_type_name} "
                    f"action: {self._get_action_name()} "
                    f"turn took {elapsed_mus}mus"
                )
            else:
                self._debug_print(
                    f"Unit {self.ct.get_id()} turn took {elapsed_mus}mus"
                )

    def _update_core_spawn_events(self) -> None:
        """
        Refresh core spawn-event flags from the current global resource state.

        Events are evaluated incrementally from turn to turn. The
        `FIRST_RESOURCE_INCREASE` event fires the first time either team
        resource increases compared to the previous core turn.
        `ENEMY_BOT_IN_CORE_VISION` fires once an enemy unit is visible to the
        core.
        """
        own_team = self.ct.get_team()
        for unit_id in self.ct.get_nearby_units():
            if self.ct.get_team(unit_id) == own_team:
                continue
            self.core_completed_spawn_events.add(
                CoreSpawnEvent.ENEMY_BOT_IN_CORE_VISION
            )
            break

        current_resources = self.ct.get_global_resources()
        if self.core_previous_resources is None:
            self.core_previous_resources = current_resources
            return

        previous_ti, previous_ax = self.core_previous_resources
        current_ti, current_ax = current_resources
        if current_ti > previous_ti or current_ax > previous_ax:
            self.core_completed_spawn_events.add(CoreSpawnEvent.FIRST_RESOURCE_INCREASE)
        self.core_previous_resources = current_resources

    def _advance_core_spawn_plan_until_next_builder(self) -> bool:
        """
        Advance scheduled event checkpoints and report whether spawning may continue.

        The spawn plan can contain both builder-role entries and event markers.
        Completed events are skipped. If the next pending entry is an unmet
        event, the core must wait and returns `False`.
        """
        while self.core_spawn_plan_index < len(INITIAL_BB):
            plan_entry = INITIAL_BB[self.core_spawn_plan_index]

            if isinstance(plan_entry, CoreSpawnTurnEvent):
                if self.ct.get_current_round() >= plan_entry.turn:
                    self.core_spawn_plan_index += 1
                    continue
                return False

            if isinstance(plan_entry, CoreSpawnEvent):
                if plan_entry in self.core_completed_spawn_events:
                    self.core_spawn_plan_index += 1
                    continue
                return False

            if callable(plan_entry):
                return True

            self.core_spawn_plan_index += 1

        return True

    def run_core(self):
        """
        Execute the core's builder spawn schedule with event checkpoints.

        The core follows `INITIAL_BB` as a spawn plan, where role entries can
        be interleaved with event markers. Before spawning roles that come
        after an event marker, the core waits until that event has fired.
        Harassment spawning by dynamic titanium threshold is evaluated
        independently and can override the initial plan for that turn. Outside
        of `INITIAL_BB`, the core only spawns harassment builders.
        """
        if self.core_bbs_spawned >= MAX_BOTS:
            return

        self._update_core_spawn_events()
        titanium, _ = self.ct.get_global_resources()
        harassment_threshold = (
            HARASSMENT_SPAWN_BASE_TITANIUM_THRESHOLD
            + self.core_harassment_bbs_spawned * HARASSMENT_SPAWN_TITANIUM_STEP
        )
        force_harassment_spawn = titanium >= harassment_threshold

        assigned_handler = Bot.run_bb_harassment
        should_spawn_from_initial_plan = False
        if force_harassment_spawn:
            assigned_handler = Bot.run_bb_harassment
        else:
            if not self._advance_core_spawn_plan_until_next_builder():
                return

            should_spawn_from_initial_plan = (
                self.core_spawn_plan_index < len(INITIAL_BB)
            )
            if not should_spawn_from_initial_plan:
                return

            if should_spawn_from_initial_plan:
                plan_entry = INITIAL_BB[self.core_spawn_plan_index]
                if callable(plan_entry):
                    assigned_handler = plan_entry

        core_pos = self.ct.get_position()
        preferred_offsets = [
            offset
            for offset, role_handler in CORE_TILE_BB_ROLE.items()
            if role_handler == assigned_handler
        ]
        if not preferred_offsets:
            return

        preferred_spawn_positions: list[Position] = []
        for dx, dy in preferred_offsets:
            spawn_pos = Position(core_pos.x + dx, core_pos.y + dy)
            if not self._is_in_bounds(spawn_pos):
                continue
            preferred_spawn_positions.append(spawn_pos)

        random.shuffle(preferred_spawn_positions)
        for spawn_pos in preferred_spawn_positions:
            if not self.ct.can_spawn(spawn_pos):
                continue

            self.ct.spawn_builder(spawn_pos)
            self.core_bbs_spawned += 1
            if assigned_handler == Bot.run_bb_harassment:
                self.core_harassment_bbs_spawned += 1
            if should_spawn_from_initial_plan:
                self.core_spawn_plan_index += 1
            self.last_action = BotAction.SPAWN_BUILDER
            return

    def run_bb(self):
        """
        Execute the builder bot's turn logic.

        The method ensures the role handler is initialised, prints the builder
        role for this turn, refreshes the builder-local map cache, and then
        runs the selected handler. It also tracks whether the previous turn
        finished, allowing the strategy executor to resume after timeouts.
        """
        self.update_bb_map()

        if self.core_center_pos is None:
            self.find_core_center()

        if self.bb_handler is None:
            self.bb_handler = self.get_initial_bb_handler()

        self.turn_type_name = self.get_bb_handler_name()

        self._bb_resume_from_incomplete_turn = not self.bb_last_turn_completed
        if not self._bb_resume_from_incomplete_turn:
            self.bb_last_completed_strategy_index = -1
            self.bb_last_completed_strategy_method = None

        self.bb_last_turn_completed = False
        self.bb_handler()
        self.bb_last_turn_completed = True

    def _has_visible_harvester_bridge_chain_to_core(self) -> bool:
        """
        Check whether a visible allied harvester supply chain reaches the core.

        The check builds a directed graph over currently visible allied bridge
        and conveyor links (including armoured conveyors) by following each
        link's output tile. Any chain that starts at a supply link orthogonally
        adjacent to a visible allied harvester and ends on a core footprint
        tile counts as an established initial resource chain.
        """
        own_team = self.turn_team if self.turn_team is not None else self.ct.get_team()
        if self.core_center_pos is None:
            self.find_core_center()
        if self.core_center_pos is None:
            return False

        core_tiles = {
            (pos.x, pos.y)
            for pos in self._get_core_footprint_positions(self.core_center_pos)
        }
        if not core_tiles:
            return False

        harvester_positions: set[tuple[int, int]] = set()
        logistics_links: dict[int, tuple[Position, Position]] = {}
        logistics_pos_to_id: dict[tuple[int, int], int] = {}
        logistics_types = {
            EntityType.BRIDGE,
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
        }

        for building_id, building_type, building_team, link_pos in self.turn_nearby_building_infos:
            if building_team != own_team:
                continue

            if building_type == EntityType.HARVESTER:
                harvester_positions.add((link_pos.x, link_pos.y))
                continue

            if building_type not in logistics_types:
                continue

            output_pos = self._get_supply_link_output_pos(building_id)
            if output_pos is None:
                continue
            logistics_links[building_id] = (link_pos, output_pos)
            logistics_pos_to_id[(link_pos.x, link_pos.y)] = building_id

        if not logistics_links:
            return False

        if not harvester_positions:
            return False

        start_link_ids: list[int] = []
        for link_id, (link_pos, _) in logistics_links.items():
            for direction in CARDINAL_DIRECTIONS:
                adjacent_pos = link_pos.add(direction)
                if (adjacent_pos.x, adjacent_pos.y) in harvester_positions:
                    start_link_ids.append(link_id)
                    break

        if not start_link_ids:
            return False

        queue = deque(start_link_ids)
        visited: set[int] = set()
        while queue:
            link_id = queue.popleft()
            if link_id in visited:
                continue
            visited.add(link_id)

            _, output_pos = logistics_links[link_id]
            target_key = (output_pos.x, output_pos.y)
            if target_key in core_tiles:
                return True

            next_link_id = logistics_pos_to_id.get(target_key)
            if next_link_id is not None and next_link_id not in visited:
                queue.append(next_link_id)

        return False

    def _switch_init_res_to_scavenger_if_ready(self, run_now: bool = False) -> bool:
        """
        Promote the initial-resource builder role to scavenger once ready.

        The first-resource role is considered complete as soon as a visible
        allied harvester supply chain reaches the allied core. After that, the
        builder permanently switches its handler to `run_bb_scavenger`. When
        `run_now` is true, the scavenger handler is executed immediately.
        """
        if not self.init_resource_chain_complete:
            self._refresh_turn_cache()
            self.init_resource_chain_complete = (
                self._has_visible_harvester_bridge_chain_to_core()
            )
        if not self.init_resource_chain_complete:
            return False

        handler_func = getattr(self.bb_handler, "__func__", self.bb_handler)
        if handler_func != Bot.run_bb_scavenger:
            self.bb_handler = Bot.run_bb_scavenger.__get__(self, type(self))
            self._debug_print("initial resource chain complete, switching to scavenger")

        if not run_now:
            return False

        self.bb_handler()
        return True

    def _run_init_res_strategy_step(self, acted: bool) -> bool:
        """
        Finalise one init-resource strategy step and recheck completion.

        When a step executes, the method immediately re-evaluates whether the
        initial resource chain is complete so the role can switch promptly.
        """
        if not acted:
            return False
        self._switch_init_res_to_scavenger_if_ready(run_now=False)
        return True

    def run_bb_init_res(self):
        """
        Bootstrap the first resource flow, then hand over to scavenger logic.

        This role focuses on establishing an early harvester supply chain to
        the allied core by prioritising harvester-adjacent links, chain-gap
        continuation, and supportive hold behavior. As soon as a visible
        harvester supply chain reaches the core footprint, the builder
        switches permanently to the regular scavenger role.
        """
        if self._switch_init_res_to_scavenger_if_ready(run_now=True):
            return

        titanium, _ = self.turn_resources

        def build_harvester_supply_link_step() -> bool:
            return self._run_init_res_strategy_step(
                self.build_harvester_supply_link(hold=True)
            )

        def protect_harvester_step() -> bool:
            return self._run_init_res_strategy_step(
                self.protect_harvester(hold=True)
            )

        def complete_supply_chain_step() -> bool:
            if titanium < CHAIN_BRIDGE_MIN_TITANIUM_THRESHOLD:
                return False
            return self._run_init_res_strategy_step(self.complete_supply_chain())

        def build_missing_supply_link_step() -> bool:
            return self._run_init_res_strategy_step(
                self.build_missing_supply_link(hold=True)
            )

        def build_harvester_step() -> bool:
            return self._run_init_res_strategy_step(self.build_harvester(hold=True))

        def init_res_scout_step() -> bool:
            return self._run_init_res_strategy_step(self.init_res_scout())

        steps = [
            ("build_harvester_supply_link", build_harvester_supply_link_step),
            ("protect_harvester", protect_harvester_step),
            ("complete_supply_chain", complete_supply_chain_step),
            ("build_missing_supply_link", build_missing_supply_link_step),
            ("build_harvester", build_harvester_step),
            # ("init_res_scout", init_res_scout_step),
            ("bb_expand", self.bb_expand)
        ]
        if self._run_bb_strategy_plan("init_res", steps):
            return

        self._switch_init_res_to_scavenger_if_ready(run_now=True)

    def run_bb_scavenger(self):
        """
        Execute the scavenger builder role for the current turn.

        The scavenger currently shares the maintainer's disruption and logistics
        checks, then also considers expanding resource extraction. When team
        titanium is low, it stops aggressive scouting and instead patrols the
        known allied supply network without laying new roads. If it has already
        found a free visible titanium tile or an unfinished supply-link gap but
        cannot yet act on it, the scavenger reuses the corresponding builder
        action in hold mode instead of recomputing the same search separately.
        """
        titanium, _ = self.turn_resources

        def complete_supply_chain_step() -> bool:
            if titanium < CHAIN_BRIDGE_MIN_TITANIUM_THRESHOLD:
                return False
            return self.complete_supply_chain()

        def attack_enemy_harvester_step() -> bool:
            if titanium < ENEMY_HARVESTER_SENTINEL_MIN_TITANIUM_THRESHOLD:
                return False
            return self.attack_enemy_harvester()

        def fallback_step() -> bool:
            if titanium < SCAVENGER_ACTIVE_TITANIUM_THRESHOLD:
                return self.scavenger_patrol_supply_chains()
            return self.bb_expand()

        steps = [
            ("destroy_hijacked_reschain", self.destroy_hijacked_reschain),
            (
                "build_harvester_supply_link",
                lambda: self.build_harvester_supply_link(hold=True),
            ),
            ("protect_harvester", lambda: self.protect_harvester(hold=True)),
            ("complete_supply_chain", complete_supply_chain_step),
            ("build_missing_supply_link", lambda: self.build_missing_supply_link(hold=True)),
            ("defend_core_prox", self.defend_core_prox),
            ("attack_enemy_harvester", attack_enemy_harvester_step),
            ("build_harvester", lambda: self.build_harvester(hold=True)),
            (
                "scavenger_patrol_supply_chains"
                if titanium < SCAVENGER_ACTIVE_TITANIUM_THRESHOLD
                else "bb_expand",
                fallback_step,
            ),
        ]
        self._run_bb_strategy_plan("scavenger", steps)

    def run_bb_harassment(self):
        """
        Execute the harassment builder role for the current turn.

        Harassment prioritises targeted economic disruption first.

        The action order is:
        1) attack enemy harvester
        2) build supplied sentinel
        3) attack high-priority enemy walkable logistics tiles
        4) move toward the inferred enemy core area
        """
        self.get_enemy_core_pos()
        steps = [
            ("attack_enemy_harvester", self.attack_enemy_harvester),
            ("build_supplied_sentinel", self.build_supplied_sentinel),
            ("attack_enemy_walkable", self.attack_enemy_walkable),
            ("harassment_scout", self.harassment_scout),
        ]
        self._run_bb_strategy_plan("harassment", steps)

    def run_bb_defender(self):
        """
        Execute the defender builder role for the current turn.

        The defender first reacts to enemy builder bots that stand on friendly
        logistics tiles by trying to place a nearby launcher, then falls back
        to patrolling known allied supply-chain structures.
        """
        self._stamp_supply_patrol_coverage()
        steps = [
            ("launcher_defend", self.launcher_defend),
            ("patrol_supply_chains", self.patrol_supply_chains),
        ]
        self._run_bb_strategy_plan("defender", steps)

    def run_gunner(self):
        """
        Fire the gunner at the highest-priority visible target it can hit.

        The exact category order is configured by `GUNNER_TARGET_PRIORITY`.
        Since a gunner can only attack its current legal target tile, the
        helper naturally respects the gunner's facing and closest-tile rules by
        filtering through `can_fire()` first.
        """
        target_pos = self._get_best_fire_target(GUNNER_TARGET_PRIORITY)
        if target_pos is None:
            return

        self.ct.fire(target_pos)
        self.last_action = BotAction.GUNNER_ATTACK

    def run_sentinel(self):
        """
        Fire the sentinel at the highest-priority visible enemy target.

        The exact category order is configured by `SENTINEL_TARGET_PRIORITY`.
        The sentinel scans currently visible tiles, keeps only those it can
        legally fire at right now, and chooses the closest tile from the first
        matching priority bucket.
        """
        target_pos = self._get_best_fire_target(SENTINEL_TARGET_PRIORITY)
        if target_pos is None:
            return

        self.ct.fire(target_pos)
        self.last_action = BotAction.SENTINEL_ATTACK

    def run_breach(self):
        """
        Fire the breach at the highest-priority visible target it can hit safely.

        The category order is configured by `BREACH_TARGET_PRIORITY`. A target
        is only considered if the breach can legally fire at it and the 3x3
        splash area would not damage allied buildings or builder bots.
        """
        target_pos = self._get_best_fire_target(
            BREACH_TARGET_PRIORITY,
            safety_check=self._is_breach_target_safe,
        )
        if target_pos is None:
            return

        self.ct.fire(target_pos)
        self.last_action = BotAction.BREACH_ATTACK

    def run_launcher(self):
        """
        Throw an enemy builder bot to a road tile chosen by defense priority.

        The launcher only throws enemy builder bots and only to road tiles.
        If any legal throw destination is targetable by at least one visible
        allied turret, such covered road tiles are preferred; among them it
        chooses the one farthest from the allied core. If none are turret-
        covered, it falls back to the farthest legal road tile from core.
        """
        if self.core_center_pos is None:
            self.find_core_center()
        core_ref_pos = self.core_center_pos or self.ct.get_position()

        own_team = self.ct.get_team()
        launcher_pos = self.ct.get_position()
        enemy_builder_positions: list[Position] = []
        for unit_id in self.ct.get_nearby_units():
            if self.ct.get_team(unit_id) == own_team:
                continue
            if self.ct.get_entity_type(unit_id) != EntityType.BUILDER_BOT:
                continue
            enemy_builder_positions.append(self.ct.get_position(unit_id))

        if not enemy_builder_positions:
            return

        road_targets: list[Position] = []
        for target_pos in self.ct.get_nearby_tiles(self.ct.get_vision_radius_sq()):
            building_id = self.ct.get_tile_building_id(target_pos)
            if building_id is None:
                continue
            if self.ct.get_entity_type(building_id) != EntityType.ROAD:
                continue
            road_targets.append(target_pos)

        if not road_targets:
            return

        own_turret_ids: list[int] = []
        for building_id in self.ct.get_nearby_buildings():
            if self.ct.get_team(building_id) != own_team:
                continue
            building_type = self.ct.get_entity_type(building_id)
            if building_type not in {
                EntityType.GUNNER,
                EntityType.SENTINEL,
                EntityType.BREACH,
            }:
                continue
            own_turret_ids.append(building_id)

        def is_targetable_by_own_turret(target_pos: Position) -> bool:
            for turret_id in own_turret_ids:
                turret_pos = self.ct.get_position(turret_id)
                if (
                    turret_pos.distance_squared(target_pos)
                    > self.ct.get_vision_radius_sq(turret_id)
                ):
                    continue

                turret_type = self.ct.get_entity_type(turret_id)
                if turret_type == EntityType.SENTINEL:
                    turret_direction = self.ct.get_direction(turret_id)
                    if self._sentinel_direction_covers_target(
                        turret_pos,
                        turret_direction,
                        target_pos,
                    ):
                        return True
                    continue

                return True

            return False

        legal_launches: list[
            tuple[tuple[int, int, int, int, int, int], Position, Position, bool]
        ] = []
        for bot_pos in enemy_builder_positions:
            for target_pos in road_targets:
                if not self.ct.can_launch(bot_pos, target_pos):
                    continue

                candidate_key = (
                    -core_ref_pos.distance_squared(target_pos),
                    launcher_pos.distance_squared(bot_pos),
                    target_pos.x,
                    target_pos.y,
                    bot_pos.x,
                    bot_pos.y,
                )
                legal_launches.append(
                    (
                        candidate_key,
                        bot_pos,
                        target_pos,
                        is_targetable_by_own_turret(target_pos),
                    )
                )

        if not legal_launches:
            return

        prefer_turret_covered_target = any(candidate[3] for candidate in legal_launches)
        best_launch = min(
            legal_launches,
            key=lambda candidate: (
                1 if prefer_turret_covered_target and not candidate[3] else 0,
                candidate[0],
            ),
        )

        _, bot_pos, target_pos, _ = best_launch
        self.ct.launch(bot_pos, target_pos)
        self.last_action = BotAction.LAUNCHER_THROW

    def surrender(self) -> bool:
        """
        Stop normal play once the configured surrender turn has been reached.

        Before `SURRENDER_AT_TURN`, the method returns immediately and lets the
        unit act normally. Once the threshold is reached, the core resigns at
        once and every other unit simply stops taking normal actions. Builder
        bots never use own-tile attacks here, which avoids any possibility of
        them deleting the structure under themselves or otherwise appearing to
        self-destruct.
        """
        if self.ct.get_current_round() < SURRENDER_AT_TURN:
            return False

        entity_type = self.ct.get_entity_type()
        if entity_type == EntityType.CORE:
            self.ct.resign()
            return True

        return True


    # Shared state and positioning helpers

    def stands_on_core(self) -> bool:
        """
        Check whether this unit is standing on the allied core footprint.

        The test compares the current position against the cached 3x3 area
        around the allied core centre.
        """
        if self.core_center_pos is None:
            return False

        pos = self.ct.get_position()
        return (
            self.core_center_pos.x - 1 <= pos.x <= self.core_center_pos.x + 1
            and self.core_center_pos.y - 1 <= pos.y <= self.core_center_pos.y + 1
        )

    def _is_in_bounds(self, pos: Position) -> bool:
        """
        Check whether a position lies inside the current map bounds.

        This keeps the common controller-sized bounds check in one place so
        movement, targeting, and cached-map lookups use the same guard.
        """
        if self.map is not None:
            return 0 <= pos.x < self.map.width and 0 <= pos.y < self.map.height
        if self.turn_map_width > 0 and self.turn_map_height > 0:
            return 0 <= pos.x < self.turn_map_width and 0 <= pos.y < self.turn_map_height
        return 0 <= pos.x < self.ct.get_map_width() and 0 <= pos.y < self.ct.get_map_height()

    def _get_known_map_tile(self, pos: Position) -> Tile | None:
        """
        Return the cached tile object for an in-bounds position if one exists.

        Unknown positions or bots without a local map cache return `None`, so
        callers can safely use this helper before reading cached tile data.
        """
        if self.map is None:
            return None
        if (
            pos.x < 0
            or pos.x >= self.map.width
            or pos.y < 0
            or pos.y >= self.map.height
        ):
            return None
        return self.map.matrix[pos.x][pos.y]

    def _is_supply_link_type(self, entity_type: EntityType | None) -> bool:
        """
        Return whether a type is one of the chain-carrying logistics links.

        Bridges and both conveyor variants all count as supply links whenever
        chain construction checks whether a path already continues onward.
        """
        return entity_type in SUPPLY_LINK_TYPES

    def _is_allied_supply_link_tile(self, tile: Tile | None) -> bool:
        """
        Return whether a cached tile currently holds an allied supply link.

        This helper keeps bridge and conveyor handling consistent throughout
        the supply-chain construction code.
        """
        return (
            tile is not None
            and tile.building_team == self.ct.get_team()
            and tile.building_type in SUPPLY_LINK_TYPES
        )

    def _get_supply_link_output_pos(self, building_id: int) -> Position | None:
        """
        Return the output tile of a visible bridge or conveyor building.

        Bridges output to their configured target tile, while conveyors and
        armoured conveyors output one tile forward in their facing direction.
        Non-link buildings return `None`.
        """
        return self._get_supply_link_output_pos_from_info(
            building_id,
            self.ct.get_entity_type(building_id),
            self.ct.get_position(building_id),
        )

    def _get_supply_link_output_pos_from_info(
        self,
        building_id: int,
        building_type: EntityType,
        building_pos: Position,
    ) -> Position | None:
        """
        Return a supply-link output tile using already cached building metadata.

        Callers that already have a building's type and position can avoid
        repeating those controller lookups by using this helper directly.
        """
        if building_type == EntityType.BRIDGE:
            return self.ct.get_bridge_target(building_id)
        if building_type in {
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
        }:
            return building_pos.add(self.ct.get_direction(building_id))
        return None

    def _is_adjacent_to_allied_harvester(self, pos: Position) -> bool:
        """
        Check whether a tile is orthogonally adjacent to a friendly harvester.

        This is used to keep generic chain continuation separate from the
        dedicated `build_harvester_supply_link` behavior.
        """
        return (pos.x, pos.y) in self.turn_allied_harvester_adjacent_keys

    def _record_action(self, action: BotAction, message: str) -> bool:
        """
        Persist a successful action and emit the matching debug message.

        Builder decision methods use this helper so action tracking and
        human-readable tracing stay consistent across the bot.
        """
        self.last_action = action
        self._debug_print(message)
        return True

    def _is_current_builder_tile(self, pos: Position) -> bool:
        """
        Return whether a tile is the builder's currently occupied tile.

        Builder bots must never place or replace a structure underneath
        themselves because that can remove the unit from the map.
        """
        return pos == self.ct.get_position()

    def _can_destroy_tile(self, pos: Position) -> bool:
        """
        Check whether the bot can safely destroy the tile at a position.

        The bot avoids destroying a visible tile that is currently occupied by
        another builder bot.
        """
        if self.ct.is_in_vision(pos):
            occupying_builder_id = self.ct.get_tile_builder_bot_id(pos)
            current_builder_id = self.turn_id if self.turn_id is not None else self.ct.get_id()
            if (
                occupying_builder_id is not None
                and occupying_builder_id != current_builder_id
            ):
                return False
        return self.ct.can_destroy(pos)

    def _get_best_action_staging_pos(self, target_pos: Position) -> Position | None:
        """
        Return the best visible tile from which the bot can act on one target.

        The staging tile must lie within builder action radius of `target_pos`,
        must not be the target tile itself, and must be a visible walkable tile
        that is not occupied by another builder bot.
        """
        current_pos = self.turn_position or self.ct.get_position()
        current_id = self.turn_id
        best_staging: tuple[tuple[int, int, int], Position] | None = None

        for dx, dy in BUILDER_STAGING_OFFSETS:
            staging_pos = Position(target_pos.x + dx, target_pos.y + dy)
            if not self._is_in_bounds(staging_pos):
                continue
            if not self.ct.is_in_vision(staging_pos):
                continue

            staging_tile = self._get_known_map_tile(staging_pos)
            if staging_tile is None:
                continue
            if staging_tile.environment == Environment.WALL:
                continue
            if (
                staging_tile.building_id is not None
                and staging_tile.building_type != EntityType.ROAD
            ):
                continue
            if (
                staging_tile.builder_bot_id is not None
                and staging_tile.builder_bot_id != current_id
            ):
                continue

            staging_key = (
                current_pos.distance_squared(staging_pos),
                staging_pos.x,
                staging_pos.y,
            )
            if best_staging is None or staging_key < best_staging[0]:
                best_staging = (staging_key, staging_pos)

        if best_staging is None:
            return None
        return best_staging[1]

    def _destroy_tile_if_safe(self, pos: Position) -> bool:
        """
        Destroy a tile only when it is confirmed safe for this builder.

        This is the central guard against deleting the tile under the bot or a
        tile currently occupied by another visible builder.
        """
        if not self._can_destroy_tile(pos):
            return False
        self.ct.destroy(pos)
        return True

    def _can_build_barrier_safely(self, pos: Position) -> bool:
        """
        Return whether a barrier can be built without replacing the current tile.
        """
        return (not self._is_current_builder_tile(pos)) and self.ct.can_build_barrier(
            pos
        )

    def _build_barrier_safely(self, pos: Position) -> bool:
        """
        Build a barrier only when the build tile is not the current tile.
        """
        if not self._can_build_barrier_safely(pos):
            return False
        self.ct.build_barrier(pos)
        return True

    def _can_build_harvester_safely(self, pos: Position) -> bool:
        """
        Return whether a harvester can be built without replacing the current tile.
        """
        return (not self._is_current_builder_tile(pos)) and self.ct.can_build_harvester(
            pos
        )

    def _build_harvester_safely(self, pos: Position) -> bool:
        """
        Build a harvester only when the ore tile is not the current tile.
        """
        if not self._can_build_harvester_safely(pos):
            return False
        self.ct.build_harvester(pos)
        return True

    def _can_build_launcher_safely(self, pos: Position) -> bool:
        """
        Return whether a launcher can be built without replacing the current tile.
        """
        return (not self._is_current_builder_tile(pos)) and self.ct.can_build_launcher(
            pos
        )

    def _build_launcher_safely(self, pos: Position) -> bool:
        """
        Build a launcher only when the build tile is not the current tile.
        """
        if not self._can_build_launcher_safely(pos):
            return False
        self.ct.build_launcher(pos)
        return True

    def _can_build_sentinel_safely(
        self,
        pos: Position,
        direction: Direction,
    ) -> bool:
        """
        Return whether a sentinel can be built without replacing the current tile.
        """
        return (not self._is_current_builder_tile(pos)) and self.ct.can_build_sentinel(
            pos,
            direction,
        )

    def _build_sentinel_safely(self, pos: Position, direction: Direction) -> bool:
        """
        Build a sentinel only when the build tile is not the current tile.
        """
        if not self._can_build_sentinel_safely(pos, direction):
            return False
        self.ct.build_sentinel(pos, direction)
        return True

    def has_enemy_bot_in_vision(self) -> bool:
        """
        Return whether any enemy unit is currently visible to this unit.

        The value is cached once per turn at the start of builder map
        refreshing and can be reused by many decision methods cheaply.
        """
        return self.turn_has_enemy_bot_in_vision

    def is_tile_in_enemy_builder_action_range(self, pos: Position) -> bool:
        """
        Return whether a visible enemy builder bot can act on a tile this turn.

        Builder-bot action range is radius squared 2. The check only uses
        currently visible enemy builder bots.
        """
        self._ensure_enemy_threat_cache()
        return (pos.x, pos.y) in self._enemy_builder_action_tiles

    def _is_on_direction_ray(
        self,
        origin: Position,
        direction: Direction,
        target: Position,
    ) -> bool:
        """
        Check whether a target lies strictly on a unit's forward direction ray.

        The ray starts one step in `direction` from `origin` and extends
        infinitely. The origin tile itself is not considered part of the ray.
        """
        if direction == Direction.CENTRE:
            return False

        delta_x, delta_y = direction.delta()
        rel_x = target.x - origin.x
        rel_y = target.y - origin.y
        if rel_x == 0 and rel_y == 0:
            return False

        if delta_x == 0:
            return rel_x == 0 and rel_y * delta_y > 0
        if delta_y == 0:
            return rel_y == 0 and rel_x * delta_x > 0
        return rel_x * delta_x > 0 and rel_y * delta_y > 0 and abs(rel_x) == abs(rel_y)

    def is_tile_in_enemy_turret_range(self, pos: Position) -> bool:
        """
        Check whether a tile is covered by any currently visible enemy turret.

        Coverage is evaluated for enemy gunners, sentinels, and breaches that
        are visible this turn. For gunners, coverage uses the current facing
        ray and range; for sentinels it uses sentinel line coverage; for
        breaches it uses radial range.
        """
        self._ensure_enemy_threat_cache()
        return (pos.x, pos.y) in self._enemy_turret_range_tiles

    def _is_next_to_core_footprint(self, pos: Position) -> bool:
        """
        Check whether a tile is adjacent (including diagonals) to core footprint.

        The check uses the in-bounds 3x3 core footprint and returns true when
        `pos` is exactly one king move away from at least one core tile.
        """
        if self.core_center_pos is None:
            self.find_core_center()
        if self.core_center_pos is None:
            return False

        return (
            max(
                abs(pos.x - self.core_center_pos.x),
                abs(pos.y - self.core_center_pos.y),
            )
            == 2
        )

    def _is_valid_supply_link_target_tile(
        self,
        tile: Tile,
        own_team: Team,
    ) -> bool:
        """
        Return whether a tile is a valid downstream target for supply links.

        Valid targets are allied supply links/core tiles, empty tiles, and road
        tiles (including enemy roads as a fallback target category).
        """
        if tile.environment == Environment.WALL:
            return False
        if tile.distance_to_core >= INFINITE_DISTANCE:
            return False
        if tile.building_team == own_team and (
            tile.building_type in SUPPLY_LINK_TYPES
            or tile.building_type == EntityType.CORE
        ):
            return True
        if tile.building_id is None:
            return True
        if tile.building_type == EntityType.ROAD:
            return True
        return False

    def _is_enemy_road_supply_target(
        self,
        tile: Tile,
        own_team: Team,
    ) -> bool:
        """
        Return whether a supply target tile is specifically an enemy road.

        Enemy-road targets are allowed, but only as the last fallback category
        after all reducing non-enemy-road targets have been exhausted.
        """
        return (
            tile.building_type == EntityType.ROAD
            and tile.building_id is not None
            and tile.building_team is not None
            and tile.building_team != own_team
        )

    def _get_supply_target_priority(
        self,
        tile: Tile,
        own_team: Team,
    ) -> tuple[int, int, int]:
        """
        Return tie-break priority for selecting supply-link target tiles.

        Priority order is:
        1. tiles with existing allied supply links or allied core tiles
        2. tiles outside enemy builder action range
        3. empty tiles, then allied roads, then enemy roads
        """
        has_allied_supply = (
            tile.building_team == own_team
            and (
                tile.building_type in SUPPLY_LINK_TYPES
                or tile.building_type == EntityType.CORE
            )
        )
        supply_rank = 0 if has_allied_supply else 1
        enemy_builder_rank = (
            1 if self.is_tile_in_enemy_builder_action_range(tile.position) else 0
        )

        if has_allied_supply:
            type_rank = 0
        elif tile.building_id is None:
            type_rank = 1
        elif tile.building_type == EntityType.ROAD and tile.building_team == own_team:
            type_rank = 2
        elif tile.building_type == EntityType.ROAD:
            type_rank = 3
        else:
            type_rank = 4

        return (supply_rank, enemy_builder_rank, type_rank)

    def _get_best_conveyor_target(
        self,
        build_pos: Position,
        origin_distance_to_core: int,
        own_team: Team,
    ) -> Position | None:
        """
        Return the best adjacent conveyor output that reduces core distance.

        The selected target must have core-distance exactly one smaller than
        the build tile and is ranked by `_get_supply_target_priority`.
        Enemy-road targets are only considered if no reducing non-enemy-road
        target exists.
        """
        best_candidate: tuple[tuple[int, int, int, int, int, int], Position] | None = None
        best_enemy_road_candidate: tuple[
            tuple[int, int, int, int, int, int],
            Position,
        ] | None = None
        for direction in DIRECTIONS:
            target_pos = build_pos.add(direction)
            if not self._is_in_bounds(target_pos):
                continue

            tile = self._get_known_map_tile(target_pos)
            if tile is None:
                continue
            if tile.distance_to_core != origin_distance_to_core - 1:
                continue
            if not self._is_valid_supply_link_target_tile(tile, own_team):
                continue
            if self.is_tile_in_enemy_turret_range(target_pos):
                continue

            delta_x, delta_y = direction.delta()
            direction_rank = 0 if abs(delta_x) + abs(delta_y) == 1 else 1
            candidate_key = (
                direction_rank,
                *self._get_supply_target_priority(tile, own_team),
                target_pos.x,
                target_pos.y,
            )
            if self._is_enemy_road_supply_target(tile, own_team):
                if (
                    best_enemy_road_candidate is None
                    or candidate_key < best_enemy_road_candidate[0]
                ):
                    best_enemy_road_candidate = (candidate_key, target_pos)
                continue

            if best_candidate is None or candidate_key < best_candidate[0]:
                best_candidate = (candidate_key, target_pos)

        if best_candidate is not None:
            return best_candidate[1]
        if best_enemy_road_candidate is not None:
            return best_enemy_road_candidate[1]
        return None

    def _get_best_bridge_target(
        self,
        build_pos: Position,
        origin_distance_to_core: int,
        own_team: Team,
    ) -> tuple[Position, int] | None:
        """
        Return the best bridge target that reduces core distance.

        Candidates are ranked by largest core-distance gain first, then by the
        same target-tile priority used for conveyors. Enemy-road targets are
        only considered if no reducing non-enemy-road target exists.
        """
        if self.map is None:
            return None

        best_candidate: tuple[
            tuple[int, int, int, int, int, int],
            Position,
            int,
        ] | None = None
        best_enemy_road_candidate: tuple[
            tuple[int, int, int, int, int, int],
            Position,
            int,
        ] | None = None
        bridge_x = build_pos.x
        bridge_y = build_pos.y
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                candidate_x = bridge_x + dx
                candidate_y = bridge_y + dy
                if candidate_x == bridge_x and candidate_y == bridge_y:
                    continue
                if not self.map._is_in_bounds(candidate_x, candidate_y):
                    continue
                dist_sq = dx * dx + dy * dy
                if dist_sq > 9:
                    continue

                tile = self.map.matrix[candidate_x][candidate_y]
                if tile is None:
                    continue
                if not self._is_valid_supply_link_target_tile(tile, own_team):
                    continue
                if tile.distance_to_core >= origin_distance_to_core:
                    continue
                if self.is_tile_in_enemy_turret_range(tile.position):
                    continue

                gain = origin_distance_to_core - tile.distance_to_core
                candidate_key = (
                    -gain,
                    *self._get_supply_target_priority(tile, own_team),
                    -dist_sq,
                    candidate_x,
                    candidate_y,
                )
                if self._is_enemy_road_supply_target(tile, own_team):
                    if (
                        best_enemy_road_candidate is None
                        or candidate_key < best_enemy_road_candidate[0]
                    ):
                        best_enemy_road_candidate = (candidate_key, tile.position, gain)
                    continue

                if best_candidate is None or candidate_key < best_candidate[0]:
                    best_candidate = (candidate_key, tile.position, gain)

        if best_candidate is not None:
            return (best_candidate[1], best_candidate[2])
        if best_enemy_road_candidate is not None:
            return (
                best_enemy_road_candidate[1],
                best_enemy_road_candidate[2],
            )
        return None

    def _get_supply_link_plan(
        self,
        build_pos: Position,
    ) -> tuple[Position, bool] | None:
        """
        Return the preferred downstream target and whether to build a bridge.

        Supply links are conveyor-first: if an adjacent conveyor target exists
        that reduces core distance by one, conveyor is preferred unless a bridge
        offers a long jump of at least `BRIDGE_LONG_JUMP_CORE_DISTANCE_GAIN`.
        If no conveyor can reduce distance, a bridge is used if it reduces
        distance by at least one. If no reducing target exists, returns `None`.
        """
        if self.map is None:
            return None

        origin_tile = self._get_known_map_tile(build_pos)
        if origin_tile is None:
            return None
        origin_distance_to_core = origin_tile.distance_to_core
        if origin_distance_to_core >= INFINITE_DISTANCE:
            return None

        own_team = self.turn_team if self.turn_team is not None else self.ct.get_team()
        best_conveyor_target = self._get_best_conveyor_target(
            build_pos,
            origin_distance_to_core,
            own_team,
        )
        best_bridge_candidate = self._get_best_bridge_target(
            build_pos,
            origin_distance_to_core,
            own_team,
        )

        if best_conveyor_target is not None:
            if self._is_next_to_core_footprint(build_pos):
                return (best_conveyor_target, False)
            if (
                best_bridge_candidate is None
                or best_bridge_candidate[1] < BRIDGE_LONG_JUMP_CORE_DISTANCE_GAIN
            ):
                return (best_conveyor_target, False)

        if best_bridge_candidate is not None:
            return (best_bridge_candidate[0], True)
        return None

    def get_supply_link_target(self, build_pos: Position) -> Position | None:
        """
        Return the preferred downstream target for one new supply link.

        This wraps `_get_supply_link_plan` and returns only the selected target
        tile, independent of whether conveyor or bridge would be used.
        """
        plan = self._get_supply_link_plan(build_pos)
        if plan is None:
            return None
        return plan[0]

    def _get_best_buildable_conveyor_target(
        self,
        build_pos: Position,
        origin_distance_to_core: int,
        own_team: Team,
    ) -> Position | None:
        """
        Return the best conveyor target that is immediately buildable now.

        This is only used in action-range contexts to recover when the
        preferred conveyor target is currently illegal (for example due to a
        direction/buildability constraint) and a different legal conveyor target
        should be used instead. Enemy-road targets are only considered if no
        reducing non-enemy-road target is buildable right now.
        """
        best_candidate: tuple[tuple[int, int, int, int, int, int], Position] | None = None
        best_enemy_road_candidate: tuple[
            tuple[int, int, int, int, int, int],
            Position,
        ] | None = None
        for direction in DIRECTIONS:
            target_pos = build_pos.add(direction)
            if not self._is_in_bounds(target_pos):
                continue

            tile = self._get_known_map_tile(target_pos)
            if tile is None:
                continue
            if tile.distance_to_core != origin_distance_to_core - 1:
                continue
            if not self._is_valid_supply_link_target_tile(tile, own_team):
                continue
            if self.is_tile_in_enemy_turret_range(target_pos):
                continue
            if self._is_supply_output_tile_unsafe(build_pos, target_pos, False):
                continue
            if not self.ct.can_build_conveyor(build_pos, direction):
                continue

            delta_x, delta_y = direction.delta()
            direction_rank = 0 if abs(delta_x) + abs(delta_y) == 1 else 1
            candidate_key = (
                direction_rank,
                *self._get_supply_target_priority(tile, own_team),
                target_pos.x,
                target_pos.y,
            )
            if self._is_enemy_road_supply_target(tile, own_team):
                if (
                    best_enemy_road_candidate is None
                    or candidate_key < best_enemy_road_candidate[0]
                ):
                    best_enemy_road_candidate = (candidate_key, target_pos)
                continue

            if best_candidate is None or candidate_key < best_candidate[0]:
                best_candidate = (candidate_key, target_pos)

        if best_candidate is not None:
            return best_candidate[1]
        if best_enemy_road_candidate is not None:
            return best_enemy_road_candidate[1]
        return None

    def _get_buildable_supply_link_plan(
        self,
        build_pos: Position,
        preferred_target_pos: Position,
        preferred_use_bridge: bool,
    ) -> tuple[Position, bool] | None:
        """
        Return a supply-link plan that is actually buildable at this moment.

        The preferred plan is tried first. If it is not currently legal, this
        helper attempts a bridge fallback and then a buildable-conveyor fallback
        while keeping the same core-distance reduction rules.
        """
        if self._can_build_supply_link(
            build_pos,
            preferred_target_pos,
            preferred_use_bridge,
        ):
            return (preferred_target_pos, preferred_use_bridge)

        origin_tile = self._get_known_map_tile(build_pos)
        if origin_tile is None:
            return None
        origin_distance_to_core = origin_tile.distance_to_core
        if origin_distance_to_core >= INFINITE_DISTANCE:
            return None

        own_team = self.turn_team if self.turn_team is not None else self.ct.get_team()
        if not preferred_use_bridge:
            bridge_candidate = self._get_best_bridge_target(
                build_pos,
                origin_distance_to_core,
                own_team,
            )
            if (
                bridge_candidate is not None
                and self._can_build_supply_link(
                    build_pos,
                    bridge_candidate[0],
                    True,
                )
            ):
                return (bridge_candidate[0], True)

        buildable_conveyor_target = self._get_best_buildable_conveyor_target(
            build_pos,
            origin_distance_to_core,
            own_team,
        )
        if buildable_conveyor_target is not None:
            return (buildable_conveyor_target, False)

        if preferred_use_bridge:
            bridge_candidate = self._get_best_bridge_target(
                build_pos,
                origin_distance_to_core,
                own_team,
            )
            if (
                bridge_candidate is not None
                and self._can_build_supply_link(
                    build_pos,
                    bridge_candidate[0],
                    True,
                )
            ):
                return (bridge_candidate[0], True)

        return None

    def _get_supply_output_tile(
        self,
        build_pos: Position,
        target_pos: Position,
        use_bridge: bool,
    ) -> Position | None:
        """
        Return the immediate output tile of the chosen supply-link build.

        Bridges output directly to `target_pos`. Conveyors output one step in
        the direction from `build_pos` toward `target_pos`.
        """
        if use_bridge:
            return target_pos
        direction = build_pos.direction_to(target_pos)
        if direction == Direction.CENTRE:
            return None
        return build_pos.add(direction)

    def _is_supply_output_tile_unsafe(
        self,
        build_pos: Position,
        target_pos: Position,
        use_bridge: bool,
    ) -> bool:
        """
        Return whether this link output would be inside enemy turret coverage.
        """
        output_pos = self._get_supply_output_tile(build_pos, target_pos, use_bridge)
        if output_pos is None:
            return True
        return self.is_tile_in_enemy_turret_range(output_pos)

    def _can_build_supply_link(
        self,
        build_pos: Position,
        target_pos: Position,
        use_bridge: bool,
    ) -> bool:
        """
        Check whether the selected supply-link build is currently legal.
        """
        if self._is_current_builder_tile(build_pos):
            return False
        if self._is_supply_output_tile_unsafe(build_pos, target_pos, use_bridge):
            return False

        if use_bridge:
            return self.ct.can_build_bridge(build_pos, target_pos)

        direction = build_pos.direction_to(target_pos)
        if direction == Direction.CENTRE:
            return False
        return self.ct.can_build_conveyor(build_pos, direction)

    def _build_supply_link(
        self,
        build_pos: Position,
        target_pos: Position,
        use_bridge: bool,
    ) -> bool:
        """
        Build one supply link (conveyor or bridge) at a selected tile.
        """
        if self._is_current_builder_tile(build_pos):
            return False
        if self._is_supply_output_tile_unsafe(build_pos, target_pos, use_bridge):
            return False

        if use_bridge:
            if not self.ct.can_build_bridge(build_pos, target_pos):
                return False
            self.ct.build_bridge(build_pos, target_pos)
            return True

        direction = build_pos.direction_to(target_pos)
        if direction == Direction.CENTRE:
            return False
        if not self.ct.can_build_conveyor(build_pos, direction):
            return False
        self.ct.build_conveyor(build_pos, direction)
        return True

    def _build_supply_link_with_optional_road_removal(
        self,
        build_pos: Position,
        target_pos: Position,
        is_road_build_pos: bool,
        use_bridge: bool,
    ) -> bool:
        """
        Build one supply link on an empty tile or prepare a road tile first.

        If the destination currently contains a road, the road is removed and
        this helper returns success for that preparation step. The caller can
        then place the supply link on the now-empty tile on the next turn.
        """
        if self._is_current_builder_tile(build_pos):
            return False
        if self._is_supply_output_tile_unsafe(build_pos, target_pos, use_bridge):
            return False

        if is_road_build_pos:
            if not self._destroy_tile_if_safe(build_pos):
                return False
            return True

        if not self._build_supply_link(build_pos, target_pos, use_bridge):
            return False

        return True

    def _get_core_footprint_positions(self, core_center_pos: Position) -> list[Position]:
        """
        Return the in-bounds 3x3 footprint tiles around a core centre.

        The helper is used for both friendly-core movement and enemy-core
        targeting, so callers can reuse the same footprint construction logic.
        """
        core_tiles: list[Position] = []
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                target_pos = Position(core_center_pos.x + dx, core_center_pos.y + dy)
                if not self._is_in_bounds(target_pos):
                    continue
                core_tiles.append(target_pos)

        return core_tiles

    def _get_core_target_tiles(self, core_center_pos: Position) -> list[Position]:
        """
        Return the visible in-bounds 3x3 footprint tiles of a core centre.

        Turrets can target any visible tile of the core footprint, so this
        helper normalises core targeting for both combat logic and build-time
        directional checks.
        """
        return [
            target_pos
            for target_pos in self._get_core_footprint_positions(core_center_pos)
            if self.ct.is_in_vision(target_pos)
        ]


    # Combat and movement helpers

    def _get_entity_fire_target_positions(self, entity_id: int) -> list[Position]:
        """
        Return the targetable tile positions associated with one visible entity.

        Most entities occupy a single tile, so their only candidate is their
        own position. The core is targetable across its visible 3x3 footprint,
        so the helper returns every visible in-bounds core tile instead.
        """
        entity_type = self.ct.get_entity_type(entity_id)
        entity_pos = self.ct.get_position(entity_id)
        if entity_type != EntityType.CORE:
            return [entity_pos]

        return self._get_core_target_tiles(entity_pos)

    def _sentinel_direction_covers_target(
        self,
        sentinel_pos: Position,
        sentinel_direction: Direction,
        target_pos: Position,
    ) -> bool:
        """
        Check whether a sentinel facing would cover a specific target tile.

        A sentinel can hit any tile within one king move of its facing line,
        subject to the sentinel attack radius. This helper approximates that
        line directly from the sentinel position and facing direction.
        """
        delta_x, delta_y = sentinel_direction.delta()
        max_steps = max(self.ct.get_map_width(), self.ct.get_map_height())

        for step in range(max_steps + 1):
            line_pos = Position(
                sentinel_pos.x + delta_x * step,
                sentinel_pos.y + delta_y * step,
            )
            if sentinel_pos.distance_squared(line_pos) > 32:
                break

            if max(abs(target_pos.x - line_pos.x), abs(target_pos.y - line_pos.y)) <= 1:
                return True

        return False

    def _is_diagonal_direction(self, direction: Direction) -> bool:
        """
        Return whether a direction is diagonal.

        Diagonal directions have both x and y deltas non-zero and are treated
        as fully feed-safe for sentinel orientation rules.
        """
        delta_x, delta_y = direction.delta()
        return abs(delta_x) + abs(delta_y) == 2

    def _get_sentinel_supplier_directions(self, sentinel_pos: Position) -> set[Direction]:
        """
        Return directions of adjacent supplier tiles around a sentinel placement.

        A supplier is any adjacent harvester or supply-link tile (conveyor,
        armoured conveyor, or bridge) that is currently visible in the map
        cache. Team ownership is intentionally ignored for this orientation
        safety rule.
        """
        current_round = (
            self.turn_round if self.turn_round >= 0 else self.ct.get_current_round()
        )
        supplier_types = {EntityType.HARVESTER, *SUPPLY_LINK_TYPES}
        supplier_directions: set[Direction] = set()

        for direction in DIRECTIONS:
            supplier_pos = sentinel_pos.add(direction)
            if not self._is_in_bounds(supplier_pos):
                continue

            tile = self._get_known_map_tile(supplier_pos)
            if tile is None:
                continue
            if tile.last_seen_round != current_round:
                continue
            if tile.building_id is None:
                continue
            if tile.building_type not in supplier_types:
                continue
            supplier_directions.add(direction)

        return supplier_directions

    def _get_sentinel_placement_direction(
        self,
        sentinel_pos: Position,
        must_cover_targets: list[Position],
        preferred_targets: list[Position] | None = None,
    ) -> tuple[Direction, bool] | None:
        """
        Choose the facing direction for one sentinel placement.

        Precedence:
        1) ammo feed safety: non-diagonal facings that point directly at a
           supplier direction are rejected; diagonals are always feed-safe.
        2) enemy-core coverage: if any safe direction covers a preferred target
           (typically enemy core tiles), one of those is always selected.
        3) deterministic fallback: diagonal-safe options are preferred, then
           direction order.

        The selected direction must always cover at least one required target
        from `must_cover_targets`.
        """
        if not must_cover_targets:
            return None

        preferred_targets = preferred_targets or []
        supplier_directions = self._get_sentinel_supplier_directions(sentinel_pos)
        best_candidate: tuple[tuple[int, int, int], Direction, bool] | None = None

        for direction_index, direction in enumerate(DIRECTIONS):
            if not self._can_build_sentinel_safely(sentinel_pos, direction):
                continue

            is_diagonal = self._is_diagonal_direction(direction)
            if not is_diagonal and direction in supplier_directions:
                continue

            covers_required = False
            for target_pos in must_cover_targets:
                if not self._sentinel_direction_covers_target(
                    sentinel_pos,
                    direction,
                    target_pos,
                ):
                    continue
                covers_required = True
                break
            if not covers_required:
                continue

            covers_preferred = False
            for target_pos in preferred_targets:
                if not self._sentinel_direction_covers_target(
                    sentinel_pos,
                    direction,
                    target_pos,
                ):
                    continue
                covers_preferred = True
                break

            candidate_key = (
                0 if covers_preferred else 1,
                0 if is_diagonal else 1,
                direction_index,
            )
            if best_candidate is None or candidate_key < best_candidate[0]:
                best_candidate = (candidate_key, direction, covers_preferred)

        if best_candidate is None:
            return None
        return (best_candidate[1], best_candidate[2])

    def _is_breach_target_safe(self, target_pos: Position) -> bool:
        """
        Check whether a breach shot would avoid allied splash damage.

        The breach damages the eight surrounding tiles around its target, so
        the helper rejects targets whose 3x3 splash area contains allied
        buildings or builder bots, except for the acting breach itself.
        """
        acting_entity_id = self.ct.get_id()

        for dx in range(-1, 2):
            for dy in range(-1, 2):
                splash_pos = Position(target_pos.x + dx, target_pos.y + dy)
                if not self._is_in_bounds(splash_pos):
                    continue
                if not self.ct.is_in_vision(splash_pos):
                    continue

                building_id = self.ct.get_tile_building_id(splash_pos)
                if (
                    building_id is not None
                    and building_id != acting_entity_id
                    and self.ct.get_team(building_id) == self.ct.get_team()
                ):
                    return False

                builder_bot_id = self.ct.get_tile_builder_bot_id(splash_pos)
                if (
                    builder_bot_id is not None
                    and self.ct.get_team(builder_bot_id) == self.ct.get_team()
                ):
                    return False

        return True

    def _get_best_fire_target(
        self,
        target_priority: list[EntityType],
        safety_check=None,
    ) -> Position | None:
        """
        Choose the best currently fireable target tile from a priority list.

        The helper scans visible tiles, keeps only those this turret can fire
        at right now, and returns the closest target tile belonging to the
        first enemy entity type that appears in the configured priority order.
        An optional safety predicate can reject otherwise fireable tiles, for
        example to avoid breach splash on allied entities.
        """
        current_pos = self.ct.get_position()
        fireable_targets: list[tuple[EntityType, tuple[int, int, int], Position]] = []

        def add_entity_targets(entity_ids: list[int]) -> None:
            for entity_id in entity_ids:
                if self.ct.get_team(entity_id) == self.ct.get_team():
                    continue

                entity_type = self.ct.get_entity_type(entity_id)
                for target_pos in self._get_entity_fire_target_positions(entity_id):
                    if not self.ct.can_fire(target_pos):
                        continue
                    if safety_check is not None and not safety_check(target_pos):
                        continue

                    candidate_key = (
                        current_pos.distance_squared(target_pos),
                        target_pos.x,
                        target_pos.y,
                    )
                    fireable_targets.append((entity_type, candidate_key, target_pos))

        add_entity_targets(self.ct.get_nearby_units())
        add_entity_targets(self.ct.get_nearby_buildings())

        if not fireable_targets:
            return None

        for target_type in target_priority:
            best_target: tuple[tuple[int, int, int], Position] | None = None

            for candidate_entity_type, candidate_key, pos in fireable_targets:
                if target_type != candidate_entity_type:
                    continue
                if best_target is None or candidate_key < best_target[0]:
                    best_target = (candidate_key, pos)

            if best_target is not None:
                return best_target[1]

        return None

    def _move_in_direction_with_roads(self, direction: Direction) -> bool:
        """
        Advance in one chosen direction while preparing the destination tile.

        The method rejects out-of-bounds and wall destinations. For a valid
        next tile, it builds a road there when legal and then attempts the move
        in the same direction, so a blocked step still spends the turn making
        future progress along the intended path.
        """
        if direction == Direction.CENTRE:
            return False
        current_pos = self.ct.get_position()
        next_pos = current_pos.add(direction)
        if next_pos == current_pos:
            return False
        if not self._is_in_bounds(next_pos):
            return False
        if self.ct.get_tile_env(next_pos) == Environment.WALL:
            return False

        acted = False
        if self.ct.can_build_road(next_pos):
            self.ct.build_road(next_pos)
            acted = True

        if self.ct.can_move(direction):
            self.ct.move(direction)
            acted = True

        return acted

    def _move_in_direction_without_roads(self, direction: Direction) -> bool:
        """
        Advance in one chosen direction without creating new road tiles.

        The method only executes an actual legal move. It rejects out-of-bounds
        and known wall destinations, which makes it suitable for resource
        recovery patrols that should stay on the existing walkable network.
        """
        if direction == Direction.CENTRE:
            return False
        current_pos = self.ct.get_position()
        next_pos = current_pos.add(direction)
        if next_pos == current_pos:
            return False
        if not self._is_in_bounds(next_pos):
            return False
        if self.ct.get_tile_env(next_pos) == Environment.WALL:
            return False
        if not self.ct.can_move(direction):
            return False

        self.ct.move(direction)
        return True

    def _move_towards_with_roads(self, target_pos: Position) -> bool:
        """
        Advance one step toward a target while preparing the chosen path tile.

        The method first asks the cached map for a BFS next step that can route
        across all known tiles (and unknown-but-not-wall tiles), then executes
        that step with normal road+move behavior. If no cached route step is
        currently available, it falls back to a local greedy adjacent-tile
        choice so the bot can still make progress this turn.
        """
        current_pos = self.ct.get_position()
        if current_pos == target_pos:
            return False

        current_distance_sq = current_pos.distance_squared(target_pos)
        direct_direction = current_pos.direction_to(target_pos)
        if direct_direction != Direction.CENTRE:
            direct_pos = current_pos.add(direct_direction)
            if (
                self._is_in_bounds(direct_pos)
                and self.ct.get_tile_env(direct_pos) != Environment.WALL
                and direct_pos.distance_squared(target_pos) < current_distance_sq
                and (
                    self.ct.can_move(direct_direction)
                    or self.ct.can_build_road(direct_pos)
                )
                and self._move_in_direction_with_roads(direct_direction)
            ):
                return True

        if self.map is not None:
            next_step_pos = self.map.get_next_field_for_target(target_pos)
            if next_step_pos is not None and next_step_pos != current_pos:
                move_direction = current_pos.direction_to(next_step_pos)
                if (
                    move_direction != Direction.CENTRE
                    and self._move_in_direction_with_roads(move_direction)
                ):
                    return True

        candidates: list[
            tuple[tuple[int, int, int, int, int, int], Direction]
        ] = []

        for direction_index, direction in enumerate(DIRECTIONS):
            next_pos = current_pos.add(direction)
            if not self._is_in_bounds(next_pos):
                continue
            if self.ct.get_tile_env(next_pos) == Environment.WALL:
                continue

            can_move = self.ct.can_move(direction)
            can_build_road = self.ct.can_build_road(next_pos)
            if not can_move and not can_build_road:
                continue

            next_distance_sq = next_pos.distance_squared(target_pos)
            action_rank = (
                0 if can_move and can_build_road else 1 if can_move else 2
            )
            progress_rank = 0 if next_distance_sq < current_distance_sq else 1
            candidate_key = (
                progress_rank,
                next_distance_sq,
                action_rank,
                direction_index,
                next_pos.x,
                next_pos.y,
            )
            candidates.append((candidate_key, direction))

        if not candidates:
            return False

        candidates.sort(key=lambda candidate: candidate[0])
        return self._move_in_direction_with_roads(candidates[0][1])

    def _move_towards_without_roads(self, target_pos: Position) -> bool:
        """
        Advance one step toward a target while staying on existing walkable tiles.

        The method prefers a cached BFS step across known currently passable
        tiles only. If no cached step is available, it falls back to a local
        greedy move choice among legal moves, still without building roads.
        """
        current_pos = self.ct.get_position()
        if current_pos == target_pos:
            return False

        current_distance_sq = current_pos.distance_squared(target_pos)
        direct_direction = current_pos.direction_to(target_pos)
        if direct_direction != Direction.CENTRE:
            direct_pos = current_pos.add(direct_direction)
            if (
                self._is_in_bounds(direct_pos)
                and self.ct.get_tile_env(direct_pos) != Environment.WALL
                and direct_pos.distance_squared(target_pos) < current_distance_sq
                and self.ct.can_move(direct_direction)
                and self._move_in_direction_without_roads(direct_direction)
            ):
                return True

        if self.map is not None:
            next_step_pos = self.map.get_next_known_walkable_field_for_target(
                target_pos
            )
            if next_step_pos is not None and next_step_pos != current_pos:
                move_direction = current_pos.direction_to(next_step_pos)
                if (
                    move_direction != Direction.CENTRE
                    and self._move_in_direction_without_roads(move_direction)
                ):
                    return True

        candidates: list[
            tuple[tuple[int, int, int, int, int], Direction]
        ] = []

        for direction_index, direction in enumerate(DIRECTIONS):
            next_pos = current_pos.add(direction)
            if not self._is_in_bounds(next_pos):
                continue
            if self.ct.get_tile_env(next_pos) == Environment.WALL:
                continue
            if not self.ct.can_move(direction):
                continue

            next_distance_sq = next_pos.distance_squared(target_pos)
            progress_rank = 0 if next_distance_sq < current_distance_sq else 1
            candidate_key = (
                progress_rank,
                next_distance_sq,
                direction_index,
                next_pos.x,
                next_pos.y,
            )
            candidates.append((candidate_key, direction))

        if not candidates:
            return False

        candidates.sort(key=lambda candidate: candidate[0])
        return self._move_in_direction_without_roads(candidates[0][1])

    def _move_towards_action_range_with_roads(
        self,
        target_pos: Position,
        action_radius_sq: int = 2,
        allow_direct_target_fallback: bool = False,
    ) -> bool:
        """
        Advance toward any tile that can act on a target, not onto the target.

        The helper asks the map cache for a wall-aware BFS next step toward a
        staging tile within `action_radius_sq` of `target_pos`, then performs
        one road+move step in that direction. When no such staged step is
        currently known, callers may optionally allow a direct fallback toward
        the target tile itself.
        """
        current_pos = self.ct.get_position()
        if (
            current_pos != target_pos
            and current_pos.distance_squared(target_pos) <= action_radius_sq
        ):
            return False

        if self.map is not None:
            next_step_pos = self.map.get_next_field_for_action_range(
                target_pos,
                action_radius_sq=action_radius_sq,
            )
            if next_step_pos is not None and next_step_pos != current_pos:
                move_direction = current_pos.direction_to(next_step_pos)
                if (
                    move_direction != Direction.CENTRE
                    and self._move_in_direction_with_roads(move_direction)
                ):
                    return True

        if not allow_direct_target_fallback:
            return False

        return self._move_towards_with_roads(target_pos)


    # Builder actions and tactical helpers

    def attack_enemy_harvester(self) -> bool:
        """
        Attack a visible enemy harvester by contesting a visible orthogonal empty tile.

        The builder searches for enemy harvesters in vision and skips any
        harvester that already has a visible orthogonally adjacent sentinel.
        For the remaining harvesters, it collects orthogonally adjacent visible
        tiles that have no building and are on empty terrain. If the team has at
        least the local sentinel threshold of titanium and one of those tiles is
        currently a legal sentinel build location, it builds a sentinel there
        with a diagonal facing that still covers the harvester tile without
        pointing directly at it. Otherwise, if the closest candidate tile is
        outside action range, the builder advances toward it and prepares the
        path with a road when needed.
        """
        if self.map is None:
            return False

        action_radius_sq = 2
        current_pos = self.turn_position or self.ct.get_position()
        current_round = (
            self.turn_round if self.turn_round >= 0 else self.ct.get_current_round()
        )

        candidate_tiles: list[
            tuple[tuple[int, int, int, int, int, int], Position, Position]
        ] = []
        best_move_target: tuple[tuple[int, int, int, int, int, int], Position] | None = None

        for entity_id, entity_type, entity_team, harvester_pos in self.turn_nearby_building_infos:
            if entity_type != EntityType.HARVESTER:
                continue
            if entity_team == self.turn_team:
                continue

            has_adjacent_sentinel = False
            empty_candidate_tiles: list[Position] = []

            for direction in CARDINAL_DIRECTIONS:
                candidate_pos = harvester_pos.add(direction)
                if not self._is_in_bounds(candidate_pos):
                    continue

                tile = self._get_known_map_tile(candidate_pos)
                if tile is None:
                    continue
                if tile.last_seen_round != current_round:
                    continue
                if tile.building_type == EntityType.SENTINEL:
                    has_adjacent_sentinel = True
                    break
                if tile.building_id is not None:
                    continue
                if tile.environment != Environment.EMPTY:
                    continue

                empty_candidate_tiles.append(candidate_pos)

            if has_adjacent_sentinel:
                continue

            for candidate_pos in empty_candidate_tiles:
                sort_key = (
                    current_pos.distance_squared(candidate_pos),
                    candidate_pos.x,
                    candidate_pos.y,
                    harvester_pos.x,
                    harvester_pos.y,
                    entity_id,
                )
                candidate_tiles.append((sort_key, candidate_pos, harvester_pos))
                if (
                    current_pos.distance_squared(candidate_pos) <= action_radius_sq
                    and candidate_pos != current_pos
                ):
                    continue
                if best_move_target is None or sort_key < best_move_target[0]:
                    best_move_target = (sort_key, candidate_pos)

        if not candidate_tiles:
            return False

        titanium, _ = self.turn_resources
        if titanium >= ENEMY_HARVESTER_SENTINEL_MIN_TITANIUM_THRESHOLD:
            candidate_tiles.sort(key=lambda candidate: candidate[0])
            self.get_enemy_core_pos()

            possible_enemy_core_tiles: list[Position] = []
            seen_core_tiles: set[tuple[int, int]] = set()
            possible_enemy_core_centers = (
                [self.enemy_core_pos]
                if self.enemy_core_pos is not None
                else list(self.enemy_core_pos_candidates)
            )
            for core_center_pos in possible_enemy_core_centers:
                for core_tile in self._get_core_target_tiles(core_center_pos):
                    core_key = (core_tile.x, core_tile.y)
                    if core_key in seen_core_tiles:
                        continue
                    seen_core_tiles.add(core_key)
                    possible_enemy_core_tiles.append(core_tile)

            build_options: list[
                tuple[tuple[int, int, int, int, int, int, int], Position, Direction]
            ] = []
            for candidate_key, candidate_pos, harvester_pos in candidate_tiles:
                if candidate_pos == current_pos:
                    continue

                direction_plan = self._get_sentinel_placement_direction(
                    candidate_pos,
                    must_cover_targets=[harvester_pos],
                    preferred_targets=possible_enemy_core_tiles,
                )
                if direction_plan is None:
                    continue
                sentinel_direction, covers_enemy_core = direction_plan

                build_key = (
                    0 if covers_enemy_core else 1,
                    *candidate_key,
                )
                build_options.append((build_key, candidate_pos, sentinel_direction))

            if build_options:
                build_options.sort(key=lambda candidate: candidate[0])
                for _, candidate_pos, sentinel_direction in build_options:
                    if not self._build_sentinel_safely(candidate_pos, sentinel_direction):
                        continue
                    return self._record_action(
                        BotAction.ATTACK_ENEMY_HARVESTER,
                        "attacking enemy harvester",
                    )

        if best_move_target is None:
            return False
        if not self._move_towards_action_range_with_roads(
            best_move_target[1],
            action_radius_sq=action_radius_sq,
            allow_direct_target_fallback=True,
        ):
            return False

        return self._record_action(
            BotAction.ATTACK_ENEMY_HARVESTER,
            "attacking enemy harvester",
        )

    def attack_enemy_walkable(self) -> bool:
        """
        Attack enemy walkable logistics tiles by configured harassment priority.

        The method targets visible enemy bridges/conveyors/armoured conveyors/
        roads. Supplier tiles feeding enemy turrets, targeting enemy core
        tiles, or adjacent to enemy harvesters are promoted above normal type
        priority. If the bot stands on a damaged enemy target tile, it keeps
        attacking that tile and ignores all other options for this turn, unless
        current titanium is below the harassment attack threshold.
        """
        current_pos = self.turn_position or self.ct.get_position()
        own_team = self.turn_team if self.turn_team is not None else self.ct.get_team()
        titanium, _ = self.turn_resources
        can_attack = titanium >= HARASSMENT_ATTACK_MIN_TITANIUM_THRESHOLD
        action_radius_sq = 2

        type_rank = HARASSMENT_ENEMY_TILE_TYPE_RANK
        special_rank = HARASSMENT_ENEMY_TILE_SPECIAL_RANK
        current_tile = self._get_known_map_tile(current_pos)
        if (
            current_tile is not None
            and current_tile.building_id is not None
            and current_tile.building_type in type_rank
            and current_tile.building_team != own_team
            and self.ct.get_hp(current_tile.building_id)
            < self.ct.get_max_hp(current_tile.building_id)
        ):
            if can_attack and self.ct.can_fire(current_pos):
                self.ct.fire(current_pos)
                return self._record_action(
                    BotAction.ATTACK_ENEMY_WALKABLE,
                    "attacking enemy walkable",
                )

        enemy_harvester_positions = {
            (building_pos.x, building_pos.y)
            for _, building_type, building_team, building_pos in self.turn_nearby_building_infos
            if (
                building_type == EntityType.HARVESTER
                and building_team != own_team
            )
        }

        def get_special_priority(
            building_id: int,
            building_type: EntityType,
            building_pos: Position,
        ) -> int:
            if building_type not in SUPPLY_LINK_TYPES:
                return special_rank["default"]

            output_pos = self._get_supply_link_output_pos_from_info(
                building_id,
                building_type,
                building_pos,
            )
            output_tile = (
                self._get_known_map_tile(output_pos)
                if output_pos is not None and self._is_in_bounds(output_pos)
                else None
            )
            if (
                output_tile is not None
                and output_tile.last_seen_round == self.turn_round
                and output_tile.building_id is not None
                and output_tile.building_team != own_team
            ):
                output_building_type = output_tile.building_type
                if output_building_type in ENEMY_TURRET_TYPES:
                    return special_rank["feeds_enemy_turret"]
                if output_building_type == EntityType.CORE:
                    return special_rank["targets_enemy_core"]

            for direction in CARDINAL_DIRECTIONS:
                adjacent_pos = building_pos.add(direction)
                if (adjacent_pos.x, adjacent_pos.y) in enemy_harvester_positions:
                    return special_rank["adjacent_enemy_harvester"]

            return special_rank["default"]

        best_candidate: tuple[tuple[int, int, int, int, int, int], Position] | None = None
        in_range_candidates: list[tuple[tuple[int, int, int, int, int, int], Position]] = []

        for building_id, building_type, building_team, building_pos in self.turn_nearby_building_infos:
            if building_team == own_team:
                continue
            type_priority = type_rank.get(building_type)
            if type_priority is None:
                continue

            distance_sq = current_pos.distance_squared(building_pos)
            candidate_key = (
                get_special_priority(building_id, building_type, building_pos),
                type_priority,
                distance_sq,
                building_pos.x,
                building_pos.y,
                building_id,
            )
            if best_candidate is None or candidate_key < best_candidate[0]:
                best_candidate = (candidate_key, building_pos)
            if building_pos == current_pos or distance_sq <= action_radius_sq:
                in_range_candidates.append((candidate_key, building_pos))

        if can_attack and in_range_candidates:
            in_range_candidates.sort(key=lambda candidate: candidate[0])
            for _, target_pos in in_range_candidates:
                if not self.ct.can_fire(target_pos):
                    continue
                self.ct.fire(target_pos)
                return self._record_action(
                    BotAction.ATTACK_ENEMY_WALKABLE,
                    "attacking enemy walkable",
                )

        if best_candidate is None:
            return False

        target_pos = best_candidate[1]
        if target_pos == current_pos:
            return self._record_action(
                BotAction.ATTACK_ENEMY_WALKABLE,
                "attacking enemy walkable",
            )
        if self._move_towards_with_roads(target_pos):
            return self._record_action(
                BotAction.ATTACK_ENEMY_WALKABLE,
                "attacking enemy walkable",
            )

        return False

    def launcher_defend(self) -> bool:
        """
        Place a launcher near enemy builders that stand on allied supply tiles.

        The method scans visible tiles for enemy builder bots occupying an
        allied conveyor or bridge tile, then tries to place a launcher on one
        of the eight neighboring tiles around that intrusion. Empty tiles are
        preferred, and allied roads may be removed first when needed. If no
        launcher can be placed immediately, the defender moves toward action
        range of the best neighboring launcher tile.
        """
        if self.map is None:
            return False

        titanium, _ = self.turn_resources
        if titanium < LAUNCHER_DEFEND_MIN_TITANIUM_THRESHOLD:
            return False

        own_team = self.turn_team if self.turn_team is not None else self.ct.get_team()
        current_pos = self.turn_position or self.ct.get_position()
        intrusion_tiles: list[tuple[tuple[int, int, int], Position]] = []
        for pos in self.ct.get_nearby_tiles():
            builder_id = self.ct.get_tile_builder_bot_id(pos)
            if builder_id is None:
                continue
            if self.ct.get_team(builder_id) == own_team:
                continue

            building_id = self.ct.get_tile_building_id(pos)
            if building_id is None:
                continue
            if self.ct.get_team(building_id) != own_team:
                continue
            if self.ct.get_hp(building_id) >= self.ct.get_max_hp(building_id):
                continue

            building_type = self.ct.get_entity_type(building_id)
            if not self._is_supply_link_type(building_type):
                continue

            intrusion_key = (
                current_pos.distance_squared(pos),
                pos.x,
                pos.y,
            )
            intrusion_tiles.append((intrusion_key, pos))

        if not intrusion_tiles:
            return False

        intrusion_tiles.sort(key=lambda candidate: candidate[0])
        actionable_candidates: list[
            tuple[tuple[int, int, int, int, int, int], Position, bool]
        ] = []
        movement_candidates: list[
            tuple[tuple[int, int, int, int, int, int, int], Position]
        ] = []

        for _, enemy_tile_pos in intrusion_tiles:
            has_adjacent_allied_launcher = False
            for direction in DIRECTIONS:
                adjacent_pos = enemy_tile_pos.add(direction)
                if not self._is_in_bounds(adjacent_pos):
                    continue

                adjacent_tile = self._get_known_map_tile(adjacent_pos)
                if adjacent_tile is None:
                    continue
                if adjacent_tile.building_type != EntityType.LAUNCHER:
                    continue
                if adjacent_tile.building_team != own_team:
                    continue

                has_adjacent_allied_launcher = True
                break

            if has_adjacent_allied_launcher:
                continue

            for direction in DIRECTIONS:
                build_pos = enemy_tile_pos.add(direction)
                if not self._is_in_bounds(build_pos):
                    continue

                build_tile = self._get_known_map_tile(build_pos)
                if build_tile is not None and build_tile.environment == Environment.WALL:
                    continue
                if (
                    build_tile is not None
                    and build_tile.building_id is not None
                    and build_tile.building_type != EntityType.ROAD
                ):
                    continue

                is_road_build_pos = (
                    build_tile is not None
                    and build_tile.building_type == EntityType.ROAD
                )
                candidate_key = (
                    current_pos.distance_squared(enemy_tile_pos),
                    current_pos.distance_squared(build_pos),
                    0 if not is_road_build_pos else 1,
                    build_pos.x,
                    build_pos.y,
                    enemy_tile_pos.x,
                    enemy_tile_pos.y,
                )
                if build_pos == current_pos:
                    movement_candidates.append((candidate_key, build_pos))
                    continue
                if current_pos.distance_squared(build_pos) <= 2:
                    if not self.ct.is_in_vision(build_pos):
                        continue
                    if (
                        not is_road_build_pos
                        and not self._can_build_launcher_safely(build_pos)
                    ):
                        continue
                    if is_road_build_pos and not self._can_destroy_tile(build_pos):
                        continue
                    actionable_candidates.append(
                        (candidate_key, build_pos, is_road_build_pos)
                    )
                    continue

                movement_candidates.append((candidate_key, build_pos))

        if actionable_candidates:
            actionable_candidates.sort(key=lambda candidate: candidate[0])
            for _, build_pos, is_road_build_pos in actionable_candidates:
                if is_road_build_pos:
                    if not self._destroy_tile_if_safe(build_pos):
                        continue

                if not self._build_launcher_safely(build_pos):
                    continue

                return self._record_action(
                    BotAction.LAUNCHER_DEFEND,
                    "launcher defending supply chain",
                )

        if not movement_candidates:
            return False

        movement_candidates.sort(key=lambda candidate: candidate[0])
        for _, build_pos in movement_candidates:
            if not self._move_towards_action_range_with_roads(
                build_pos,
                action_radius_sq=2,
                allow_direct_target_fallback=False,
            ):
                continue

            return self._record_action(
                BotAction.LAUNCHER_DEFEND,
                "moving to launcher defend",
            )

        return False

    def repair_if_damaged(self, check_vision_radius: bool = False) -> bool:
        """
        Heal a damaged friendly building on the current tile when possible.

        If `check_vision_radius` is true and no immediate heal is performed, the
        builder also searches visible friendly damaged buildings that it could
        stand on and advances toward the closest one, building a road first when
        that path still needs to be prepared.
        """
        current_pos = self.turn_position or self.ct.get_position()
        titanium, _ = self.turn_resources

        current_building_id = self.ct.get_tile_building_id(current_pos)
        if current_building_id is not None:
            if self.ct.get_team(
                current_building_id
            ) == self.ct.get_team() and self.ct.get_hp(
                current_building_id
            ) < self.ct.get_max_hp(
                current_building_id
            ):
                if titanium >= REPAIR_MIN_TITANIUM_THRESHOLD and self.ct.can_heal(
                    current_pos
                ):
                    self.ct.heal(current_pos)
                    return self._record_action(
                        BotAction.REPAIR_IF_DAMAGED,
                        "repairing damaged building",
                    )
                return False

        if not check_vision_radius:
            return False

        damaged_targets: list[tuple[tuple[int, int, int], Position]] = []
        for building_id, _, building_team, building_pos in self.turn_nearby_building_infos:
            if building_team != self.turn_team:
                continue
            if self.ct.get_hp(building_id) >= self.ct.get_max_hp(building_id):
                continue

            building_tile = self._get_known_map_tile(building_pos)
            if building_tile is None or not building_tile.is_passable:
                continue

            sort_key = (
                current_pos.distance_squared(building_pos),
                building_pos.x,
                building_pos.y,
            )
            damaged_targets.append((sort_key, building_pos))

        if not damaged_targets:
            return False

        damaged_targets.sort(key=lambda target: target[0])
        target_pos = damaged_targets[0][1]

        if not self._move_towards_with_roads(target_pos):
            return False

        return self._record_action(
            BotAction.REPAIR_IF_DAMAGED,
            "repairing damaged building",
        )

    def get_bridge_target(self, bridge_pos: Position) -> Position | None:
        """
        Backward-compatible alias for `get_supply_link_target`.
        """
        return self.get_supply_link_target(bridge_pos)

    def build_harvester_supply_link(self, hold: bool = False) -> bool:
        """
        Build or stage a supply link next to a visible allied harvester.

        The method scans visible allied harvesters, skips any that already have
        an orthogonally adjacent allied supply link, and looks for empty
        orthogonal neighbor tiles where a new link could be placed. When team
        titanium is above the harvester-bridge threshold, it builds or moves
        toward the closest legal candidate. When `hold` is true and titanium is
        still below that threshold, it instead moves into action range of the
        best candidate and waits there for the future build.
        """
        if self.map is None:
            return False

        titanium, _ = self.turn_resources
        can_build = titanium >= HARVESTER_BRIDGE_MIN_TITANIUM_THRESHOLD
        if not can_build and not hold:
            return False

        current_pos = self.turn_position or self.ct.get_position()
        actionable_candidates: list[
            tuple[tuple[int, int, int, int, int, int], Position, Position, bool]
        ] = []
        movement_candidates: list[
            tuple[tuple[int, int, int, int, int, int], Position]
        ] = []
        hold_candidates: list[
            tuple[tuple[int, int, int, int, int, int], Position, Position]
        ] = []

        for harvester_id, harvester_type, harvester_team, harvester_pos in self.turn_nearby_building_infos:
            if harvester_type != EntityType.HARVESTER:
                continue
            if harvester_team != self.turn_team:
                continue

            empty_adjacent_tiles: list[Position] = []
            for direction in CARDINAL_DIRECTIONS:
                adjacent_pos = harvester_pos.add(direction)
                if not self._is_in_bounds(adjacent_pos):
                    continue
                if not self.ct.is_in_vision(adjacent_pos):
                    continue

                tile = self._get_known_map_tile(adjacent_pos)
                if tile is None:
                    continue
                if self._is_allied_supply_link_tile(tile):
                    empty_adjacent_tiles = []
                    break
                if tile.building_id is not None:
                    continue
                if tile.environment != Environment.EMPTY:
                    continue
                empty_adjacent_tiles.append(adjacent_pos)

            for build_pos in empty_adjacent_tiles:
                candidate_key = (
                    current_pos.distance_squared(build_pos),
                    build_pos.x,
                    build_pos.y,
                    harvester_pos.x,
                    harvester_pos.y,
                    harvester_id,
                )
                target_plan = self._get_supply_link_plan(build_pos)
                if target_plan is None:
                    movement_candidates.append((candidate_key, build_pos))
                    continue
                target_pos, use_bridge = target_plan

                if can_build:
                    if (
                        build_pos != current_pos
                        and current_pos.distance_squared(build_pos) <= 2
                    ):
                        buildable_plan = self._get_buildable_supply_link_plan(
                            build_pos,
                            target_pos,
                            use_bridge,
                        )
                        if buildable_plan is None:
                            movement_candidates.append((candidate_key, build_pos))
                            continue
                        target_pos, use_bridge = buildable_plan
                        actionable_candidates.append(
                            (candidate_key, build_pos, target_pos, use_bridge)
                        )
                    else:
                        movement_candidates.append((candidate_key, build_pos))
                    continue

                staging_pos = self._get_best_action_staging_pos(build_pos)
                if staging_pos is None:
                    continue

                hold_key = (
                    current_pos.distance_squared(staging_pos),
                    1 if staging_pos == build_pos else 0,
                    staging_pos.x,
                    staging_pos.y,
                    build_pos.x,
                    build_pos.y,
                )
                hold_candidates.append((hold_key, staging_pos, build_pos))

        if can_build:
            if actionable_candidates:
                actionable_candidates.sort(key=lambda candidate: candidate[0])
                _, build_pos, target_pos, use_bridge = actionable_candidates[0]
                if not self._build_supply_link(build_pos, target_pos, use_bridge):
                    return False
                return self._record_action(
                    BotAction.BUILD_HARVESTER_BRIDGE,
                    "building harvester supply link",
                )

            if not movement_candidates:
                return False

            movement_candidates.sort(key=lambda candidate: candidate[0])
            target_build_pos = movement_candidates[0][1]
            if (
                target_build_pos != current_pos
                and current_pos.distance_squared(target_build_pos) <= 2
            ):
                return self._record_action(
                    BotAction.HOLD_BUILD_HARVESTER_BRIDGE,
                    "holding harvester supply link position",
                )
            if not self._move_towards_action_range_with_roads(
                target_build_pos,
                action_radius_sq=2,
                allow_direct_target_fallback=False,
            ):
                if (
                    target_build_pos != current_pos
                    and current_pos.distance_squared(target_build_pos) <= 2
                ):
                    return self._record_action(
                        BotAction.HOLD_BUILD_HARVESTER_BRIDGE,
                        "holding harvester supply link position",
                    )
                return False

            return self._record_action(
                BotAction.BUILD_HARVESTER_BRIDGE,
                "building harvester supply link",
            )

        if not hold_candidates:
            return False

        hold_candidates.sort(key=lambda candidate: candidate[0])
        _, staging_pos, build_pos = hold_candidates[0]
        if current_pos.distance_squared(build_pos) <= 2 and current_pos != build_pos:
            return self._record_action(
                BotAction.HOLD_BUILD_HARVESTER_BRIDGE,
                "holding harvester supply link position",
            )

        if not self._move_towards_action_range_with_roads(
            build_pos,
            action_radius_sq=2,
            allow_direct_target_fallback=False,
        ) and not self._move_towards_with_roads(staging_pos):
            return False

        return self._record_action(
            BotAction.HOLD_BUILD_HARVESTER_BRIDGE,
            "holding harvester supply link position",
        )

    def build_harvester_bridge(self, hold: bool = False) -> bool:
        """
        Backward-compatible alias for `build_harvester_supply_link`.
        """
        return self.build_harvester_supply_link(hold=hold)

    def build_missing_supply_link(self, hold: bool = False) -> bool:
        """
        Extend a non-harvester supply-chain gap with a new link.

        The method looks for allied supply links whose output tile is empty or
        occupied by a road, skipping harvester-adjacent gaps that are handled
        by `build_harvester_supply_link()`. It also remembers one pending
        missing-link tile from previous turns, so a builder keeps working on
        that same gap even if the originating link temporarily leaves vision.
        When team titanium is above the chain threshold, it builds or moves
        toward the closest legal missing link. If the missing-link tile is
        currently blocked by an enemy passable structure (for example an enemy
        road), the builder first moves onto that tile and destroys it, then
        continues normal link placement on subsequent turns. If the builder is
        already standing on such a blocker tile and that tile is the output
        target of an allied bridge or conveyor, it immediately attacks the
        current tile before any hold or fallback behavior. When `hold` is true
        and titanium is still below that threshold, it instead stages near the
        best missing-link tile so the build can happen immediately once
        resources recover.
        """
        if self.map is None:
            return False

        current_pos = self.turn_position or self.ct.get_position()
        own_team = self.turn_team if self.turn_team is not None else self.ct.get_team()
        current_pos_key = (current_pos.x, current_pos.y)
        if self.missing_supply_target is not None:
            pending_pos = Position(
                self.missing_supply_target[0],
                self.missing_supply_target[1],
            )
            if not self._is_in_bounds(pending_pos):
                self.missing_supply_target = None
            else:
                pending_tile = self._get_known_map_tile(pending_pos)
                if pending_tile is not None:
                    if self._is_allied_supply_link_tile(pending_tile):
                        self.missing_supply_target = None
                    elif pending_tile.environment != Environment.EMPTY:
                        self.missing_supply_target = None

        current_building_id = self.ct.get_tile_building_id(current_pos)
        if (
            current_building_id is None
            and self.missing_supply_blocker_target == current_pos_key
        ):
            self.missing_supply_blocker_target = None

        current_tile_is_visible_supply_blocker = False
        if (
            current_building_id is not None
            and self.ct.get_team(current_building_id) != own_team
        ):
            current_tile_is_visible_supply_blocker = (
                current_pos_key in self.turn_allied_supply_output_keys
            )

            if (
                current_tile_is_visible_supply_blocker
                or self.missing_supply_blocker_target == current_pos_key
            ):
                self.missing_supply_blocker_target = current_pos_key
                self.missing_supply_target = current_pos_key
                if self.ct.can_fire(current_pos):
                    self.ct.fire(current_pos)
                    return self._record_action(
                        BotAction.BUILD_MISSING_BRIDGE,
                        "building missing supply link",
                    )
                return self._record_action(
                    BotAction.HOLD_MISSING_BRIDGE,
                    "holding missing supply link position",
                )

        titanium, _ = self.turn_resources
        can_build = titanium >= CHAIN_BRIDGE_MIN_TITANIUM_THRESHOLD
        if not can_build and not hold:
            return False

        actionable_candidates: list[
            tuple[
                tuple[int, int, int, int, int, int, int],
                Position,
                Position,
                bool,
                bool,
            ]
        ] = []
        movement_candidates: list[
            tuple[tuple[int, int, int, int, int, int, int], Position]
        ] = []
        enemy_blocker_action_candidates: list[
            tuple[tuple[int, int, int, int, int, int, int], Position]
        ] = []
        enemy_blocker_move_candidates: list[
            tuple[tuple[int, int, int, int, int, int, int], Position]
        ] = []
        hold_candidates: list[
            tuple[tuple[int, int, int, int, int, int, int], Position, Position]
        ] = []
        candidate_build_pos_keys: set[tuple[int, int]] = set()

        for link_id, _link_type, link_pos, build_pos in self.turn_allied_supply_link_infos:
            if build_pos is None:
                continue
            if not self._is_in_bounds(build_pos):
                continue
            if not self.ct.is_in_vision(build_pos):
                continue
            if self._is_adjacent_to_allied_harvester(build_pos):
                continue

            tile = self._get_known_map_tile(build_pos)
            if tile is None:
                continue
            if tile.environment != Environment.EMPTY:
                continue
            if self._is_allied_supply_link_tile(tile):
                continue

            is_empty_build_pos = tile.building_id is None
            is_road_build_pos = tile.building_type == EntityType.ROAD
            if not (is_empty_build_pos or is_road_build_pos):
                continue

            build_pos_type_rank = 0 if is_empty_build_pos else 1
            candidate_key = (
                current_pos.distance_squared(build_pos),
                build_pos_type_rank,
                build_pos.x,
                build_pos.y,
                link_pos.x,
                link_pos.y,
                link_id,
            )
            candidate_build_pos_keys.add((build_pos.x, build_pos.y))

            if can_build:
                is_enemy_blocker_tile = (
                    tile.building_id is not None
                    and tile.building_team != self.turn_team
                    and (tile.is_passable or tile.building_type == EntityType.BRIDGE)
                )
                if is_enemy_blocker_tile:
                    if build_pos == current_pos:
                        enemy_blocker_action_candidates.append(
                            (candidate_key, build_pos)
                        )
                    else:
                        enemy_blocker_move_candidates.append(
                            (candidate_key, build_pos)
                        )
                    continue

                target_plan = self._get_supply_link_plan(build_pos)
                if target_plan is None:
                    movement_candidates.append((candidate_key, build_pos))
                    continue
                target_pos, use_bridge = target_plan
                if self._is_supply_output_tile_unsafe(
                    build_pos,
                    target_pos,
                    use_bridge,
                ):
                    continue
                if (
                    build_pos != current_pos
                    and current_pos.distance_squared(build_pos) <= 2
                ):
                    if is_road_build_pos:
                        if not self._can_destroy_tile(build_pos):
                            movement_candidates.append((candidate_key, build_pos))
                            continue
                    else:
                        buildable_plan = self._get_buildable_supply_link_plan(
                            build_pos,
                            target_pos,
                            use_bridge,
                        )
                        if buildable_plan is None:
                            movement_candidates.append((candidate_key, build_pos))
                            continue
                        target_pos, use_bridge = buildable_plan

                    actionable_candidates.append(
                        (
                            candidate_key,
                            build_pos,
                            target_pos,
                            is_road_build_pos,
                            use_bridge,
                        )
                    )
                else:
                    movement_candidates.append((candidate_key, build_pos))
                continue

            staging_pos = self._get_best_action_staging_pos(build_pos)
            if staging_pos is None:
                continue

            hold_key = (
                current_pos.distance_squared(staging_pos),
                build_pos_type_rank,
                1 if staging_pos == build_pos else 0,
                staging_pos.x,
                staging_pos.y,
                build_pos.x,
                build_pos.y,
            )
            hold_candidates.append((hold_key, staging_pos, build_pos))

        if (
            self.missing_supply_target is not None
            and self.missing_supply_target not in candidate_build_pos_keys
        ):
            build_pos = Position(
                self.missing_supply_target[0],
                self.missing_supply_target[1],
            )
            if self._is_in_bounds(build_pos) and not self._is_adjacent_to_allied_harvester(
                build_pos
            ):
                tile = self._get_known_map_tile(build_pos)
                if tile is not None and tile.environment == Environment.EMPTY:
                    if self._is_allied_supply_link_tile(tile):
                        self.missing_supply_target = None
                    else:
                        is_empty_build_pos = tile.building_id is None
                        is_road_build_pos = tile.building_type == EntityType.ROAD
                        if is_empty_build_pos or is_road_build_pos:
                            build_pos_type_rank = 0 if is_empty_build_pos else 1
                            candidate_key = (
                                current_pos.distance_squared(build_pos),
                                build_pos_type_rank,
                                build_pos.x,
                                build_pos.y,
                                build_pos.x,
                                build_pos.y,
                                -1,
                            )
                            if can_build:
                                is_enemy_blocker_tile = (
                                    tile.building_id is not None
                                    and tile.building_team != self.turn_team
                                    and (
                                        tile.is_passable
                                        or tile.building_type == EntityType.BRIDGE
                                    )
                                )
                                if is_enemy_blocker_tile:
                                    if build_pos == current_pos:
                                        enemy_blocker_action_candidates.append(
                                            (candidate_key, build_pos)
                                        )
                                    else:
                                        enemy_blocker_move_candidates.append(
                                            (candidate_key, build_pos)
                                        )
                                else:
                                    target_plan = self._get_supply_link_plan(build_pos)
                                    if target_plan is None:
                                        movement_candidates.append((candidate_key, build_pos))
                                    else:
                                        target_pos, use_bridge = target_plan
                                        if self._is_supply_output_tile_unsafe(
                                            build_pos,
                                            target_pos,
                                            use_bridge,
                                        ):
                                            movement_candidates.append((candidate_key, build_pos))
                                        elif (
                                            build_pos != current_pos
                                            and current_pos.distance_squared(build_pos) <= 2
                                        ):
                                            if is_road_build_pos:
                                                if not self._can_destroy_tile(build_pos):
                                                    movement_candidates.append((candidate_key, build_pos))
                                                else:
                                                    actionable_candidates.append(
                                                        (
                                                            candidate_key,
                                                            build_pos,
                                                            target_pos,
                                                            is_road_build_pos,
                                                            use_bridge,
                                                        )
                                                    )
                                            else:
                                                buildable_plan = self._get_buildable_supply_link_plan(
                                                    build_pos,
                                                    target_pos,
                                                    use_bridge,
                                                )
                                                if buildable_plan is None:
                                                    movement_candidates.append((candidate_key, build_pos))
                                                else:
                                                    actionable_candidates.append(
                                                        (
                                                            candidate_key,
                                                            build_pos,
                                                            buildable_plan[0],
                                                            is_road_build_pos,
                                                            buildable_plan[1],
                                                        )
                                                    )
                                        else:
                                            movement_candidates.append((candidate_key, build_pos))
                            else:
                                staging_pos = self._get_best_action_staging_pos(build_pos)
                                if staging_pos is not None:
                                    hold_key = (
                                        current_pos.distance_squared(staging_pos),
                                        build_pos_type_rank,
                                        1 if staging_pos == build_pos else 0,
                                        staging_pos.x,
                                        staging_pos.y,
                                        build_pos.x,
                                        build_pos.y,
                                    )
                                    hold_candidates.append(
                                        (hold_key, staging_pos, build_pos)
                                    )

        if can_build:
            if enemy_blocker_action_candidates:
                enemy_blocker_action_candidates.sort(key=lambda candidate: candidate[0])
                for _, build_pos in enemy_blocker_action_candidates:
                    if not self.ct.can_fire(build_pos):
                        continue
                    self.ct.fire(build_pos)
                    self.missing_supply_blocker_target = (build_pos.x, build_pos.y)
                    self.missing_supply_target = (build_pos.x, build_pos.y)
                    return self._record_action(
                        BotAction.BUILD_MISSING_BRIDGE,
                        "building missing supply link",
                    )

            if enemy_blocker_move_candidates:
                enemy_blocker_move_candidates.sort(key=lambda candidate: candidate[0])
                target_blocker_pos = enemy_blocker_move_candidates[0][1]
                if not self._move_towards_with_roads(target_blocker_pos):
                    return False
                self.missing_supply_blocker_target = (
                    target_blocker_pos.x,
                    target_blocker_pos.y,
                )
                self.missing_supply_target = (
                    target_blocker_pos.x,
                    target_blocker_pos.y,
                )
                return self._record_action(
                    BotAction.BUILD_MISSING_BRIDGE,
                    "building missing supply link",
                )

            if actionable_candidates:
                actionable_candidates.sort(key=lambda candidate: candidate[0])
                for (
                    _,
                    build_pos,
                    target_pos,
                    is_road_build_pos,
                    use_bridge,
                ) in actionable_candidates:
                    if not self._build_supply_link_with_optional_road_removal(
                        build_pos,
                        target_pos,
                        is_road_build_pos,
                        use_bridge,
                    ):
                        continue
                    self.missing_supply_blocker_target = None
                    if is_road_build_pos:
                        self.missing_supply_target = (build_pos.x, build_pos.y)
                    else:
                        self.missing_supply_target = None

                    return self._record_action(
                        BotAction.BUILD_MISSING_BRIDGE,
                        "building missing supply link",
                    )

            if not movement_candidates:
                return False

            movement_candidates.sort(key=lambda candidate: candidate[0])
            target_build_pos = movement_candidates[0][1]
            self.missing_supply_target = (
                target_build_pos.x,
                target_build_pos.y,
            )
            if (
                target_build_pos != current_pos
                and current_pos.distance_squared(target_build_pos) <= 2
            ):
                return self._record_action(
                    BotAction.HOLD_MISSING_BRIDGE,
                    "holding missing supply link position",
                )

            if not self._move_towards_action_range_with_roads(
                target_build_pos,
                action_radius_sq=2,
                allow_direct_target_fallback=False,
            ):
                if (
                    target_build_pos != current_pos
                    and current_pos.distance_squared(target_build_pos) <= 2
                ):
                    return self._record_action(
                        BotAction.HOLD_MISSING_BRIDGE,
                        "holding missing supply link position",
                    )
                return False

            return self._record_action(
                BotAction.HOLD_MISSING_BRIDGE,
                "holding missing supply link position",
            )

        if not hold_candidates:
            return False

        hold_candidates.sort(key=lambda candidate: candidate[0])
        _, staging_pos, build_pos = hold_candidates[0]
        self.missing_supply_target = (build_pos.x, build_pos.y)
        if current_pos.distance_squared(build_pos) <= 2 and current_pos != build_pos:
            return self._record_action(
                BotAction.HOLD_MISSING_BRIDGE,
                "holding missing supply link position",
            )

        if not self._move_towards_action_range_with_roads(
            build_pos,
            action_radius_sq=2,
            allow_direct_target_fallback=False,
        ) and not self._move_towards_with_roads(staging_pos):
            return False

        return self._record_action(
            BotAction.HOLD_MISSING_BRIDGE,
            "holding missing supply link position",
        )

    def build_missing_bridge(self, hold: bool = False) -> bool:
        """
        Backward-compatible alias for `build_missing_supply_link`.
        """
        return self.build_missing_supply_link(hold=hold)

    def destroy_hijacked_reschain(self) -> bool:
        """
        Destroy allied logistics buildings that feed enemy combat or supply.

        The method checks nearby allied conveyors, armoured conveyors, and
        bridges that this builder can destroy right now. If one of those
        buildings outputs onto an enemy turret or enemy supply tile, the
        builder destroys the closest such building, breaking the hijacked
        resource chain. Occupied logistics tiles with another visible builder
        are never destroyed.
        """
        current_pos = self.turn_position or self.ct.get_position()
        enemy_turret_types = {
            EntityType.GUNNER,
            EntityType.SENTINEL,
            EntityType.BREACH,
            EntityType.LAUNCHER,
        }
        enemy_supplier_types = set(SUPPLY_LINK_TYPES)
        enemy_supplier_types.add(EntityType.SPLITTER)
        destroy_candidates: list[tuple[tuple[int, int, int, int], Position]] = []

        for building_id, _building_type, building_pos, target_pos in self.turn_allied_supply_link_infos:
            if target_pos is None:
                continue
            if not (
                0 <= target_pos.x < self.ct.get_map_width()
                and 0 <= target_pos.y < self.ct.get_map_height()
            ):
                continue
            if not self.ct.is_in_vision(target_pos):
                continue

            target_tile = self._get_known_map_tile(target_pos)
            if target_tile is None or target_tile.building_id is None:
                continue
            if target_tile.building_team == self.ct.get_team():
                continue
            if (
                target_tile.building_type not in enemy_turret_types
                and target_tile.building_type not in enemy_supplier_types
            ):
                continue

            if self.ct.is_in_vision(building_pos) and not self._can_destroy_tile(
                building_pos
            ):
                continue
            if not self.ct.can_destroy(building_pos):
                continue

            candidate_key = (
                current_pos.distance_squared(building_pos),
                building_pos.x,
                building_pos.y,
                building_id,
            )
            destroy_candidates.append((candidate_key, building_pos))

        if not destroy_candidates:
            return False

        destroy_candidates.sort(key=lambda candidate: candidate[0])
        if not self._destroy_tile_if_safe(destroy_candidates[0][1]):
            return False
        return self._record_action(
            BotAction.DESTROY_HIJACKED_RESCHAIN,
            "destroying hijacked reschain",
        )

    def defend_core_prox(self) -> bool:
        """
        Clear enemy passable structures or bridges from allied core proximity.

        The method scans visible enemy buildings that are inside the fixed
        core-proximity radius and are passable (for example enemy roads or bridges).
        It keeps a sticky target when possible, destroys that
        target immediately once it is inside builder action range (including
        when standing directly on it), and otherwise moves toward action range.
        """
        if self.map is None:
            return False

        if self.core_center_pos is None:
            self.find_core_center()
        if self.core_center_pos is None:
            return False

        current_pos = self.turn_position or self.ct.get_position()
        core_x = self.core_center_pos.x
        core_y = self.core_center_pos.y
        prox_dist = CORE_PROXIMITY_DIST

        current_building_id = self.ct.get_tile_building_id(current_pos)
        if (
            current_building_id is not None
            and self.ct.get_team(current_building_id) != self.turn_team
            and max(abs(current_pos.x - core_x), abs(current_pos.y - core_y)) <= prox_dist
        ):
            current_tile = self._get_known_map_tile(current_pos)
            tile_is_passable = current_tile is not None and current_tile.is_passable
            current_type = self.ct.get_entity_type(current_building_id)
            if current_type == EntityType.BRIDGE or tile_is_passable:
                self.core_prox_defend_target = (current_pos.x, current_pos.y)
                if self.ct.can_fire(current_pos):
                    self.ct.fire(current_pos)
                return self._record_action(
                    BotAction.DEFEND_CORE_PROX,
                    "defending core proximity",
                )

        prox_targets: list[
            tuple[tuple[int, int, int, int, int], Position, EntityType]
        ] = []

        for building_id, target_type, target_team, target_pos in self.turn_nearby_building_infos:
            if target_team == self.turn_team:
                continue

            if max(abs(target_pos.x - core_x), abs(target_pos.y - core_y)) > prox_dist:
                continue

            target_tile = self._get_known_map_tile(target_pos)
            tile_is_passable = target_tile is not None and target_tile.is_passable
            if not (target_type == EntityType.BRIDGE or tile_is_passable):
                continue
            if target_type == EntityType.BRIDGE and not tile_is_passable:
                continue

            type_rank = 0 if target_type == EntityType.ROAD else 1
            candidate_key = (
                current_pos.distance_squared(target_pos),
                type_rank,
                target_pos.x,
                target_pos.y,
                building_id,
            )
            prox_targets.append((candidate_key, target_pos, target_type))

        if not prox_targets:
            self.core_prox_defend_target = None
            return False

        prox_targets.sort(key=lambda candidate: candidate[0])
        target_by_pos: dict[tuple[int, int], tuple[Position, EntityType]] = {
            (candidate_pos.x, candidate_pos.y): (candidate_pos, candidate_type)
            for _, candidate_pos, candidate_type in prox_targets
        }

        ordered_targets: list[tuple[Position, EntityType]] = []
        if (
            self.core_prox_defend_target is not None
            and self.core_prox_defend_target in target_by_pos
        ):
            ordered_targets.append(target_by_pos[self.core_prox_defend_target])
        for _, candidate_pos, candidate_type in prox_targets:
            if (
                ordered_targets
                and candidate_pos == ordered_targets[0][0]
            ):
                continue
            ordered_targets.append((candidate_pos, candidate_type))

        for target_pos, target_type in ordered_targets:
            target_key = (target_pos.x, target_pos.y)

            if current_pos.distance_squared(target_pos) <= 2:
                if self._destroy_tile_if_safe(target_pos):
                    self.core_prox_defend_target = target_key
                    return self._record_action(
                        BotAction.DEFEND_CORE_PROX,
                        "defending core proximity",
                    )
                if current_pos == target_pos:
                    continue

            if not self._move_towards_action_range_with_roads(
                target_pos,
                action_radius_sq=2,
                allow_direct_target_fallback=False,
            ):
                continue

            self.core_prox_defend_target = target_key
            return self._record_action(
                BotAction.DEFEND_CORE_PROX,
                "defending core proximity",
            )

        return False

    def _get_harvester_protection_candidates(
        self,
    ) -> list[tuple[tuple[int, int, int, int, int, int, int], Position, bool]]:
        """
        Return visible exposed tiles next to allied harvesters that want protection.

        A candidate is an orthogonally adjacent empty tile or allied road next
        to a visible allied harvester. Harvesters are only considered when
        sealing one of those tiles would still leave a valid resource outlet:
        either an adjacent pulling building already exists, or at least one
        other exposed adjacent tile remains.
        """
        if self.map is None:
            return []
        if self.turn_round == self._harvester_protection_cache_round:
            return self._harvester_protection_cache

        current_pos = self.turn_position or self.ct.get_position()
        pulling_building_types = {
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.SPLITTER,
            EntityType.BRIDGE,
        }
        protection_candidates: list[
            tuple[tuple[int, int, int, int, int, int, int], Position, bool]
        ] = []

        for harvester_id, harvester_type, harvester_team, harvester_pos in self.turn_nearby_building_infos:
            if harvester_type != EntityType.HARVESTER:
                continue
            if harvester_team != self.turn_team:
                continue

            exposed_adjacent_tiles: list[tuple[Position, bool]] = []
            has_pulling_building = False

            for direction in CARDINAL_DIRECTIONS:
                adjacent_pos = harvester_pos.add(direction)
                if not self._is_in_bounds(adjacent_pos):
                    continue
                if not self.ct.is_in_vision(adjacent_pos):
                    continue

                tile = self._get_known_map_tile(adjacent_pos)
                if tile is None:
                    continue

                if (
                    tile.building_type in pulling_building_types
                    and tile.building_team == self.ct.get_team()
                ):
                    has_pulling_building = True

                is_empty_tile = (
                    tile.building_id is None and tile.environment == Environment.EMPTY
                )
                is_allied_road_tile = (
                    tile.building_type == EntityType.ROAD
                    and tile.building_team == self.ct.get_team()
                )
                if not (is_empty_tile or is_allied_road_tile):
                    continue

                exposed_adjacent_tiles.append((adjacent_pos, is_allied_road_tile))

            if not exposed_adjacent_tiles:
                continue

            if not has_pulling_building and len(exposed_adjacent_tiles) < 2:
                continue

            for candidate_pos, is_road_tile in exposed_adjacent_tiles:
                candidate_key = (
                    current_pos.distance_squared(candidate_pos),
                    0 if not is_road_tile else 1,
                    candidate_pos.x,
                    candidate_pos.y,
                    harvester_pos.x,
                    harvester_pos.y,
                    harvester_id,
                )
                protection_candidates.append(
                    (candidate_key, candidate_pos, is_road_tile)
                )

        self._harvester_protection_cache_round = self.turn_round
        self._harvester_protection_cache = protection_candidates
        return protection_candidates

    def protect_harvester(self, hold: bool = False) -> bool:
        """
        Build or stage a barrier next to a friendly harvester.

        The method targets visible exposed orthogonal tiles next to allied
        harvesters. Empty tiles can be walled directly, while allied roads can
        be replaced by barriers when that is legal in the same turn. It first
        prefers an immediate build or a move that prepares the build. When
        `hold` is true and no protection action succeeds, it reuses the same
        candidate scan to wait in action range of the best exposed tile.
        """
        barrier_candidates = self._get_harvester_protection_candidates()
        if not barrier_candidates:
            return False

        current_pos = self.turn_position or self.ct.get_position()
        barrier_ti, barrier_ax = self.ct.get_barrier_cost()
        titanium, axionite = self.turn_resources
        can_afford_barrier = titanium >= barrier_ti and axionite >= barrier_ax
        movement_candidates: list[tuple[tuple[int, int, int, int], Position]] = []
        hold_candidates: list[
            tuple[tuple[int, int, int, int, int], Position, Position]
        ] = []

        for _, candidate_pos, is_road_tile in barrier_candidates:
            candidate_rank = 0 if not is_road_tile else 1
            if current_pos.distance_squared(candidate_pos) <= 2 and candidate_pos != current_pos:
                if is_road_tile:
                    if (
                        can_afford_barrier
                        and self._destroy_tile_if_safe(candidate_pos)
                        and self._build_barrier_safely(candidate_pos)
                    ):
                        return self._record_action(
                            BotAction.PROTECT_HARVESTER,
                            "protecting harvester",
                        )
                elif self._build_barrier_safely(candidate_pos):
                    return self._record_action(
                        BotAction.PROTECT_HARVESTER,
                        "protecting harvester",
                    )
            else:
                move_key = (
                    current_pos.distance_squared(candidate_pos),
                    candidate_rank,
                    candidate_pos.x,
                    candidate_pos.y,
                )
                movement_candidates.append((move_key, candidate_pos))

            if not hold:
                continue

            staging_pos = self._get_best_action_staging_pos(candidate_pos)
            if staging_pos is None:
                continue

            hold_key = (
                current_pos.distance_squared(staging_pos),
                candidate_rank,
                1 if staging_pos == candidate_pos else 0,
                staging_pos.x,
                staging_pos.y,
            )
            hold_candidates.append((hold_key, staging_pos, candidate_pos))

        attempted_move_target: Position | None = None
        if movement_candidates:
            movement_candidates.sort(key=lambda candidate: candidate[0])
            attempted_move_target = movement_candidates[0][1]
            if self._move_towards_action_range_with_roads(
                attempted_move_target,
                action_radius_sq=2,
                allow_direct_target_fallback=False,
            ):
                return self._record_action(
                    BotAction.PROTECT_HARVESTER,
                    "protecting harvester",
                )

        if not hold or not hold_candidates:
            return False

        hold_candidates.sort(key=lambda candidate: candidate[0])
        _, staging_pos, target_pos = hold_candidates[0]
        if current_pos.distance_squared(target_pos) <= 2 and current_pos != target_pos:
            return self._record_action(
                BotAction.HOLD_PROTECT_HARVESTER,
                "holding harvester protection position",
            )

        if (
            target_pos != attempted_move_target
            and self._move_towards_action_range_with_roads(
                target_pos,
                action_radius_sq=2,
                allow_direct_target_fallback=False,
            )
        ):
            return self._record_action(
                BotAction.HOLD_PROTECT_HARVESTER,
                "holding harvester protection position",
            )

        if staging_pos == attempted_move_target or not self._move_towards_with_roads(
            staging_pos
        ):
            return False

        return self._record_action(
            BotAction.HOLD_PROTECT_HARVESTER,
            "holding harvester protection position",
        )

    def build_harvester(self, hold: bool = False) -> bool:
        """
        Build or hold a visible titanium tile for later harvester placement.

        The method scans every visible titanium deposit once and reuses that
        information for both the normal build behavior and the fallback hold
        behavior. If harvester placement is currently allowed, it first tries
        to build immediately or move into action range of the best visible ore
        tile. When `hold` is true and no build action succeeds, it instead
        claims one visible titanium tile deterministically and stages next to
        it without stepping onto the ore. While holding with a visible enemy
        builder in range, the bot prefers securing that ore tile with an allied
        barrier.
        """
        if self.map is None:
            return False

        current_pos = self.turn_position or self.ct.get_position()
        current_id = self.turn_id
        own_team = self.turn_team if self.turn_team is not None else self.ct.get_team()
        titanium, _ = self.turn_resources
        can_build = (
            not self.has_enemy_bot_in_vision()
            and titanium >= HARVESTER_MIN_TITANIUM_THRESHOLD
            and self.map.known_harvesters_built < MAX_HARVESTORS
        )
        action_radius_sq = 2
        ore_candidates: list[tuple[tuple[int, int, int], Position, bool, Tile]] = []

        for ore_pos in self.turn_nearby_tiles:
            ore_tile = self._get_known_map_tile(ore_pos)
            if ore_tile is None or ore_tile.environment != Environment.ORE_TITANIUM:
                continue
            has_replaceable_structure = ore_tile.building_type in {
                EntityType.ROAD,
                EntityType.BARRIER,
            }
            if ore_tile.building_id is not None and not has_replaceable_structure:
                continue

            target_key = (
                current_pos.distance_squared(ore_pos),
                ore_pos.x,
                ore_pos.y,
            )
            ore_candidates.append(
                (target_key, ore_pos, has_replaceable_structure, ore_tile)
            )

        if can_build and ore_candidates:
            ore_candidates.sort(key=lambda target: target[0])

            for _, target_pos, has_replaceable_structure, ore_tile in ore_candidates:
                if target_pos == current_pos:
                    continue
                if current_pos.distance_squared(target_pos) > action_radius_sq:
                    continue

                if has_replaceable_structure and ore_tile.building_id is not None:
                    if not self._destroy_tile_if_safe(target_pos):
                        continue
                    if not self._build_harvester_safely(target_pos):
                        continue
                elif not self._build_harvester_safely(target_pos):
                    continue

                return self._record_action(
                    BotAction.BUILD_HARVESTER,
                    "building harvester",
                )

            for _, target_pos, _has_replaceable_structure, _ore_tile in ore_candidates:
                if (
                    current_pos.distance_squared(target_pos) <= action_radius_sq
                    and target_pos != current_pos
                ):
                    continue

                if not self._move_towards_action_range_with_roads(
                    target_pos,
                    action_radius_sq=action_radius_sq,
                    allow_direct_target_fallback=False,
                ):
                    continue

                return self._record_action(
                    BotAction.BUILD_HARVESTER,
                    "building harvester",
                )

        if not hold:
            return False
        if not ore_candidates:
            return False

        ore_candidates.sort(key=lambda target: target[0])
        if self.has_enemy_bot_in_vision():
            for _, target_pos, has_replaceable_structure, ore_tile in ore_candidates:
                if target_pos == current_pos:
                    continue
                if current_pos.distance_squared(target_pos) > action_radius_sq:
                    continue

                if (
                    ore_tile.building_type == EntityType.BARRIER
                    and ore_tile.building_team == own_team
                ):
                    return self._record_action(
                        BotAction.HOLD_TITANIUM,
                        "holding titanium tile",
                    )

                if has_replaceable_structure and ore_tile.building_id is not None:
                    if not self._destroy_tile_if_safe(target_pos):
                        continue

                if not self._build_barrier_safely(target_pos):
                    continue

                return self._record_action(
                    BotAction.HOLD_TITANIUM,
                    "holding titanium tile",
                )

            for _, target_pos, _has_replaceable_structure, _ore_tile in ore_candidates:
                if (
                    current_pos.distance_squared(target_pos) <= action_radius_sq
                    and target_pos != current_pos
                ):
                    continue
                if not self._move_towards_action_range_with_roads(
                    target_pos,
                    action_radius_sq=action_radius_sq,
                    allow_direct_target_fallback=False,
                ):
                    continue
                return self._record_action(
                    BotAction.HOLD_TITANIUM,
                    "holding titanium tile",
                )

        allied_builder_positions = [
            unit_pos
            for unit_id, unit_type, unit_team, unit_pos in self.turn_nearby_unit_infos
            if unit_team == own_team
            and unit_type == EntityType.BUILDER_BOT
            and unit_id != current_id
        ]
        hold_targets: list[tuple[tuple[int, int, int, int, int], Position]] = []
        for _key, ore_pos, _has_allied_road, ore_tile in ore_candidates:
            occupying_builder_id = ore_tile.builder_bot_id
            if occupying_builder_id is not None and occupying_builder_id != current_id:
                continue
            if not self._should_claim_titanium_tile(
                ore_pos,
                current_pos,
                allied_builder_positions,
            ):
                continue

            staging_pos = self._get_best_action_staging_pos(ore_pos)
            if staging_pos is None:
                continue

            hold_key = (
                current_pos.distance_squared(staging_pos),
                staging_pos.x,
                staging_pos.y,
                ore_pos.x,
                ore_pos.y,
            )
            hold_targets.append((hold_key, staging_pos))

        if not hold_targets:
            return False

        hold_targets.sort(key=lambda target: target[0])
        staging_pos = hold_targets[0][1]
        if staging_pos == current_pos:
            return self._record_action(
                BotAction.HOLD_TITANIUM,
                "holding titanium tile",
            )

        if not self._move_towards_with_roads(staging_pos):
            return False

        return self._record_action(
            BotAction.HOLD_TITANIUM,
            "holding titanium tile",
        )

    def _get_titanium_adj_rank(self, ore_pos: Position, bot_pos: Position) -> int | None:
        """
        Return deterministic cardinal-adjacency precedence around a titanium tile.

        Precedence order is top, bottom, left, right. Non-cardinal-adjacent
        positions return `None`.
        """
        if bot_pos.x == ore_pos.x and bot_pos.y == ore_pos.y - 1:
            return 0  # top
        if bot_pos.x == ore_pos.x and bot_pos.y == ore_pos.y + 1:
            return 1  # bottom
        if bot_pos.x == ore_pos.x - 1 and bot_pos.y == ore_pos.y:
            return 2  # left
        if bot_pos.x == ore_pos.x + 1 and bot_pos.y == ore_pos.y:
            return 3  # right
        return None

    def _get_titanium_diag_rank(self, ore_pos: Position, bot_pos: Position) -> int | None:
        """
        Return deterministic diagonal-adjacency precedence around titanium.

        Diagonal precedence is NE, SE, SW, NW. Non-diagonal-adjacent
        positions return `None`.
        """
        if bot_pos.x == ore_pos.x + 1 and bot_pos.y == ore_pos.y - 1:
            return 0  # NE
        if bot_pos.x == ore_pos.x + 1 and bot_pos.y == ore_pos.y + 1:
            return 1  # SE
        if bot_pos.x == ore_pos.x - 1 and bot_pos.y == ore_pos.y + 1:
            return 2  # SW
        if bot_pos.x == ore_pos.x - 1 and bot_pos.y == ore_pos.y - 1:
            return 3  # NW
        return None

    def _should_claim_titanium_tile(
        self,
        ore_pos: Position,
        current_pos: Position,
        allied_builder_positions: list[Position],
    ) -> bool:
        """
        Decide whether this bot should claim holding responsibility for one ore tile.

        Cardinal-adjacent builders are preferred first using deterministic
        precedence top > bottom > left > right. If no other cardinal-adjacent
        builder exists, diagonal-adjacent builders are preferred next with
        precedence NE > SE > SW > NW.
        """
        current_rank = self._get_titanium_adj_rank(ore_pos, current_pos)
        other_adj_ranks = [
            rank
            for other_pos in allied_builder_positions
            if (rank := self._get_titanium_adj_rank(ore_pos, other_pos)) is not None
        ]
        if other_adj_ranks:
            if current_rank is None:
                return False
            return current_rank <= min(other_adj_ranks)

        if current_rank is not None:
            return True

        current_diag_rank = self._get_titanium_diag_rank(ore_pos, current_pos)
        other_diag_ranks = [
            rank
            for other_pos in allied_builder_positions
            if (rank := self._get_titanium_diag_rank(ore_pos, other_pos)) is not None
        ]
        if not other_diag_ranks:
            return True
        if current_diag_rank is None:
            return False
        return current_diag_rank <= min(other_diag_ranks)

    def get_enemy_core_pos(self) -> Position | None:
        """
        Infer the enemy core centre from map symmetry and visible information.

        The method first returns an actually visible enemy core if one is in
        sight. Otherwise it tests rotational and axis-reflection symmetries
        against the known static terrain in the cached map, stores every still
        valid enemy core candidate, and only marks the enemy core position as
        resolved when exactly one candidate remains.
        """
        current_round = (
            self.turn_round if self.turn_round >= 0 else self.ct.get_current_round()
        )
        if self._enemy_core_inference_round == current_round:
            return self.enemy_core_pos

        for building_id, building_type, building_team, building_pos in self.turn_nearby_building_infos:
            if building_type != EntityType.CORE:
                continue
            if building_team == self.turn_team:
                continue

            self.enemy_core_pos = building_pos
            self.enemy_core_pos_candidates = [self.enemy_core_pos]
            self._enemy_core_inference_round = current_round
            return self.enemy_core_pos

        if self.map is None:
            self.enemy_core_pos = None
            self.enemy_core_pos_candidates = []
            self._enemy_core_inference_round = current_round
            self._enemy_core_knowledge_revision = -1
            self._enemy_core_symmetry_modes = None
            return None

        if self.core_center_pos is None:
            self.find_core_center()
        if self.core_center_pos is None:
            self.enemy_core_pos = None
            self.enemy_core_pos_candidates = []
            self._enemy_core_inference_round = current_round
            self._enemy_core_knowledge_revision = -1
            self._enemy_core_symmetry_modes = None
            return None

        if self.enemy_core_pos is not None:
            self.enemy_core_pos_candidates = [self.enemy_core_pos]
            self._enemy_core_inference_round = current_round
            return self.enemy_core_pos

        width = self.map.width
        height = self.map.height
        own_core_pos = self.core_center_pos
        map_revision = self.map.knowledge_revision
        if map_revision < self._enemy_core_knowledge_revision:
            self._enemy_core_symmetry_modes = None
            self._enemy_core_knowledge_revision = -1

        if (
            self._enemy_core_symmetry_modes is not None
            and map_revision == self._enemy_core_knowledge_revision
        ):
            self._enemy_core_inference_round = current_round
            return self.enemy_core_pos

        matrix = self.map.matrix
        if self._enemy_core_symmetry_modes is None:
            symmetry_modes = {"rotation", "mirror_x", "mirror_y"}
            positions_to_check = self.map.known_positions
        else:
            symmetry_modes = set(self._enemy_core_symmetry_modes)
            positions_to_check = self.map.newly_known_positions

        for mode in tuple(symmetry_modes):
            is_valid_symmetry = True
            for x, y in positions_to_check:
                tile = matrix[x][y]
                if tile is None:
                    continue

                if mode == "rotation":
                    mirror_x = width - 1 - x
                    mirror_y = height - 1 - y
                elif mode == "mirror_x":
                    mirror_x = width - 1 - x
                    mirror_y = y
                else:
                    mirror_x = x
                    mirror_y = height - 1 - y

                mirrored_tile = matrix[mirror_x][mirror_y]
                if mirrored_tile is None:
                    continue
                if tile.environment != mirrored_tile.environment:
                    is_valid_symmetry = False
                    break

            if is_valid_symmetry:
                continue
            symmetry_modes.discard(mode)

        self._enemy_core_symmetry_modes = symmetry_modes
        self._enemy_core_knowledge_revision = map_revision

        valid_candidate_map: dict[tuple[int, int], Position] = {}
        if "rotation" in symmetry_modes:
            candidate_pos = Position(width - 1 - own_core_pos.x, height - 1 - own_core_pos.y)
            valid_candidate_map[(candidate_pos.x, candidate_pos.y)] = candidate_pos
        if "mirror_x" in symmetry_modes:
            candidate_pos = Position(width - 1 - own_core_pos.x, own_core_pos.y)
            valid_candidate_map[(candidate_pos.x, candidate_pos.y)] = candidate_pos
        if "mirror_y" in symmetry_modes:
            candidate_pos = Position(own_core_pos.x, height - 1 - own_core_pos.y)
            valid_candidate_map[(candidate_pos.x, candidate_pos.y)] = candidate_pos

        sorted_candidate_keys = sorted(valid_candidate_map)
        self.enemy_core_pos_candidates = [
            valid_candidate_map[candidate_key]
            for candidate_key in sorted_candidate_keys
        ]

        if len(self.enemy_core_pos_candidates) == 1:
            self.enemy_core_pos = self.enemy_core_pos_candidates[0]
            self._enemy_core_inference_round = current_round
            return self.enemy_core_pos

        self.enemy_core_pos = None
        self._enemy_core_inference_round = current_round
        return None

    def build_supplied_sentinel(self):
        pass


    # Builder scouting, patrol, and logistics continuation

    def _get_core_ring_positions(self, radius: int) -> list[Position]:
        """
        Return clockwise in-bounds positions on one square ring around the core.

        The ring uses Chebyshev distance to the core center. Radius `2` is the
        first ring outside the core footprint and larger radii expand outward.
        """
        if self.core_center_pos is None:
            return []
        if radius < 2:
            return []

        center_x = self.core_center_pos.x
        center_y = self.core_center_pos.y
        ring_positions: list[Position] = []

        top_y = center_y - radius
        bottom_y = center_y + radius
        left_x = center_x - radius
        right_x = center_x + radius

        for x in range(left_x, right_x + 1):
            pos = Position(x, top_y)
            if self._is_in_bounds(pos):
                ring_positions.append(pos)

        for y in range(top_y + 1, bottom_y + 1):
            pos = Position(right_x, y)
            if self._is_in_bounds(pos):
                ring_positions.append(pos)

        for x in range(right_x - 1, left_x - 1, -1):
            pos = Position(x, bottom_y)
            if self._is_in_bounds(pos):
                ring_positions.append(pos)

        for y in range(bottom_y - 1, top_y, -1):
            pos = Position(left_x, y)
            if self._is_in_bounds(pos):
                ring_positions.append(pos)

        return ring_positions

    def init_res_scout(self) -> bool:
        """
        Expand roads around the core in widening circular rings.

        The scout prefers tiles on the current core ring that do not yet have
        an allied road, walking clockwise by default and flipping direction
        when blocked. If a ring is already roaded, it gradually increases the
        scouting radius and continues the same pattern farther out.
        """
        if self.map is None:
            return False

        if self.core_center_pos is None:
            self.find_core_center()
        if self.core_center_pos is None:
            return self.bb_expand()

        current_pos = self.ct.get_position()
        own_team = self.ct.get_team()
        max_radius = max(self.map.width, self.map.height)
        if max_radius < 2:
            return False

        def is_walkable_ring_tile(pos: Position) -> bool:
            tile = self._get_known_map_tile(pos)
            if tile is None:
                return True
            if tile.environment == Environment.WALL:
                return False
            if tile.building_id is None:
                return True
            return (
                tile.building_type == EntityType.ROAD
                and tile.building_team == own_team
            )

        def has_owned_road(pos: Position) -> bool:
            tile = self._get_known_map_tile(pos)
            return (
                tile is not None
                and tile.building_type == EntityType.ROAD
                and tile.building_team == own_team
            )

        start_radius = max(2, min(self.init_res_scout_radius, max_radius))
        ring_count = max_radius - 1

        selected_radius: int | None = None
        selected_ring: list[Position] = []
        fallback_radius: int | None = None
        fallback_ring: list[Position] = []

        for offset in range(ring_count):
            radius = 2 + ((start_radius - 2 + offset) % ring_count)
            ring_positions = [
                pos
                for pos in self._get_core_ring_positions(radius)
                if is_walkable_ring_tile(pos)
            ]
            if not ring_positions:
                continue

            roadless_ring_positions = [
                pos for pos in ring_positions if not has_owned_road(pos)
            ]
            if roadless_ring_positions:
                selected_radius = radius
                selected_ring = ring_positions
                break

            if fallback_radius is None:
                fallback_radius = radius
                fallback_ring = ring_positions

        if selected_radius is None:
            if fallback_radius is None:
                return False
            selected_radius = fallback_radius
            selected_ring = fallback_ring

        self.init_res_scout_radius = selected_radius
        roadless_positions = [
            pos for pos in selected_ring if not has_owned_road(pos)
        ]
        target_pool = roadless_positions if roadless_positions else selected_ring
        if not target_pool:
            return False

        if current_pos in selected_ring:
            for step_sign in (
                1 if self.init_res_scout_clockwise else -1,
                -1 if self.init_res_scout_clockwise else 1,
            ):
                start_index = selected_ring.index(current_pos)
                for step in range(1, len(selected_ring) + 1):
                    next_pos = selected_ring[(start_index + step_sign * step) % len(selected_ring)]
                    if next_pos == current_pos:
                        continue
                    if roadless_positions and next_pos not in roadless_positions:
                        continue

                    move_direction = current_pos.direction_to(next_pos)
                    if move_direction == Direction.CENTRE:
                        continue
                    if not self._move_in_direction_with_roads(move_direction):
                        continue

                    self.init_res_scout_clockwise = step_sign == 1
                    return self._record_action(
                        BotAction.BB_SCOUT,
                        "init resource scouting",
                    )

        best_target_pos = min(
            target_pool,
            key=lambda pos: (
                0 if not has_owned_road(pos) else 1,
                current_pos.distance_squared(pos),
                pos.x,
                pos.y,
            ),
        )

        next_step_pos = self.map.get_next_field_for_target(best_target_pos)
        if next_step_pos is not None and next_step_pos != current_pos:
            move_direction = current_pos.direction_to(next_step_pos)
            if (
                move_direction != Direction.CENTRE
                and self._move_in_direction_with_roads(move_direction)
            ):
                return self._record_action(
                    BotAction.BB_SCOUT,
                    "init resource scouting",
                )

        if not self._move_towards_with_roads(best_target_pos):
            return False

        return self._record_action(
            BotAction.BB_SCOUT,
            "init resource scouting",
        )

    def bb_expand(self) -> bool:
        """
        Expand by scoring known tiles and fog frontier targets via a cached PQ.

        Candidate tiles are cached across turns in a priority queue and only
        touched candidates are re-scored each turn. Frontier tiles are highest
        priority, then known tiles not seen for longer. The method also reuses
        the previously selected target for a few rounds to avoid recomputing
        full scoring every turn while a bot is already moving toward one goal.
        """
        if self.map is None:
            return False

        current_pos = self.turn_position or self.ct.get_position()
        current_round = (
            self.turn_round if self.turn_round >= 0 else self.ct.get_current_round()
        )
        own_builder_id = self.turn_id if self.turn_id >= 0 else self.ct.get_id()
        current_x = current_pos.x
        current_y = current_pos.y
        visible_coords = {(pos.x, pos.y) for pos in self.turn_nearby_tiles}

        if self._expand_cached_map_size != (self.map.width, self.map.height):
            self._expand_heap.clear()
            self._expand_candidate_revision.clear()
            self._expand_known_candidates.clear()
            self._expand_frontier_candidates.clear()
            self._expand_revision_counter = 0
            self._expand_target_coord = None
            self._expand_target_round = -1
            self._expand_cached_map_size = (self.map.width, self.map.height)

        matrix = self.map.matrix
        width = self.map.width
        height = self.map.height
        known_candidates = self._expand_known_candidates
        frontier_candidates = self._expand_frontier_candidates
        candidate_revision = self._expand_candidate_revision
        expand_heap = self._expand_heap

        def is_known_reachable_tile(x: int, y: int) -> bool:
            tile = matrix[x][y]
            if tile is None:
                return False
            if tile.environment == Environment.WALL:
                return False
            if tile.building_id is not None and not tile.is_passable:
                return False
            if (
                tile.last_seen_round == current_round
                and tile.builder_bot_id is not None
                and tile.builder_bot_id != own_builder_id
            ):
                return False
            return True

        def is_expand_target_traversable(coord: tuple[int, int]) -> bool:
            x, y = coord
            tile = matrix[x][y]
            if tile is None:
                return True
            if tile.environment == Environment.WALL:
                return False
            if tile.building_id is not None and not tile.is_passable:
                return False
            if (
                tile.last_seen_round == current_round
                and tile.builder_bot_id is not None
                and tile.builder_bot_id != own_builder_id
            ):
                return False
            return True

        def is_frontier_tile(x: int, y: int) -> bool:
            if matrix[x][y] is not None:
                return False
            for shift_x, shift_y in FLOOD_FILL_SHIFTS:
                nx = x + shift_x
                ny = y + shift_y
                if nx < 0 or nx >= width or ny < 0 or ny >= height:
                    continue
                if is_known_reachable_tile(nx, ny):
                    return True
            return False

        def get_candidate_priority(coord: tuple[int, int]) -> tuple[int, int, int, int] | None:
            x, y = coord

            if coord in known_candidates:
                if not is_known_reachable_tile(x, y):
                    known_candidates.discard(coord)
                    candidate_revision.pop(coord, None)
                    return None
                tile = matrix[x][y]
                if tile is None:
                    known_candidates.discard(coord)
                    candidate_revision.pop(coord, None)
                    return None
                if coord in visible_coords:
                    return (2, 0, x, y)
                return (1, tile.last_seen_round, x, y)

            if coord in frontier_candidates:
                if not is_frontier_tile(x, y):
                    frontier_candidates.discard(coord)
                    candidate_revision.pop(coord, None)
                    return None
                return (0, 0, x, y)

            candidate_revision.pop(coord, None)
            return None

        def push_candidate(coord: tuple[int, int]) -> None:
            priority = get_candidate_priority(coord)
            if priority is None:
                return

            self._expand_revision_counter += 1
            revision = self._expand_revision_counter
            candidate_revision[coord] = revision
            heapq.heappush(
                expand_heap,
                (*priority, revision),
            )

        if self._expand_target_coord is not None:
            if (
                current_round - self._expand_target_round
                > BB_EXPAND_TARGET_REUSE_ROUNDS
            ):
                self._expand_target_coord = None
            else:
                target_x, target_y = self._expand_target_coord
                if target_x == current_x and target_y == current_y:
                    self._expand_target_coord = None
                elif is_expand_target_traversable(self._expand_target_coord):
                    target_pos = Position(target_x, target_y)
                    if self._move_towards_with_roads(target_pos):
                        self._expand_target_round = current_round
                        return self._record_action(
                            BotAction.BB_SCOUT,
                            "expanding territory",
                        )
                    self._expand_target_coord = None
                else:
                    self._expand_target_coord = None

        if not known_candidates and not frontier_candidates:
            for x, y in self.map.known_positions:
                known_coord = (x, y)
                known_candidates.add(known_coord)
                for shift_x, shift_y in FLOOD_FILL_SHIFTS:
                    nx = x + shift_x
                    ny = y + shift_y
                    if nx < 0 or nx >= width or ny < 0 or ny >= height:
                        continue
                    if matrix[nx][ny] is None:
                        frontier_candidates.add((nx, ny))

            for coord in tuple(known_candidates):
                push_candidate(coord)
            for coord in tuple(frontier_candidates):
                push_candidate(coord)

        touched_coords: set[tuple[int, int]] = set()
        for pos in self.turn_nearby_tiles:
            x = pos.x
            y = pos.y
            coord = (x, y)
            known_candidates.add(coord)
            frontier_candidates.discard(coord)
            touched_coords.add(coord)

            for shift_x, shift_y in FLOOD_FILL_SHIFTS:
                nx = x + shift_x
                ny = y + shift_y
                if nx < 0 or nx >= width or ny < 0 or ny >= height:
                    continue
                if matrix[nx][ny] is None:
                    frontier_coord = (nx, ny)
                    frontier_candidates.add(frontier_coord)
                    touched_coords.add(frontier_coord)

        for coord in touched_coords:
            push_candidate(coord)

        failed_coords: set[tuple[int, int]] = set()
        pop_attempts = 0
        max_pop_attempts = BB_EXPAND_MAX_POP_ATTEMPTS

        while expand_heap and pop_attempts < max_pop_attempts:
            pop_attempts += 1
            tier, aux, x, y, revision = heapq.heappop(expand_heap)
            coord = (x, y)

            if coord in failed_coords:
                continue

            if revision != candidate_revision.get(coord):
                continue

            priority = get_candidate_priority(coord)
            if priority is None:
                continue

            if priority != (tier, aux, x, y):
                push_candidate(coord)
                continue

            target_pos = Position(x, y)
            if target_pos == current_pos:
                continue

            if self._move_towards_with_roads(target_pos):
                self._expand_target_coord = coord
                self._expand_target_round = current_round
                for failed_coord in failed_coords:
                    push_candidate(failed_coord)
                return self._record_action(
                    BotAction.BB_SCOUT,
                    "expanding territory",
                )

            failed_coords.add(coord)

        for failed_coord in failed_coords:
            push_candidate(failed_coord)

        if not expand_heap:
            for coord in tuple(known_candidates):
                push_candidate(coord)
            for coord in tuple(frontier_candidates):
                push_candidate(coord)

            return False

        return False

    def harassment_scout(self) -> bool:
        """
        Advance toward the enemy core area instead of exploring randomly.

        If the exact enemy core location is known, the harassment builder heads
        there directly. Otherwise it keeps a randomly chosen possible enemy
        core location from the currently inferred candidates and moves toward
        that area, rebuilding the choice if the candidate set changes.
        """
        self.get_enemy_core_pos()

        if self.enemy_core_pos is not None:
            self.harassment_scout_target = self.enemy_core_pos
            candidate_targets = [self.enemy_core_pos]
        else:
            candidate_targets = list(self.enemy_core_pos_candidates)
            if not candidate_targets:
                return False

            if self.harassment_scout_target not in candidate_targets:
                self.harassment_scout_target = random.choice(candidate_targets)

            candidate_targets = [
                self.harassment_scout_target,
                *[
                    pos
                    for pos in candidate_targets
                    if pos != self.harassment_scout_target
                ],
            ]

        current_pos = self.ct.get_position()
        for target_pos in candidate_targets:
            if target_pos == current_pos and len(candidate_targets) > 1:
                continue
            if not self._move_towards_with_roads(target_pos):
                continue

            self.harassment_scout_target = target_pos
            return self._record_action(
                BotAction.HARASSMENT_SCOUT,
                "harassment scouting",
            )

        return False

    def _get_maintainer_patrol_targets(self) -> list[Position]:
        """
        Return all known walkable tiles that belong to the friendly base area.

        A base patrol tile is a known non-wall tile the builder can plausibly
        stand on and that either is an allied road or sits directly next to
        friendly infrastructure. The maintainer patrol then chooses among these
        global candidates using the hot-floor values instead of following a
        fixed waypoint loop.
        """
        if self.map is None:
            return []
        if self.core_center_pos is None:
            self.find_core_center()

        own_team = self.ct.get_team()
        patrol_targets: list[Position] = []

        for x, y in self.map.known_positions:
            tile = self.map.matrix[x][y]
            if tile is None or tile.environment == Environment.WALL:
                continue

            pos = Position(x, y)
            if self.core_center_pos is not None and (
                self.core_center_pos.x - 1 <= x <= self.core_center_pos.x + 1
                and self.core_center_pos.y - 1 <= y <= self.core_center_pos.y + 1
            ):
                continue

            is_walkable_target = (
                tile.building_id is None or tile.building_type == EntityType.ROAD
            )
            if not is_walkable_target:
                continue

            is_base_tile = (
                tile.building_type == EntityType.ROAD
                and tile.building_team == own_team
            )
            if not is_base_tile:
                for direction in DIRECTIONS:
                    neighbor_pos = pos.add(direction)
                    if not self._is_in_bounds(neighbor_pos):
                        continue

                    neighbor_tile = self._get_known_map_tile(neighbor_pos)
                    if neighbor_tile is None:
                        continue
                    if neighbor_tile.building_team != own_team:
                        continue

                    is_base_tile = True
                    break

            if not is_base_tile:
                continue

            patrol_targets.append(pos)

        return patrol_targets

    def maintainer_patrol(self) -> bool:
        """
        Patrol through the known friendly base instead of staying local.

        The maintainer considers every known base tile on the map and prefers
        nearby allied roads first, then other base tiles, with distance to the
        current position as the main tie-break. This keeps maintenance patrols
        simple and predictable while still covering the known base.
        """
        patrol_targets = self._get_maintainer_patrol_targets()
        if not patrol_targets:
            return False

        own_team = self.ct.get_team()
        current_pos = self.ct.get_position()
        best_target: tuple[tuple[int, int, int, int, int, int], Position] | None = None

        for target_pos in patrol_targets:
            if target_pos == current_pos:
                continue

            tile = self._get_known_map_tile(target_pos)
            if tile is None:
                continue

            is_owned_road = (
                tile.building_type == EntityType.ROAD
                and tile.building_team == own_team
            )
            candidate_key = (
                0 if is_owned_road else 1,
                current_pos.distance_squared(target_pos),
                -tile.distance_to_core,
                target_pos.x,
                target_pos.y,
            )
            if best_target is None or candidate_key < best_target[0]:
                best_target = (candidate_key, target_pos)

        if best_target is None:
            return False

        if not self._move_towards_with_roads(best_target[1]):
            return False

        return self._record_action(
            BotAction.MAINTAINER_PATROL,
            "patrolling base",
        )

    def _stamp_supply_patrol_coverage(self) -> None:
        """
        Stamp current and adjacent relevant supply tiles with patrol index.

        This writes the bot's current supply patrol index onto allied conveyor
        and bridge tiles in the local 8-neighborhood plus the current tile.
        """
        if self.map is None:
            return

        own_team = self.ct.get_team()
        current_pos = self.ct.get_position()
        patrol_relevant_types = {
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.BRIDGE,
        }
        coverage_positions = [current_pos] + [
            current_pos.add(direction) for direction in DIRECTIONS
        ]
        for pos in coverage_positions:
            if not self._is_in_bounds(pos):
                continue

            tile = self._get_known_map_tile(pos)
            if tile is None:
                continue
            if tile.building_team != own_team:
                continue
            if tile.building_type not in patrol_relevant_types:
                continue

            tile.last_patrolled_index = self.supply_patrol_index

    def _patrol_supply_chains(
        self,
        allow_road_building: bool,
        action: BotAction,
        message: str,
    ) -> bool:
        """
        Patrol outdated allied supply-chain tiles with optional road building.

        Each bot tracks one patrol index and relevant supply tiles remember the
        last index that touched them. The bot moves toward the closest known
        allied conveyor or bridge whose stored patrol index is still lower than
        its own. When no such tile is currently known, the bot advances its
        patrol index instead of forcing pointless movement.
        """
        if self.map is None:
            return False

        current_pos = self.turn_position or self.ct.get_position()
        self._stamp_supply_patrol_coverage()

        best_target: tuple[tuple[int, int, int, int], Position] | None = None
        for x, y in self.map.supply_link_positions:
            tile = self.map.matrix[x][y]
            if tile is None:
                continue
            if tile.last_patrolled_index >= self.supply_patrol_index:
                continue

            target_pos = Position(x, y)
            candidate_key = (
                current_pos.distance_squared(target_pos),
                tile.last_patrolled_index,
                target_pos.x,
                target_pos.y,
            )
            if best_target is None or candidate_key < best_target[0]:
                best_target = (candidate_key, target_pos)

        if best_target is None:
            self.supply_patrol_index += 1
            return False

        move_towards = (
            self._move_towards_with_roads
            if allow_road_building
            else self._move_towards_without_roads
        )
        if not move_towards(best_target[1]):
            return False

        return self._record_action(action, message)

    def patrol_supply_chains(self) -> bool:
        """
        Patrol allied supply-chain tiles using an ever-increasing patrol index.

        The defender tracks one global patrol index and each relevant known
        supply tile stores its last patrolled index. Every turn this method is
        called, the defender stamps its current tile and all adjacent tiles
        with its current patrol index when those tiles are allied conveyors or
        bridges. While at least one relevant tile has a lower stored index than
        the defender's current index, the defender moves toward the closest
        such outdated tile. If no outdated relevant tile is currently known, it
        advances its own patrol index by one.
        """
        return self._patrol_supply_chains(
            allow_road_building=True,
            action=BotAction.PATROL_SUPPLY_CHAINS,
            message="patrolling supply chains",
        )

    def scavenger_patrol_supply_chains(self) -> bool:
        """
        Recover on allied supply chains without spending titanium on movement.

        Low-resource scavengers reuse the same patrol-index logic as defenders,
        but they only move across already walkable known tiles. This keeps them
        active inside the supply network while avoiding new road costs until the
        titanium stock recovers.
        """
        return self._patrol_supply_chains(
            allow_road_building=False,
            action=BotAction.SCAVENGER_PATROL_SUPPLY_CHAINS,
            message="recovering on supply chains",
        )

    def complete_supply_chain(self) -> bool:
        """
        Continue a recently started supply chain until it reconnects inward.

        The method only triggers when the previous turn ended with a
        supply-chain continuation action. It looks for a visible allied bridge
        or conveyor whose output tile is still unknown in the cached map, or is
        known but not yet occupied by another allied supply link. If the
        missing continuation tile is buildable and in action range, it extends
        the chain there; when the tile is a road, it first clears the road and
        then places the next link on a following turn. Existing
        allied downstream conveyors or bridges already count as a valid
        continuation and are skipped. Otherwise it moves toward a tile that can
        place the continuation while building roads on the way.
        """
        if self.map is None:
            return False
        titanium, _ = self.turn_resources
        if titanium < CHAIN_BRIDGE_MIN_TITANIUM_THRESHOLD:
            return False
        if self.previous_action not in {
            BotAction.BUILD_HARVESTER_BRIDGE,
            BotAction.BUILD_MISSING_BRIDGE,
            BotAction.COMPLETE_SUPPLY_CHAIN,
        }:
            return False

        current_pos = self.turn_position or self.ct.get_position()
        actionable_candidates: list[
            tuple[
                tuple[int, int, int, int, int, int, int],
                Position,
                Position,
                bool,
                bool,
            ]
        ] = []
        movement_candidates: list[
            tuple[tuple[int, int, int, int, int, int], Position]
        ] = []

        for link_id, link_type, link_team, link_pos in self.turn_nearby_building_infos:
            if not self._is_supply_link_type(link_type):
                continue
            if link_team != self.turn_team:
                continue

            target_pos = self._get_supply_link_output_pos(link_id)
            if target_pos is None:
                continue
            if not self._is_in_bounds(target_pos):
                continue

            tile = self._get_known_map_tile(target_pos)
            if tile is None:
                candidate_key = (
                    current_pos.distance_squared(target_pos),
                    target_pos.x,
                    target_pos.y,
                    link_pos.x,
                    link_pos.y,
                    link_id,
                )
                movement_candidates.append((candidate_key, target_pos))
                continue

            if self._is_allied_supply_link_tile(tile):
                continue
            if tile.environment != Environment.EMPTY:
                continue

            is_empty_build_pos = tile.building_id is None
            is_road_build_pos = tile.building_type == EntityType.ROAD
            if not (is_empty_build_pos or is_road_build_pos):
                continue

            target_plan = self._get_supply_link_plan(target_pos)
            if target_plan is None:
                continue
            next_target_pos, use_bridge = target_plan

            build_pos_type_rank = 0 if is_empty_build_pos else 1
            candidate_key = (
                current_pos.distance_squared(target_pos),
                build_pos_type_rank,
                target_pos.x,
                target_pos.y,
                link_pos.x,
                link_pos.y,
                link_id,
            )
            if current_pos.distance_squared(target_pos) <= 2:
                if self._is_supply_output_tile_unsafe(
                    target_pos,
                    next_target_pos,
                    use_bridge,
                ):
                    continue
                if is_road_build_pos:
                    if not self._can_destroy_tile(target_pos):
                        movement_candidates.append((candidate_key, target_pos))
                        continue
                else:
                    buildable_plan = self._get_buildable_supply_link_plan(
                        target_pos,
                        next_target_pos,
                        use_bridge,
                    )
                    if buildable_plan is None:
                        movement_candidates.append((candidate_key, target_pos))
                        continue
                    next_target_pos, use_bridge = buildable_plan

                if target_pos == current_pos:
                    movement_candidates.append((candidate_key, target_pos))
                    continue
                actionable_candidates.append(
                    (
                        candidate_key,
                        target_pos,
                        next_target_pos,
                        is_road_build_pos,
                        use_bridge,
                    )
                )
                continue

            movement_candidates.append((candidate_key, target_pos))

        if actionable_candidates:
            actionable_candidates.sort(key=lambda candidate: candidate[0])
            _, build_pos, target_pos, is_road_build_pos, use_bridge = actionable_candidates[0]
            if not self._build_supply_link_with_optional_road_removal(
                build_pos,
                target_pos,
                is_road_build_pos,
                use_bridge,
            ):
                return False

            return self._record_action(
                BotAction.COMPLETE_SUPPLY_CHAIN,
                "completing supply chain",
            )

        if not movement_candidates:
            return False

        movement_candidates.sort(key=lambda candidate: candidate[0])
        target_build_pos = movement_candidates[0][1]
        if (
            target_build_pos != current_pos
            and current_pos.distance_squared(target_build_pos) <= 2
        ):
            return self._record_action(
                BotAction.COMPLETE_SUPPLY_CHAIN,
                "completing supply chain",
            )

        if not self._move_towards_action_range_with_roads(
            target_build_pos,
            action_radius_sq=2,
            allow_direct_target_fallback=False,
        ):
            if (
                target_build_pos != current_pos
                and current_pos.distance_squared(target_build_pos) <= 2
            ):
                return self._record_action(
                    BotAction.COMPLETE_SUPPLY_CHAIN,
                    "completing supply chain",
                )
            return False

        return self._record_action(
            BotAction.COMPLETE_SUPPLY_CHAIN,
            "completing supply chain",
        )



class Player(Bot):
    pass


INITIAL_BB = [
    Bot.run_bb_init_res,
    Bot.run_bb_harassment,
    CoreSpawnEvent.FIRST_RESOURCE_INCREASE,
    Bot.run_bb_scavenger,
    Bot.run_bb_scavenger,
    Bot.run_bb_scavenger,
    CoreSpawnTurnEvent(150),
    CoreSpawnEvent.ENEMY_BOT_IN_CORE_VISION,
    Bot.run_bb_defender,
]
CORE_TILE_BB_ROLE = {
    (-1, -1): Bot.run_bb_scavenger,
    (0, -1): Bot.run_bb_harassment,
    (1, -1): Bot.run_bb_defender,
    (-1, 0): Bot.run_bb_scavenger,
    (0, 0): Bot.run_bb_scavenger,
    (1, 0): Bot.run_bb_harassment,
    (-1, 1): Bot.run_bb_scavenger,
    (0, 1): Bot.run_bb_init_res,
    (1, 1): Bot.run_bb_defender,
}
