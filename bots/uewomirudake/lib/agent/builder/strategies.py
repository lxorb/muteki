from cambc import Environment

from lib.agent.constants import (
    DEFENDER_STRATEGY_ID,
    FOUNDRY_STRATEGY_ID,
    HARASSMENT_STRATEGY_ID,
    INITRES_STRATEGY_ID,
    SCAVENGER_STRATEGY_ID,
)
from .strategy_methods import BuilderStrategyMethodsMixin
from .types import StrategyEntry

INITRES_STRATEGY = [
    (BuilderStrategyMethodsMixin.s_heal_self,),
    (BuilderStrategyMethodsMixin.s_convert_to_defender,),
    (
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        True,
        Environment.ORE_TITANIUM,
    ),
    (
        BuilderStrategyMethodsMixin.s_surround_harvester,
        True,
        True,
        Environment.ORE_TITANIUM,
    ),
    (BuilderStrategyMethodsMixin.s_build_missing_supply_link, True, True, True),
    (
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        True,
        Environment.ORE_TITANIUM,
    ),
    (BuilderStrategyMethodsMixin.s_frontier_expand,),
]

SCAVENGER_STRATEGY = [
    (BuilderStrategyMethodsMixin.s_heal_self,),
    (BuilderStrategyMethodsMixin.s_destroy_hijacked_supplier, True),
    (BuilderStrategyMethodsMixin.s_protect_own_harvester, True, True),
    (BuilderStrategyMethodsMixin.s_heal_own_building,),
    (BuilderStrategyMethodsMixin.s_fix_harvester, True, True),
    (BuilderStrategyMethodsMixin.s_build_missing_supply_link, True, True, True),
    (
        BuilderStrategyMethodsMixin.s_sentinel_next_to_enemy_harvester,
        True,
        False,
        False,
    ),
    (BuilderStrategyMethodsMixin.s_convert_to_defender,),
        (
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        True,
        Environment.ORE_TITANIUM,
        True,
        False
    ),
    (BuilderStrategyMethodsMixin.s_frontier_expand,),
]

HARASSMENT_STRATEGY = [
    (BuilderStrategyMethodsMixin.s_heal_self,),
    (BuilderStrategyMethodsMixin.s_sentinel_next_to_enemy_harvester, True, True, True),
    (BuilderStrategyMethodsMixin.s_build_enemy_supplied_sentinel, True, True),
    (BuilderStrategyMethodsMixin.s_attack_key_enemy_supply_chain, True),
    (BuilderStrategyMethodsMixin.s_attack_enemy_harvester_supply_link, True),
    (BuilderStrategyMethodsMixin.s_block_enemy_supply_chain, True, True),
    # (BuilderStrategyMethodsMixin.s_block_titanium, True),
    (BuilderStrategyMethodsMixin.s_attack_enemy_core_supply_link, True),
    (BuilderStrategyMethodsMixin.s_move_toward_enemy_core,),
    (BuilderStrategyMethodsMixin.s_patrol_enemy_core,),
    (BuilderStrategyMethodsMixin.s_frontier_expand,),
]

# TODO
FOUNDRY_STRATEGY = [
    (BuilderStrategyMethodsMixin.s_heal_self,),
    (BuilderStrategyMethodsMixin.s_convert_to_defender,),
    (BuilderStrategyMethodsMixin.s_insert_core_splitter, True, True),
    (BuilderStrategyMethodsMixin.s_build_core_foundry, True, True),
    (
        BuilderStrategyMethodsMixin.s_build_harvester_supply_link,
        True,
        True,
        Environment.ORE_AXIONITE,
    ),
    (
        BuilderStrategyMethodsMixin.s_surround_harvester,
        True,
        True,
        Environment.ORE_AXIONITE,
    ),
    (
        BuilderStrategyMethodsMixin.s_build_missing_supply_link,
        True,
        True,
        True,
        Environment.ORE_AXIONITE,
    ),
    (
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        True,
        Environment.ORE_AXIONITE,
    ),
    (BuilderStrategyMethodsMixin.s_frontier_expand,),
]

DEFENDER_STRATEGY = [
    (BuilderStrategyMethodsMixin.s_heal_self,),
    (BuilderStrategyMethodsMixin.s_destroy_hijacked_supplier, True),
    (BuilderStrategyMethodsMixin.s_protect_own_harvester, True, True),
    (BuilderStrategyMethodsMixin.s_heal_own_building,),
    (BuilderStrategyMethodsMixin.s_fix_harvester, True, True),
    (BuilderStrategyMethodsMixin.s_build_missing_supply_link, True, True, True),
    (
        BuilderStrategyMethodsMixin.s_sentinel_next_to_enemy_harvester,
        True,
        False,
        False,
    ),
    (
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        False,
        Environment.ORE_TITANIUM,
        False,
        True
    ),
    (BuilderStrategyMethodsMixin.s_patrol_supply_chains,)
]

### STRATEGIES REGISTRY ###
STRATEGIES: dict[str, list[StrategyEntry]] = {
    INITRES_STRATEGY_ID: INITRES_STRATEGY,
    SCAVENGER_STRATEGY_ID: SCAVENGER_STRATEGY,
    HARASSMENT_STRATEGY_ID: HARASSMENT_STRATEGY,
    FOUNDRY_STRATEGY_ID: FOUNDRY_STRATEGY,
    DEFENDER_STRATEGY_ID: DEFENDER_STRATEGY,
}

### CORE LOGIC ###
BUILDER_STRATEGY_BY_TILE: dict[tuple[int, int], str] = {
    (-1, -1): SCAVENGER_STRATEGY_ID,
    (0, -1): FOUNDRY_STRATEGY_ID,
    (1, -1): HARASSMENT_STRATEGY_ID,
    (-1, 0): INITRES_STRATEGY_ID,
    (0, 0): HARASSMENT_STRATEGY_ID,
    (1, 0): HARASSMENT_STRATEGY_ID,
    (-1, 1): HARASSMENT_STRATEGY_ID,
    (0, 1): HARASSMENT_STRATEGY_ID,
    (1, 1): SCAVENGER_STRATEGY_ID,
}
INITIAL_BB_ORDER: list[str] = [
    HARASSMENT_STRATEGY_ID,
    HARASSMENT_STRATEGY_ID,
    SCAVENGER_STRATEGY_ID,
    SCAVENGER_STRATEGY_ID,
    SCAVENGER_STRATEGY_ID,
    # SCAVENGER_STRATEGY_ID,
    # FOUNDRY_STRATEGY_ID,
]
FURTHER_BB_ROTATION: list[str] = [
    # FOUNDRY_STRATEGY_ID,
    SCAVENGER_STRATEGY_ID,
]
FURTHER_BB_MIN_TITANIUM: int = 200
FURTHER_BB_TITANIUM_INCREASE_PER_SPAWN: int = 70
MAX_BOTS: int = 999
DISABLE_HARASSMENT: bool = False
START_FOUNDRY_TURN: int = 150
