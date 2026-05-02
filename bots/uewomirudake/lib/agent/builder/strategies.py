from cambc import Environment

from lib.agent.constants import (
    CORE_DEFENDER_STRATEGY_ID,
    DEFENDER_STRATEGY_ID,
    HARASSMENT_STRATEGY_ID,
    SCAVENGER_STRATEGY_ID,
)
from .strategy_methods import BuilderStrategyMethodsMixin
from .types import StrategyEntry

# Each strategy entry is `(skip_on_tle, method, *args)`:
#  - skip_on_tle=True: the executor may skip this step when saver mode is on
#  - skip_on_tle=False: the step is always executed
# Only scavenger and defender strategies currently mark any step
# skip_on_tle=True (s_split_supply_sentinel, s_turret_next_to_enemy_harvester,
# s_swap_with_splitter).
SCAVENGER_STRATEGY = [
    (False, BuilderStrategyMethodsMixin.s_target_follow_enemy_bb),
    (False, BuilderStrategyMethodsMixin.s_delete_pending_tile),
    (False, BuilderStrategyMethodsMixin.s_step_off_core),
    (False, BuilderStrategyMethodsMixin.s_move_out_of_gunner_range),
    (False, BuilderStrategyMethodsMixin.s_turn_to_harassment),
    (False, BuilderStrategyMethodsMixin.s_destroy_hijacked_supplier, True),
    (False, BuilderStrategyMethodsMixin.s_heal_self),
    (False, BuilderStrategyMethodsMixin.s_obliterate_target, True, True),
    (False, BuilderStrategyMethodsMixin.s_protect_own_harvester, True, True),
    (False, BuilderStrategyMethodsMixin.s_build_missing_supply_link, True, True, True),
    (False, BuilderStrategyMethodsMixin.s_replace_damaged_conveyor, True, True),
    # (True, BuilderStrategyMethodsMixin.s_split_supply_sentinel),
    (False, BuilderStrategyMethodsMixin.s_integrate_own_turret, True, True),
    # (False, BuilderStrategyMethodsMixin.s_defend_attacked_harvester, True, True),
    (False, BuilderStrategyMethodsMixin.s_heal_own_building),
    (False, BuilderStrategyMethodsMixin.s_fix_harvester, True, True),
    # (False, BuilderStrategyMethodsMixin.s_simple_harvester_build, True),
    # (False, BuilderStrategyMethodsMixin.s_standing_next_to_you),
    (
        True,
        BuilderStrategyMethodsMixin.s_turret_next_to_enemy_harvester,
        True,
        False,
        False,
    ),
    (False, BuilderStrategyMethodsMixin.s_proceed_follow_enemy_bb),
    # (False, BuilderStrategyMethodsMixin.s_convert_to_defender),
    (True, BuilderStrategyMethodsMixin.s_swap_with_splitter, True, True),
    (
        False,
        BuilderStrategyMethodsMixin.s_convert_initial_scavenger_to_self_patrol_defender,
    ),
    (
        False,
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        True,
        Environment.ORE_AXIONITE,
        True,
        False,
    ),
    (
        False,
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        True,
        Environment.ORE_TITANIUM,
        True,
        False,
    ),
    (False, BuilderStrategyMethodsMixin.s_information_gain_scout, 0),
    (False, BuilderStrategyMethodsMixin.s_frontier_expand, 0),
    (False, BuilderStrategyMethodsMixin.s_move_toward_enemy_core),
    (False, BuilderStrategyMethodsMixin.s_patrol_supply_chains),
]

DEFENDER_STRATEGY = [
    (False, BuilderStrategyMethodsMixin.s_target_follow_enemy_bb),
    (False, BuilderStrategyMethodsMixin.s_delete_pending_tile),
    (False, BuilderStrategyMethodsMixin.s_step_off_core),
    (False, BuilderStrategyMethodsMixin.s_move_out_of_gunner_range),
    (False, BuilderStrategyMethodsMixin.s_heal_self),
    (False, BuilderStrategyMethodsMixin.s_destroy_hijacked_supplier, True),
    (False, BuilderStrategyMethodsMixin.s_obliterate_target, True, True),
    (False, BuilderStrategyMethodsMixin.s_protect_own_harvester, True, True),
    (False, BuilderStrategyMethodsMixin.s_replace_damaged_conveyor, True, True),
    # (True, BuilderStrategyMethodsMixin.s_split_supply_sentinel),
    (False, BuilderStrategyMethodsMixin.s_integrate_own_turret, True, True),
    # (False, BuilderStrategyMethodsMixin.s_defend_attacked_harvester, True, False),
    (False, BuilderStrategyMethodsMixin.s_heal_own_building),
    (False, BuilderStrategyMethodsMixin.s_fix_harvester, True, True),
    (False, BuilderStrategyMethodsMixin.s_simple_harvester_build, True),
    (False, BuilderStrategyMethodsMixin.s_build_missing_supply_link, True, True, True),
    (
        True,
        BuilderStrategyMethodsMixin.s_turret_next_to_enemy_harvester,
        True,
        False,
        False,
    ),
    (True, BuilderStrategyMethodsMixin.s_swap_with_splitter, True, True),
    (False, BuilderStrategyMethodsMixin.s_integrate_foundry_passing_splitter, True, True),
    (False, BuilderStrategyMethodsMixin.s_integrate_foundry, True, True),
    (False, BuilderStrategyMethodsMixin.s_proceed_follow_enemy_bb),
    (False, BuilderStrategyMethodsMixin.s_patrol_supply_chains),
    (
        False,
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        True,
        Environment.ORE_AXIONITE,
        True,
        False,
    ),
    (
        False,
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        False,
        Environment.ORE_TITANIUM,
        False,
        True,
    ),
]

CORE_DEFENDER_STRATEGY = [
    (False, BuilderStrategyMethodsMixin.s_heal_self),
    (False, BuilderStrategyMethodsMixin.s_destroy_hijacked_supplier, True),
    (False, BuilderStrategyMethodsMixin.s_obliterate_target, True, True),
    (False, BuilderStrategyMethodsMixin.s_protect_own_harvester, True, True),
    (False, BuilderStrategyMethodsMixin.s_replace_damaged_conveyor, True, True),
    (False, BuilderStrategyMethodsMixin.s_heal_own_building),
    (False, BuilderStrategyMethodsMixin.s_integrate_foundry_passing_splitter, True, True),
    (False, BuilderStrategyMethodsMixin.s_integrate_foundry, True, True),
    (False, BuilderStrategyMethodsMixin.s_build_missing_supply_link, True, True, True),
    (False, BuilderStrategyMethodsMixin.s_close_patrol_own_core),
]

HARASSMENT_STRATEGY = [
    (False, BuilderStrategyMethodsMixin.s_berserk),
    (False, BuilderStrategyMethodsMixin.s_attack_inn_yeeter),
    (False, BuilderStrategyMethodsMixin.s_step_off_core),
    (False, BuilderStrategyMethodsMixin.s_move_out_of_gunner_range),
    (False, BuilderStrategyMethodsMixin.s_heal_self),
    (False, BuilderStrategyMethodsMixin.s_gunner_next_to_enemy_core),
    (
        False,
        BuilderStrategyMethodsMixin.s_turret_next_to_enemy_harvester,
        True,
        True,
        False,
    ),
    (False, BuilderStrategyMethodsMixin.s_hijack_enemy_supply_chain, True, True),
    (False, BuilderStrategyMethodsMixin.s_build_enemy_supplied_turret, True, False),
    (False, BuilderStrategyMethodsMixin.s_heal_own_building, True, True),
    (False, BuilderStrategyMethodsMixin.s_build_missing_supply_link, True, True, True),
    (False, BuilderStrategyMethodsMixin.s_attack_key_enemy_supply_chain, True, True),
    (False, BuilderStrategyMethodsMixin.s_attack_enemy_harvester_supply_link, True),
    (False, BuilderStrategyMethodsMixin.s_block_enemy_supply_chain, True, True),
    (False, BuilderStrategyMethodsMixin.s_annoy_with_yeeter, True, True),
    (False, BuilderStrategyMethodsMixin.s_patrol_enemy_supply_chains),
    (False, BuilderStrategyMethodsMixin.s_move_toward_enemy_core, True),
    (False, BuilderStrategyMethodsMixin.s_patrol_enemy_core),
    (False, BuilderStrategyMethodsMixin.s_information_gain_scout),
    (False, BuilderStrategyMethodsMixin.s_frontier_expand),
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
    (1, 1): SCAVENGER_STRATEGY_ID,
    (1, -1): SCAVENGER_STRATEGY_ID,
    (-1, 1): SCAVENGER_STRATEGY_ID,
    (0, -1): HARASSMENT_STRATEGY_ID,
    (0, 1): HARASSMENT_STRATEGY_ID,
    (-1, 0): HARASSMENT_STRATEGY_ID,
    (1, 0): HARASSMENT_STRATEGY_ID,
    (0, 0): CORE_DEFENDER_STRATEGY_ID,
}
INITIAL_BB_ORDER: list[str] = [
    HARASSMENT_STRATEGY_ID,
    SCAVENGER_STRATEGY_ID,
    SCAVENGER_STRATEGY_ID,
]

FUTHER_BB_ROTATION: list[str] = [
    SCAVENGER_STRATEGY_ID,
    HARASSMENT_STRATEGY_ID,
]
FURTHER_BB_MIN_TURN: int = 50
FURTHER_BB_MIN_REM_TITANIUM: int = 50
