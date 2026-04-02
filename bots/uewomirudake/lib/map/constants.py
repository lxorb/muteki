from cambc import Direction, EntityType

INF_DIST = 10**9
CORE_DIST_INF = 0xFFFF
CHOKEPOINT_MIN_DIST_INCREASE = 4
DEEP_CHOKEPOINT_CHECKING = False
OPPOSITE_ORE_SUPPLY_CHAIN_SEPARATION_INCLUDES_DIAGONALS = True


DIRECTIONS = tuple(
    direction for direction in Direction if direction != Direction.CENTRE
)

CARDINAL_DIRECTIONS = tuple(
    direction
    for direction in DIRECTIONS
    if sum(abs(delta) for delta in direction.delta()) == 1
)

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
    EntityType.FOUNDRY,
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

TEMPORARY_TITANIUM_SUPPLY_AT_FOUNDRY_FIX = True
