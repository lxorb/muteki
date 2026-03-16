from enum import Enum

class Field(Enum):
    __slots__ = ()
    BUILDABLE = "buildable"
    NON_BUILDABLE = "non_buildable"
    CONVEYOR = "conveyor"
    HARVESTER = "harvester"