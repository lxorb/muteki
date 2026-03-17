from enum import StrEnum

class DirectionInfo(StrEnum):
    __slots__ = ()
    NONE = "none"
    NORTH = "north"
    EAST = "east"
    SOUTH = "south"
    WEST = "west"
    ALL = "all"