from cambc import *
from src.lib.information.map_matrix.field import Field
from src.lib.information.map_matrix.direction import DirectionInfo


DEFAULT_ENTRY = (Field.BUILDABLE, DirectionInfo.NONE)

def get_direction(unit_id: int, ct: Controller):
    cambcDirection = ct.get_direction(unit_id)

    match cambcDirection:
        case Direction.NORTH:
            return DirectionInfo.NORTH
        case Direction.EAST:
            return DirectionInfo.EAST
        case Direction.SOUTH:
            return DirectionInfo.SOUTH
        case Direction.WEST:
            return DirectionInfo.WEST
        case _:
            raise ValueError(f"Unexpected (conveyor) direction: {cambcDirection}")

def create_matrix_entry(unit_id: int, ct: Controller):

    entity_type = ct.get_entity_type(unit_id)

    match entity_type:
        case EntityType.CONVEYOR:
            field = Field.CONVEYOR
            direction = get_direction(unit_id, ct)

        case EntityType.HARVESTER:
            field = Field.HARVESTER
            direction = DirectionInfo.ALL

        # case that buildable doesn't need to be covered:
        # This function is only called for UNITS!

        case _:
            field = Field.NON_BUILDABLE
            direction = DirectionInfo.NONE

    return (field, direction)
