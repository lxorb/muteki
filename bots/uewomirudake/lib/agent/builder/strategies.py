from cambc import Environment

from lib.agent.constants import (
    CORE_DEFENDER_STRATEGY_ID,
    DEFENDER_STRATEGY_ID,
    HARASSMENT_STRATEGY_ID,
    SCAVENGER_STRATEGY_ID,
)
from .strategy_methods import BuilderStrategyMethodsMixin
from .types import StrategyEntry

SCAVENGER_STRATEGY = [
    (BuilderStrategyMethodsMixin.s_turn_to_harassment,),
    (BuilderStrategyMethodsMixin.s_heal_self,),
    (BuilderStrategyMethodsMixin.s_destroy_hijacked_supplier, True),
    (BuilderStrategyMethodsMixin.s_protect_own_harvester, True, True),
    (BuilderStrategyMethodsMixin.s_replace_damaged_conveyor, True, True),
    (BuilderStrategyMethodsMixin.s_split_supply_sentinel,),
    (BuilderStrategyMethodsMixin.s_integrate_own_sentinel, True, True),
    # (BuilderStrategyMethodsMixin.s_defend_attacked_harvester, True, True),
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
    (BuilderStrategyMethodsMixin.s_swap_with_splitter, True, True),
    (BuilderStrategyMethodsMixin.s_integrate_foundry_passing_splitter, True, True),
    (BuilderStrategyMethodsMixin.s_integrate_foundry, True, True),
    (
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        True,
        Environment.ORE_AXIONITE,
        True,
        False,
    ),
    (
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        True,
        Environment.ORE_TITANIUM,
        True,
        False,
    ),
    (BuilderStrategyMethodsMixin.s_frontier_expand, 100),
    (BuilderStrategyMethodsMixin.s_patrol_supply_chains,),
]

DEFENDER_STRATEGY = [
    (BuilderStrategyMethodsMixin.s_heal_self,),
    (BuilderStrategyMethodsMixin.s_destroy_hijacked_supplier, True),
    (BuilderStrategyMethodsMixin.s_protect_own_harvester, True, True),
    (BuilderStrategyMethodsMixin.s_replace_damaged_conveyor, True, True),
    (BuilderStrategyMethodsMixin.s_split_supply_sentinel,),
    (BuilderStrategyMethodsMixin.s_integrate_own_sentinel, True, True),
    # (BuilderStrategyMethodsMixin.s_defend_attacked_harvester, True, False),
    (BuilderStrategyMethodsMixin.s_heal_own_building,),
    (BuilderStrategyMethodsMixin.s_fix_harvester, True, True),
    (BuilderStrategyMethodsMixin.s_build_missing_supply_link, True, True, True),
    (
        BuilderStrategyMethodsMixin.s_sentinel_next_to_enemy_harvester,
        True,
        False,
        False,
    ),
    (BuilderStrategyMethodsMixin.s_swap_with_splitter, True, True),
    (BuilderStrategyMethodsMixin.s_integrate_foundry_passing_splitter, True, True),
    (BuilderStrategyMethodsMixin.s_integrate_foundry, True, True),
    (
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        True,
        Environment.ORE_AXIONITE,
        True,
        False,
    ),
    (
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        False,
        Environment.ORE_TITANIUM,
        False,
        True,
    ),
    (BuilderStrategyMethodsMixin.s_patrol_supply_chains,),
]

CORE_DEFENDER_STRATEGY = [
    (BuilderStrategyMethodsMixin.s_heal_self,),
    (BuilderStrategyMethodsMixin.s_destroy_hijacked_supplier, True),
    (BuilderStrategyMethodsMixin.s_protect_own_harvester, True, True),
    (BuilderStrategyMethodsMixin.s_replace_damaged_conveyor, True, True),
    (BuilderStrategyMethodsMixin.s_heal_own_building,),
    (BuilderStrategyMethodsMixin.s_return_to_core_center,),
]

HARASSMENT_STRATEGY = [
    (BuilderStrategyMethodsMixin.s_heal_self,),
    (BuilderStrategyMethodsMixin.s_gunner_next_to_enemy_core),
    (
        BuilderStrategyMethodsMixin.s_sentinel_next_to_enemy_harvester,
        True,
        False,
        False,
    ),
    (BuilderStrategyMethodsMixin.s_hijack_enemy_supply_chain, True, True),
    (BuilderStrategyMethodsMixin.s_build_enemy_supplied_turret, True, False),
    (BuilderStrategyMethodsMixin.s_heal_own_building, True, True, 3),
    (BuilderStrategyMethodsMixin.s_attack_enemy_core_supply_link, True),
    (BuilderStrategyMethodsMixin.s_attack_key_enemy_supply_chain, True),
    (BuilderStrategyMethodsMixin.s_attack_enemy_harvester_supply_link, True),
    (BuilderStrategyMethodsMixin.s_block_enemy_supply_chain, True, True),
    (BuilderStrategyMethodsMixin.s_move_toward_enemy_core),
    (BuilderStrategyMethodsMixin.s_patrol_enemy_core,),
    (BuilderStrategyMethodsMixin.s_frontier_expand,),
]

### STRATEGIES REGISTRY ###
STRATEGIES: dict[str, list[StrategyEntry]] = {
    SCAVENGER_STRATEGY_ID: SCAVENGER_STRATEGY,
    HARASSMENT_STRATEGY_ID: HARASSMENT_STRATEGY,
    DEFENDER_STRATEGY_ID: DEFENDER_STRATEGY,
    CORE_DEFENDER_STRATEGY_ID: CORE_DEFENDER_STRATEGY,
}

### CORE LOGIC ###
BUILDER_STRATEGY_BY_TILE: dict[tuple[int, int], str] = {
    (-1, -1): SCAVENGER_STRATEGY_ID,
    (0, -1): SCAVENGER_STRATEGY_ID,
    (1, -1): HARASSMENT_STRATEGY_ID,
    (-1, 0): SCAVENGER_STRATEGY_ID,
    (0, 0): CORE_DEFENDER_STRATEGY_ID,
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
    # FIRST RESOURCE INCREASE
    SCAVENGER_STRATEGY_ID,
]
FUTHER_BB_ROTATION: list[str] = [
    HARASSMENT_STRATEGY_ID,
    HARASSMENT_STRATEGY_ID,
    HARASSMENT_STRATEGY_ID,
    SCAVENGER_STRATEGY_ID,
    HARASSMENT_STRATEGY_ID,
]
FURTHER_BB_MIN_TURN: int = 50
FURTHER_BB_MIN_TITANIUM: int = 200
FURTHER_BB_TITANIUM_INCREASE_PER_SPAWN: int = 70
