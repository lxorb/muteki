from cambc import Environment

from . import BuilderAgent
from .types import StrategyEntry


INITRES_STRATEGY = [
    (BuilderAgent.s_build_harvester, True, True, True, Environment.ORE_TITANIUM),
    (BuilderAgent.s_surround_harvester, True, True),
    (BuilderAgent.s_build_missing_supply_link, True, True, True),
    (BuilderAgent.s_build_harvester, True, True, True, Environment.ORE_TITANIUM),
    (BuilderAgent.s_expand,),
]

SCAVENGER_STRATEGY = [
    (BuilderAgent.s_destroy_hijacked_supplier, True),
    (BuilderAgent.s_build_harvester_supply_link, True, True),
    (BuilderAgent.s_surround_harvester, True, True),
    (BuilderAgent.s_build_missing_supply_link, True, True, True),
    (BuilderAgent.s_sentinel_next_to_enemy_harvester, True, False, False),
    (BuilderAgent.s_build_harvester, True, True, True, Environment.ORE_TITANIUM),
    (BuilderAgent.s_expand,),
]

HARASSMENT_STRATEGY = [
    (BuilderAgent.s_sentinel_next_to_enemy_harvester, True, True, True),
    (BuilderAgent.s_block_enemy_supply_chain, True, True),
    (BuilderAgent.s_block_titanium, True),
    (BuilderAgent.s_attack_enemy_harvester_supply_link, True),
    (BuilderAgent.s_attack_enemy_core_supply_link, True),
]

# TODO
FOUNDRY_STRATEGY = [
    # INSERT SPLITTER
    # BUILD FOUNDRY (next to splitter)
    # BUILD AXIONITE HARVESTER SUPPLY LINK
    (BuilderAgent.s_surround_harvester, True, True),
    # BUILD MISSING AXIONITE SUPPLY LINK
    # BUILD AXIONITE HARVESTER
    # SCOUT (search for axionite)
]

# TODO
# SHOULD PATROL SUPPLY CHAINS AND REBUILD
# THINGS DESTROYED BY THE ENEMY
DEFENDER_STRATEGY = []

BUILDER_STRATEGY_BY_CORE_RELATIVE_TILE: dict[tuple[int, int], list[StrategyEntry]] = {
    (-1, -1): HARASSMENT_STRATEGY,
    (0, -1): SCAVENGER_STRATEGY,
    (1, -1): HARASSMENT_STRATEGY,
    (-1, 0): SCAVENGER_STRATEGY,
    (0, 0): INITRES_STRATEGY,
    (1, 0): SCAVENGER_STRATEGY,
    (-1, 1): HARASSMENT_STRATEGY,
    (0, 1): SCAVENGER_STRATEGY,
    (1, 1): HARASSMENT_STRATEGY,
}
