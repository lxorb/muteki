from cambc import EntityType

### GAME CONSTANTS ###
BUILDER_ACTION_RADIUS_SQ: int = 2
NS_PER_TURN: int = 2_000_000

### STRATEGY NAMES ###
INITRES_STRATEGY_ID: str = "initres"
SCAVENGER_STRATEGY_ID: str = "scavenger"
HARASSMENT_STRATEGY_ID: str = "harassment"
FOUNDRY_STRATEGY_ID: str = "foundry"
DEFENDER_STRATEGY_ID: str = "defender"

### BOT LOGIC ###
BRIDGE_PREFERRED_DIST: int = 6
# TODO: Temporary fix for bots becoming unable to place supply chains.
AVOID_EMPTY_ORE_BRIDGE_TARGETS: bool = False
AVOID_OTHER_SUPPLY_LABEL_ORES: bool = False
HARVESTERS_BUILT_BEFORE_CONVERT_TO_DEFENDER: int = 1
MAX_CORE_ORE_DIRECT_DIST: int = 20
PREVENT_SUPPLY_LINKS_TILL_HARVESTER: bool = True
SURROUND_HARVESTER_ENTITY_TYPE: EntityType = EntityType.ROAD

# Builder tuning constants.
# `BUILD_FOUNDRY_BEFORE_AXIONITE_SUPPLY_CHAIN` toggles when
# `s_build_core_foundry()` is allowed to commit to the planned foundry site.
# Building the foundry first guarantees it can still be afforded before
# titanium costs scale too high, but may force a suboptimal placement.
# Building the supply chain first allows for optimal foundry placement, but
# increases the risk that the foundry later becomes too expensive to build.
FOUNDRY_WAIT_RADIUS_SQ: int = 8
MAX_TEMP_FOUNDRY_BARRIER_TITANIUM_COST: int = 0  # TODO: Unused
BUILD_FOUNDRY_BEFORE_AXIONITE_SUPPLY_CHAIN: bool = True

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
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.BARRIER,
    EntityType.SPLITTER,
    EntityType.FOUNDRY,
    EntityType.ROAD,
    EntityType.ARMOURED_CONVEYOR,
)
TURRET_TARGET_PRIORITY_RANK = {
    target_type: idx for idx, target_type in enumerate(TURRET_TARGET_PRIORITY)
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
    target_type: idx for idx, target_type in enumerate(LAUNCHER_THROWABLE_PRIORITY)
}


"""
The following code automatically prevents
surrendering early in submissions.
"""

import sys
from pathlib import Path

SURRENDER_AT_TURN: int = 1e6

try:
    exclude_module_dir: str | None = None
    for parent in Path(__file__).resolve().parents:
        candidate_dir = parent / "bots" / "exclude"
        if (candidate_dir / "exclude.py").exists():
            exclude_module_dir = str(candidate_dir)
            break

    if exclude_module_dir is not None:
        sys.path.insert(0, exclude_module_dir)

        import exclude

        SURRENDER_AT_TURN = exclude.SURRENDER_AT_TURN
except Exception:
    pass
