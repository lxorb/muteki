from enum import StrEnum

class Field(StrEnum):
    __slots__ = ()
    BUILDABLE = "buildable"
    NON_BUILDABLE = "non_buildable"
    CONVEYOR = "conveyor"
    HARVESTER = "harvester"