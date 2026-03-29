from enum import StrEnum, auto

from cambc import Direction

BUILDER_ACTION_RADIUS_SQ = 2

class BBType(StrEnum):
    HARASSMENT = auto()
    SCAVENGER = auto()
    DEFENDER = auto()
    INIT_RES = auto()
    FOUNDRY = auto()


INITIAL_BB_STRATEGIES = [
    BBType.INIT_RES,
    BBType.INIT_RES,
    BBType.HARASSMENT,
    BBType.DEFENDER,
    BBType.SCAVENGER,
]

CORE_TILE_BB_STRATEGY = {
    Direction.NORTHWEST: BBType.INIT_RES,
    Direction.NORTH: BBType.HARASSMENT,
    Direction.NORTHEAST: BBType.DEFENDER,
    Direction.WEST: BBType.SCAVENGER,
    Direction.CENTRE: BBType.FOUNDRY,
    Direction.EAST: BBType.HARASSMENT,
    Direction.SOUTHWEST: BBType.SCAVENGER,
    Direction.SOUTH: BBType.SCAVENGER,
    Direction.SOUTHEAST: BBType.INIT_RES,
}