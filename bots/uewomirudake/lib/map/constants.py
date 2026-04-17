from cambc import Direction, EntityType
from lib.agent.constants import SCAVENGER_STRATEGY_ID, HARASSMENT_STRATEGY_ID, DEFENDER_STRATEGY_ID
from lib.map.types import SymmetryMode

INF_DIST = 10**9
CORE_DIST_INF = 0xFFFF
OPPOSITE_ORE_SUPPLY_CHAIN_SEPARATION_INCLUDES_DIAGONALS = True
ENABLE_MAP_DETECTION = False


DIRECTIONS = tuple(
    direction for direction in Direction if direction != Direction.CENTRE
)

CARDINAL_DIRECTIONS = tuple(
    direction
    for direction in DIRECTIONS
    if sum(abs(delta) for delta in direction.delta()) == 1
)
CARDINAL_ORDINAL_DIRECTIONS = DIRECTIONS

BUILDER_ACTION_OFFSETS = tuple(
    (dx, dy) for dx in range(-1, 2) for dy in range(-1, 2) if dx * dx + dy * dy <= 2
)

SENTINEL_COVER_OFFSETS = tuple((dx, dy) for dx in range(-1, 2) for dy in range(-1, 2))


RESOURCE_TARGET_TYPES = {
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.HARVESTER,
}

WEAPON_TARGET_TYPES = {
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.LAUNCHER,
}

PASSABLE_TYPES = {
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

OWN_CORE_DISTANCE_INIT_SETTLE_BUDGET = 128
DISABLE_CORRECT_OWN_CORE_DISTANCE = False

### MARKER INFORMATION ###
MARKER_STRATEGIES_LIST = [SCAVENGER_STRATEGY_ID, HARASSMENT_STRATEGY_ID, DEFENDER_STRATEGY_ID]
MARKER_SYMMETRY_LIST = [SymmetryMode.ROTATION, SymmetryMode.MIRROR_X, SymmetryMode.MIRROR_Y, None]

MAGIC_PATH_LAUNCHER_TARGET_INDEX = 0
