from cambc import Environment

from .types import StrategyEntry


INITRES_STRATEGY = [
    ("s_build_harvester", True, True, True, Environment.ORE_TITANIUM),
    ("s_surround_harvester", True, True),
    ("s_build_missing_supply_link", True, True, True),
    ("s_build_harvester", True, True, True, Environment.ORE_TITANIUM),
    ("s_frontier_expand",),
]

SCAVENGER_STRATEGY = [
    ("s_destroy_hijacked_supplier", True),
    ("s_build_harvester_supply_link", True, True),
    ("s_surround_harvester", True, True),
    ("s_build_missing_supply_link", True, True, True),
    ("s_sentinel_next_to_enemy_harvester", True, False, False),
    ("s_build_harvester", True, True, True, Environment.ORE_TITANIUM),
    ("s_frontier_expand",),
]

HARASSMENT_STRATEGY = [
    ("s_sentinel_next_to_enemy_harvester", True, True, True),
    ("s_block_enemy_supply_chain", True, True),
    ("s_block_titanium", True),
    ("s_attack_enemy_harvester_supply_link", True),
    ("s_attack_enemy_core_supply_link", True),
]

# TODO
FOUNDRY_STRATEGY = [
    # INSERT SPLITTER
    # BUILD FOUNDRY (next to splitter)
    # BUILD AXIONITE HARVESTER SUPPLY LINK
    ("s_surround_harvester", True, True),
    # BUILD MISSING AXIONITE SUPPLY LINK
    # BUILD AXIONITE HARVESTER
    # SCOUT (search for axionite)
]

# TODO
# SHOULD PATROL SUPPLY CHAINS AND REBUILD
# THINGS DESTROYED BY THE ENEMY
DEFENDER_STRATEGY = []
