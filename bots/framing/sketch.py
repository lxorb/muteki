from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Final, TypeAlias

from cambc import (
    Controller,
    Direction,
    EntityType,
    Environment,
    Position,
    Team,
)

# every method that starts with u_ was initially created by a user
# every method that was created by ai should start with c_
# this excludes some convention names like __init__ obviously
# methods starting with s_ are strategy submethods (as described later in this file)

PositionKey: TypeAlias = tuple[int, int]
PathMap: TypeAlias = dict[Position, list[Position]]

INFINITE_DISTANCE: Final[int] = 10**9
TURN_CPU_BUDGET_NS: Final[int] = 2_000_000
BUILDER_ACTION_RADIUS_SQ: Final[int] = 2
BRIDGE_PREFERRED_DIST: Final[int] = 5
DEFAULT_CORE_PROXIMITY_DIST: Final[int] = 2

FOUNDRY_TURN_CONSTANT: Final[int] = 1600
MIN_FOUNDRY_TITANIUM_CONSTANT: Final[int] = 1000
AXIONITE_FARMING_BOTS_TO_SPAWN: Final[int] = 2

HARVESTER_SUPPLY_LINK_MIN_TITANIUM_THRESHOLD: Final[int] = 100
CHAIN_SUPPLY_LINK_MIN_TITANIUM_THRESHOLD: Final[int] = 50
SCAVENGER_ACTIVE_TITANIUM_THRESHOLD: Final[int] = 200
HARASSMENT_SPAWN_BASE_TITANIUM_THRESHOLD: Final[int] = 1600
HARASSMENT_SPAWN_TITANIUM_STEP: Final[int] = 100
HARASSMENT_ATTACK_MIN_TITANIUM_THRESHOLD: Final[int] = 20
LAUNCHER_DEFEND_MIN_TITANIUM_THRESHOLD: Final[int] = 70
REPAIR_MIN_TITANIUM_THRESHOLD: Final[int] = 10

MAX_BOTS: Final[int] = 999
MAX_HARVESTORS: Final[int] = 999

DIRECTIONS: Final[tuple[Direction, ...]] = tuple(
    direction for direction in Direction if direction != Direction.CENTRE
)
CARDINAL_DIRECTIONS: Final[tuple[Direction, ...]] = tuple(
    direction
    for direction in DIRECTIONS
    if sum(abs(delta) for delta in direction.delta()) == 1
)

ENEMY_TURRET_TYPES: Final[frozenset[EntityType]] = frozenset(
    {
        EntityType.GUNNER,
        EntityType.SENTINEL,
        EntityType.BREACH,
    }
)
SUPPLY_LINK_TYPES: Final[frozenset[EntityType]] = frozenset(
    {
        EntityType.CONVEYOR,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.BRIDGE,
        EntityType.SPLITTER,
    }
)
WALKABLE_BUILDING_TYPES: Final[frozenset[EntityType]] = frozenset(
    {
        EntityType.CONVEYOR,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.SPLITTER,
        EntityType.BRIDGE,
        EntityType.ROAD,
    }
)
PATH_BUILDING_TYPE_PRIORITY: Final[tuple[EntityType, ...]] = (
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ROAD,
    EntityType.CORE,
)
SUPPLIER_TARGET_CATEGORY_PRIORITY: Final[tuple[str, ...]] = (
    "existing_supply_link",
    "own_barrier",
    "own_road",
    "empty",
    "enemy_road",
)
DEFAULT_TURRET_TARGET_PRIORITY: Final[tuple[EntityType, ...]] = (
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
)
BREACH_TARGET_PRIORITY: Final[tuple[EntityType, ...]] = DEFAULT_TURRET_TARGET_PRIORITY


class BuilderBotType(Enum):
    """Enumerate the planned builder-bot role families."""

    SCAVENGER = "scavenger"
    HARASSMENT = "harassment"
    DEFENDER = "defender"
    INITIAL_RES = "initial_res"
    FOUNDRYBOT = "foundrybot"


class CoreSpawnEvent(Enum):
    """Enumerate core-side checkpoints that can gate the spawn plan."""

    FIRST_RESOURCE_INCREASE = auto()
    ENEMY_BOT_IN_CORE_VISION = auto()


class SupplyChainKind(Enum):
    """Label the resource flavour currently carried by a supply chain."""

    TITANIUM = "titanium"
    AXIONITE = "axionite"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class CoreSpawnTurnEvent:
    """Gate part of the spawn plan until a specific round is reached."""

    turn: int


CoreSpawnPlanEntry: TypeAlias = BuilderBotType | CoreSpawnEvent | CoreSpawnTurnEvent


@dataclass(slots=True)
class CommittedPath:
    """Store one path commitment that can be resumed across turns."""

    tiles: list[Position] = field(default_factory=list)
    destination: Position | None = None
    allow_enemy_tiles: bool = True
    allow_build_new_tiles: bool = True


@dataclass(slots=True)
class VisionCache:
    """Cache all map facts that are recomputed from current vision each turn."""

    round_seen: int = -1
    visible_positions: list[Position] = field(default_factory=list)
    visible_position_keys: set[PositionKey] = field(default_factory=set)
    orthogonally_adjacent_positions: list[Position] = field(default_factory=list)
    diagonally_adjacent_positions: list[Position] = field(default_factory=list)
    visible_building_positions: list[Position] = field(default_factory=list)
    visible_enemy_builder_positions: list[Position] = field(default_factory=list)
    visible_enemy_harvester_positions: list[Position] = field(default_factory=list)
    visible_own_harvester_positions: list[Position] = field(default_factory=list)
    visible_enemy_turret_positions: list[Position] = field(default_factory=list)
    visible_enemy_launcher_positions: list[Position] = field(default_factory=list)
    visible_titanium_positions: list[Position] = field(default_factory=list)
    visible_axionite_positions: list[Position] = field(default_factory=list)
    visible_supply_link_positions: list[Position] = field(default_factory=list)
    known_missing_supply_link_positions: list[Position] = field(default_factory=list)
    has_enemy_bot_in_vision: bool = False


@dataclass(slots=True)
class StrategyStep:
    """Describe one named strategy step and the method that should run it."""

    label: str
    method_name: str
    kwargs: dict[str, object] = field(default_factory=dict)


StrategyStepSequence: TypeAlias = tuple[StrategyStep, ...]


@dataclass(slots=True)
class Tile:
    """Store all cached knowledge about one map tile."""

    position: Position
    environment: Environment | None = None
    own_core_dist: int = INFINITE_DISTANCE
    enemy_core_dist: int = INFINITE_DISTANCE
    building_id: int | None = None
    building_type: EntityType | None = None
    building_team: Team | None = None
    builder_bot_id: int | None = None
    builder_bot_team: Team | None = None
    is_passable: bool = False
    is_known: bool = False
    is_core_tile: bool = False
    is_supply_link_tile: bool = False
    last_seen_turn: int = -1
    last_titanium_on_it_turn: int = -1
    last_axionite_on_it_turn: int = -1
    in_enemy_launcher_pickup_zone: bool = False
    in_action_radius: bool = False
    in_vision_radius: bool = False
    in_enemy_attack_range: bool = False
    is_in_enemy_bot_action_range: bool = False
    supply_chain_kind: SupplyChainKind | None = None
    resource_targets: tuple[Position, ...] = ()

    def u_get_resource_targets(self, ct: Controller) -> list[Position]:
        """Return every currently known resource-output tile for this tile."""
        raise NotImplementedError


class Map:
    """Cache the board and precompute the facts that strategy steps consume."""

    def __init__(self, ct: Controller) -> None:
        """
        Create the persistent map cache for one bot instance.

        The constructor allocates tile objects for the whole board and prepares
        the long-lived containers that later `u_update_vision` will populate.
        """
        self.ct = ct
        self.width = ct.get_map_width()
        self.height = ct.get_map_height()
        self.matrix: list[list[Tile]] = self.c_create_tile_matrix()
        self.core_center_pos: Position | None = None
        self.enemy_core_center_pos: Position | None = None
        self.enemy_core_center_pos_candidates: list[Position] = []
        self.vision_cache = VisionCache()
        self.committed_path = CommittedPath()
        self.known_positions: set[PositionKey] = set()
        self.known_harvester_ids: set[int] = set()
        self.known_foundry_ids: set[int] = set()
        self.known_core_adjacent_splitter_ids: set[int] = set()
        self.knowledge_revision = 0
        self.path_revision = 0

    def c_create_tile_matrix(self) -> list[list[Tile]]:
        """Allocate the full tile matrix with placeholder tile objects."""
        return [
            [self.c_create_tile(Position(x, y)) for y in range(self.height)]
            for x in range(self.width)
        ]

    def c_create_tile(self, pos: Position) -> Tile:
        """Create one blank tile object for a specific board position."""
        return Tile(position=pos)

    def c_reset_turn_cache(self) -> None:
        """Clear all per-turn map caches before rebuilding them from vision."""
        self.vision_cache = VisionCache()

    def u_change_controller(self, ct: Controller) -> None:
        """
        Replace the controller currently used by the map cache.

        If the map dimensions changed, the structural caches are rebuilt to
        match the new board shape before future updates.
        """
        self.ct = ct

        width = ct.get_map_width()
        height = ct.get_map_height()
        if width == self.width and height == self.height:
            return

        self.width = width
        self.height = height
        self.matrix = self.c_create_tile_matrix()
        self.core_center_pos = None
        self.enemy_core_center_pos = None
        self.enemy_core_center_pos_candidates = []
        self.committed_path = CommittedPath()
        self.known_positions.clear()
        self.known_harvester_ids.clear()
        self.known_foundry_ids.clear()
        self.known_core_adjacent_splitter_ids.clear()
        self.knowledge_revision = 0
        self.path_revision = 0
        self.c_reset_turn_cache()

    def u_calc_core_center_pos(self) -> Position | None:
        """Infer and cache the allied core center from current local knowledge."""
        raise NotImplementedError

    def u_update_vision(self) -> None:
        """
        Refresh all visible-map knowledge and all derived turn caches.

        This method is intended to do the heavy work of the rewrite: collect
        fresh tile facts, rebuild the priority-driving cache lists, update
        missing supply-link metadata, refresh enemy threat zones, and then
        recompute both allied and enemy core distance fields.
        """
        raise NotImplementedError

    def c_refresh_visible_tiles(self, visible_positions: list[Position]) -> None:
        """Merge raw tile observations into the cached tile matrix."""
        raise NotImplementedError

    def c_refresh_visible_buildings(self, visible_building_ids: list[int]) -> None:
        """Update building-related caches for the currently visible area."""
        raise NotImplementedError

    def c_refresh_visible_builder_bots(self, visible_unit_ids: list[int]) -> None:
        """Update builder-bot occupancy and enemy-bot visibility caches."""
        raise NotImplementedError

    def c_refresh_resource_targets(self) -> None:
        """Stamp supplier outputs and resource-routing metadata onto tiles."""
        raise NotImplementedError

    def c_refresh_missing_supply_links(self) -> None:
        """Rebuild the lazy cache of known supply-link gaps."""
        raise NotImplementedError

    def c_refresh_threat_zones(self) -> None:
        """Stamp enemy action, attack, and launcher-pickup coverage onto tiles."""
        raise NotImplementedError

    def c_refresh_enemy_core_candidates(self) -> None:
        """Prune enemy-core candidates using symmetry and current visibility."""
        raise NotImplementedError

    def c_refresh_distance_fields(self) -> None:
        """Refresh every cached distance field needed by strategy decisions."""
        raise NotImplementedError

    def c_refresh_distance_field(
        self,
        source_positions: list[Position],
        target_attribute: str,
    ) -> None:
        """Apply one lazy flood-fill into a chosen tile distance attribute."""
        raise NotImplementedError

    def c_collect_core_footprint(self, center: Position) -> list[Position]:
        """Return the in-bounds 3x3 footprint tiles around a core center."""
        raise NotImplementedError

    def u_calc_enemy_core_center_candidates(self) -> list[Position]:
        """
        Infer every still-possible enemy core center from map symmetry.

        The candidate list should shrink as the bot rules out symmetries or
        directly sees evidence that excludes specific locations.
        """
        raise NotImplementedError

    # generally for all path findings, if there is a choice where there are tiles that seem equally good
    # then prioritize tiles of the own team
    # if there is still a tie then prioritize by bridges > conveyors > roads > core_tile
    # make this priority configurable easily and hence modular
    def u_calculate_shortest_walk_path_to(
        self,
        dest: Position,
        allow_enemy_tiles: bool = True,
        allow_build_new_tiles: bool = True,
        source: Position | None = None,
    ) -> list[Position]:
        """
        Return the preferred shortest walk path to one destination tile.

        Unknown tiles are treated as buildable empty space, and tie breaks are
        expected to follow the configurable path-priority constants above.
        """
        raise NotImplementedError

    def u_calculate_all_shortest_walk_paths(
        self,
        allow_enemy_tiles: bool = True,
        allow_build_new_tiles: bool = True,
        source: Position | None = None,
    ) -> PathMap:
        """
        Return shortest walk paths to every currently relevant known target tile.

        Relevance should include tiles that are already known plus the local
        frontier that the bot could reasonably expand into next.
        """
        raise NotImplementedError

    def c_collect_action_staging_tiles(
        self,
        target: Position,
        action_radius_sq: int,
    ) -> list[Position]:
        """Collect the tiles from which the bot could act on one target tile."""
        raise NotImplementedError

    def u_calculate_shortest_action_path_to(
        self,
        target: Position,
        action_radius_sq: int = BUILDER_ACTION_RADIUS_SQ,
        allow_enemy_tiles: bool = True,
        allow_build_new_tiles: bool = True,
        source: Position | None = None,
    ) -> list[Position]:
        """
        Return the preferred shortest path into action range of one target tile.

        The destination of the path is one staging tile, not the target tile
        itself, so the caller can act without occupying the build target.
        """
        raise NotImplementedError

    def u_commit_new_path(
        self,
        path: list[Position],
        destination: Position | None = None,
        allow_enemy_tiles: bool = True,
        allow_build_new_tiles: bool = True,
    ) -> None:
        """
        Save a path that the builder should continue following across turns.

        The first element of the stored list should be the next tile to enter.
        """
        self.committed_path = CommittedPath(
            tiles=path,
            destination=destination,
            allow_enemy_tiles=allow_enemy_tiles,
            allow_build_new_tiles=allow_build_new_tiles,
        )

    def u_follow_commit_path(self) -> bool:
        """
        Continue the currently committed path if it is still valid.

        Validation should consider both the path contents and the rules that
        were saved together with that committed path.
        """
        raise NotImplementedError

    def u_move_to(self, dest: Position, allow_build: bool = True) -> bool:
        """
        Advance one step toward a target tile and prepare the tile if needed.

        If the destination tile is not already walkable, later implementation
        should decide whether to build a road or a supply link on that tile.
        """
        raise NotImplementedError

    def u_build_supplier(self, pos: Position) -> bool:
        """
        Decide which supplier type should be built at one tile.

        The later implementation should compare the best conveyor and bridge
        options and then build the higher-priority candidate.
        """
        raise NotImplementedError

    def u_best_conveyor_orientation(self, pos: Position) -> Direction | None:
        """
        Return the best conveyor orientation for a proposed supplier tile.

        The decision should be purely cache-driven and use configurable target
        category ordering so users can tune the rewrite easily.
        """
        raise NotImplementedError

    def u_best_bridge_target(self, pos: Position) -> Position | None:
        """
        Return the best bridge target for a proposed supplier tile.

        The decision should prefer long, meaningful jumps toward the allied
        core while staying configurable through shared ranking constants.
        """
        raise NotImplementedError


class Strategy:
    """Store one ordered builder strategy with resumable main steps."""

    def __init__(
        self,
        name: str,
        pre_steps: StrategyStepSequence = (),
        main_steps: StrategyStepSequence = (),
        post_steps: StrategyStepSequence = (),
    ) -> None:
        """
        Create one strategy from ordered pre, main, and post step lists.

        Each step stores a printable label plus the name of the `Bot` method
        that will later implement the action.
        """
        self.name = name
        self.pre_steps = pre_steps
        self.main_steps = main_steps
        self.post_steps = post_steps

    def c_reset_progress(self, bot: Bot) -> None:
        """Clear the stored resume state for this strategy on one bot."""
        bot.last_strategy_name = self.name
        bot.last_strategy_subaction = None
        bot.last_strategy_subaction_index = -1

    def c_get_main_start_index(self, bot: Bot) -> int:
        """Return the main-step index from which execution should resume."""
        raise NotImplementedError

    def u_execute_strategy(self, bot: Bot) -> bool:
        """
        Execute the strategy around one bot instance.

        The later implementation should always run pre steps, resume main
        steps after TLE when needed, stop the main list after the first
        success, and then always run the post steps.
        """
        raise NotImplementedError


class Bot:
    """Store persistent unit state and expose the rewrite handler surface."""

    def __init__(self) -> None:
        """Initialise the persistent state containers shared across turns."""
        self.bbs_spawned_by_type: dict[BuilderBotType, int] = {
            builder_type: 0 for builder_type in BuilderBotType
        }
        self.core_spawn_tile_usage_counts: dict[PositionKey, int] = {}
        self.core_previous_resources: tuple[int, int] | None = None
        # -> resources in last turn
        self.core_spawn_plan_index = 0
        self.core_completed_spawn_events: set[CoreSpawnEvent] = set()
        self.ct: Controller | None = None
        self.map: Map | None = None
        self.core_center_pos: Position | None = None
        self.enemy_core_center_pos: Position | None = None
        self.resource_increase_once = False
        # -> the first time the core registers an increase in its resources
        #    this variable is set to true and then left at that value

        self.first_turn_completed = False
        self.bb_last_turn_completed = True
        # this saves whether the last turn was completed or had TLE
        # basically set this to false at the beginning of each turn
        # and set it to True at the very end of each turn
        # use the general run method for that

        self.last_strategy_name: str | None = None
        self.last_strategy_subaction: str | None = None
        # -> this is saved after one strategy method in the list of strategy elements
        #    finishes execution to be able to continue after TLEs
        self.last_strategy_subaction_index = -1

        self.bb_type: BuilderBotType | None = None
        self.bb_strategy: Strategy | None = None
        # -> this saves the strategy of the builder bot

        self.turn_started_ns: int | None = None
        self.turn_position: Position | None = None
        self.turn_team: Team | None = None
        self.turn_resources: tuple[int, int] = (0, 0)

    def u_first_turn_init(self) -> None:
        """
        Run the one-time initialisation that cannot happen in the constructor.

        This should set up role inference, populate the first visible map
        snapshot, and then mark the bot as fully initialised.
        """
        raise NotImplementedError

    def u_turn_init(self) -> None:
        """
        Refresh the per-turn controller and cached world state.

        The later implementation should keep this lightweight by delegating the
        heavy precomputation to `Map.u_update_vision`.
        """
        raise NotImplementedError

    def u_infer_strategy_by_spawning_tile(self) -> Strategy | None:
        """
        Infer the builder strategy from the core tile on which the bot spawned.

        There should be a constant declared somewhere that assigns each of the
        nine core tiles a builder-bot role.
        """
        raise NotImplementedError

    def c_get_builder_strategy(self, builder_type: BuilderBotType) -> Strategy | None:
        """Return the declared strategy for one builder-bot role."""
        return BUILDER_STRATEGIES.get(builder_type)

    def c_update_core_spawn_events(self) -> None:
        """Refresh the set of core spawn events that have already fired."""
        raise NotImplementedError

    def c_get_next_scheduled_builder_type(self) -> BuilderBotType | None:
        """Return the next builder type that the core spawn plan wants to emit."""
        raise NotImplementedError

    def c_choose_core_spawn_tile(self, builder_type: BuilderBotType) -> Position | None:
        """Choose the preferred currently legal spawn tile for one builder type."""
        raise NotImplementedError

    def c_select_fire_target(
        self,
        priority: tuple[EntityType, ...],
    ) -> Position | None:
        """Choose one fire target from the already cached visible battlefield."""
        raise NotImplementedError

    def c_select_launcher_throw(self) -> tuple[Position, Position] | None:
        """Choose the pickup tile and throw target for a launcher turn."""
        raise NotImplementedError

    def u_run(self, ct: Controller) -> None:
        """
        Execute one full turn for the current unit.

        The later implementation should update the controller reference, run
        turn initialisation, dispatch to the right unit handler, and then mark
        turn completion in `u_turn_post`.
        """
        raise NotImplementedError

    def u_turn_post(self) -> None:
        """Finalize one turn and persist any state needed for the next round."""
        raise NotImplementedError

    def u_get_ns_elapsed(self) -> int:
        """Return the nanoseconds already spent in the current turn."""
        raise NotImplementedError

    def u_get_ns_remaining(self) -> int:
        """Estimate the nanoseconds still available in the current turn."""
        raise NotImplementedError

    def u_handler_bb(self) -> None:
        """Execute the currently assigned builder-bot strategy."""
        raise NotImplementedError

    def u_handler_core(self) -> None:
        """
        Execute the core builder-spawn plan and any dynamic spawn overrides.

        There should be a constant declared in this file that sets the initial
        builder bots to spawn, interleaved with event checkpoints.
        """
        raise NotImplementedError

    def u_handler_gunner(self) -> None:
        """
        Fire the gunner according to the modular target-priority system.

        The target selection should be fully cache-driven so this handler only
        needs to choose and execute the final fire decision.
        """
        raise NotImplementedError

    def u_handler_sentinel(self) -> None:
        """
        Fire the sentinel according to the modular target-priority system.

        The target selection should be fully cache-driven so this handler only
        needs to choose and execute the final fire decision.
        """
        raise NotImplementedError

    def u_handler_launcher(self) -> None:
        """
        Throw a builder bot according to the modular launcher-priority system.

        The expensive search should already be encoded in cached map facts so
        this handler mainly performs the final throw decision.
        """
        raise NotImplementedError

    def u_handler_breach(self) -> None:
        """Leave the breach handler empty for now."""
        raise NotImplementedError

    def s_build_harvester_supply_link(
        self,
        move_towards: bool = True,
        hold: bool = True,
        resource_environment: Environment = Environment.ORE_TITANIUM,
        destination_building_type: EntityType = EntityType.CORE,
    ) -> bool:
        """
        Build a supplier next to a harvester that still lacks one.

        The later implementation should use cache-driven candidate ordering so
        the step only has to pick the highest-priority prepared option.
        """
        # TODO: manually review the priority generated by ai here
        raise NotImplementedError

    def s_harvester_launcher(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> bool:
        """
        Build a launcher next to an allied harvester that needs protection.

        The later implementation should prefer placements that still leave the
        supplying tile within launcher coverage.
        """
        raise NotImplementedError

    def s_harvester_barrier(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> bool:
        """
        Build a barrier next to an allied harvester that has open exposure.

        This is the cheaper protection fallback when a launcher is not the
        desired answer for the current tile.
        """
        raise NotImplementedError

    def s_complete_supply_chain(
        self,
        move_towards: bool = True,
        hold: bool = True,
        destination_building_type: EntityType = EntityType.CORE,
    ) -> bool:
        """
        Continue a partially started supply chain until it reconnects inward.

        This step exists separately from generic gap-filling so recent chain
        work can be finished deterministically before new gaps are chosen.
        """
        raise NotImplementedError

    def s_build_missing_supply_link(
        self,
        move_towards: bool = True,
        hold: bool = True,
        destroy_enemy_tile: bool = True,
        destination_building_type: EntityType = EntityType.CORE,
    ) -> bool:
        """
        Fill a cached supply-link gap inside an already known resource chain.

        The goal of this method is to ensure complete supply chains. Basically,
        if there is some tile known to be pointed at by a conveyor or bridge
        but the tile itself is not a core tile, nor an own supply link tile
        itself, then we want to build a supply link at that location.
        """
        raise NotImplementedError

    def s_build_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
        destroy_enemy_tile: bool = True,
        resource_environment: Environment = Environment.ORE_TITANIUM,
        enforce_harvester_cap: bool = True,
    ) -> bool:
        """
        Build a new harvester on the highest-priority visible ore tile.

        The later implementation should support both titanium and axionite by
        reusing the same cache-driven ranking pipeline.
        """
        # TODO: manually review the priority generated by ai here
        raise NotImplementedError

    def s_expand(self) -> bool:
        """
        Explore outward when no higher-priority builder action is available.

        This will be the low-priority generic scouting fallback.
        """
        # TODO: come up with a nice system for expansion / scouting
        raise NotImplementedError

    def s_destroy_hijacked_supply_link(self, move_towards: bool = True) -> bool:
        """
        Destroy allied supply links that currently feed enemy structures.

        This should mainly target cases where our own logistics now benefit an
        enemy turret or an enemy continuation of that chain.
        """
        # TODO: review the priority ordering here
        raise NotImplementedError

    def u_get_sentinel_orientation(self, pos: Position) -> Direction | None:
        """
        Return the best facing for a sentinel that will be built at one tile.

        The later implementation should first preserve supply access, then rank
        enemy-core pressure, turret coverage, and logistics disruption.
        """
        raise NotImplementedError

    def u_get_gunner_orientation(self, pos: Position) -> Direction | None:
        """
        Return the best facing for a gunner that will be built at one tile.

        This should mirror the sentinel orientation pipeline where appropriate
        while still allowing gunner-specific targeting differences later.
        """
        raise NotImplementedError

    def s_sentinel_next_to_enemy_harvester(
        self,
        move_towards: bool = True,
        destroy_enemy_tile: bool = False,
        hold: bool = False,
    ) -> bool:
        """
        Build a sentinel next to an exposed enemy harvester.

        If there are multiple valid placements, the later implementation
        should rely on a dedicated priority ordering.
        """
        # TODO: review this priority ordering
        raise NotImplementedError

    def s_block_enemy_supply_chain(self, move_towards: bool = True) -> bool:
        """
        Build a barrier on a tile currently targeted by an enemy supply link.

        Distance should matter strongly here so the bot does not oscillate
        between two equally annoying enemy chain points.
        """
        # TODO: review this priority ordering
        raise NotImplementedError

    def s_block_titanium(self, move_towards: bool = True) -> bool:
        """
        Build a barrier on a titanium tile to deny or delay enemy extraction.

        The barrier should remain a reversible claim because a harvester can
        later replace it if we decide to take the tile ourselves.
        """
        raise NotImplementedError

    def s_attack_enemy_harvester_supply_link(self, move_towards: bool = True) -> bool:
        """
        Attack enemy supply links that keep an enemy harvester connected.

        This is meant to open follow-up pressure such as turret placement next
        to the now-starved harvester.
        """
        # TODO: review priority
        raise NotImplementedError

    def s_attack_enemy_core_supply_link(self, move_towards: bool = True) -> bool:
        """
        Attack enemy supply links that directly feed the enemy core.

        This should later use a dedicated priority ordering just like the
        harvester-supply-link attack step.
        """
        # TODO: review priority
        raise NotImplementedError

    def s_build_core_splitter(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> bool:
        """Build the planned core-adjacent splitter for the foundry pipeline."""
        raise NotImplementedError

    def s_connect_core_splitter(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> bool:
        """Connect the core-adjacent splitter back to the existing supply net."""
        raise NotImplementedError

    def s_build_foundry(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> bool:
        """Build the planned allied foundry once its staging area is ready."""
        raise NotImplementedError

    def s_attack_res_blocking_enemy_tile(self, move_towards: bool = True) -> bool:
        """Destroy enemy tiles that currently block high-priority resource claims."""
        raise NotImplementedError

    def s_foundry_expand(self) -> bool:
        """Scout for axionite opportunities once the foundry pipeline exists."""
        raise NotImplementedError

    def s_launcher_defend(
        self,
        move_towards: bool = True,
        hold: bool = False,
    ) -> bool:
        """Build or stage a launcher against enemy builders on allied logistics."""
        raise NotImplementedError

    def s_patrol_supply_chains(
        self,
        move_towards: bool = True,
        allow_build: bool = True,
    ) -> bool:
        """Patrol allied supply chains and react to stale or vulnerable segments."""
        raise NotImplementedError


UNIT_HANDLER_METHOD_NAMES: Final[dict[EntityType, str]] = {
    EntityType.BUILDER_BOT: "u_handler_bb",
    EntityType.CORE: "u_handler_core",
    EntityType.GUNNER: "u_handler_gunner",
    EntityType.SENTINEL: "u_handler_sentinel",
    EntityType.LAUNCHER: "u_handler_launcher",
    EntityType.BREACH: "u_handler_breach",
}

INITIAL_BB_SPAWN_PLAN: Final[tuple[CoreSpawnPlanEntry, ...]] = (
    BuilderBotType.INITIAL_RES,
    BuilderBotType.INITIAL_RES,
    BuilderBotType.HARASSMENT,
    CoreSpawnEvent.FIRST_RESOURCE_INCREASE,
    CoreSpawnEvent.ENEMY_BOT_IN_CORE_VISION,
    BuilderBotType.DEFENDER,
    CoreSpawnTurnEvent(100),
    BuilderBotType.SCAVENGER,
)

CORE_TILE_BB_TYPE: Final[dict[PositionKey, BuilderBotType]] = {
    (-1, -1): BuilderBotType.INITIAL_RES,
    (0, -1): BuilderBotType.HARASSMENT,
    (1, -1): BuilderBotType.DEFENDER,
    (-1, 0): BuilderBotType.SCAVENGER,
    (0, 0): BuilderBotType.FOUNDRYBOT,
    (1, 0): BuilderBotType.HARASSMENT,
    (-1, 1): BuilderBotType.SCAVENGER,
    (0, 1): BuilderBotType.SCAVENGER,
    (1, 1): BuilderBotType.INITIAL_RES,
}

INITIAL_RES_STRATEGY = Strategy(
    name="initial_res",
    main_steps=(
        StrategyStep(
            "build_harvester_supply_link",
            "s_build_harvester_supply_link",
            {"hold": True},
        ),
        StrategyStep("harvester_launcher", "s_harvester_launcher", {"hold": True}),
        StrategyStep("harvester_barrier", "s_harvester_barrier", {"hold": True}),
        StrategyStep("complete_supply_chain", "s_complete_supply_chain", {"hold": True}),
        StrategyStep(
            "build_missing_supply_link",
            "s_build_missing_supply_link",
            {"hold": True},
        ),
        StrategyStep("build_harvester", "s_build_harvester", {"hold": True}),
        StrategyStep("expand", "s_expand"),
    ),
)

SCAVENGER_STRATEGY = Strategy(
    name="scavenger",
    main_steps=(
        StrategyStep(
            "destroy_hijacked_supply_link",
            "s_destroy_hijacked_supply_link",
        ),
        StrategyStep(
            "build_harvester_supply_link",
            "s_build_harvester_supply_link",
            {"hold": True},
        ),
        StrategyStep("harvester_launcher", "s_harvester_launcher", {"hold": True}),
        StrategyStep("harvester_barrier", "s_harvester_barrier", {"hold": True}),
        StrategyStep("complete_supply_chain", "s_complete_supply_chain", {"hold": True}),
        StrategyStep(
            "build_missing_supply_link",
            "s_build_missing_supply_link",
            {"hold": True},
        ),
        StrategyStep(
            "sentinel_next_to_enemy_harvester",
            "s_sentinel_next_to_enemy_harvester",
            {
                "move_towards": True,
                "destroy_enemy_tile": False,
                "hold": False,
            },
        ),
        StrategyStep("build_harvester", "s_build_harvester", {"hold": True}),
        StrategyStep(
            "patrol_supply_chains",
            "s_patrol_supply_chains",
            {"allow_build": False},
        ),
        StrategyStep("expand", "s_expand"),
    ),
)

HARASSMENT_STRATEGY = Strategy(
    name="harassment",
    main_steps=(
        StrategyStep(
            "sentinel_next_to_enemy_harvester",
            "s_sentinel_next_to_enemy_harvester",
            {
                "move_towards": True,
                "destroy_enemy_tile": False,
                "hold": False,
            },
        ),
        StrategyStep("block_enemy_supply_chain", "s_block_enemy_supply_chain"),
        StrategyStep("block_titanium", "s_block_titanium"),
        StrategyStep(
            "attack_enemy_harvester_supply_link",
            "s_attack_enemy_harvester_supply_link",
        ),
        StrategyStep(
            "attack_enemy_core_supply_link",
            "s_attack_enemy_core_supply_link",
        ),
        StrategyStep("expand", "s_expand"),
    ),
)

# foundry bot
# still TODO
FOUNDRY_STRATEGY = Strategy(
    name="foundry",
    main_steps=(
        StrategyStep("build_core_splitter", "s_build_core_splitter", {"hold": True}),
        StrategyStep(
            "connect_core_splitter",
            "s_connect_core_splitter",
            {"hold": True},
        ),
        StrategyStep("build_foundry", "s_build_foundry", {"hold": True}),
        StrategyStep(
            "attack_res_blocking_enemy_tile",
            "s_attack_res_blocking_enemy_tile",
        ),
        StrategyStep(
            "build_harvester_axionite",
            "s_build_harvester",
            {
                "hold": True,
                "resource_environment": Environment.ORE_AXIONITE,
                "enforce_harvester_cap": False,
            },
        ),
        StrategyStep(
            "build_harvester_supply_link_axionite",
            "s_build_harvester_supply_link",
            {
                "hold": True,
                "resource_environment": Environment.ORE_AXIONITE,
                "destination_building_type": EntityType.FOUNDRY,
            },
        ),
        StrategyStep(
            "build_missing_supply_link_axionite",
            "s_build_missing_supply_link",
            {
                "hold": True,
                "destination_building_type": EntityType.FOUNDRY,
            },
        ),
        StrategyStep("foundry_expand", "s_foundry_expand"),
    ),
)

# defender bot
# still TODO
DEFENDER_STRATEGY = Strategy(
    name="defender",
    main_steps=(
        StrategyStep("launcher_defend", "s_launcher_defend"),
        StrategyStep("patrol_supply_chains", "s_patrol_supply_chains"),
    ),
)

BUILDER_STRATEGIES: Final[dict[BuilderBotType, Strategy]] = {
    BuilderBotType.INITIAL_RES: INITIAL_RES_STRATEGY,
    BuilderBotType.SCAVENGER: SCAVENGER_STRATEGY,
    BuilderBotType.HARASSMENT: HARASSMENT_STRATEGY,
    BuilderBotType.FOUNDRYBOT: FOUNDRY_STRATEGY,
    BuilderBotType.DEFENDER: DEFENDER_STRATEGY,
}


class Player(Bot):
    """Expose the standard bot entry point expected by the game engine."""

    pass
