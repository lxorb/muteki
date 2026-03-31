from cambc import EntityType

from lib.agent.builder.strategies import (
    DEFENDER_STRATEGY,
    FOUNDRY_STRATEGY,
    HARASSMENT_STRATEGY,
    INITRES_STRATEGY,
    SCAVENGER_STRATEGY,
)
from lib.agent.builder.types import StrategyEntry

### GAME CONSTANTS ###
BUILDER_ACTION_RADIUS_SQ: int = 2
NS_PER_TURN: int = 2_000_000

### BOT LOGIC ###
BRIDGE_PREFERRED_DIST: int = 6

### ENTITY TYPE GROUPS ###
ATTACK_TURRET_FEEDER_TYPES: set[EntityType] = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.HARVESTER,
}
ENEMY_TURRET_TYPES: set[EntityType] = {
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.LAUNCHER,
}
OWN_SUPPLIER_TYPES: set[EntityType] = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
}
DIRECTIONAL_BUILDING_TYPES: set[EntityType] = {
    EntityType.CONVEYOR,
    EntityType.SPLITTER,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
}
NONDIRECTIONAL_BUILDING_TYPES: set[EntityType] = {
    EntityType.HARVESTER,
    EntityType.ROAD,
    EntityType.BARRIER,
    EntityType.FOUNDRY,
    EntityType.LAUNCHER,
}
ATTACK_TURRET_TYPES: set[EntityType] = {
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
}
TURRET_TARGET_PRIORITY = (
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.BREACH,
    EntityType.LAUNCHER,
    "enemy_bot_on_ally_tile",
    "enemy_bot_on_non_ally_tile",
    EntityType.CORE,
    EntityType.HARVESTER,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.BARRIER,
    EntityType.SPLITTER,
    EntityType.FOUNDRY,
    EntityType.ROAD,
    EntityType.ARMOURED_CONVEYOR,
)
TURRET_TARGET_PRIORITY_RANK = {
    target_type: idx
    for idx, target_type in enumerate(TURRET_TARGET_PRIORITY)
}
LAUNCHER_THROWABLE_PRIORITY = (
    "enemy_bot_on_ally_bridge",
    "enemy_bot_on_ally_conveyor",
    "enemy_bot_on_ally_armoured_conveyor",
    "enemy_bot_on_ally_road",
    "enemy_bot_on_empty_tile",
    "enemy_bot_elsewhere",
)
LAUNCHER_THROWABLE_PRIORITY_RANK = {
    target_type: idx
    for idx, target_type in enumerate(LAUNCHER_THROWABLE_PRIORITY)
}

### CORE LOGIC ###
BUILDER_STRATEGY_BY_TILE: dict[tuple[int, int], list[StrategyEntry]] = {
    (-1, -1): SCAVENGER_STRATEGY,
    (0, -1): HARASSMENT_STRATEGY,
    (1, -1): HARASSMENT_STRATEGY,
    (-1, 0): INITRES_STRATEGY,
    (0, 0): HARASSMENT_STRATEGY,
    (1, 0): HARASSMENT_STRATEGY,
    (-1, 1): HARASSMENT_STRATEGY,
    (0, 1): HARASSMENT_STRATEGY,
    (1, 1): SCAVENGER_STRATEGY,
}
INITIAL_BB_ORDER: list[list[StrategyEntry]] = [
    SCAVENGER_STRATEGY,
    SCAVENGER_STRATEGY,
    # HARASSMENT_STRATEGY,
]
MAX_BOTS: int = 10
DISABLE_HARASSMENT: bool = False
SURRENDER_AT_TURN: int = 100
