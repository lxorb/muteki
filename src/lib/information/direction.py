from enum import StrEnum

class Directions(StrEnum):
    __slots__ = ()
    NONE = "none"
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"
    ALL = "all"