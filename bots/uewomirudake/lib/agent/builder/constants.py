"""
Builder tuning constants.

`BUILD_FOUNDRY_BEFORE_AXIONITE_SUPPLY_CHAIN` toggles when `s_build_core_foundry()`
is allowed to commit to the planned foundry site.

Building the foundry first guarantees it can still be afforded before titanium
costs scale too high, but may force a suboptimal placement. Building the supply
chain first allows for optimal foundry placement, but increases the risk that
the foundry later becomes too expensive to build.
"""

FOUNDRY_WAIT_RADIUS_SQ: int = 8
MAX_TEMP_FOUNDRY_BARRIER_TITANIUM_COST: int = 0  # TODO: Unused
BUILD_FOUNDRY_BEFORE_AXIONITE_SUPPLY_CHAIN: bool = True
