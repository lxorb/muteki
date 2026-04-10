"""
LLM / CODING AGENT CAMBC PACKAGE KNOWLEDGE

The following is the content of the _types.py file, which defines the cambc package api.
The doc-string-comments are prefixed with a backslash because
the content is wrapped in this current doc-string, with whom they would interact otherwise.
So the backslashes don't have any meaning, they are just there to have the entire file inside one doc-string.

\"""Common types for the Titan game.\"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, NamedTuple


class GameError(Exception):
    \"""Raised when a player issues an invalid action.\"""

    __slots__ = ()


class Team(Enum):
    __slots__ = ()

    A = "a"
    B = "b"


class ResourceType(Enum):
    __slots__ = ()

    TITANIUM = "titanium"
    RAW_AXIONITE = "raw_axionite"
    REFINED_AXIONITE = "refined_axionite"


class EntityType(Enum):
    __slots__ = ()

    BUILDER_BOT = "builder_bot"
    CORE = "core"
    GUNNER = "gunner"
    SENTINEL = "sentinel"
    BREACH = "breach"
    LAUNCHER = "launcher"
    CONVEYOR = "conveyor"
    SPLITTER = "splitter"
    ARMOURED_CONVEYOR = "armoured_conveyor"
    BRIDGE = "bridge"
    HARVESTER = "harvester"
    FOUNDRY = "foundry"
    ROAD = "road"
    BARRIER = "barrier"
    MARKER = "marker"


class GameConstants:
    __slots__ = ()

    MAX_TURNS = 2000
    STACK_SIZE = 10
    STARTING_TITANIUM = 500
    STARTING_AXIONITE = 0
    MAX_TEAM_UNITS = 50
    PASSIVE_TITANIUM_AMOUNT = 10
    PASSIVE_TITANIUM_INTERVAL = 4
    AXIONITE_CONVERSION_TITANIUM_RATE = 4

    ACTION_RADIUS_SQ = 2
    CORE_SPAWNING_RADIUS_SQ = 2
    CORE_ACTION_RADIUS_SQ = 8

    BRIDGE_TARGET_RADIUS_SQ = 9

    CORE_VISION_RADIUS_SQ = 36
    BUILDER_BOT_VISION_RADIUS_SQ = 20
    GUNNER_VISION_RADIUS_SQ = 13
    SENTINEL_VISION_RADIUS_SQ = 32
    BREACH_VISION_RADIUS_SQ = 2
    LAUNCHER_VISION_RADIUS_SQ = 26

    CONVEYOR_BASE_COST = (3, 0)
    SPLITTER_BASE_COST = (6, 0)
    BRIDGE_BASE_COST = (20, 0)
    ARMOURED_CONVEYOR_BASE_COST = (5, 5)
    HARVESTER_BASE_COST = (20, 0)
    ROAD_BASE_COST = (1, 0)
    BARRIER_BASE_COST = (3, 0)
    GUNNER_BASE_COST = (10, 0)
    SENTINEL_BASE_COST = (30, 0)
    BREACH_BASE_COST = (15, 10)
    LAUNCHER_BASE_COST = (20, 0)
    FOUNDRY_BASE_COST = (40, 0)
    BUILDER_BOT_BASE_COST = (30, 0)
    GUNNER_ROTATE_COST = (10, 0)
    GUNNER_ROTATE_COOLDOWN = 1

    CONVEYOR_MAX_HP = 20
    SPLITTER_MAX_HP = 20
    BRIDGE_MAX_HP = 20
    ARMOURED_CONVEYOR_MAX_HP = 50
    HARVESTER_MAX_HP = 30
    ROAD_MAX_HP = 5
    BARRIER_MAX_HP = 30
    FOUNDRY_MAX_HP = 50
    MARKER_MAX_HP = 1

    BUILDER_BOT_MAX_HP = 40
    CORE_MAX_HP = 500
    GUNNER_MAX_HP = 40
    SENTINEL_MAX_HP = 30
    BREACH_MAX_HP = 60
    LAUNCHER_MAX_HP = 30

    BUILDER_BOT_SELF_DESTRUCT_DAMAGE = 0
    BUILDER_BOT_ATTACK_DAMAGE = 2
    BUILDER_BOT_ATTACK_COST = (2, 0)
    BUILDER_BOT_HEAL_COST = (1, 0)
    HEAL_AMOUNT = 4

    GUNNER_DAMAGE = 10
    GUNNER_AXIONITE_DAMAGE = 40
    GUNNER_FIRE_COOLDOWN = 1
    GUNNER_AMMO_COST = 2

    SENTINEL_DAMAGE = 18
    SENTINEL_FIRE_COOLDOWN = 3
    SENTINEL_AMMO_COST = 10
    SENTINEL_STUN_DURATION = 5

    BREACH_DAMAGE = 40
    BREACH_SPLASH_DAMAGE = 20
    BREACH_FIRE_COOLDOWN = 1
    BREACH_AMMO_COST = 5
    BREACH_ATTACK_RADIUS_SQ = 13

    LAUNCHER_FIRE_COOLDOWN = 1



class Environment(Enum):
    __slots__ = ()

    EMPTY = "empty"
    WALL = "wall"
    ORE_TITANIUM = "ore_titanium"
    ORE_AXIONITE = "ore_axionite"


class Direction(Enum):
    __slots__ = ()

    NORTH = "north"
    NORTHEAST = "northeast"
    EAST = "east"
    SOUTHEAST = "southeast"
    SOUTH = "south"
    SOUTHWEST = "southwest"
    WEST = "west"
    NORTHWEST = "northwest"
    CENTRE = "centre"

    def delta(self) -> tuple[int, int]:
        \"""Return the (dx, dy) step for this direction.\"""
        return {
            Direction.NORTH: (0, -1),
            Direction.NORTHEAST: (1, -1),
            Direction.EAST: (1, 0),
            Direction.SOUTHEAST: (1, 1),
            Direction.SOUTH: (0, 1),
            Direction.SOUTHWEST: (-1, 1),
            Direction.WEST: (-1, 0),
            Direction.NORTHWEST: (-1, -1),
            Direction.CENTRE: (0, 0),
        }[self]

    def rotate_left(self) -> Direction:
        \"""Return the direction rotated 45 degrees counterclockwise.\"""
        return {
            Direction.NORTH: Direction.NORTHWEST,
            Direction.NORTHEAST: Direction.NORTH,
            Direction.EAST: Direction.NORTHEAST,
            Direction.SOUTHEAST: Direction.EAST,
            Direction.SOUTH: Direction.SOUTHEAST,
            Direction.SOUTHWEST: Direction.SOUTH,
            Direction.WEST: Direction.SOUTHWEST,
            Direction.NORTHWEST: Direction.WEST,
            Direction.CENTRE: Direction.CENTRE,
        }[self]

    def rotate_right(self) -> Direction:
        \"""Return the direction rotated 45 degrees clockwise.\"""
        return {
            Direction.NORTH: Direction.NORTHEAST,
            Direction.NORTHEAST: Direction.EAST,
            Direction.EAST: Direction.SOUTHEAST,
            Direction.SOUTHEAST: Direction.SOUTH,
            Direction.SOUTH: Direction.SOUTHWEST,
            Direction.SOUTHWEST: Direction.WEST,
            Direction.WEST: Direction.NORTHWEST,
            Direction.NORTHWEST: Direction.NORTH,
            Direction.CENTRE: Direction.CENTRE,
        }[self]

    def opposite(self) -> Direction:
        \"""Return the opposite direction (180 degrees).\"""
        return {
            Direction.NORTH: Direction.SOUTH,
            Direction.NORTHEAST: Direction.SOUTHWEST,
            Direction.EAST: Direction.WEST,
            Direction.SOUTHEAST: Direction.NORTHWEST,
            Direction.SOUTH: Direction.NORTH,
            Direction.SOUTHWEST: Direction.NORTHEAST,
            Direction.WEST: Direction.EAST,
            Direction.NORTHWEST: Direction.SOUTHEAST,
            Direction.CENTRE: Direction.CENTRE,
        }[self]


class Position(NamedTuple):
    x: int
    y: int

    def add(self, d: Direction) -> Position:
        \"""Return a new position offset by the direction delta.\"""
        dx, dy = d.delta()
        return Position(self.x + dx, self.y + dy)

    def distance_squared(self, other: Position) -> int:
        \"""Return squared distance to another position.\"""
        dx = self.x - other.x
        dy = self.y - other.y
        return dx * dx + dy * dy

    def direction_to(self, other: Position) -> Direction:
        \"""Return the closest 45-degree Direction approximation toward other.\"""
        dx = other.x - self.x
        dy = other.y - self.y
        if dx == 0 and dy == 0:
            return Direction.CENTRE
        # atan2 gives angle in radians; map to one of 8 compass directions.
        import math
        # Use y-up convention for direction mapping: north is decreasing y.
        angle = math.atan2(-dy, dx)  # radians, x-east / y-north convention
        # Snap to nearest 45-degree sector (each sector is pi/4 wide).
        # Sectors: E=0, NE=1, N=2, NW=3, W=4, SW=5, S=6, SE=7
        sector = int((angle + 2 * math.pi + math.pi / 8) / (math.pi / 4)) % 8
        return [
            Direction.EAST,
            Direction.NORTHEAST,
            Direction.NORTH,
            Direction.NORTHWEST,
            Direction.WEST,
            Direction.SOUTHWEST,
            Direction.SOUTH,
            Direction.SOUTHEAST,
        ][sector]


# Stub for type-checking only. The real Controller is injected from Rust at runtime.
# Keep in sync with engine/rust/src/bindings/controller.rs.
#
# IMPORTANT: The stub class must NOT be defined at runtime. With SHARED_GIL
# subinterpreters, a Python Controller class whose methods share names with the
# Rust Controller's methods (e.g. `move`) pollutes method resolution across
# subinterpreters, causing bot-defined Python methods to be incorrectly bound to
# Controller instances. The real Controller is set by the engine after import.

# The real Controller is injected from Rust at runtime. We must NOT define a
# Python class with method stubs here — with SHARED_GIL subinterpreters, Python
# methods on a stub Controller class pollute the Rust Controller's method
# resolution, causing bot-defined methods with the same name (e.g. `move`) to be
# incorrectly bound to Controller instances in other subinterpreters.
class Controller:  # Placeholder — overwritten by Rust class before bot code runs.
    pass

if TYPE_CHECKING:
    class Controller:  # type: ignore[no-redef]
        # --- Info ---

        def get_team(self, id: int | None = None) -> Team:
            \"""Return the team of the entity with the given id, or this unit if omitted.\"""
            ...

        def get_position(self, id: int | None = None) -> Position:
            \"""Return the position of the entity with the given id, or this unit if omitted.\"""
            ...

        def get_id(self) -> int:
            \"""Return this unit's entity id.\"""
...

def get_action_cooldown(self) -> int:
    \"""Return this unit's current action cooldown. Actions require cooldown == 0.\"""
    ...

def get_move_cooldown(self) -> int:
    \"""Return this unit's current move cooldown. Movement requires cooldown == 0.\"""
    ...

def get_ammo_amount(self) -> int:
    \"""Return the amount of ammo this turret currently holds.\"""
    ...

def get_ammo_type(self) -> ResourceType | None:
    \"""Return the resource type loaded as ammo, or None if empty.\"""
    ...

def get_vision_radius_sq(self, id: int | None = None) -> int:
    \"""Return the vision radius squared of the given unit, or this unit if omitted.\"""
    ...

def get_hp(self, id: int | None = None) -> int:
    \"""Return the current HP of the entity with the given id, or this unit if omitted.\"""
    ...

def get_max_hp(self, id: int | None = None) -> int:
    \"""Return the max HP of the entity with the given id, or this unit if omitted.\"""
    ...

def get_entity_type(self, id: int | None = None) -> EntityType:
    \"""Return the EntityType of the entity with the given id, or this unit if omitted.\"""
    ...

def get_direction(self, id: int | None = None) -> Direction:
    \"""Return the facing direction of a conveyor, splitter, armoured conveyor, or turret.
    Raises GameError if the entity has no direction.\"""
    ...

def get_bridge_target(self, id: int) -> Position:
    \"""Return the output target position of a bridge. Raises GameError if not a bridge.\"""
    ...

def get_stored_resource(self, id: int | None = None) -> ResourceType | None:
    \"""Return the resource stored in a conveyor, splitter, armoured conveyor, bridge, or foundry.
    Returns None if empty. Raises GameError if the entity has no storage.\"""
    ...

def get_stored_resource_id(self, id: int | None = None) -> int | None:
    \"""Return the id of the resource stored in a conveyor, splitter, armoured conveyor, bridge, or foundry.
    Returns None if empty. Raises GameError if the entity has no storage.\"""
    ...

def get_tile_env(self, pos: Position) -> Environment:
    \"""Return the environment type (empty, wall, ore) of the tile at pos.\"""
    ...

def get_tile_building_id(self, pos: Position) -> int | None:
    \"""Return the id of the building on the tile at pos, or None if there is none.\"""
    ...

def get_tile_builder_bot_id(self, pos: Position) -> int | None:
    \"""Return the id of the builder bot on the tile at pos, or None if there is none.\"""
    ...

def is_tile_empty(self, pos: Position) -> bool:
    \"""Return True if the tile has no building and is not a wall.\"""
    ...

def is_tile_passable(self, pos: Position) -> bool:
    \"""Return True if a builder bot belonging to this team could stand on the tile
    (i.e. it contains a conveyor, road, or allied core, and no other builder bot).\"""
    ...

def is_in_vision(self, pos: Position) -> bool:
    \"""Return True if pos is within this unit's vision radius.\"""
    ...

def get_nearby_tiles(self, dist_sq: int | None = None) -> list[Position]:
    \"""Return all in-bounds tile positions within dist_sq of this unit (defaults to vision radius).
    dist_sq must not exceed the vision radius.\"""
    ...

def get_nearby_entities(self, dist_sq: int | None = None) -> list[int]:
    \"""Return ids of all entities on tiles within dist_sq (defaults to vision radius).\"""
    ...

def get_nearby_buildings(self, dist_sq: int | None = None) -> list[int]:
    \"""Return ids of all buildings within dist_sq (defaults to vision radius).\"""
    ...

def get_nearby_units(self, dist_sq: int | None = None) -> list[int]:
    \"""Return ids of all units within dist_sq (defaults to vision radius).\"""
    ...

def get_map_width(self) -> int:
    \"""Return the width of the map in tiles.\"""
    ...

def get_map_height(self) -> int:
    \"""Return the height of the map in tiles.\"""
    ...

def get_current_round(self) -> int:
    \"""Return the current round number (starts at 1).\"""
    ...

def get_global_resources(self) -> tuple[int, int]:
    \"""Return (titanium, axionite) in this team's global resource pool.\"""
    ...

def get_scale_percent(self) -> float:
    \"""Return this team's current cost scale as a percentage (100.0 = base cost; used in the scaling formula).\"""
    ...

def get_cpu_time_elapsed(self) -> int:
    \"""Return the CPU time elapsed this turn in microseconds.\"""
    ...

    # --- Cost getters ---

def get_conveyor_cost(self) -> tuple[int, int]:
    \"""Return the current scaled cost (Ti, Ax) to build a conveyor.\"""
    ...

def get_splitter_cost(self) -> tuple[int, int]:
    \"""Return the current scaled cost (Ti, Ax) to build a splitter.\"""
    ...

def get_bridge_cost(self) -> tuple[int, int]:
    \"""Return the current scaled cost (Ti, Ax) to build a bridge.\"""
    ...

def get_armoured_conveyor_cost(self) -> tuple[int, int]:
    \"""Return the current scaled cost (Ti, Ax) to build an armoured conveyor.\"""
    ...

def get_harvester_cost(self) -> tuple[int, int]:
    \"""Return the current scaled cost (Ti, Ax) to build a harvester.\"""
    ...

def get_road_cost(self) -> tuple[int, int]:
    \"""Return the current scaled cost (Ti, Ax) to build a road.\"""
    ...

def get_barrier_cost(self) -> tuple[int, int]:
    \"""Return the current scaled cost (Ti, Ax) to build a barrier.\"""
    ...

def get_gunner_cost(self) -> tuple[int, int]:
    \"""Return the current scaled cost (Ti, Ax) to build a gunner.\"""
    ...

def get_sentinel_cost(self) -> tuple[int, int]:
    \"""Return the current scaled cost (Ti, Ax) to build a sentinel.\"""
    ...

def get_breach_cost(self) -> tuple[int, int]:
    \"""Return the current scaled cost (Ti, Ax) to build a breach.\"""
    ...

def get_launcher_cost(self) -> tuple[int, int]:
    \"""Return the current scaled cost (Ti, Ax) to build a launcher.\"""
    ...

def get_foundry_cost(self) -> tuple[int, int]:
    \"""Return the current scaled cost (Ti, Ax) to build an axionite foundry.\"""
    ...

def get_builder_bot_cost(self) -> tuple[int, int]:
    \"""Return the current scaled cost (Ti, Ax) to spawn a builder bot.\"""
    ...

def get_unit_count(self) -> int:
    \"""Return the number of living units currently on this unit's team, including the core.\"""
    ...

    # --- Movement ---

def move(self, direction: Direction) -> None:
    \"""Move this builder bot one step in direction. Raises GameError if the move is not legal.\"""
    ...

def can_move(self, direction: Direction) -> bool:
    \"""Return True if this builder bot can move in direction this turn.\"""
    ...

    # --- Building ---

def can_build_conveyor(self, position: Position, direction: Direction) -> bool:
    \"""Return True if a conveyor facing direction can be built at position.\"""
    ...

def can_build_splitter(self, position: Position, direction: Direction) -> bool:
    \"""Return True if a splitter facing direction can be built at position.\"""
    ...

def can_build_bridge(self, position: Position, target: Position) -> bool:
    \"""Return True if a bridge outputting to target can be built at position.
    target must be within distance_squared BRIDGE_TARGET_RADIUS_SQ of position.\"""
    ...

def can_build_armoured_conveyor(self, position: Position, direction: Direction) -> bool:
    \"""Return True if an armoured conveyor facing direction can be built at position.\"""
    ...

def can_build_harvester(self, position: Position) -> bool:
    \"""Return True if a harvester can be built at position (must be an ore tile).\"""
    ...

def can_build_road(self, position: Position) -> bool:
    \"""Return True if a road can be built at position.\"""
    ...

def can_build_barrier(self, position: Position) -> bool:
    \"""Return True if a barrier can be built at position.\"""
    ...

def can_build_gunner(self, position: Position, direction: Direction) -> bool:
    \"""Return True if a gunner facing direction can be built at position.
    Respects the global unit cap.\"""
    ...

def can_build_sentinel(self, position: Position, direction: Direction) -> bool:
    \"""Return True if a sentinel facing direction can be built at position.
    Respects the global unit cap.\"""
    ...

def can_build_breach(self, position: Position, direction: Direction) -> bool:
    \"""Return True if a breach facing direction can be built at position.
    Respects the global unit cap.\"""
    ...

def can_build_launcher(self, position: Position) -> bool:
    \"""Return True if a launcher can be built at position.
    Respects the global unit cap.\"""
    ...

def can_build_foundry(self, position: Position) -> bool:
    \"""Return True if an axionite foundry can be built at position.\"""
    ...

def build_conveyor(self, position: Position, direction: Direction) -> int:
    \"""Build a conveyor facing direction at position. Raises GameError if not legal.\"""
    ...

def build_splitter(self, position: Position, direction: Direction) -> int:
    \"""Build a splitter facing direction at position. Raises GameError if not legal.\"""
    ...

def build_bridge(self, position: Position, target: Position) -> int:
    \"""Build a bridge at position outputting to target. Raises GameError if not legal.\"""
    ...

def build_armoured_conveyor(self, position: Position, direction: Direction) -> int:
    \"""Build an armoured conveyor facing direction at position. Raises GameError if not legal.\"""
    ...

def build_harvester(self, position: Position) -> int:
    \"""Build a harvester at position (must be an ore tile). Raises GameError if not legal.\"""
    ...

def build_road(self, position: Position) -> int:
    \"""Build a road at position. Raises GameError if not legal.\"""
    ...

def build_barrier(self, position: Position) -> int:
    \"""Build a barrier at position. Raises GameError if not legal.\"""
    ...

def build_gunner(self, position: Position, direction: Direction) -> int:
    \"""Build a gunner facing direction at position. Raises GameError if not legal.\"""
    ...

def build_sentinel(self, position: Position, direction: Direction) -> int:
    \"""Build a sentinel facing direction at position. Raises GameError if not legal.\"""
    ...

def build_breach(self, position: Position, direction: Direction) -> int:
    \"""Build a breach facing direction at position. Raises GameError if not legal.\"""
    ...

def build_launcher(self, position: Position) -> int:
    \"""Build a launcher at position. Raises GameError if not legal.\"""
    ...

def build_foundry(self, position: Position) -> int:
    \"""Build an axionite foundry at position. Raises GameError if not legal.\"""
    ...

def can_build(
        self,
        entity_type: EntityType,
        position: Position,
        extra: Direction | Position | None = None,
) -> bool:
    \"""Return True if entity_type can be built at position.
    For entity types that require a direction (conveyor, splitter, armoured_conveyor,
    gunner, sentinel, breach), extra must be a Direction.
    For bridge, extra must be the target Position.
    For harvester, road, barrier, launcher, foundry, extra is unused.\"""
    ...

def build(
        self,
        entity_type: EntityType,
        position: Position,
        extra: Direction | Position | None = None,
) -> int:
    \"""Build entity_type at position. Raises GameError if not legal.
    For entity types that require a direction (conveyor, splitter, armoured_conveyor,
    gunner, sentinel, breach), extra must be a Direction.
    For bridge, extra must be the target Position.
    For harvester, road, barrier, launcher, foundry, extra is unused.\"""
    ...

    # --- Healing ---

def heal(self, position: Position) -> None:
    \"""Heal all friendly entities on a tile within this builder bot's action radius by 4 HP.
    If both a friendly builder bot and a friendly building are on the tile, both are healed.
    Costs 1 titanium and one action cooldown. Raises GameError if not legal.\"""
    ...

def can_heal(self, position: Position) -> bool:
    \"""Return True if this builder bot can heal the tile at position this turn.
    position must be within the builder bot's action radius.
    Requires action cooldown == 0, enough titanium, and at least one damaged friendly entity
    on the tile.\"""
    ...

    # --- Destruction ---

def can_destroy(self, building_pos: Position) -> bool:
    \"""Return True if this builder bot can destroy the allied building at building_pos.\"""
    ...

def destroy(self, building_pos: Position) -> None:
    \"""Destroy the allied building at building_pos. Does not cost action cooldown.
    Raises GameError if not legal.\"""
    ...

def self_destruct(self) -> None:
    \"""Destroy this unit. Builder bots no longer deal explosion damage when they self-destruct.\"""
    ...

def resign(self, message: str | None = None) -> None:
    \"""Forfeit the game immediately. Destroys this team's core, ending the game as a loss.

    Args:
        message: Optional reason for resigning. Displayed in match results.
    \"""
    ...

    # --- Markers ---

def can_place_marker(self, position: Position) -> bool:
    \"""Return True if this unit can place a marker at position this turn.
    Each unit may place at most one marker per turn; cannot overwrite enemy markers.\"""
    ...

def place_marker(self, position: Position, value: int) -> None:
    \"""Place a marker with the given u32 value at position. Does not cost action cooldown.
    Raises GameError if not legal.\"""
    ...

def get_marker_value(self, id: int) -> int:
    \"""Return the u32 value stored in the friendly marker with the given id.
    Raises GameError if the entity is not a marker or belongs to the enemy.\"""
    ...

    # --- Turrets ---

def can_fire(self, target: Position) -> bool:
    \"""Return True if this builder bot or turret can fire at target this turn.
    Builder bots may only target their own tile and only damage the building on it.
    For gunners, only empty tiles and markers fail to block the firing line. Markers are
    targetable and non-blocking. Walls block the line but are not targetable. Builder bots
    and non-marker buildings are both targetable and blocking.
    Use can_launch() instead for launchers.\"""
    ...

def can_fire_from(
        self,
        position: Position,
        direction: Direction,
        turret_type: EntityType,
        target: Position,
) -> bool:
    \"""Return True if a hypothetical turret at position facing direction could fire at target.
    This uses the current map state for occupancy and walls, but ignores ammo and cooldown.
    For gunners, the target tile must be occupied. Empty tiles and markers do not block the
    line; walls, builder bots, and non-marker buildings do, with walls remaining untargetable.
    For launchers this only checks raw throw range, and direction is ignored.\"""
    ...

def fire(self, target: Position) -> None:
    \"""Fire this builder bot or turret at target. Builder bots may only target their own tile.
    Gunners may fire through markers at occupied tiles behind them. Walls, builder bots,
    and non-marker buildings stop the firing line; walls themselves are not valid targets.
    Use launch() instead for launchers.
    Raises GameError if not legal.\"""
    ...

def can_rotate(self, direction: Direction) -> bool:
    \"""Return True if this gunner can rotate to a different compass direction this turn.
    Also checks that your team can afford the global titanium cost.\"""
    ...

def rotate(self, direction: Direction) -> None:
    \"""Rotate this gunner to a different compass direction.
    Costs 10 titanium and sets action cooldown to 1.
    Raises GameError if not legal.\"""
    ...

def get_gunner_target(self) -> Position | None:
    \"""Return the position of the closest targetable tile in the gunner's facing direction,
    or None if nothing is in range. Empty tiles are skipped. Markers may be returned even
    though they do not block farther legal targets. Walls block the line without being
    targetable. Only valid on gunners.\"""
    ...

def get_attackable_tiles(self) -> list[Position]:
    \"""Return all in-bounds tiles in this turret's raw attack pattern.
    This ignores ammo, cooldown, occupancy, and other target-specific legality checks.
    For gunners this includes the full firing line within range, even behind walls.
    Use get_gunner_target(), can_fire(), or can_launch() for actual legal targets.
    Raises GameError if this unit is not a turret.\"""
    ...

def get_attackable_tiles_from(
        self,
        position: Position,
        direction: Direction,
        turret_type: EntityType,
) -> list[Position]:
    \"""Return all in-bounds tiles in a hypothetical turret's raw attack pattern.
    This ignores ammo, cooldown, occupancy, and other target-specific legality checks.
    For gunners this includes the full firing line within range, even behind walls.
    Launchers ignore direction.\"""
    ...

def can_launch(self, bot_pos: Position, target: Position) -> bool:
    \"""Return True if this launcher can pick up the builder bot at bot_pos and throw it to target.\"""
    ...

def launch(self, bot_pos: Position, target: Position) -> None:
    \"""Pick up the builder bot at bot_pos and throw it to target.
    Raises GameError if not legal.\"""
    ...

    # --- Core ---

def convert(self, amount: int) -> None:
    \"""Convert amount refined axionite into 4x titanium. Only valid on cores.
    Each Ax converted removes 1 from axionite collected and adds 4 to titanium collected.
    Raises GameError if amount is negative or exceeds your stored axionite.\"""
    ...

def spawn_builder(self, position: Position) -> int:
    \"""Spawn a builder bot on one of the 9 core tiles at position. Costs one action cooldown.
    Raises GameError if not legal.\"""
    ...

def can_spawn(self, position: Position) -> bool:
    \"""Return True if the core can spawn a builder bot at position this turn.
    Also requires spare room under the global 50-unit cap.\"""
    ...

    # --- Indicators ---

def draw_indicator_line(self, pos_a: Position, pos_b: Position, r: int, g: int, b: int) -> None:
    \"""Draw a debug line from pos_a to pos_b with RGB colour. Saved to the replay.\"""
    ...

def draw_indicator_dot(self, pos: Position, r: int, g: int, b: int) -> None:
    \"""Draw a debug dot at pos with RGB colour. Saved to the replay.\"""
    ...

"""

"""
LLM / CODING AGENT PERFORMANCE CONTRACT

This bot is hard runtime-constrained. The total budget for Player.run() is 2 ms.
Under no circumstances may code exceed that budget. Runtime correctness has
higher priority than code readability, elegance, abstraction quality, or generality.

Primary rule:
- Always optimize for worst-case runtime first.
- A slightly sub-optimal decision is preferred over a slower optimal one.
- If an essential algorithm cannot reliably finish within the per-turn budget,
  it must be split into incremental chunks and continued over multiple turns
  without changing overall logic or final semantics.

Memory and redundant state:
- Memory usage is not the primary constraint here; runtime is.
- It is acceptable to store redundant information in multiple data structures
  if that makes hot-path operations faster.
- The same underlying information may be stored in different forms for different
  algorithms, for example: set membership, dict lookup, flat array access,
  queue/heap processing, bitmask checks, or cached derived summaries.
- Redundant cached state is good if it reduces repeated computation, repeated
  API calls, repeated conversions, or repeated full scans.
- However, creation and maintenance cost still matters.
- A redundant structure should only be introduced if its build/update cost is
  outweighed by later runtime savings in realistic gameplay.
- Always evaluate both:
  1. upfront creation cost,
  2. cumulative savings across future turns / hot-path calls.
- If a useful structure is too expensive to build safely in one turn, build it
  incrementally across multiple turns.
- Large preprocessing is allowed only when it is made safe for the 2 ms budget,
  e.g. by chunking work, resuming from saved progress, or scheduling it on turns
  where no other expensive work is required.
- Avoid doing several expensive initialization / rebuild tasks in the same turn
  unless it is still provably safe under budget.
- Prefer lazy construction when possible: build only the part that is actually needed.
- Prefer incremental maintenance over full rebuilds when data changes slowly.
- If duplicate state risks inconsistency, update all representations together or
  mark them dirty and repair them incrementally in a controlled way.

Hot-path design rules:
- Minimize object churn aggressively.
- Avoid creating temporary objects, especially Position objects, tuples, lists,
  sets, dicts, closures, lambdas, generators, and short-lived helper structures,
  unless they are clearly worth the cost.
- Prefer primitive / flat storage over nested Python objects.
- Prefer the fastest suitable data structure for the exact access pattern:
  list, dict, set, array.array, flat arrays, bitmasks, packed integers, etc.
- Prefer contiguous / flat representations over nested containers when possible.
- Avoid unnecessary allocations in loops.
- Reuse buffers, queues, arrays, and mutable containers instead of recreating them.
- Cache hot attributes, repeated lookups, constants, and bound methods into locals.
- Avoid repeated attribute access inside tight loops.
- Avoid repeated global lookups and repeated function dispatch in hot code.
- Inline tiny hot helpers if that measurably reduces overhead.
- Reduce iteration count whenever possible; fewer passes usually beats cleaner structure.
- Fuse loops when practical.
- Exit early whenever enough information is already known.
- Do not scan full collections if a partial scan or maintained incremental state is enough.
- Prefer amortized / incremental updates over full recomputation.
- Precompute anything immutable or rarely changing.
- Maintain state across turns if that avoids recomputation.
- Keep critical paths branch-light and data-local where possible.

API usage rules:
- Treat engine/API calls as potentially expensive.
- Do not call the same getter multiple times if the result can be cached locally.
- Avoid repeated idx <-> Position conversion unless strictly necessary.
- If a value is needed often, store the index/int form and convert only at the boundary.
- Avoid exception-driven control flow in hot paths.

Algorithmic rules:
- Favor bounded-time heuristics over expensive exact algorithms when the runtime win is large.
- Prefer "good enough now" over "optimal too late".
- Any search / planning / preprocessing with variable or high worst-case cost must be
  time-bounded, incrementally resumable, or both.
- Long repair, pathfinding, map analysis, or planning work should be chunked across turns.
- Preserve persistent progress/state so later turns continue work instead of restarting it.

Code style rules for performance-sensitive sections:
- Do not introduce abstractions that add overhead in hot paths just for readability.
- Avoid unnecessary wrapper classes, deep inheritance dispatch, properties,
  decorators, generic utility layers, or callback-heavy designs in performance-critical code.
- Prefer direct code over elegant indirection when performance matters.
- Avoid recursion in hot or potentially deep code paths.
- Avoid sorting unless strictly required.
- Avoid copying containers unless mutation safety truly requires it.
- Avoid debug printing/logging in hot paths in production code.
- Comments are fine, but code structure should not sacrifice speed for aesthetics.

When editing this script:
- Assume Player.run() is a hard real-time-like budget.
- Every added loop, allocation, conversion, lookup, and API call must be justified.
- Prefer changes that reduce worst-case runtime, object churn, and repeated work.
- If a faster version is uglier but safe and maintainable enough, prefer the faster version.
"""

import random
import time
from abc import ABC, abstractmethod
from typing import NamedTuple
import array
import heapq
from collections import deque

from cambc import (
    Controller,
    EntityType,
    Team,
    Direction,
    Position,
    Environment,
)


def idx_to_pos(idx: int, width: int) -> Position:
    return Position(idx % width, idx // width)


def pos_to_idx(pos: Position, width: int) -> int:
    return pos.y * width + pos.x


class Player:
    def __init__(self):
        self.agent: Agent = Agent()

    def run(self, ct: Controller) -> None:
        if type(self.agent) is Agent:
            t = ct.get_entity_type()
            if t is EntityType.CORE:
                self.agent = CoreAgent(ct)
            elif t is EntityType.BUILDER_BOT:
                self.agent = BuilderAgent(ct)
            elif t in [EntityType.SENTINEL, EntityType.GUNNER, EntityType.BREACH]:
                self.agent = TurretAgent(ct)

        self.agent.run()


class Agent:
    def run(self):
        pass


# Todo: remove Resources inefficient too many object creations
class Resources(NamedTuple):
    ti: int
    ax: int

    def change_to(self, new: 'Resources') -> 'Resources':
        return Resources(
            ti=self.ti - new.ti,
            ax=self.ax - new.ax
        )

    def is_neg(self) -> bool:
        return self.ti <= 0 and self.ax <= 0


class DefaultAgent(ABC, Agent):
    ct: Controller
    id: int
    team: Team
    birth: int
    round: int
    width: int
    height: int
    size: int
    position: int
    neighbors_manhattan: list[list[int]]
    neighbors_chebyshev: list[list[int]]
    neighbors_bridge: list[list[int]]
    core_pos: int
    core_tiles: list[int]
    turn_last_completed: bool | None
    res_prev: Resources
    res: Resources
    res_change: Resources
    res_last_dec: int
    def __init__(self, ct: Controller):
        self.ct = ct
        self.id = ct.get_id()
        self.team = ct.get_team()
        self.birth = ct.get_current_round()
        self.round = ct.get_current_round()
        self.width = ct.get_map_width()
        self.height = ct.get_map_height()
        self.size = self.width * self.height
        self.position = pos_to_idx(ct.get_position(), self.width)

        self.neighbors_manhattan = [[] for _ in range(self.size)]
        self.neighbors_chebyshev = [[] for _ in range(self.size)]
        self.neighbors_bridge = [[] for _ in range(self.size)]

        _manhattan_offsets = (
            (-1, 0), (1, 0), (0, -1), (0, 1),
        )

        _chebyshev_offsets = (
            (-1, -1), (0, -1), (1, -1),
            (-1,  0),          (1,  0),
            (-1,  1), (0,  1), (1,  1),
        )

        # row widths by dy are 3, 5, 7, 7, 7, 5, 3
        _bridge_offsets = tuple(
            (dx, dy)
            for dy, max_dx in (
                (-3, 1),
                (-2, 2),
                (-1, 3),
                ( 0, 3),
                ( 1, 3),
                ( 2, 2),
                ( 3, 1),
            )
            for dx in range(-max_dx, max_dx + 1)
            if dx != 0 or dy != 0
        )

        _w = self.width
        _h = self.height

        for y in range(_h):
            row = y * _w
            for x in range(_w):
                idx = row + x

                man = self.neighbors_manhattan[idx]
                cheb = self.neighbors_chebyshev[idx]
                bridge = self.neighbors_bridge[idx]

                for dx, dy in _manhattan_offsets:
                    nx = x + dx
                    ny = y + dy
                    if 0 <= nx < _w and 0 <= ny < _h:
                        man.append(ny * _w + nx)

                for dx, dy in _chebyshev_offsets:
                    nx = x + dx
                    ny = y + dy
                    if 0 <= nx < _w and 0 <= ny < _h:
                        cheb.append(ny * _w + nx)

                for dx, dy in _bridge_offsets:
                    nx = x + dx
                    ny = y + dy
                    if 0 <= nx < _w and 0 <= ny < _h:
                        bridge.append(ny * _w + nx)

        _core = ct.get_nearby_buildings(1)
        _core = ct.get_position(_core[0])
        self.core_pos = pos_to_idx(_core, self.width)
        # 3x3 core footprint
        self.core_tiles = [self.core_pos] + self.neighbors_chebyshev[self.core_pos]
        self.turn_last_completed = None

        _r = ct.get_global_resources() # Todo: replace through attributes for each resource no object churn
        self.res_prev = Resources(_r[0], _r[1])
        self.res = Resources(0, 0)
        self.res_change = Resources(0, 0)
        self.res_last_dec = 0

    def run(self) -> None:
        self.turn_last_completed = False
        time_start = time.perf_counter_ns()
        # --------------------------------------------------------

        _r = self.ct.get_global_resources()
        self.res = Resources(_r[0], _r[1])
        self.res_change = self.res_prev.change_to(self.res)
        if self.res_change.is_neg():
            self.res_last_dec = self.round

        # --------------------------------------------------------
        self.make_turn()
        # --------------------------------------------------------

        self.res_prev = self.res
        self.round += 1

        # --------------------------------------------------------
        time_end = time.perf_counter_ns()
        time_delta = time_end - time_start
        print(f'run() took: {time_delta / 1_000_000:.4f} ms')
        self.turn_last_completed = True

    @abstractmethod
    def make_turn(self) -> None:
        pass


# Todo: rename to WALK_PASS, etc
WALK_PASS: float = 10
WALK_EMPTY: float = 11
WALK_UNKNOWN: float = 12
WALK_BLOCK: float = 10_000_000

_CHEBYSHEV_DICT: dict[tuple[int, int], Direction] = {
    (0, -1): Direction.NORTH,
    (0, 1): Direction.SOUTH,
    (1, 0): Direction.EAST,
    (-1, 0): Direction.WEST,
    (1, -1): Direction.NORTHEAST,
    (-1, -1): Direction.NORTHWEST,
    (1, 1): Direction.SOUTHEAST,
    (-1, 1): Direction.SOUTHWEST,
}


class DStarLite:
    """D* Lite algorithm for incremental path planning with dynamic obstacles."""
    agent: 'BuilderAgent'
    width: int
    height: int
    size: int
    neighbors: list[list[int]]
    g: list[float]  # or list[int] if TILE_BLOCK is int
    rhs: list[float]
    U: list[tuple[float, float, int]]
    km: float
    s_start_idx: int
    s_goal_idx: int
    s_last_idx: int
    in_queue: list[tuple[float, float] | None]
    changed_cells: set[int]

    def __init__(self, agent: 'BuilderAgent'):
        time_init_start = time.perf_counter_ns()

        self.agent = agent
        self.width = agent.width
        self.height = agent.height
        self.size = agent.size

        self.neighbors = agent.neighbors_chebyshev

        self.reset()

        time_init_end = time.perf_counter_ns()

        print(f'd star lite __init__() took: {(time_init_end - time_init_start) / 1_000_000:.4f} ms')

    def reset(self) -> None:
        # D* Lite state using lists for performance
        self.g = [WALK_BLOCK] * self.size
        self.rhs = [WALK_BLOCK] * self.size
        self.U = []  # Flattened: (k1, k2, idx)
        self.km = 0.0

        self.s_start_idx = -1
        self.s_goal_idx = -1
        self.s_last_idx = -1

        # in_queue tracks the key (k1, k2) for each idx (lazy deletion)
        self.in_queue = [None] * self.size

        # Track which cells have changed since last replan
        self.changed_cells = set()

    def target_position(self) -> int:
        return self.s_goal_idx

    def _heuristic(self, s1_idx: int, s2_idx: int) -> float:
        """Chebyshev distance heuristic for 8-directional movement with uniform cost."""
        x1, y1 = s1_idx % self.width, s1_idx // self.width
        x2, y2 = s2_idx % self.width, s2_idx // self.width
        return float(max(abs(x1 - x2), abs(y1 - y2)))

    def _calculate_key(self, s_idx: int) -> tuple[float, float]:
        g_val = self.g[s_idx]
        rhs_val = self.rhs[s_idx]
        min_val = min(g_val, rhs_val)

        # Inlined heuristic for speed
        # s_idx % self.width, s_idx // self.width
        # self.s_start_idx % self.width, self.s_start_idx // self.width
        h = float(max(abs((s_idx % self.width) - (self.s_start_idx % self.width)),
                      abs((s_idx // self.width) - (self.s_start_idx // self.width))))

        return min_val + h + self.km, min_val

    def _calculate_rhs(self, u_idx: int) -> float:
        """Calculate one-step lookahead value for vertex u."""
        if u_idx == self.s_goal_idx:
            return 0.0

        min_rhs = WALK_BLOCK
        map_walk = self.agent.map_walk
        g = self.g
        for s_prime_idx in self.neighbors[u_idx]:
            cost = map_walk[s_prime_idx]
            if cost < WALK_BLOCK:
                candidate = cost + g[s_prime_idx]
                if candidate < min_rhs:
                    min_rhs = candidate
        return min_rhs

    def _push_vertex(self, u_idx: int, key: tuple[float, float]) -> None:
        """Push u into the heap with the given key and record it in in_queue."""
        if self.in_queue[u_idx] == key:
            return
        self.in_queue[u_idx] = key
        heapq.heappush(self.U, (key[0], key[1], u_idx))

    def _update_vertex(self, u_idx: int) -> None:
        """Update a vertex's rhs value and its position in the priority queue."""
        if u_idx != self.s_goal_idx:
            self.rhs[u_idx] = self._calculate_rhs(u_idx)

        g_val = self.g[u_idx]
        rhs_val = self.rhs[u_idx]

        if g_val != rhs_val:
            self._push_vertex(u_idx, self._calculate_key(u_idx))
        else:
            self.in_queue[u_idx] = None

    def _compute_shortest_path(self) -> None:
        """Compute or update the shortest path (canonical D* Lite inner loop)."""
        max_iterations = self.size * 4

        # Cache hot attributes as locals
        g = self.g
        rhs = self.rhs
        in_queue = self.in_queue
        U = self.U
        width = self.width
        s_start_idx = self.s_start_idx
        km = self.km
        neighbors = self.neighbors

        for _ in range(max_iterations):
            if not U:
                break

            # Inlined _calculate_key(self.s_start_idx)
            g_start = g[s_start_idx]
            rhs_start = rhs[s_start_idx]
            min_start = min(g_start, rhs_start)
            # h is 0 for start to start
            start_key = (min_start + km, min_start)

            # Peek at flattened heap entry
            top_k1, top_k2, _ = U[0]
            top_key = (top_k1, top_k2)
            if top_key >= start_key and rhs_start == g_start:
                break

            # Pop flattened entry
            k1_old, k2_old, u_idx = heapq.heappop(U)
            k_old = (k1_old, k2_old)

            # Inlined _calculate_key(u_idx)
            g_u = g[u_idx]
            rhs_u = rhs[u_idx]
            min_u = min(g_u, rhs_u)
            h_u = float(max(abs((u_idx % width) - (s_start_idx % width)),
                            abs((u_idx // width) - (s_start_idx // width))))
            k_new = (min_u + h_u + km, min_u)

            if k_old < k_new:
                if g[u_idx] != rhs[u_idx]:
                    self._push_vertex(u_idx, k_new)
                continue

            in_queue[u_idx] = None
            g_val = g[u_idx]
            rhs_val = rhs[u_idx]

            if g_val == rhs_val:
                continue

            if g_val > rhs_val:
                g[u_idx] = rhs_val
                for s_idx in neighbors[u_idx]:
                    self._update_vertex(s_idx)
            else:
                g[u_idx] = WALK_BLOCK
                self._update_vertex(u_idx)
                for s_idx in neighbors[u_idx]:
                    self._update_vertex(s_idx)

    def initialize(self, start_idx: int, goal_idx: int) -> None:
        """Initialize D* Lite for a new goal."""
        time_init_start = time.perf_counter_ns()

        self.s_start_idx = start_idx
        self.s_goal_idx = goal_idx
        self.s_last_idx = self.s_start_idx
        self.km = 0.0

        # Fast full reset using list multiplication
        self.g = [WALK_BLOCK] * self.size
        self.rhs = [WALK_BLOCK] * self.size
        self.in_queue = [None] * self.size
        self.U.clear()
        self.changed_cells.clear()

        self.rhs[self.s_goal_idx] = 0.0
        self._push_vertex(self.s_goal_idx, self._calculate_key(self.s_goal_idx))

        self._compute_shortest_path()

        time_init_end = time.perf_counter_ns()

        print(f'd star lite initialize() took: {(time_init_end - time_init_start) / 1_000_000:.4f} ms')

    def update_start(self, new_start_idx: int) -> None:
        """Update when the agent has moved to a new position."""
        start = time.perf_counter_ns()
        if self.s_start_idx == -1 or self.s_goal_idx == -1:
            end = time.perf_counter_ns()
            print(f'd star lite update_start() took: {(end - start) / 1_000_000:.4f} ms')
            return

        # Inlined heuristic
        x1, y1 = self.s_last_idx % self.width, self.s_last_idx // self.width
        x2, y2 = new_start_idx % self.width, new_start_idx // self.width
        self.km += float(max(abs(x1 - x2), abs(y1 - y2)))

        self.s_last_idx = new_start_idx
        self.s_start_idx = new_start_idx
        end = time.perf_counter_ns()
        print(f'd star lite update_start() took: {(end - start) / 1_000_000:.4f} ms')

    def update_cell(self, idx: int) -> None:
        """Mark a cell as changed (obstacle detected/removed)."""
        self.changed_cells.add(idx)

    def replan(self) -> None:
        start = time.perf_counter_ns()
        if self.s_start_idx == -1 or self.s_goal_idx == -1:
            end = time.perf_counter_ns()
            print(f'd star lite replan() took: {(end - start) / 1_000_000:.4f} ms')
            return

        if self.agent.map_walk[self.s_goal_idx] >= WALK_BLOCK:
            self.changed_cells.clear()
            end = time.perf_counter_ns()
            print(f'd star lite replan() took: {(end - start) / 1_000_000:.4f} ms')
            return

        if self.changed_cells:
            # Improved affected-cell expansion
            affected = set(self.changed_cells)
            neighbors = self.neighbors
            for u_idx in self.changed_cells:
                affected.update(neighbors[u_idx])
            self.changed_cells.clear()

            for u_idx in affected:
                self._update_vertex(u_idx)

        self._compute_shortest_path()
        end = time.perf_counter_ns()
        print(f'd star lite replan() took: {(end - start) / 1_000_000:.4f} ms')

    def get_next_direction(self) -> Direction:
        """Return the next direction the robot should move toward the goal."""
        start = time.perf_counter_ns()
        if self.s_start_idx == -1 or self.s_goal_idx == -1:
            end = time.perf_counter_ns()
            print(f'd star lite get_next_direction() took: {(end - start) / 1_000_000:.4f} ms')
            return Direction.CENTRE

        if self.s_start_idx == self.s_goal_idx:
            end = time.perf_counter_ns()
            print(f'd star lite get_next_direction() took: {(end - start) / 1_000_000:.4f} ms')
            return Direction.CENTRE

        if self.rhs[self.s_start_idx] >= WALK_BLOCK or self.agent.map_walk[self.s_goal_idx] >= WALK_BLOCK:
            end = time.perf_counter_ns()
            print(f'd star lite get_next_direction() took: {(end - start) / 1_000_000:.4f} ms')
            return Direction.CENTRE

        best_cost = WALK_BLOCK
        best_dir = Direction.CENTRE

        # Still need current Position to get coordinates for Direction calculation
        # but we can do it more efficiently
        curr_x, curr_y = self.s_start_idx % self.width, self.s_start_idx // self.width

        map_walk = self.agent.map_walk
        g = self.g
        rhs = self.rhs
        width = self.width

        for neighbor_idx in self.neighbors[self.s_start_idx]:
            cost = map_walk[neighbor_idx]
            if cost < WALK_BLOCK:
                neighbor_cost = min(g[neighbor_idx], rhs[neighbor_idx])
                total = cost + neighbor_cost
                if total < best_cost:
                    best_cost = total

                    # Calculate direction from indices
                    nx, ny = neighbor_idx % width, neighbor_idx // width
                    dx, dy = nx - curr_x, ny - curr_y

                    # Use dictionary lookup for direction
                    best_dir = _CHEBYSHEV_DICT.get((dx, dy), Direction.CENTRE)

        end = time.perf_counter_ns()
        print(f'd star lite get_next_direction() took: {(end - start) / 1_000_000:.4f} ms')
        return best_dir

    def has_path(self) -> bool:
        """Check if a valid path exists to the goal."""
        start = time.perf_counter_ns()
        if self.s_start_idx == -1:
            end = time.perf_counter_ns()
            print(f'd star lite has_path() took: {(end - start) / 1_000_000:.4f} ms')
            return False
        ret = self.rhs[self.s_start_idx] < WALK_BLOCK
        end = time.perf_counter_ns()
        print(f'd star lite has_path() took: {(end - start) / 1_000_000:.4f} ms')
        return ret


TRANS_SOURCE: float = 0.0
TRANS_PASS: float = 1.0
TRANS_EMPTY: float = 3.0
TRANS_BRIDGE: float = 20.0
TRANS_UNKNOWN: float = 4.0
TRANS_BLOCK: float = 10_000_000.0

# manhattan direction lookup dictionary for (dx, dy) -> Direction
_MANHATTAN_DICT: dict[tuple[int, int], Direction] = {
    (0, -1): Direction.NORTH,
    (0, 1): Direction.SOUTH,
    (1, 0): Direction.EAST,
    (-1, 0): Direction.WEST,
}


class LPAStar:
    """LPA* algorithm for incremental path planning."""
    agent: 'BuilderAgent'
    width: int
    height: int
    size: int
    g: list[float]
    rhs: list[float]
    U: list[tuple[float, float, int]]
    s_source_idx: int
    in_queue: list[tuple[float, float] | None]
    changed_cells: set[int]

    def __init__(self, agent: 'BuilderAgent'):
        time_init_start = time.perf_counter_ns()

        self.agent = agent
        self.width = agent.width
        self.height = agent.height
        self.size = agent.size

        self.reset()

        time_init_end = time.perf_counter_ns()
        print(f'lpa star __init__() took: {(time_init_end - time_init_start) / 1_000_000:.4f} ms')

    def reset(self) -> None:
        # LPA* state using lists for performance
        self.g = [TRANS_BLOCK] * self.size
        self.rhs = [TRANS_BLOCK] * self.size
        self.U = []  # Priority queue: (k1, k2, idx)

        self.s_source_idx = -1

        # in_queue tracks the key (k1, k2) for each idx (lazy deletion)
        self.in_queue = [None] * self.size

        # Track which cells have changed since last replan
        self.changed_cells = set()

    def set_source(self, source_idx: int) -> None:
        """Set the source (harvester) position. Re-keys the priority queue if it changed."""
        if self.s_source_idx == source_idx:
            return

        self.s_source_idx = source_idx
        if self.s_source_idx == -1 or not self.U:
            return

        # Re-key all vertices in the priority queue because the heuristic changed.
        # We must collect the valid nodes first using the old in_queue for staleness check.
        old_U = self.U
        self.U = []
        nodes = set()
        in_queue = self.in_queue
        for k1, k2, u_idx in old_U:
            if in_queue[u_idx] == (k1, k2):
                nodes.add(u_idx)

        # Then clear in_queue before re-pushing with new keys.
        self.in_queue = [None] * self.size
        for u_idx in nodes:
            self._push_vertex(u_idx, self._calculate_key(u_idx))

    def _heuristic(self, s_idx: int) -> float:
        """Manhattan distance heuristic to s_source_idx."""
        if self.s_source_idx == -1:
            return 0.0
        x1, y1 = s_idx % self.width, s_idx // self.width
        x2, y2 = self.s_source_idx % self.width, self.s_source_idx // self.width
        return float(abs(x1 - x2) + abs(y1 - y2)) * TRANS_PASS # Scaled to match TRANS_PASS

    def _calculate_key(self, s_idx: int) -> tuple[float, float]:
        g_val = self.g[s_idx]
        rhs_val = self.rhs[s_idx]
        min_val = min(g_val, rhs_val)

        # Inlined Manhattan heuristic for speed
        gx, gy = self.s_source_idx % self.width, self.s_source_idx // self.width
        h = float(abs((s_idx % self.width) - gx) + abs((s_idx // self.width) - gy)) * TRANS_PASS

        return min_val + h, min_val

    def _calculate_rhs(self, u_idx: int) -> float:
        """Calculate one-step lookahead value for vertex u."""
        # Core-connected tiles are sources with rhs 0
        if self.agent.dict_ti_conn.get(u_idx, False):
            return 0.0

        min_rhs = TRANS_BLOCK
        g = self.g
        
        # Try Manhattan neighbors (Conveyors)
        for v_idx in self.agent.neighbors_manhattan[u_idx]:
            cost = self._get_edge_cost(u_idx, v_idx)
            if cost < TRANS_BLOCK:
                candidate = cost + g[v_idx]
                if candidate < min_rhs:
                    min_rhs = candidate
        
        # Try Bridge neighbors
        for v_idx in self.agent.neighbors_bridge[u_idx]:
            cost = self._get_edge_cost(u_idx, v_idx)
            if cost < TRANS_BLOCK:
                candidate = cost + g[v_idx]
                if candidate < min_rhs:
                    min_rhs = candidate
                    
        return min_rhs

    def _get_edge_cost(self, u_idx: int, v_idx: int) -> float:
        """Get the cost of an edge from u to v."""
        if self.agent.map_ti_pointer[u_idx] == v_idx:
            return TRANS_PASS                              # existing structure reused

        u_trans = self.agent.map_ti_trans[u_idx]

        if u_trans == TRANS_SOURCE:                        # harvester
            if v_idx in self.agent.neighbors_manhattan[u_idx]:
                return TRANS_SOURCE                        # 0.0 — free outbound edge
            return TRANS_BLOCK

        elif u_trans == TRANS_EMPTY:
            if v_idx in self.agent.neighbors_manhattan[u_idx]:
                return TRANS_EMPTY
            return TRANS_BRIDGE

        elif u_trans == TRANS_UNKNOWN:
            return TRANS_UNKNOWN

        return TRANS_BLOCK

    def _push_vertex(self, u_idx: int, key: tuple[float, float]) -> None:
        """Push u into the heap with the given key and record it in in_queue."""
        if self.in_queue[u_idx] == key:
            return
        self.in_queue[u_idx] = key
        heapq.heappush(self.U, (key[0], key[1], u_idx))

    def _update_vertex(self, u_idx: int) -> None:
        """Update a vertex's rhs value and its position in the priority queue."""
        # Note: _calculate_rhs correctly guards core-connected tiles with rhs = 0.0.
        self.rhs[u_idx] = self._calculate_rhs(u_idx)

        g_val = self.g[u_idx]
        rhs_val = self.rhs[u_idx]

        if g_val != rhs_val:
            self._push_vertex(u_idx, self._calculate_key(u_idx))
        else:
            self.in_queue[u_idx] = None

    def _compute_shortest_path(self) -> None:
        """Compute or update the shortest path (canonical LPA* inner loop)."""
        max_iterations = self.size * 4
        iterations = 0

        U = self.U
        g = self.g
        rhs = self.rhs
        in_queue = self.in_queue

        while U and iterations < max_iterations:
            top_key = U[0][:2]
            source_key = self._calculate_key(self.s_source_idx)

            if top_key >= source_key and rhs[self.s_source_idx] == g[self.s_source_idx]:
                break

            k1, k2, u_idx = heapq.heappop(U)
            iterations += 1

            if in_queue[u_idx] != (k1, k2):
                continue
            in_queue[u_idx] = None

            if g[u_idx] > rhs[u_idx]:
                g[u_idx] = rhs[u_idx]
                # Predecessors of u_idx are tiles v such that cost(v, u_idx) might have changed.
                # In this grid, any neighbor can potentially point to u_idx.
                for s_idx in self.agent.neighbors_manhattan[u_idx]:
                    self._update_vertex(s_idx)
                for s_idx in self.agent.neighbors_bridge[u_idx]:
                    self._update_vertex(s_idx)
            else:
                g[u_idx] = TRANS_BLOCK
                # When g[u_idx] increases, we must update u_idx itself and all its predecessors.
                self._update_vertex(u_idx)
                for s_idx in self.agent.neighbors_manhattan[u_idx]:
                    self._update_vertex(s_idx)
                for s_idx in self.agent.neighbors_bridge[u_idx]:
                    self._update_vertex(s_idx)

    def initialize(self, source_idx: int) -> None:
        """Initial compute of the shortest path from the goal (core-connected network) to the source (harvester)."""
        self.reset()
        # s_source_idx must be set before _calculate_key is called (via _push_vertex).
        self.s_source_idx = source_idx

        # All core-connected tiles are starts
        for i in self.agent.dict_ti_conn:
            self.rhs[i] = 0.0
            self._push_vertex(i, self._calculate_key(i))
        
        self._compute_shortest_path()

    def update_cell(self, idx: int) -> None:
        """Mark a cell as changed."""
        self.changed_cells.add(idx)

    def replan(self, source_idx: int = -1) -> None:
        """Replan the shortest path based on changed cells and source."""
        if source_idx != -1:
            self.set_source(source_idx)
        
        if not self.changed_cells:
            # If source changed but no cells changed, we might still need to compute
            # if the source is not yet consistent.
            if self.rhs[self.s_source_idx] != self.g[self.s_source_idx]:
                self._compute_shortest_path()
            return

        start_time = time.perf_counter_ns()

        # Update affected vertices
        affected = set()
        for u_idx in self.changed_cells:
            affected.add(u_idx)
            # In LPA*, if cost(u, v) changes, u needs updating.
            # If u enters/leaves dict_ti_conn, u needs updating.
            # If g[v] changes, predecessors of v need updating.
            # Since neighbors are symmetric, we update neighbors.
            affected.update(self.agent.neighbors_manhattan[u_idx])
            affected.update(self.agent.neighbors_bridge[u_idx])
        self.changed_cells.clear()

        for u_idx in affected:
            self._update_vertex(u_idx)

        self._compute_shortest_path()

        end_time = time.perf_counter_ns()
        print(f'lpa star replan() took: {(end_time - start_time) / 1_000_000:.4f} ms')

    def get_next_direction(self, from_idx: int) -> Direction:
        """Follow the gradient back to the core-connected network."""
        g = self.g
        rhs = self.rhs
        if min(g[from_idx], rhs[from_idx]) >= TRANS_BLOCK:
            return Direction.CENTRE

        best_val = TRANS_BLOCK
        best_dir = Direction.CENTRE
        curr_pos = idx_to_pos(from_idx, self.width)

        # Manhattan steps
        for nb in self.agent.neighbors_manhattan[from_idx]:
            cost = self._get_edge_cost(from_idx, nb)
            if cost >= TRANS_BLOCK:
                continue
            val = cost + min(g[nb], rhs[nb])
            if val < best_val:
                best_val = val
                nx, ny = nb % self.width, nb // self.width
                dx, dy = nx - curr_pos.x, ny - curr_pos.y
                best_dir = _MANHATTAN_DICT.get((dx, dy), Direction.CENTRE)
        
        # Bridge steps
        for nb in self.agent.neighbors_bridge[from_idx]:
            cost = self._get_edge_cost(from_idx, nb)
            if cost >= TRANS_BLOCK:
                continue
            val = cost + min(g[nb], rhs[nb])
            if val < best_val:
                best_val = val
                best_dir = Direction.CENTRE # Placeholder for bridge

        return best_dir

    def has_path(self) -> bool:
        """Check if a valid path exists to the source."""
        if self.s_source_idx == -1:
            return False
        return min(self.g[self.s_source_idx], self.rhs[self.s_source_idx]) < TRANS_BLOCK


class Action(ABC):
    agent: 'BuilderAgent'

    def set_builder_agent(self, agent: 'BuilderAgent'):
        self.agent = agent

    @abstractmethod
    def do(self) -> bool:
        pass


class Explore(Action):
    goal: int = -1
    since: int = -1

    def do(self) -> bool:
        agent = self.agent

        if (
                self.goal == -1 or
                20 < agent.round - self.since or
                agent.position == self.goal or
                agent.map_walk[self.goal] == WALK_BLOCK
        ):
            # Todo: maybe frame the new position to be in medium range from the current position
            # such that it can be reached realistically
            self.goal = random.randrange(agent.size)  # 0 <= n < size, because we start at 0, uniform random
            self.since = agent.round

        agent.move(self.goal)
        return True


class EnemyCore(Action):
    done: bool = False

    def do(self) -> bool:
        agent = self.agent

        if agent.core_enemy_pos == -1 or self.done:
            return False

        if agent.position in agent.core_tiles:
            print('brought information home')
            self.done = True
            return False

        agent.move(agent.core_tiles[0])
        agent.write_marker() # write enemy core position
        # if marker place before movement d star moves on top because not yet updated doesn't know about the marker
        # solution would be update the map_walk and dstar.update_cell inside write_marker on successful placement
        return True


class BuildHarvester(Action):
    def do(self) -> bool:
        return False


class RepairHarvester(Action):
    def do(self) -> bool:
        return False



ORE_NOTHING = 0
ORE_TI = 1
ORE_AX = 2

BB_NORMAL = 0

HIERARCHIES: dict[int, tuple] = {
    BB_NORMAL: (RepairHarvester(), BuildHarvester(), EnemyCore(), Explore()),
}

_start: int = 0


def mask_offset(width: int) -> tuple[int, int]:
    global _start
    out = (1 << width) - 1, _start
    _start += width
    return out


M_ENEMY_CORE_SET = mask_offset(1)
M_ENEMY_CORE_POS = mask_offset(12)
M_DUMMY1 = mask_offset(7)
M_DUMMY2 = mask_offset(6)
M_DUMMY3 = mask_offset(6)

del _start
del mask_offset


class BuilderAgent(DefaultAgent):
    bb_type: int
    todo_hierarchy: tuple
    todo_list: deque
    core_enemy_pos: int
    core_enemy_tiles: list[int]
    map_walk: array.array
    map_ore: array.array
    map_ti_trans: array.array
    map_ti_pointer: array.array
    dict_ti_reverse_pointer: dict[int, set[int]]
    dict_ti_conn: dict[int, bool]
    ti_finished: set[int]
    ti_pending: set[int]
    ax_finished: set[int]
    ax_pending: set[int]
    dstar: DStarLite
    lpastar: LPAStar
    def __init__(self, ct: Controller):
        super().__init__(ct)
        self.bb_type = BB_NORMAL  # Todo: here should go spawn-position-based type derivation
        self.todo_hierarchy = HIERARCHIES[self.bb_type]
        for action in self.todo_hierarchy:
            action.set_builder_agent(self)
        self.todo_list = deque([self.todo_hierarchy[-1]], maxlen=len(self.todo_hierarchy))

        self.core_enemy_pos = -1
        self.core_enemy_tiles = []

        self.map_walk = array.array('d', [WALK_UNKNOWN] * self.size)
        self.map_ore = array.array('i', [ORE_NOTHING] * self.size)
        self.map_ti_trans = array.array('d', [TRANS_UNKNOWN] * self.size)
        self.map_ti_pointer = array.array('i', [-1] * self.size)
        self.dict_ti_reverse_pointer = {}
        self.dict_ti_conn = {}

        self.ti_finished = set()
        self.ti_pending = set()
        self.ax_finished = set()
        self.ax_pending = set()

        self.dstar = DStarLite(self)
        self.lpastar = LPAStar(self)

    def make_turn(self):
        ct = self.ct
        self.position = pos_to_idx(ct.get_position(), self.width)

        start = time.perf_counter_ns()

        self.update_on_view()

        if self.lpastar.s_source_idx == -1:
            self.lpastar.initialize(self.position)
        else:
            self.lpastar.replan(self.position)

        end = time.perf_counter_ns()

        print(f'update_on_view() took: {(end - start) / 1_000_000:.4f} ms')

        self.handle_todos()

        # Todo: try to use your leftover actions in a meaningful way

        # Todo: place marker with information

        # Todo: do any precomputation until turn 2ms reached

    def handle_todos(self):
        todo = self.todo_list[0] if self.todo_list else None
        if todo is not None:
            idx = self.todo_hierarchy.index(todo)
            self.todo_list.extendleft(
                self.todo_hierarchy[idx - 1::-1]
            )  # 2k, all C — optimal
        else:
            self.todo_list.extendleft(
                reversed(self.todo_hierarchy)
            )  # n, all C — optimal

        while self.todo_list:
            todo = self.todo_list[0]  # peek at front without removing
            print(f'TODO: {todo}')
            repeat = todo.do()
            print(f'REPEAT: {repeat}')
            if repeat:
                break
            else:
                self.todo_list.popleft()  # now safe to remove

    def move(self, target_idx: int):
        ct = self.ct
        position = self.position
        print(f'move from {idx_to_pos(position, self.width)} to {idx_to_pos(target_idx, self.width)}')

        if self.map_walk[target_idx] == WALK_BLOCK:
            self.map_walk[target_idx] = WALK_UNKNOWN
            self.dstar.update_cell(target_idx)

        direction = self.greedy_best_first_search(target_idx)

        if direction is None or direction == Direction.CENTRE:
            print('d star lite is used')
            if target_idx != self.dstar.target_position():
                self.dstar.initialize(position, target_idx)
            else:
                self.dstar.update_start(position)
                self.dstar.replan()

            direction = self.dstar.get_next_direction()  # Todo: first try greedy best first search for in vision targets
        else:
            print('greedy bfs is used')

        if direction != Direction.CENTRE:
            pos = idx_to_pos(position, self.width)
            next_pos = pos.add(direction)
            if ct.can_build_road(next_pos):
                ct.build_road(next_pos)
            if ct.can_move(direction):
                ct.move(direction)

    def greedy_best_first_search(self, target_idx: int) -> 'Direction | None':
        """GBFS from self.position to target_idx. Returns first-step Direction or None."""
        timer_start = time.perf_counter_ns()

        start = self.position
        if start == target_idx:

            timer_end = time.perf_counter_ns()
            print(f'greedy_bfs() took: {(timer_end - timer_start) / 1_000_000:.4f} ms')
            return Direction.CENTRE

        map_walk  = self.map_walk       # array.array – agent attribute confirmed
        neighbors = self.neighbors_chebyshev      # list[list[int]] – precomputed by DefaultAgent.__init__
        width     = self.width

        tx = target_idx % width
        ty = target_idx // width

        # --- Seed the heap with direct walkable neighbors of start ---
        # Store first_step_idx so path reconstruction is O(1) at goal.
        heap: list[tuple[int, int, int]] = []   # (h, first_step_nb, current_idx)
        visited: set[int] = {start}

        for nb in neighbors[start]:
            if map_walk[nb] < WALK_BLOCK:
                visited.add(nb)
                nx = nb % width
                ny = nb // width
                h  = max(abs(nx - tx), abs(ny - ty))   # Chebyshev, no float needed
                heap.append((h, nb, nb))

        heapq.heapify(heap)

        while heap:
            _, first_nb, idx = heapq.heappop(heap)

            if idx == target_idx:
                # Recover direction from start → first_nb
                sx  = start   % width
                sy  = start   // width
                fnx = first_nb % width
                fny = first_nb // width

                timer_end = time.perf_counter_ns()
                print(f'greedy_bfs() took: {(timer_end - timer_start) / 1_000_000:.4f} ms')
                return _CHEBYSHEV_DICT.get((fnx - sx, fny - sy), Direction.CENTRE)

            for nb in neighbors[idx]:
                if nb not in visited and map_walk[nb] < WALK_BLOCK:
                    visited.add(nb)
                    nx = nb % width
                    ny = nb // width
                    h  = max(abs(nx - tx), abs(ny - ty))
                    heapq.heappush(heap, (h, first_nb, nb))

        timer_end = time.perf_counter_ns()
        print(f'greedy_bfs() took: {(timer_end - timer_start) / 1_000_000:.4f} ms')
        return None  # no walkable path found within explored area

    def write_marker(self) -> None:
        ct = self.ct

        neighbors = self.neighbors_chebyshev[self.position]
        pos = None
        for idx in neighbors:
            neighbor = idx_to_pos(idx, self.width)
            if ct.can_place_marker(neighbor):
                pos = neighbor
                break

        if pos is None:
            print('no marker position found')
            return

        enemy_core_pos = self.core_enemy_pos
        enemy_core_set = enemy_core_pos != -1

        dummy1 = 1
        dummy2 = 2
        dummy3 = 3

        marker_value = (
            (
                (int(enemy_core_set) & M_ENEMY_CORE_SET[0])
                << M_ENEMY_CORE_SET[1]
            ) | (
                (enemy_core_pos & M_ENEMY_CORE_POS[0])
                << M_ENEMY_CORE_POS[1]
            ) | (
                (dummy1 & M_DUMMY1[0])
                << M_DUMMY1[1]
            ) | (
                (dummy2 & M_DUMMY2[0])
                << M_DUMMY2[1]
            ) | (
                (dummy3 & M_DUMMY3[0])
                << M_DUMMY3[1]
            )
        )

        ct.place_marker(pos, marker_value)
        print(f'wrote marker {idx_to_pos(enemy_core_pos, self.width)}')

    def read_marker(self, marker_id: int) -> None:
        marker_value = self.ct.get_marker_value(marker_id)

        print('reading marker')

        if self.core_enemy_pos == -1 and bool(
                (marker_value >> M_ENEMY_CORE_SET[1]) & M_ENEMY_CORE_SET[0]
        ):
            self.core_enemy_pos = (marker_value >> M_ENEMY_CORE_POS[1]) & M_ENEMY_CORE_POS[0]
            self.core_enemy_tiles = [self.core_enemy_pos] + self.neighbors_chebyshev[self.core_enemy_pos]
            print(f'updated enemy core: {idx_to_pos(self.core_enemy_pos, self.width)}')

        # self.dummy1 = (packed >> MARKER_DUMMY1[1]) & MARKER_DUMMY1[0]
        # self.dummy2 = (packed >> MARKER_DUMMY2[1]) & MARKER_DUMMY2[0]
        # self.dummy3 = (packed >> MARKER_DUMMY3[1]) & MARKER_DUMMY3[0]

    def update_on_view(self):
        ct = self.ct
        width = self.width
        neighbors = self.neighbors_chebyshev
        our_team = self.team
        map_walk = self.map_walk
        dstar_update = self.dstar.update_cell
        map_ore = self.map_ore
        map_ti_trans = self.map_ti_trans
        map_ti_pointer = self.map_ti_pointer
        rev_pointer = self.dict_ti_reverse_pointer
        lpa_update = self.lpastar.update_cell
        ti_finished = self.ti_finished
        ti_pending = self.ti_pending
        ax_finished = self.ax_finished
        ax_pending = self.ax_pending

        for entity_id in ct.get_nearby_entities(): # do little in this loop, else it gets slow
            entity_type = ct.get_entity_type(entity_id)
            entity_team = ct.get_team(entity_id)
            if entity_type is EntityType.MARKER and entity_team == our_team:
                self.read_marker(entity_id)

        enemy_core_pos = self.core_enemy_pos

        # Todo: reset map_walk tiles where a bb was on last turn to walk again

        for pos in ct.get_nearby_tiles(): # do much more in this loop because it has fewer iterations
            idx = pos.y * width + pos.x

            passable = ct.is_tile_passable(pos)
            bb = ct.get_tile_builder_bot_id(pos)
            empty = ct.is_tile_empty(pos)
            env = ct.get_tile_env(pos)
            building_id = ct.get_tile_building_id(pos)
            building_team = ct.get_team(building_id) if building_id else None
            building_type = ct.get_entity_type(building_id) if building_id else None

            # movement related:
            if passable:
                walk = WALK_PASS
            elif bb is not None:
                walk = WALK_BLOCK
            elif empty:
                walk = WALK_EMPTY
            elif env is Environment.WALL:
                walk = WALK_BLOCK
            elif building_id is not None:
                walk = WALK_BLOCK
            else:
                walk = WALK_UNKNOWN

            if walk != map_walk[idx]:
                dstar_update(idx)
                map_walk[idx] = walk

            # transport related (pointers):
            old_target = map_ti_pointer[idx]
            new_target = -1
            if building_team == our_team:
                if building_type == EntityType.CONVEYOR:
                    direction = ct.get_direction(building_id)
                    new_target = pos_to_idx(pos.add(direction), width)
                elif building_type == EntityType.BRIDGE:
                    target_pos = ct.get_bridge_target(building_id)
                    new_target = pos_to_idx(target_pos, width)
            
            pointer_changed = False
            if old_target != new_target:
                if old_target != -1:
                    if old_target in rev_pointer:
                        rev_pointer[old_target].discard(idx)
                        if not rev_pointer[old_target]:
                            del rev_pointer[old_target]
                if new_target != -1:
                    if new_target not in rev_pointer:
                        rev_pointer[new_target] = set()
                    rev_pointer[new_target].add(idx)
                map_ti_pointer[idx] = new_target
                pointer_changed = True

            # node-based trans costs:
            if empty:
                trans = TRANS_EMPTY
            elif building_type in (EntityType.CONVEYOR, EntityType.BRIDGE) and building_team == our_team:
                trans = TRANS_PASS
            elif building_type == EntityType.CORE and building_team == our_team:
                trans = TRANS_PASS
            elif building_type == EntityType.HARVESTER and building_team == our_team:
                trans = TRANS_SOURCE
            else:
                trans = TRANS_BLOCK

            if pointer_changed or trans != map_ti_trans[idx]:
                lpa_update(idx)
                map_ti_trans[idx] = trans

            # environment related:
            if (
                    idx not in ti_finished and
                    idx not in ti_pending and
                    idx not in ax_finished and
                    idx not in ax_pending
            ):
                # Todo: add opponent and harvester connection check
                if env is Environment.ORE_TITANIUM:
                    map_ore[idx] = ORE_TI
                    ti_pending.add(idx)
                elif env is Environment.ORE_AXIONITE:
                    map_ore[idx] = ORE_AX
                    ax_pending.add(idx)

            # enemy core related:
            if (
                    enemy_core_pos == -1 and
                    building_team is not our_team and
                    building_type == EntityType.CORE
            ):
                # we query the buildings pos because the core is at idx but its center position can be different.
                self.core_enemy_pos = pos_to_idx(ct.get_position(building_id), width)
                self.core_enemy_tiles = [self.core_enemy_pos] + neighbors[self.core_enemy_pos]

        # Recalculate core-connectivity (BFS)
        old_conn = self.dict_ti_conn
        self.dict_ti_conn = {}
        core_seeds = self.core_tiles
        queue = deque()
        for s_idx in core_seeds:
            if s_idx not in self.dict_ti_conn:
                self.dict_ti_conn[s_idx] = True
                lpa_update(s_idx) # Ensure core tiles are updated if they were not before
                queue.append(s_idx)
        
        while queue:
            u = queue.popleft()
            if u in rev_pointer:
                for v in rev_pointer[u]:
                    if v not in self.dict_ti_conn:
                        self.dict_ti_conn[v] = True
                        lpa_update(v)
                        queue.append(v)
        
        # Check for tiles that lost connectivity
        for i in old_conn:
            if i not in self.dict_ti_conn:
                lpa_update(i)


BB_COUNT_MAX = 3


class CoreAgent(DefaultAgent):
    def __init__(self, ct: Controller):
        super().__init__(ct)
        self.spawn_bb_count: int = 0

    def make_turn(self) -> None:
        if self.spawn_bb_count < BB_COUNT_MAX:
            self.spawn_bb()

    def spawn_bb(self) -> bool:
        ct = self.ct
        pos = idx_to_pos(self.position, self.width)

        if ct.can_spawn(pos):
            ct.spawn_builder(pos)
            self.spawn_bb_count += 1
            return True

        return False

    def convert_refined_ax(self, amount: int) -> bool:
        if 0 <= amount <= self.res.ax:
            self.ct.convert(amount)
            return True

        return False


class TurretAgent(DefaultAgent):
    def __init__(self, ct: Controller):
        super().__init__(ct)

    def make_turn(self):
        pass
