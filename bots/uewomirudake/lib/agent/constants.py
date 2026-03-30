from cambc import Direction
from lib.agent.builder.strategies import (
    DEFENDER_STRATEGY,
    FOUNDRY_STRATEGY,
    HARASSMENT_STRATEGY,
    INITRES_STRATEGY,
    SCAVENGER_STRATEGY,
)
from lib.agent.builder.types import StrategyEntry


BUILDER_ACTION_RADIUS_SQ: int = 2
BRIDGE_PREFERRED_DIST: int = 5
CHOKEPOINT_MIN_DIST_INCREASE: int = 4


INITIAL_BB_ORDER: list[list[StrategyEntry]] = [
    INITRES_STRATEGY,
    INITRES_STRATEGY,
    HARASSMENT_STRATEGY,
    DEFENDER_STRATEGY,
    SCAVENGER_STRATEGY,
]


MAX_BOTS: int = 10
MAX_RESOURCE_HISTORY = 100

FOUNDRY_TURN: int = 1600
MIN_FOUNDRY_TITANIUM: int = 1000
AXIONITE_FARMING_BOTS_TO_SPAWN = 2
HARASSMENT_SPAWN_BASE_TITANIUM_THRESHOLD = 1600
HARASSMENT_SPAWN_TITANIUM_STEP = 100
HARASSMENT_ATTACK_MIN_TITANIUM_THRESHOLD = 20
DISABLE_HARASSMENT = False


_CORE_TILE_TO_STRATEGY: dict[Direction, list[StrategyEntry]] = {
    Direction.NORTHWEST: INITRES_STRATEGY,
    Direction.NORTH: HARASSMENT_STRATEGY,
    Direction.NORTHEAST: DEFENDER_STRATEGY,
    Direction.WEST: SCAVENGER_STRATEGY,
    Direction.CENTRE: FOUNDRY_STRATEGY,
    Direction.EAST: HARASSMENT_STRATEGY,
    Direction.SOUTHWEST: SCAVENGER_STRATEGY,
    Direction.SOUTH: SCAVENGER_STRATEGY,
    Direction.SOUTHEAST: INITRES_STRATEGY,
}


def CORE_TILE_STRATEGY(direction: Direction) -> list[StrategyEntry]:
    strategy = _CORE_TILE_TO_STRATEGY.get(direction)
    if strategy is None:
        raise ValueError("CORE TILE MAPPING ERROR")
    return strategy


_STRATEGY_TO_CORE_TILES: list[tuple[list[StrategyEntry], list[Direction]]] = []
for direction, strategy in _CORE_TILE_TO_STRATEGY.items():
    for known_strategy, directions in _STRATEGY_TO_CORE_TILES:
        if known_strategy is strategy:
            directions.append(direction)
            break
    else:
        _STRATEGY_TO_CORE_TILES.append((strategy, [direction]))


def STRATEGY_CORE_TILES(strategy: list[StrategyEntry]) -> list[Direction]:
    for known_strategy, directions in _STRATEGY_TO_CORE_TILES:
        if known_strategy is strategy:
            return directions
    raise ValueError("BUILDER STRATEGY MAPPING ERROR")
