from cambc import Environment

from .strategy_methods import BuilderStrategyMethodsMixin
from .types import StrategyEntry


INITRES_STRATEGY = [
    (
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        True,
        Environment.ORE_TITANIUM,
    ),
    (BuilderStrategyMethodsMixin.s_surround_harvester, True, True),
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
    (BuilderStrategyMethodsMixin.s_destroy_hijacked_supplier, True),
    (BuilderStrategyMethodsMixin.s_build_missing_supply_link, True, True, True),
    (BuilderStrategyMethodsMixin.s_build_harvester_supply_link, True, True),
    (BuilderStrategyMethodsMixin.s_surround_harvester, True, True),
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
        True,
        Environment.ORE_TITANIUM,
    ),
    (BuilderStrategyMethodsMixin.s_frontier_expand,),
]

HARASSMENT_STRATEGY = [
    (BuilderStrategyMethodsMixin.s_sentinel_next_to_enemy_harvester, True, True, True),
    (BuilderStrategyMethodsMixin.s_block_enemy_supply_chain, True, True),
    (BuilderStrategyMethodsMixin.s_block_titanium, True),
    (BuilderStrategyMethodsMixin.s_attack_enemy_harvester_supply_link, True),
    (BuilderStrategyMethodsMixin.s_attack_enemy_core_supply_link, True),
]

# TODO
FOUNDRY_STRATEGY = [
    (BuilderStrategyMethodsMixin.s_build_foundry_next_to_splitter, True, True),
    (BuilderStrategyMethodsMixin.s_insert_core_splitter, True, True),
    (
        BuilderStrategyMethodsMixin.s_build_harvester_supply_link,
        True,
        True,
        Environment.ORE_AXIONITE,
    ),
    # TODO: -> for axionite harvester
    # (BuilderStrategyMethodsMixin.s_surround_harvester, True, True),
    (
        BuilderStrategyMethodsMixin.s_build_missing_supply_link,
        True,
        True,
        True,
        Environment.ORE_AXIONITE,
    ),
    # TODO: -> for axionite supply chain
    (
        BuilderStrategyMethodsMixin.s_build_harvester,
        True,
        True,
        True,
        Environment.ORE_AXIONITE,
    ),
    (BuilderStrategyMethodsMixin.s_frontier_expand,),
]

# TODO
DEFENDER_STRATEGY = [
    (BuilderStrategyMethodsMixin.s_destroy_hijacked_supplier, True),
    (BuilderStrategyMethodsMixin.s_build_missing_supply_link, True, True, True),
    (
        BuilderStrategyMethodsMixin.s_sentinel_next_to_enemy_harvester,
        True,
        False,
        False,
    ),
    (BuilderStrategyMethodsMixin.s_patrol_supply_chains,),
]
