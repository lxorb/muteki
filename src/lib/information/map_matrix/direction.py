from enum import Enum

class Directions(Enum):
    __slots__ = ()
    NONE = "none"
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"
    ALL = "all"