from enum import StrEnum, auto

from cambc import Direction

# Builder Bot Constants
BUILDER_ACTION_RADIUS_SQ: int = 2

class BBType(StrEnum):
    HARASSMENT = auto()
    SCAVENGER = auto()
    DEFENDER = auto()
    INIT_RES = auto()
    FOUNDRY = auto()

INITIAL_BB_ORDER: list[BBType] = [
    BBType.INIT_RES,
    BBType.INIT_RES,
    BBType.HARASSMENT,
    BBType.DEFENDER,
    BBType.SCAVENGER,
]

# Core Constants
MAX_BOTS: int = 10
MAX_RESOURCE_HISTORY = 100

FOUNDRY_TURN: int = 1600
MIN_FOUNDRY_TITANIUM: int = 1000
AXIONITE_FARMING_BOTS_TO_SPAWN = 2
HARASSMENT_SPAWN_BASE_TITANIUM_THRESHOLD = 1600
HARASSMENT_SPAWN_TITANIUM_STEP = 100
HARASSMENT_ATTACK_MIN_TITANIUM_THRESHOLD = 20
DISABLE_HARASSMENT = False


mapping: dict[Direction, BBType] = {
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

def CORE_TILE_BB_TYPE(d: Direction) -> BBType:
    t = mapping.get(d)

    if t is None:
        raise Exception('CORE TILE MAPPING ERROR')

    return t


remapping: dict[BBType, list[Direction]] = {}

for dir, t in mapping.items():
    temp = remapping.get(t) or []
    temp.append(dir)
    remapping[t] = temp


def BB_TYPE_CORE_TILE(t: BBType) -> list[Direction]:
    d = remapping.get(t)

    if d is None:
        raise Exception('CORE TILE MAPPING ERROR')

    return d


del mapping, remapping