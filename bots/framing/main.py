from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
import random
import time
from cambc import Controller, Direction, EntityType, Environment, Position, Team

INFINITE_DISTANCE = 10**9
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
EXTRACTOR_MIN_TITANIUM_THRESHOLD = 300
ENEMY_HARVESTER_SENTINEL_MIN_TITANIUM_THRESHOLD = 300
FURTHER_BB_THRESHOLD = 600
SCAVENGER_ACTIVE_TITANIUM_THRESHOLD = 200
MAX_BOTS = 3
MAX_HARVESTORS = 999
SURRENDER_AT_TURN = 300

SENTINEL_TARGET_PRIORITY = [
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.CORE,
    EntityType.BUILDER_BOT,
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.LAUNCHER,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.FOUNDRY,
    EntityType.ROAD,
    EntityType.BARRIER,
    EntityType.MARKER,
]
GUNNER_TARGET_PRIORITY = [
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.CORE,
    EntityType.BUILDER_BOT,
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.LAUNCHER,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.FOUNDRY,
    EntityType.ROAD,
    EntityType.BARRIER,
    EntityType.MARKER,
]
BREACH_TARGET_PRIORITY = [
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.CORE,
    EntityType.BUILDER_BOT,
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.LAUNCHER,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.FOUNDRY,
    EntityType.ROAD,
    EntityType.BARRIER,
    EntityType.MARKER,
]


class BotAction(Enum):
    NONE = auto()
    SPAWN_BUILDER = auto()
    ATTACK_ENEMY_HARVESTER = auto()
    ATTACK_ENEMY_BRIDGE = auto()
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
    PROTECT_HARVESTER = auto()
    HOLD_PROTECT_HARVESTER = auto()
    BUILD_EXTRACTOR = auto()
    HOLD_TITANIUM = auto()
    BB_SCOUT = auto()


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

    def update_from_controller(self, ct: Controller) -> None:
        """
        Refresh this tile from the latest controller state.

        The update records the current terrain, building occupancy, and builder
        bot occupancy for the tile, including the owning team for any present
        building or builder bot.
        """
        self.environment = ct.get_tile_env(self.position)
        self.building_id = ct.get_tile_building_id(self.position)
        self.builder_bot_id = ct.get_tile_builder_bot_id(self.position)

        if self.building_id is None:
            self.building_type = None
            self.building_team = None
        else:
            self.building_type = ct.get_entity_type(self.building_id)
            self.building_team = ct.get_team(self.building_id)

        if self.builder_bot_id is None:
            self.builder_bot_team = None
        else:
            self.builder_bot_team = ct.get_team(self.builder_bot_id)


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

    def update_vision(self) -> None:
        """
        Merge currently visible map information into the cache.

        Visible tiles are created or refreshed in place, and the cached
        distance-to-core values are recomputed when the known wall layout or
        visible core position changes. Friendly harvester ids seen in vision
        are remembered so the bot can track how many harvesters are known to
        have been built so far.
        """
        distance_dirty = self._update_core_center_pos()
        visible_positions = self.ct.get_nearby_tiles()

        for pos in visible_positions:
            x = pos.x
            y = pos.y
            environment = self.ct.get_tile_env(pos)
            tile = self.matrix[x][y]

            if tile is None:
                tile = Tile(
                    position=pos,
                    environment=environment,
                    distance_to_core=INFINITE_DISTANCE,
                )
                self.matrix[x][y] = tile
                if environment == Environment.WALL:
                    distance_dirty = True
            elif tile.environment != environment and (
                tile.environment == Environment.WALL or environment == Environment.WALL
            ):
                distance_dirty = True

            tile.update_from_controller(self.ct)
            if (
                tile.building_id is not None
                and tile.building_type == EntityType.HARVESTER
                and tile.building_team == self.ct.get_team()
            ):
                self.known_harvester_ids.add(tile.building_id)

        self.known_harvesters_built = len(self.known_harvester_ids)

        if distance_dirty:
            self._refresh_distance_matrix()
            self._apply_distances_to_known_tiles()
            return

        for pos in visible_positions:
            tile = self.matrix[pos.x][pos.y]
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

    def _update_core_center_pos(self) -> bool:
        """
        Refresh the cached allied core centre if it is currently visible.

        The method returns whether the cached value changed, which lets callers
        decide whether dependent distance information needs to be recomputed.
        """
        core_center_pos = self._find_visible_core_center()
        if core_center_pos is None or core_center_pos == self.core_center_pos:
            return False

        self.core_center_pos = core_center_pos
        return True

    def _find_visible_core_center(self) -> Position | None:
        """
        Find the allied core centre from currently visible information.

        The search first checks the bot's current tile, then scans nearby
        buildings for a friendly core and returns its centre position if found.
        """
        current_pos = self.ct.get_position()
        building_id = self.ct.get_tile_building_id(current_pos)
        if (
            building_id is not None
            and self.ct.get_entity_type(building_id) == EntityType.CORE
            and self.ct.get_team(building_id) == self.ct.get_team()
        ):
            return self.ct.get_position(building_id)

        for building_id in self.ct.get_nearby_buildings():
            if (
                self.ct.get_entity_type(building_id) == EntityType.CORE
                and self.ct.get_team(building_id) == self.ct.get_team()
            ):
                return self.ct.get_position(building_id)

        return None

    def _refresh_distance_matrix(self) -> None:
        """
        Recompute flood-fill distances from the allied core.

        The fill starts from all nine core tiles and treats only permanent wall
        tiles as blocked, leaving every other known or unknown tile passable.
        """
        self.distance_matrix = self._create_distance_matrix()
        if self.core_center_pos is None:
            return

        queue = deque()
        for x, y in self._get_core_tiles():
            if self._is_wall(x, y):
                continue

            self.distance_matrix[x][y] = 0
            queue.append((x, y))

        while queue:
            x, y = queue.popleft()
            next_distance = self.distance_matrix[x][y] + 1

            for shift_x, shift_y in FLOOD_FILL_SHIFTS:
                new_x = x + shift_x
                new_y = y + shift_y

                if not self._is_in_bounds(new_x, new_y):
                    continue
                if self._is_wall(new_x, new_y):
                    continue
                if next_distance >= self.distance_matrix[new_x][new_y]:
                    continue

                self.distance_matrix[new_x][new_y] = next_distance
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
        for x, column in enumerate(self.matrix):
            for y, tile in enumerate(column):
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

    def get_next_field_for_target(self, target_pos: Position) -> Position | None:
        """
        Return the next path step toward a target tile while avoiding known walls.

        The search runs a grid BFS from the current bot position stored in this
        map's controller and treats unknown tiles as passable. It returns the
        first tile on the shortest discovered path to `target_pos`, or `None`
        when no path can currently be found or the target lies outside the map.
        """
        start_pos = self.ct.get_position()
        start_key = (start_pos.x, start_pos.y)
        target_key = (target_pos.x, target_pos.y)

        if not self._is_in_bounds(*start_key):
            return None
        if not self._is_in_bounds(*target_key):
            return None
        if start_key == target_key:
            return start_pos

        target_tile = self.matrix[target_pos.x][target_pos.y]
        if target_tile is not None and target_tile.environment == Environment.WALL:
            return None

        queue = deque([start_key])
        visited = {start_key}
        parent: dict[tuple[int, int], tuple[int, int]] = {}

        found = False
        while queue:
            x, y = queue.popleft()
            if (x, y) == target_key:
                found = True
                break

            for shift_x, shift_y in FLOOD_FILL_SHIFTS:
                new_x = x + shift_x
                new_y = y + shift_y
                if not self._is_in_bounds(new_x, new_y):
                    continue

                next_key = (new_x, new_y)
                if next_key in visited:
                    continue

                next_tile = self.matrix[new_x][new_y]
                if next_tile is not None and next_tile.environment == Environment.WALL:
                    continue

                visited.add(next_key)
                parent[next_key] = (x, y)
                queue.append(next_key)

        if not found:
            return None

        step_key = target_key
        while parent.get(step_key) is not None and parent[step_key] != start_key:
            step_key = parent[step_key]

        if parent.get(step_key) is None:
            return None

        return Position(step_key[0], step_key[1])


class Bot:
    # Builder lifecycle and role selection

    def __init__(self):
        """
        Initialise persistent per-unit bot state.

        The bot stores controller-linked helpers, builder-role state, and the
        cached allied core position so this information survives across rounds.
        """
        self.core_bbs_spawned = 0  # number of builder bots spawned so far (core)
        self.ct: Controller | None = None
        self.map: Map | None = None
        self.bb_handler = None
        self.core_center_pos: Position | None = None
        self.enemy_core_pos: Position | None = None
        self.enemy_core_pos_candidates: list[Position] = []
        self.harassment_scout_target: Position | None = None
        self.previous_action = BotAction.NONE
        self.last_action = BotAction.NONE

    def initialize_bb(self):
        """
        Initialise builder-specific cached state on its first turn.

        This creates the builder-local map cache, performs an immediate vision
        update, and adopts the cached core position when it is available.
        """
        self.map = Map(self.ct)
        self.map.update_vision()
        if self.map.core_center_pos is not None:
            self.core_center_pos = self.map.core_center_pos

    def update_bb_map(self):
        """
        Refresh the builder-local map cache for the current turn.

        The method initialises the cache on first use, otherwise swaps in the
        latest controller and updates visible map information in place. It also
        prints the time spent on the map update for this unit and turn.
        """
        map_update_start = time.perf_counter_ns()
        if self.map is None:
            self.initialize_bb()
        else:
            self.map.update_controller(self.ct)
            self.map.update_vision()
        if self.map.core_center_pos is not None:
            self.core_center_pos = self.map.core_center_pos
        map_update_elapsed = time.perf_counter_ns() - map_update_start
        print(
            f"Unit {self.ct.get_id()} map update took {map_update_elapsed / 1000}mus"
        )

    def get_initial_bb_handler(self):
        """
        Choose the builder's initial role handler.

        The selection uses the current round index to map early builders onto
        predefined opening roles and falls back to the configured post-opening
        builder role later.
        """
        round_index = self.ct.get_current_round() - 1
        if 0 <= round_index < len(INITIAL_BB):
            return INITIAL_BB[round_index].__get__(self, type(self))
        return FURTHER_BB.__get__(self, type(self))

    def get_bb_handler_name(self) -> str:
        """
        Return the current builder role as a short human-readable label.

        The method maps the active bound handler to the role name used in logs
        so builder turns can announce whether they are acting as maintainers,
        scavengers, harassment units, and so on.
        """
        if self.bb_handler is None:
            return "unassigned"

        handler_func = getattr(self.bb_handler, "__func__", self.bb_handler)
        handler_names = {
            Bot.run_bb_maintainer: "maintainer",
            Bot.run_bb_scavenger: "scavenger",
            Bot.run_bb_harassment: "harassment",
            Bot.run_bb_unassigned: "unassigned",
        }
        return handler_names.get(handler_func, handler_func.__name__)

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
        etype = self.ct.get_entity_type()
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
            print(f"Unit {self.ct.get_id()} turn took {self.get_ns_elapsed() / 1000}mus")

    def run_core(self):
        """
        Execute the core's turn logic.

        The current implementation only handles opening builder production and
        spawns initial builders on random adjacent core tiles while slots remain.
        After the opening, it continues spawning builders whenever the team has
        at least `FURTHER_BB_THRESHOLD` titanium available, but never after the
        core has already spawned `MAX_BOTS` builder bots in total.
        """
        if self.core_bbs_spawned >= MAX_BOTS:
            return

        titanium, _ = self.ct.get_global_resources()
        should_spawn = self.core_bbs_spawned < len(INITIAL_BB)
        if not should_spawn and titanium < FURTHER_BB_THRESHOLD:
            return

        spawn_directions = DIRECTIONS[:]
        random.shuffle(spawn_directions)
        for direction in spawn_directions:
            spawn_pos = self.ct.get_position().add(direction)
            if not self.ct.can_spawn(spawn_pos):
                continue

            self.ct.spawn_builder(spawn_pos)
            self.core_bbs_spawned += 1
            self.last_action = BotAction.SPAWN_BUILDER
            return

    def run_bb(self):
        """
        Execute the builder bot's turn logic.

        The method ensures the role handler is initialised, prints the builder
        role for this turn, refreshes the builder-local map cache, and then
        runs the selected handler.
        """
        if self.bb_handler is None:
            self.bb_handler = self.get_initial_bb_handler()

        print(f"builder type: {self.get_bb_handler_name()}")
        self.update_bb_map()

        if self.core_center_pos is None:
            self.find_core_center()

        self.bb_handler()

    def run_bb_maintainer(self):
        """
        Execute the maintainer builder role for the current turn.

        The maintainer prioritises harvester pressure, repairing friendly
        structures, restoring bridge links, clearing compromised logistics,
        protecting owned harvesters, and opportunistically expanding resource
        extraction before falling back to a patrol through the known base.
        """
        if self.complete_supply_chain():
            return

        if self.attack_enemy_harvester():
            return

        if self.repair_if_damaged():
            return

        if self.build_harvester_bridge():
            return

        if self.build_missing_bridge():
            return

        if self.destroy_hijacked_reschain():
            return

        if self.protect_harvester():
            return

        if self.build_extractor():
            return

        self.maintainer_patrol()

    def run_bb_scavenger(self):
        """
        Execute the scavenger builder role for the current turn.

        The scavenger currently shares the maintainer's disruption and logistics
        checks, then also considers expanding resource extraction. When team
        titanium is low, it stops aggressive scouting and chills in the base
        instead of spending more resources on frontier expansion. If it has
        already found a free visible titanium tile but cannot yet build there,
        it holds that resource instead of continuing to scout away from it.
        Likewise, when a bridge chain clearly wants to continue but titanium is
        still missing, the scavenger waits near the gap instead of wandering
        into unrelated fallback behavior.
        """
        if self.destroy_hijacked_reschain():
            return
        
        if self.build_harvester_bridge():
            return
        
        if self.hold_build_harvester_bridge():
            return
        
        if self.protect_harvester():
            return
        
        if self.hold_protect_harvester():
            return
        
        if self.complete_supply_chain():
            return

        if self.build_missing_bridge():
            return

        if self.hold_missing_bridge():
            return

        if self.attack_enemy_harvester():
            return

        if self.build_extractor():
            return

        if self.hold_visible_titanium():
            return

        titanium, _ = self.ct.get_global_resources()
        if titanium < SCAVENGER_ACTIVE_TITANIUM_THRESHOLD:
            self.maintainer_patrol()
            return

        self.bb_scout()

    def run_bb_harassment(self):
        """
        Execute the harassment builder role for the current turn.

        The harassment flow estimates enemy core information, sabotages visible
        enemy bridges, applies the harvester-pressure routine, and looks for
        sentinel placements that can interfere with enemy logistics around
        exposed harvesters. When no other action triggers, it advances toward
        the inferred enemy core area.
        """
        # calc poss. enemy core locations
        #   -> infer possible enemy core locations from own core location and map size
        self.get_enemy_core_pos()

        # build gunner if poss. next to enemy extractor
        if self.attack_enemy_harvester():
            return

        # is there a spot either next to enemy harvester or
        # so that enemy resources will flow into the sentinel?
        # then build a sentinel there
        if self.build_supplied_sentinel():
            return

        if self.attack_enemy_bridge():
            return

        self.harassment_scout()

    def run_bb_unassigned(self):
        """
        Fall back to safe generic builder behavior when no role is assigned.

        An unassigned builder first takes obvious extractor opportunities, then
        uses the normal scout fallback, and finally chills in the base instead
        of idling completely.
        """
        if self.build_extractor():
            return
        if self.bb_scout():
            return
        self.maintainer_patrol()

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
        # throw away enemy bots
        #   -> to own turret if available
        #   -> otherwise just maximize distance from the core
        # throw own bot for lane traversal
        pass

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
        return 0 <= pos.x < self.ct.get_map_width() and 0 <= pos.y < self.ct.get_map_height()

    def _get_known_map_tile(self, pos: Position) -> Tile | None:
        """
        Return the cached tile object for an in-bounds position if one exists.

        Unknown positions or bots without a local map cache return `None`, so
        callers can safely use this helper before reading cached tile data.
        """
        if self.map is None or not self._is_in_bounds(pos):
            return None
        return self.map.matrix[pos.x][pos.y]

    def _is_adjacent_to_allied_harvester(self, pos: Position) -> bool:
        """
        Check whether a tile is orthogonally adjacent to a friendly harvester.

        This is used to keep generic chain continuation separate from the
        dedicated `build_harvester_bridge` behavior.
        """
        if self.map is None:
            return False

        own_team = self.ct.get_team()
        for direction in CARDINAL_DIRECTIONS:
            adjacent_pos = pos.add(direction)
            if not self._is_in_bounds(adjacent_pos):
                continue

            adjacent_tile = self._get_known_map_tile(adjacent_pos)
            if adjacent_tile is None:
                continue
            if adjacent_tile.building_type != EntityType.HARVESTER:
                continue
            if adjacent_tile.building_team != own_team:
                continue
            return True

        return False

    def _record_action(self, action: BotAction, message: str) -> bool:
        """
        Persist a successful action and emit the matching debug message.

        Builder decision methods use this helper so action tracking and
        human-readable tracing stay consistent across the bot.
        """
        self.last_action = action
        print(message)
        return True

    def _can_destroy_tile(self, pos: Position) -> bool:
        """
        Check whether the bot can safely destroy the tile at a position.

        The bot never destroys the tile it currently occupies and also avoids
        destroying a visible tile that is currently occupied by another builder
        bot.
        """
        if pos == self.ct.get_position():
            return False
        if self.ct.is_in_vision(pos):
            occupying_builder_id = self.ct.get_tile_builder_bot_id(pos)
            if occupying_builder_id is not None:
                return False
        return self.ct.can_destroy(pos)

    def _build_bridge_with_optional_road_removal(
        self,
        build_pos: Position,
        target_pos: Position,
        is_road_build_pos: bool,
    ) -> bool:
        """
        Build a bridge on an empty tile or prepare one by clearing a road first.

        If the destination already contains a road, the road is removed and the
        bridge is also placed in the same turn whenever that immediately
        becomes legal. On empty tiles, the method only succeeds when the bridge
        build itself is currently legal.
        """
        if is_road_build_pos:
            if not self._can_destroy_tile(build_pos):
                return False
            self.ct.destroy(build_pos)
            if self.ct.can_build_bridge(build_pos, target_pos):
                self.ct.build_bridge(build_pos, target_pos)
            return True

        if not self.ct.can_build_bridge(build_pos, target_pos):
            return False

        self.ct.build_bridge(build_pos, target_pos)
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
        current_pos = self.ct.get_position()
        next_pos = current_pos.add(direction)
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

    def _move_towards_with_roads(self, target_pos: Position) -> bool:
        """
        Advance one step toward a target while preparing the chosen path tile.

        The method scores adjacent non-wall tiles by whether they improve the
        distance to the target and whether the builder can both road and move,
        move only, or road only. This keeps movement goal-directed while
        remaining simple and predictable.
        """
        current_pos = self.ct.get_position()
        current_distance_sq = current_pos.distance_squared(target_pos)
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
        current_pos = self.ct.get_position()

        candidate_tiles: list[
            tuple[tuple[int, int, int, int, int, int], Position, Position]
        ] = []

        for entity_id in self.ct.get_nearby_buildings():
            if self.ct.get_entity_type(entity_id) != EntityType.HARVESTER:
                continue
            if self.ct.get_team(entity_id) == self.ct.get_team():
                continue

            harvester_pos = self.ct.get_position(entity_id)
            has_adjacent_sentinel = False
            empty_candidate_tiles: list[Position] = []

            for direction in CARDINAL_DIRECTIONS:
                candidate_pos = harvester_pos.add(direction)
                if not self._is_in_bounds(candidate_pos):
                    continue
                if not self.ct.is_in_vision(candidate_pos):
                    continue

                tile = self._get_known_map_tile(candidate_pos)
                if tile is None:
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

        if not candidate_tiles:
            return False

        candidate_tiles.sort(key=lambda candidate: candidate[0])
        self.get_enemy_core_pos()

        possible_enemy_core_tiles: list[Position] = []
        possible_enemy_core_centers = []
        if self.enemy_core_pos is not None:
            possible_enemy_core_centers = [self.enemy_core_pos]
        elif self.enemy_core_pos_candidates:
            possible_enemy_core_centers = self.enemy_core_pos_candidates

        for core_center_pos in possible_enemy_core_centers:
            for core_tile in self._get_core_target_tiles(core_center_pos):
                if core_tile not in possible_enemy_core_tiles:
                    possible_enemy_core_tiles.append(core_tile)

        titanium, _ = self.ct.get_global_resources()
        if titanium >= ENEMY_HARVESTER_SENTINEL_MIN_TITANIUM_THRESHOLD:
            for _, candidate_pos, harvester_pos in candidate_tiles:
                direct_direction = candidate_pos.direction_to(harvester_pos)
                buildable_diagonal_directions = []
                for sentinel_direction in [
                    direct_direction.rotate_left(),
                    direct_direction.rotate_right(),
                ]:
                    if not self.ct.can_build_sentinel(candidate_pos, sentinel_direction):
                        continue
                    buildable_diagonal_directions.append(sentinel_direction)

                preferred_directions = [
                    sentinel_direction
                    for sentinel_direction in buildable_diagonal_directions
                    if any(
                        self._sentinel_direction_covers_target(
                            candidate_pos,
                            sentinel_direction,
                            core_tile,
                        )
                        for core_tile in possible_enemy_core_tiles
                    )
                ]
                candidate_directions = (
                    preferred_directions or buildable_diagonal_directions
                )

                for sentinel_direction in candidate_directions:
                    self.ct.build_sentinel(candidate_pos, sentinel_direction)
                    return self._record_action(
                        BotAction.ATTACK_ENEMY_HARVESTER,
                        "attacking enemy harvester",
                    )

        for _, candidate_pos, _ in candidate_tiles:
            if current_pos.distance_squared(candidate_pos) <= action_radius_sq:
                continue

            if not self._move_towards_with_roads(candidate_pos):
                continue

            return self._record_action(
                BotAction.ATTACK_ENEMY_HARVESTER,
                "attacking enemy harvester",
            )

        return False

    def attack_enemy_bridge(self) -> bool:
        """
        Climb onto a visible enemy bridge and hold it in place.

        If the builder is already standing on an enemy bridge, it stays there
        to interfere with that logistics tile instead of using an own-tile
        attack. This avoids builders disappearing after removing the tile under
        themselves. Otherwise it moves toward the closest visible enemy bridge,
        preparing the path with roads when useful.
        """
        current_pos = self.ct.get_position()

        current_building_id = self.ct.get_tile_building_id(current_pos)
        if (
            current_building_id is not None
            and self.ct.get_entity_type(current_building_id) == EntityType.BRIDGE
            and self.ct.get_team(current_building_id) != self.ct.get_team()
        ):
            return self._record_action(
                BotAction.ATTACK_ENEMY_BRIDGE,
                "holding enemy bridge",
            )

        bridge_targets: list[tuple[tuple[int, int, int, int], Position]] = []
        for building_id in self.ct.get_nearby_buildings():
            if self.ct.get_entity_type(building_id) != EntityType.BRIDGE:
                continue
            if self.ct.get_team(building_id) == self.ct.get_team():
                continue

            bridge_pos = self.ct.get_position(building_id)
            candidate_key = (
                current_pos.distance_squared(bridge_pos),
                bridge_pos.x,
                bridge_pos.y,
                building_id,
            )
            bridge_targets.append((candidate_key, bridge_pos))

        if not bridge_targets:
            return False

        bridge_targets.sort(key=lambda candidate: candidate[0])
        target_pos = bridge_targets[0][1]
        if not self._move_towards_with_roads(target_pos):
            return False

        return self._record_action(
            BotAction.ATTACK_ENEMY_BRIDGE,
            "attacking enemy bridge",
        )

    def repair_if_damaged(self, check_vision_radius: bool = False) -> bool:
        """
        Heal a damaged friendly building on the current tile when possible.

        If `check_vision_radius` is true and no immediate heal is performed, the
        builder also searches visible friendly damaged buildings that it could
        stand on and advances toward the closest one, building a road first when
        that path still needs to be prepared.
        """
        current_pos = self.ct.get_position()
        titanium, _ = self.ct.get_global_resources()

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
        for building_id in self.ct.get_nearby_buildings():
            if self.ct.get_team(building_id) != self.ct.get_team():
                continue
            if self.ct.get_hp(building_id) >= self.ct.get_max_hp(building_id):
                continue

            building_pos = self.ct.get_position(building_id)
            if not self.ct.is_tile_passable(building_pos):
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
        Return the best target tile for an existing bridge to point at.

        If the bridge can point directly onto the allied core footprint, an
        in-range core tile is returned immediately. Otherwise, prefer an
        already existing allied bridge in range whose stored distance to the
        core is strictly smaller than the originating bridge tile's distance.
        If no such bridge exists, among all known tiles within bridge range,
        prefer the buildable tile with the smallest stored distance to the
        core. When multiple candidates are equally good strategically, the
        bridge prefers the farther legal target so it uses as much of the
        bridge's range as possible. Empty tiles are still preferred over roads
        or markers when the stored distance is tied.
        """
        if self.map is None:
            return None

        bridge_target_radius_sq = 9
        origin_distance_to_core = self.map.distance_matrix[bridge_pos.x][bridge_pos.y]
        origin_tile = self.map.matrix[bridge_pos.x][bridge_pos.y]
        if origin_tile is not None:
            origin_distance_to_core = origin_tile.distance_to_core

        if self.core_center_pos is not None:
            best_core_tile: tuple[tuple[int, int, int], Position] | None = None
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    core_tile = Position(
                        self.core_center_pos.x + dx,
                        self.core_center_pos.y + dy,
                    )
                    if not (
                        0 <= core_tile.x < self.map.width
                        and 0 <= core_tile.y < self.map.height
                    ):
                        continue
                    if bridge_pos.distance_squared(core_tile) > bridge_target_radius_sq:
                        continue

                    candidate_key = (
                        -bridge_pos.distance_squared(core_tile),
                        core_tile.x,
                        core_tile.y,
                    )
                    if best_core_tile is None or candidate_key < best_core_tile[0]:
                        best_core_tile = (candidate_key, core_tile)

            if best_core_tile is not None:
                return best_core_tile[1]

        best_bridge_candidate: tuple[tuple[int, int, int, int], Position] | None = None
        best_candidate: tuple[tuple[int, int, int, int], Position] | None = None

        for dx in range(-3, 4):
            for dy in range(-3, 4):
                candidate_pos = Position(bridge_pos.x + dx, bridge_pos.y + dy)
                if candidate_pos == bridge_pos:
                    continue
                if not (
                    0 <= candidate_pos.x < self.map.width
                    and 0 <= candidate_pos.y < self.map.height
                ):
                    continue
                if bridge_pos.distance_squared(candidate_pos) > bridge_target_radius_sq:
                    continue

                tile = self.map.matrix[candidate_pos.x][candidate_pos.y]
                if tile is None:
                    continue
                if tile.distance_to_core >= INFINITE_DISTANCE:
                    continue
                if tile.environment == Environment.WALL:
                    continue

                if (
                    tile.building_type == EntityType.BRIDGE
                    and tile.building_team == self.ct.get_team()
                    and tile.distance_to_core < origin_distance_to_core
                ):
                    bridge_candidate_key = (
                        tile.distance_to_core,
                        -bridge_pos.distance_squared(candidate_pos),
                        candidate_pos.x,
                        candidate_pos.y,
                    )
                    if (
                        best_bridge_candidate is None
                        or bridge_candidate_key < best_bridge_candidate[0]
                    ):
                        best_bridge_candidate = (bridge_candidate_key, candidate_pos)
                    continue

                is_buildable = tile.building_id is None
                is_replaceable = tile.building_type in {
                    EntityType.ROAD,
                    EntityType.MARKER,
                }
                if not (is_buildable or is_replaceable):
                    continue

                target_type_rank = (
                    0
                    if is_buildable
                    else 1 if tile.building_type == EntityType.ROAD else 2
                )
                candidate_key = (
                    tile.distance_to_core,
                    target_type_rank,
                    -bridge_pos.distance_squared(candidate_pos),
                    candidate_pos.x,
                    candidate_pos.y,
                )
                if best_candidate is None or candidate_key < best_candidate[0]:
                    best_candidate = (candidate_key, candidate_pos)

        if best_bridge_candidate is not None:
            return best_bridge_candidate[1]

        if best_candidate is None:
            return None

        return best_candidate[1]

    def build_harvester_bridge(self) -> bool:
        """
        Build a bridge orthogonally next to a nearby allied harvester that lacks one.

        The method scans visible allied harvesters, skips any that already have
        an orthogonally adjacent allied bridge, and looks for empty orthogonal
        neighbor tiles where a new bridge could be placed. It uses
        `get_bridge_target` to choose the new bridge target and builds the
        closest legal candidate when the local titanium threshold is met.
        """
        if self.map is None:
            return False

        titanium, _ = self.ct.get_global_resources()
        if titanium < HARVESTER_BRIDGE_MIN_TITANIUM_THRESHOLD:
            return False

        current_pos = self.ct.get_position()
        bridge_candidates: list[
            tuple[tuple[int, int, int, int, int, int], Position, Position]
        ] = []

        for harvester_id in self.ct.get_nearby_buildings():
            if self.ct.get_entity_type(harvester_id) != EntityType.HARVESTER:
                continue
            if self.ct.get_team(harvester_id) != self.ct.get_team():
                continue

            harvester_pos = self.ct.get_position(harvester_id)
            has_adjacent_bridge = False
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
                if (
                    tile.building_type == EntityType.BRIDGE
                    and tile.building_team == self.ct.get_team()
                ):
                    has_adjacent_bridge = True
                    break
                if tile.building_id is not None:
                    continue
                if tile.environment != Environment.EMPTY:
                    continue

                empty_adjacent_tiles.append(adjacent_pos)

            if has_adjacent_bridge:
                continue

            for bridge_pos in empty_adjacent_tiles:
                target_pos = self.get_bridge_target(bridge_pos)
                if target_pos is None:
                    continue
                if not self.ct.can_build_bridge(bridge_pos, target_pos):
                    continue

                candidate_key = (
                    current_pos.distance_squared(bridge_pos),
                    bridge_pos.x,
                    bridge_pos.y,
                    harvester_pos.x,
                    harvester_pos.y,
                    harvester_id,
                )
                bridge_candidates.append((candidate_key, bridge_pos, target_pos))

        if not bridge_candidates:
            return False

        bridge_candidates.sort(key=lambda candidate: candidate[0])
        _, bridge_pos, target_pos = bridge_candidates[0]
        self.ct.build_bridge(bridge_pos, target_pos)
        return self._record_action(
            BotAction.BUILD_HARVESTER_BRIDGE,
            "building harvester bridge",
        )

    def hold_build_harvester_bridge(self) -> bool:
        """
        Wait near a visible unbridged allied harvester until bridge building is possible.

        When team titanium is still below the harvester-bridge threshold, the
        bot looks for visible allied harvesters that do not yet have an
        orthogonally adjacent allied bridge. It then moves into action range of
        one legal orthogonal bridge tile and waits there so it can place the
        bridge as soon as resources are available.
        """
        if self.map is None:
            return False

        titanium, _ = self.ct.get_global_resources()
        if titanium >= HARVESTER_BRIDGE_MIN_TITANIUM_THRESHOLD:
            return False

        current_pos = self.ct.get_position()
        current_id = self.ct.get_id()
        hold_candidates: list[
            tuple[tuple[int, int, int, int, int, int], Position, Position]
        ] = []

        for harvester_id in self.ct.get_nearby_buildings():
            if self.ct.get_entity_type(harvester_id) != EntityType.HARVESTER:
                continue
            if self.ct.get_team(harvester_id) != self.ct.get_team():
                continue

            harvester_pos = self.ct.get_position(harvester_id)
            has_adjacent_bridge = False
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
                if (
                    tile.building_type == EntityType.BRIDGE
                    and tile.building_team == self.ct.get_team()
                ):
                    has_adjacent_bridge = True
                    break
                if tile.building_id is not None:
                    continue
                if tile.environment != Environment.EMPTY:
                    continue
                if self.get_bridge_target(adjacent_pos) is None:
                    continue

                empty_adjacent_tiles.append(adjacent_pos)

            if has_adjacent_bridge:
                continue

            for build_pos in empty_adjacent_tiles:
                staging_positions: list[Position] = []
                for dx in range(-1, 2):
                    for dy in range(-1, 2):
                        staging_pos = Position(build_pos.x + dx, build_pos.y + dy)
                        if not self._is_in_bounds(staging_pos):
                            continue
                        if staging_pos.distance_squared(build_pos) > 2:
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

                        staging_positions.append(staging_pos)

                if not staging_positions:
                    continue

                best_staging_pos = min(
                    staging_positions,
                    key=lambda pos: (
                        1 if pos == build_pos else 0,
                        current_pos.distance_squared(pos),
                        pos.x,
                        pos.y,
                    ),
                )
                candidate_key = (
                    current_pos.distance_squared(best_staging_pos),
                    1 if best_staging_pos == build_pos else 0,
                    best_staging_pos.x,
                    best_staging_pos.y,
                    build_pos.x,
                    build_pos.y,
                )
                hold_candidates.append((candidate_key, best_staging_pos, build_pos))

        if not hold_candidates:
            return False

        hold_candidates.sort(key=lambda candidate: candidate[0])
        _, staging_pos, _ = hold_candidates[0]

        if current_pos == staging_pos:
            return self._record_action(
                BotAction.HOLD_BUILD_HARVESTER_BRIDGE,
                "holding harvester bridge position",
            )

        if not self._move_towards_with_roads(staging_pos):
            return False

        return self._record_action(
            BotAction.HOLD_BUILD_HARVESTER_BRIDGE,
            "holding harvester bridge position",
        )

    def build_missing_bridge(self) -> bool:
        """
        Extend broken bridge chains by placing missing bridges on empty or road targets.

        The method first prioritises adding a bridge next to a nearby allied
        harvester via `build_harvester_bridge`. If that does not build
        anything, it then looks for allied bridges whose current target tile is
        empty or occupied by a road, and attempts to place a new bridge on that
        tile pointing onward using `get_bridge_target`, subject to its own
        titanium threshold. If the chosen missing tile is currently outside
        action range, the bot moves toward it (building roads as needed)
        instead of giving up that turn. If a road occupies the chosen build
        tile, the road is removed first and the bridge is placed immediately
        when the rules allow both actions in the same turn.
        """
        if self.build_harvester_bridge():
            return True

        if self.map is None:
            return False

        titanium, _ = self.ct.get_global_resources()
        if titanium < CHAIN_BRIDGE_MIN_TITANIUM_THRESHOLD:
            return False

        current_pos = self.ct.get_position()
        actionable_candidates: list[
            tuple[tuple[int, int, int, int, int, int, int], Position, Position, bool]
        ] = []
        movement_candidates: list[
            tuple[tuple[int, int, int, int, int, int, int], Position]
        ] = []

        for bridge_id in self.ct.get_nearby_buildings():
            if self.ct.get_entity_type(bridge_id) != EntityType.BRIDGE:
                continue
            if self.ct.get_team(bridge_id) != self.ct.get_team():
                continue

            bridge_pos = self.ct.get_position(bridge_id)
            build_pos = self.ct.get_bridge_target(bridge_id)
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

            is_empty_build_pos = tile.building_id is None
            is_road_build_pos = tile.building_type == EntityType.ROAD
            if not (is_empty_build_pos or is_road_build_pos):
                continue

            target_pos = self.get_bridge_target(build_pos)
            if target_pos is None:
                continue
            build_pos_type_rank = 0 if is_empty_build_pos else 1
            if current_pos.distance_squared(build_pos) <= 2:
                if is_road_build_pos and not self._can_destroy_tile(build_pos):
                    continue
                if (
                    not is_road_build_pos
                    and not self.ct.can_build_bridge(build_pos, target_pos)
                ):
                    continue

                candidate_key = (
                    current_pos.distance_squared(build_pos),
                    build_pos_type_rank,
                    build_pos.x,
                    build_pos.y,
                    bridge_pos.x,
                    bridge_pos.y,
                    bridge_id,
                )
                actionable_candidates.append(
                    (candidate_key, build_pos, target_pos, is_road_build_pos)
                )
                continue

            candidate_key = (
                current_pos.distance_squared(build_pos),
                build_pos_type_rank,
                build_pos.x,
                build_pos.y,
                bridge_pos.x,
                bridge_pos.y,
                bridge_id,
            )
            movement_candidates.append((candidate_key, build_pos))

        if actionable_candidates:
            actionable_candidates.sort(key=lambda candidate: candidate[0])
            _, build_pos, target_pos, is_road_build_pos = actionable_candidates[0]
            if not self._build_bridge_with_optional_road_removal(
                build_pos,
                target_pos,
                is_road_build_pos,
            ):
                return False

            return self._record_action(
                BotAction.BUILD_MISSING_BRIDGE,
                "building missing bridge",
            )

        if not movement_candidates:
            return False

        movement_candidates.sort(key=lambda candidate: candidate[0])
        if not self._move_towards_with_roads(movement_candidates[0][1]):
            return False

        return self._record_action(
            BotAction.BUILD_MISSING_BRIDGE,
            "building missing bridge",
        )

    def hold_missing_bridge(self) -> bool:
        """
        Wait near a visible missing bridge continuation until titanium is available.

        When a scavenger can see that an allied bridge points to a tile that
        still needs another bridge, but team titanium is below the bridge
        threshold, it moves into action range of that missing build tile and
        then stays there. This keeps the bot ready to continue the chain on a
        later turn instead of drifting into unrelated fallback behaviors.
        """
        if self.map is None:
            return False

        titanium, _ = self.ct.get_global_resources()
        if titanium >= CHAIN_BRIDGE_MIN_TITANIUM_THRESHOLD:
            return False

        current_pos = self.ct.get_position()
        current_id = self.ct.get_id()
        hold_candidates: list[tuple[tuple[int, int, int, int, int, int], Position, Position]] = []

        for bridge_id in self.ct.get_nearby_buildings():
            if self.ct.get_entity_type(bridge_id) != EntityType.BRIDGE:
                continue
            if self.ct.get_team(bridge_id) != self.ct.get_team():
                continue

            build_pos = self.ct.get_bridge_target(bridge_id)
            if not self._is_in_bounds(build_pos):
                continue
            if not self.ct.is_in_vision(build_pos):
                continue
            if self._is_adjacent_to_allied_harvester(build_pos):
                continue

            build_tile = self._get_known_map_tile(build_pos)
            if build_tile is None:
                continue
            if build_tile.environment != Environment.EMPTY:
                continue
            if build_tile.building_type in {EntityType.CONVEYOR, EntityType.BRIDGE}:
                continue

            is_empty_build_pos = build_tile.building_id is None
            is_road_build_pos = build_tile.building_type == EntityType.ROAD
            if not (is_empty_build_pos or is_road_build_pos):
                continue
            if self.get_bridge_target(build_pos) is None:
                continue

            staging_positions: list[Position] = []
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    staging_pos = Position(build_pos.x + dx, build_pos.y + dy)
                    if not self._is_in_bounds(staging_pos):
                        continue
                    if staging_pos.distance_squared(build_pos) > 2:
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

                    staging_positions.append(staging_pos)

            if not staging_positions:
                continue

            best_staging_pos = min(
                staging_positions,
                key=lambda pos: (
                    1 if pos == build_pos else 0,
                    current_pos.distance_squared(pos),
                    pos.x,
                    pos.y,
                ),
            )
            candidate_key = (
                current_pos.distance_squared(best_staging_pos),
                1 if best_staging_pos == build_pos else 0,
                best_staging_pos.x,
                best_staging_pos.y,
                build_pos.x,
                build_pos.y,
            )
            hold_candidates.append((candidate_key, best_staging_pos, build_pos))

        if not hold_candidates:
            return False

        hold_candidates.sort(key=lambda candidate: candidate[0])
        _, staging_pos, build_pos = hold_candidates[0]

        if current_pos == staging_pos:
            return self._record_action(
                BotAction.HOLD_MISSING_BRIDGE,
                "holding missing bridge position",
            )

        if not self._move_towards_with_roads(staging_pos):
            return False

        return self._record_action(
            BotAction.HOLD_MISSING_BRIDGE,
            "holding missing bridge position",
        )

    def destroy_hijacked_reschain(self) -> bool:
        """
        Destroy allied logistics buildings that directly feed enemy turrets.

        The method checks nearby allied conveyors, armoured conveyors, and
        bridges that this builder can destroy right now. If one of those
        buildings outputs onto an enemy turret tile, the builder destroys the
        closest such building, breaking the hijacked resource chain. Occupied
        logistics tiles and the builder's own current tile are never destroyed.
        """
        current_pos = self.ct.get_position()
        enemy_turret_types = {
            EntityType.GUNNER,
            EntityType.SENTINEL,
            EntityType.BREACH,
            EntityType.LAUNCHER,
        }
        destroy_candidates: list[tuple[tuple[int, int, int, int], Position]] = []

        for building_id in self.ct.get_nearby_buildings():
            if self.ct.get_team(building_id) != self.ct.get_team():
                continue

            building_type = self.ct.get_entity_type(building_id)
            if building_type in {
                EntityType.CONVEYOR,
                EntityType.ARMOURED_CONVEYOR,
            }:
                target_pos = self.ct.get_position(building_id).add(
                    self.ct.get_direction(building_id)
                )
            elif building_type == EntityType.BRIDGE:
                target_pos = self.ct.get_bridge_target(building_id)
            else:
                continue

            if not (
                0 <= target_pos.x < self.ct.get_map_width()
                and 0 <= target_pos.y < self.ct.get_map_height()
            ):
                continue
            if not self.ct.is_in_vision(target_pos):
                continue

            target_building_id = self.ct.get_tile_building_id(target_pos)
            if target_building_id is None:
                continue
            if self.ct.get_team(target_building_id) == self.ct.get_team():
                continue
            if self.ct.get_entity_type(target_building_id) not in enemy_turret_types:
                continue

            building_pos = self.ct.get_position(building_id)
            if building_pos == current_pos:
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
        self.ct.destroy(destroy_candidates[0][1])
        return self._record_action(
            BotAction.DESTROY_HIJACKED_RESCHAIN,
            "destroying hijacked reschain",
        )

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

        current_pos = self.ct.get_position()
        pulling_building_types = {
            EntityType.CONVEYOR,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.SPLITTER,
            EntityType.BRIDGE,
        }
        protection_candidates: list[
            tuple[tuple[int, int, int, int, int, int, int], Position, bool]
        ] = []

        for harvester_id in self.ct.get_nearby_buildings():
            if self.ct.get_entity_type(harvester_id) != EntityType.HARVESTER:
                continue
            if self.ct.get_team(harvester_id) != self.ct.get_team():
                continue

            harvester_pos = self.ct.get_position(harvester_id)
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

        return protection_candidates

    def protect_harvester(self) -> bool:
        """
        Build a barrier next to a friendly harvester to reduce enemy build space.

        The method looks for visible allied harvesters with orthogonally
        adjacent exposed tiles. Empty tiles can be walled directly, while
        allied roads can be replaced by barriers when that is legal in the same
        turn. It only seals one of those tiles when the harvester already has
        an adjacent logistics building that can pull resources away, or when at
        least one other exposed adjacent tile would remain after the barrier is
        built. Among legal choices, it deterministically prefers the closest
        candidate, with empty tiles preferred over road replacements.
        """
        barrier_candidates = self._get_harvester_protection_candidates()
        if not barrier_candidates:
            return False

        barrier_candidates.sort(key=lambda candidate: candidate[0])
        barrier_ti, barrier_ax = self.ct.get_barrier_cost()
        titanium, axionite = self.ct.get_global_resources()
        can_afford_barrier = titanium >= barrier_ti and axionite >= barrier_ax

        for _, candidate_pos, is_road_tile in barrier_candidates:
            if is_road_tile:
                if not can_afford_barrier:
                    continue
                if not self._can_destroy_tile(candidate_pos):
                    continue
                self.ct.destroy(candidate_pos)
                if not self.ct.can_build_barrier(candidate_pos):
                    continue
                self.ct.build_barrier(candidate_pos)
                return self._record_action(
                    BotAction.PROTECT_HARVESTER,
                    "protecting harvester",
                )

            if self.ct.can_build_barrier(candidate_pos):
                self.ct.build_barrier(candidate_pos)
                return self._record_action(
                    BotAction.PROTECT_HARVESTER,
                    "protecting harvester",
                )

        return False

    def hold_protect_harvester(self) -> bool:
        """
        Move into position near a visible unprotected harvester and wait there.

        The method targets the same exposed harvester-adjacent tiles as
        `protect_harvester()`, including allied roads that should later be
        replaced by barriers. If one of those exposed tiles is already in
        action range, it tries to finish the protection immediately. Otherwise
        it moves to the closest visible staging tile within barrier action
        range and then holds there until the barrier can be placed.
        """
        if self.map is None:
            return False

        protection_candidates = self._get_harvester_protection_candidates()
        if not protection_candidates:
            return False

        current_pos = self.ct.get_position()
        current_id = self.ct.get_id()
        barrier_ti, barrier_ax = self.ct.get_barrier_cost()
        titanium, axionite = self.ct.get_global_resources()
        can_afford_barrier = titanium >= barrier_ti and axionite >= barrier_ax

        actionable_candidates: list[
            tuple[tuple[int, int, int, int], Position, bool]
        ] = []
        hold_candidates: list[
            tuple[tuple[int, int, int, int, int, int], Position]
        ] = []

        for candidate_key, candidate_pos, is_road_tile in protection_candidates:
            if current_pos.distance_squared(candidate_pos) <= 2:
                actionable_key = (
                    0 if not is_road_tile else 1,
                    candidate_key[0],
                    candidate_pos.x,
                    candidate_pos.y,
                )
                actionable_candidates.append(
                    (actionable_key, candidate_pos, is_road_tile)
                )
                continue

            staging_positions: list[Position] = []
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    staging_pos = Position(candidate_pos.x + dx, candidate_pos.y + dy)
                    if not self._is_in_bounds(staging_pos):
                        continue
                    if staging_pos == candidate_pos:
                        continue
                    if staging_pos.distance_squared(candidate_pos) > 2:
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

                    staging_positions.append(staging_pos)

            if not staging_positions:
                continue

            best_staging_pos = min(
                staging_positions,
                key=lambda pos: (
                    current_pos.distance_squared(pos),
                    pos.x,
                    pos.y,
                ),
            )
            hold_key = (
                current_pos.distance_squared(best_staging_pos),
                0 if not is_road_tile else 1,
                best_staging_pos.x,
                best_staging_pos.y,
                candidate_pos.x,
                candidate_pos.y,
            )
            hold_candidates.append((hold_key, best_staging_pos))

        if actionable_candidates:
            actionable_candidates.sort(key=lambda candidate: candidate[0])
            _, candidate_pos, is_road_tile = actionable_candidates[0]

            if is_road_tile:
                if not can_afford_barrier:
                    pass
                elif self._can_destroy_tile(candidate_pos):
                    self.ct.destroy(candidate_pos)
                    if self.ct.can_build_barrier(candidate_pos):
                        self.ct.build_barrier(candidate_pos)
                        return self._record_action(
                            BotAction.PROTECT_HARVESTER,
                            "protecting harvester",
                        )
            elif self.ct.can_build_barrier(candidate_pos):
                self.ct.build_barrier(candidate_pos)
                return self._record_action(
                    BotAction.PROTECT_HARVESTER,
                    "protecting harvester",
                )

        if not hold_candidates:
            return False

        hold_candidates.sort(key=lambda candidate: candidate[0])
        staging_pos = hold_candidates[0][1]
        if current_pos == staging_pos:
            return self._record_action(
                BotAction.HOLD_PROTECT_HARVESTER,
                "holding harvester protection position",
            )

        if not self._move_towards_with_roads(staging_pos):
            return False

        return self._record_action(
            BotAction.HOLD_PROTECT_HARVESTER,
            "holding harvester protection position",
        )

    def build_extractor(self) -> bool:
        """
        Build a harvester on a visible titanium tile when enough titanium is available.

        The method explicitly scans every tile in the builder's current vision
        radius and only considers visible unoccupied titanium deposits. If one
        is already within action radius and the build is legal, it immediately
        builds the harvester. Otherwise, it advances toward the nearest visible
        titanium target that it can currently make progress toward. Path
        selection first asks the map cache for a BFS-based next step that
        avoids known wall tiles and then performs the actual step with normal
        road/move behavior. Trying multiple visible targets keeps maintainers
        from giving up and falling back to patrol just because the single
        closest deposit is awkward to approach that turn. Once the map already
        knows about `MAX_HARVESTORS` friendly harvesters, the method stops
        expanding extractor production entirely.
        """
        if self.map is None:
            return False

        titanium, _ = self.ct.get_global_resources()
        if titanium < EXTRACTOR_MIN_TITANIUM_THRESHOLD:
            return False
        if self.map.known_harvesters_built >= MAX_HARVESTORS:
            return False

        current_pos = self.ct.get_position()
        action_radius_sq = 2
        ore_targets: list[tuple[tuple[int, int, int], Position]] = []
        visible_tiles = self.ct.get_nearby_tiles(self.ct.get_vision_radius_sq())

        for pos in visible_tiles:
            environment = self.ct.get_tile_env(pos)
            if environment != Environment.ORE_TITANIUM:
                continue
            if self.ct.get_tile_building_id(pos) is not None:
                continue

            target_key = (
                current_pos.distance_squared(pos),
                pos.x,
                pos.y,
            )
            ore_targets.append((target_key, pos))

        if not ore_targets:
            return False

        ore_targets.sort(key=lambda target: target[0])

        for _, target_pos in ore_targets:
            if current_pos.distance_squared(target_pos) > action_radius_sq:
                continue
            if self.ct.can_build_harvester(target_pos):
                self.ct.build_harvester(target_pos)
                return self._record_action(
                    BotAction.BUILD_EXTRACTOR,
                    "building extractor",
                )

        for _, target_pos in ore_targets:
            if current_pos.distance_squared(target_pos) <= action_radius_sq:
                continue

            next_step_pos = self.map.get_next_field_for_target(target_pos)
            if next_step_pos is not None and next_step_pos != current_pos:
                move_direction = current_pos.direction_to(next_step_pos)
                if (
                    move_direction != Direction.CENTRE
                    and self._move_in_direction_with_roads(move_direction)
                ):
                    return self._record_action(
                        BotAction.BUILD_EXTRACTOR,
                        "building extractor",
                    )

            if not self._move_towards_with_roads(target_pos):
                continue

            return self._record_action(
                BotAction.BUILD_EXTRACTOR,
                "building extractor",
            )

        return False

    def hold_visible_titanium(self) -> bool:
        """
        Hold a visible free titanium tile instead of scouting away from it.

        When a scavenger sees an unoccupied titanium deposit but cannot or does
        not yet build a harvester there, it moves to or stays on a nearby
        staging tile within action range of that deposit. The builder never
        steps onto the titanium tile itself and never roads it, which keeps
        the deposit clean for the later harvester build.
        """
        current_pos = self.ct.get_position()
        current_id = self.ct.get_id()
        ore_targets: list[tuple[tuple[int, int, int], Position, Position]] = []

        for ore_pos in self.ct.get_nearby_tiles():
            if self.ct.get_tile_env(ore_pos) != Environment.ORE_TITANIUM:
                continue
            if self.ct.get_tile_building_id(ore_pos) is not None:
                continue

            occupying_builder_id = self.ct.get_tile_builder_bot_id(ore_pos)
            if occupying_builder_id is not None and occupying_builder_id != current_id:
                continue

            staging_positions: list[Position] = []
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    staging_pos = Position(ore_pos.x + dx, ore_pos.y + dy)
                    if not self._is_in_bounds(staging_pos):
                        continue
                    if staging_pos == ore_pos:
                        continue
                    if staging_pos.distance_squared(ore_pos) > 2:
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

                    staging_builder_id = staging_tile.builder_bot_id
                    if staging_builder_id is not None and staging_builder_id != current_id:
                        continue

                    staging_positions.append(staging_pos)

            if not staging_positions:
                continue

            best_staging_pos = min(
                staging_positions,
                key=lambda pos: (
                    current_pos.distance_squared(pos),
                    pos.x,
                    pos.y,
                ),
            )
            candidate_key = (
                current_pos.distance_squared(best_staging_pos),
                best_staging_pos.x,
                best_staging_pos.y,
            )
            ore_targets.append((candidate_key, ore_pos, best_staging_pos))

        if not ore_targets:
            return False

        ore_targets.sort(key=lambda target: target[0])
        _, _, staging_pos = ore_targets[0]

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

    def get_enemy_core_pos(self) -> Position | None:
        """
        Infer the enemy core centre from map symmetry and visible information.

        The method first returns an actually visible enemy core if one is in
        sight. Otherwise it tests rotational and axis-reflection symmetries
        against the known static terrain in the cached map, stores every still
        valid enemy core candidate, and only marks the enemy core position as
        resolved when exactly one candidate remains.
        """
        for building_id in self.ct.get_nearby_buildings():
            if self.ct.get_entity_type(building_id) != EntityType.CORE:
                continue
            if self.ct.get_team(building_id) == self.ct.get_team():
                continue

            self.enemy_core_pos = self.ct.get_position(building_id)
            self.enemy_core_pos_candidates = [self.enemy_core_pos]
            return self.enemy_core_pos

        if self.map is None:
            self.enemy_core_pos = None
            self.enemy_core_pos_candidates = []
            return None

        if self.core_center_pos is None:
            self.find_core_center()
        if self.core_center_pos is None:
            self.enemy_core_pos = None
            self.enemy_core_pos_candidates = []
            return None

        width = self.map.width
        height = self.map.height
        own_core_pos = self.core_center_pos

        symmetry_candidates = [
            (
                "rotation",
                lambda pos: Position(width - 1 - pos.x, height - 1 - pos.y),
                Position(width - 1 - own_core_pos.x, height - 1 - own_core_pos.y),
            ),
            (
                "mirror_x",
                lambda pos: Position(width - 1 - pos.x, pos.y),
                Position(width - 1 - own_core_pos.x, own_core_pos.y),
            ),
            (
                "mirror_y",
                lambda pos: Position(pos.x, height - 1 - pos.y),
                Position(own_core_pos.x, height - 1 - own_core_pos.y),
            ),
        ]

        valid_candidate_map: dict[tuple[int, int], Position] = {}

        for _, transform, candidate_pos in symmetry_candidates:
            is_valid_symmetry = True

            for x, column in enumerate(self.map.matrix):
                for y, tile in enumerate(column):
                    if tile is None:
                        continue

                    mirrored_pos = transform(Position(x, y))
                    mirrored_tile = self.map.matrix[mirrored_pos.x][mirrored_pos.y]
                    if mirrored_tile is None:
                        continue
                    if tile.environment != mirrored_tile.environment:
                        is_valid_symmetry = False
                        break

                if not is_valid_symmetry:
                    break

            if is_valid_symmetry:
                valid_candidate_map[(candidate_pos.x, candidate_pos.y)] = candidate_pos

        self.enemy_core_pos_candidates = sorted(
            valid_candidate_map.values(),
            key=lambda pos: (pos.x, pos.y),
        )

        if len(self.enemy_core_pos_candidates) == 1:
            self.enemy_core_pos = self.enemy_core_pos_candidates[0]
            return self.enemy_core_pos

        self.enemy_core_pos = None
        return None

    def build_supplied_sentinel(self):
        pass


    # Builder scouting, patrol, and logistics continuation

    def bb_scout(self) -> bool:
        """
        Expand outward into lightly developed frontier areas.

        The scavenger reevaluates its scout target every turn instead of
        forcing one fixed direction. It prefers adjacent steps that open into
        broader unknown space, that can receive a new road, and that are not
        surrounded by friendly infrastructure. When no such step is directly
        available, it heads toward the best known frontier tile with the same
        bias, which keeps expansion on the outer edge of the base instead of
        chasing isolated leftover holes inside already developed territory.
        """
        if self.map is None:
            return False

        current_pos = self.ct.get_position()
        own_team = self.ct.get_team()
        current_tile = self._get_known_map_tile(current_pos)
        current_distance_to_core = (
            current_tile.distance_to_core
            if current_tile is not None
            else -1
        )

        def is_walkable_scout_tile(tile: Tile | None) -> bool:
            if tile is None:
                return False
            if tile.environment == Environment.WALL:
                return False
            if tile.building_id is None:
                return True
            return (
                tile.building_type == EntityType.ROAD
                and tile.building_team == own_team
            )

        def count_unknown_tiles(pos: Position, radius: int) -> int:
            unknown_tiles = 0
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if dx == 0 and dy == 0:
                        continue
                    sample_pos = Position(pos.x + dx, pos.y + dy)
                    if not self._is_in_bounds(sample_pos):
                        continue
                    if self._get_known_map_tile(sample_pos) is None:
                        unknown_tiles += 1
            return unknown_tiles

        def count_owned_infrastructure(pos: Position, radius: int) -> int:
            owned_infrastructure = 0
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    sample_pos = Position(pos.x + dx, pos.y + dy)
                    if not self._is_in_bounds(sample_pos):
                        continue
                    tile = self._get_known_map_tile(sample_pos)
                    if tile is None:
                        continue
                    if tile.building_team == own_team:
                        owned_infrastructure += 1
                    if tile.builder_bot_team == own_team:
                        owned_infrastructure += 1
            return owned_infrastructure

        direct_candidates: list[
            tuple[tuple[int, int, int, int, int, int, int, int, int], Direction]
        ] = []

        for direction_index, direction in enumerate(DIRECTIONS):
            next_pos = current_pos.add(direction)
            if not self._is_in_bounds(next_pos):
                continue

            next_tile = self._get_known_map_tile(next_pos)
            if next_tile is not None and next_tile.environment == Environment.WALL:
                continue

            can_move = self.ct.can_move(direction)
            can_build_road = self.ct.can_build_road(next_pos)
            if not can_move and not can_build_road:
                continue

            nearby_unknown_tiles = count_unknown_tiles(next_pos, 2)
            immediate_unknown_tiles = count_unknown_tiles(next_pos, 1)
            owned_infrastructure = count_owned_infrastructure(next_pos, 2)
            has_owned_road = (
                next_tile is not None
                and next_tile.building_type == EntityType.ROAD
                and next_tile.building_team == own_team
            )
            distance_to_core = (
                next_tile.distance_to_core
                if next_tile is not None
                else current_distance_to_core + 1
            )
            action_rank = (
                0
                if can_build_road and can_move
                else 1
                if can_build_road
                else 2
            )
            candidate_key = (
                0 if nearby_unknown_tiles > 0 else 1,
                owned_infrastructure,
                -nearby_unknown_tiles,
                -immediate_unknown_tiles,
                action_rank,
                0 if not has_owned_road else 1,
                0 if distance_to_core > current_distance_to_core else 1,
                -distance_to_core,
                direction_index,
                next_pos.x,
                next_pos.y,
            )
            direct_candidates.append((candidate_key, direction))

        if direct_candidates:
            direct_candidates.sort(key=lambda candidate: candidate[0])
            best_direction = direct_candidates[0][1]
            if self._move_in_direction_with_roads(best_direction):
                return self._record_action(
                    BotAction.BB_SCOUT,
                    "expanding territory",
                )

        frontier_targets: list[
            tuple[tuple[int, int, int, int, int, int, int], Position]
        ] = []
        expansion_targets: list[
            tuple[tuple[int, int, int, int, int], Position]
        ] = []

        for x, column in enumerate(self.map.matrix):
            for y, tile in enumerate(column):
                if not is_walkable_scout_tile(tile):
                    continue

                pos = Position(x, y)
                if pos == current_pos:
                    continue

                nearby_unknown_tiles = count_unknown_tiles(pos, 2)
                immediate_unknown_tiles = count_unknown_tiles(pos, 1)
                owned_infrastructure = count_owned_infrastructure(pos, 2)
                target_key = (
                    owned_infrastructure,
                    -nearby_unknown_tiles,
                    -immediate_unknown_tiles,
                    -tile.distance_to_core,
                    current_pos.distance_squared(pos),
                    x,
                    y,
                )
                if nearby_unknown_tiles > 0:
                    frontier_targets.append((target_key, pos))
                else:
                    expansion_targets.append(
                        (
                            (
                                owned_infrastructure,
                                -tile.distance_to_core,
                                current_pos.distance_squared(pos),
                                x,
                                y,
                            ),
                            pos,
                        )
                    )

        for candidate_list in (frontier_targets, expansion_targets):
            if not candidate_list:
                continue

            candidate_list.sort(key=lambda candidate: candidate[0])
            target_pos = candidate_list[0][1]
            if not self._move_towards_with_roads(target_pos):
                continue

            return self._record_action(
                BotAction.BB_SCOUT,
                "expanding territory",
            )

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

        for x, column in enumerate(self.map.matrix):
            for y, tile in enumerate(column):
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

    def complete_supply_chain(self) -> bool:
        """
        Continue a recently started bridge chain until it reconnects inward.

        The method only triggers when the previous turn ended with a bridge
        continuation action. It looks for a visible allied bridge whose target
        tile is still unknown in the cached map, or is known but not yet
        occupied by a conveyor or bridge. If the missing continuation tile is
        buildable and in action range, it extends the chain there, removing a
        road first and placing the bridge immediately when both actions are
        legal in the same turn. Otherwise it moves toward the missing tile
        while building roads on the way.
        """
        if self.map is None:
            return False
        if self.previous_action not in {
            BotAction.BUILD_HARVESTER_BRIDGE,
            BotAction.BUILD_MISSING_BRIDGE,
            BotAction.COMPLETE_SUPPLY_CHAIN,
        }:
            return False

        current_pos = self.ct.get_position()
        actionable_candidates: list[
            tuple[
                tuple[int, int, int, int, int, int, int],
                Position,
                Position,
                bool,
            ]
        ] = []
        movement_candidates: list[
            tuple[tuple[int, int, int, int, int, int], Position]
        ] = []

        for bridge_id in self.ct.get_nearby_buildings():
            if self.ct.get_entity_type(bridge_id) != EntityType.BRIDGE:
                continue
            if self.ct.get_team(bridge_id) != self.ct.get_team():
                continue

            bridge_pos = self.ct.get_position(bridge_id)
            target_pos = self.ct.get_bridge_target(bridge_id)
            if not self._is_in_bounds(target_pos):
                continue

            tile = self._get_known_map_tile(target_pos)
            if tile is None:
                candidate_key = (
                    current_pos.distance_squared(target_pos),
                    target_pos.x,
                    target_pos.y,
                    bridge_pos.x,
                    bridge_pos.y,
                    bridge_id,
                )
                movement_candidates.append((candidate_key, target_pos))
                continue

            if tile.building_type in {EntityType.CONVEYOR, EntityType.BRIDGE}:
                continue
            if tile.environment != Environment.EMPTY:
                continue

            is_empty_build_pos = tile.building_id is None
            is_road_build_pos = tile.building_type == EntityType.ROAD
            if not (is_empty_build_pos or is_road_build_pos):
                continue

            next_target_pos = self.get_bridge_target(target_pos)
            if next_target_pos is None:
                continue

            if current_pos.distance_squared(target_pos) <= 2:
                if is_road_build_pos:
                    if not self._can_destroy_tile(target_pos):
                        continue
                elif not self.ct.can_build_bridge(target_pos, next_target_pos):
                    continue

                build_pos_type_rank = 0 if is_empty_build_pos else 1
                candidate_key = (
                    current_pos.distance_squared(target_pos),
                    build_pos_type_rank,
                    target_pos.x,
                    target_pos.y,
                    bridge_pos.x,
                    bridge_pos.y,
                    bridge_id,
                )
                actionable_candidates.append(
                    (candidate_key, target_pos, next_target_pos, is_road_build_pos)
                )
                continue

            candidate_key = (
                current_pos.distance_squared(target_pos),
                target_pos.x,
                target_pos.y,
                bridge_pos.x,
                bridge_pos.y,
                bridge_id,
            )
            movement_candidates.append((candidate_key, target_pos))

        if actionable_candidates:
            actionable_candidates.sort(key=lambda candidate: candidate[0])
            _, build_pos, target_pos, is_road_build_pos = actionable_candidates[0]
            if not self._build_bridge_with_optional_road_removal(
                build_pos,
                target_pos,
                is_road_build_pos,
            ):
                return False

            return self._record_action(
                BotAction.COMPLETE_SUPPLY_CHAIN,
                "completing supply chain",
            )

        if not movement_candidates:
            return False

        movement_candidates.sort(key=lambda candidate: candidate[0])
        if not self._move_towards_with_roads(movement_candidates[0][1]):
            return False

        return self._record_action(
            BotAction.COMPLETE_SUPPLY_CHAIN,
            "completing supply chain",
        )



class Player(Bot):
    pass


### constants ###
INITIAL_BB = [
    Bot.run_bb_scavenger,
    Bot.run_bb_scavenger,
    Bot.run_bb_scavenger,
]
FURTHER_BB = Bot.run_bb_harassment
