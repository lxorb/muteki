# Let's create a new information-class, combining previous ideas of id_map and map_matrx
from cambc import *
from src.lib.information.map_matrix import create_matrix_entry, DEFAULT_ENTRY, DirectionInfo
from src.lib.information.map_matrix.field import Field
from src.lib.information.id_map.unit import Unit, exists


class Information:
    ct: Controller = None
    max_seen_id: int = -1
    buffer: int = 100
    id_map: dict[int, Unit] = {}
    map_matrix: list[list[tuple[Field, DirectionInfo]]] = []

    def __init__(self, ct: Controller):
        self.ct = ct

        width = ct.get_map_width()
        height = ct.get_map_height()

        # initialize map matrix
        self.map_matrix = [[DEFAULT_ENTRY] * height for h in range(width)]

    def remove_id(self, unit_id: int):
        if unit_id not in self.id_map:
            return

        position = self.id_map[unit_id].position
        self.map_matrix[position.x][position.y] = DEFAULT_ENTRY
        self.id_map.pop(unit_id)

    def update_unit(self, unit_id: int):

        if not exists(unit_id, self.ct):
            self.remove_id(unit_id)
            return

        if unit_id <= self.max_seen_id:
            self.id_map[unit_id].update_unit()
        else:
            self.max_seen_id = unit_id
            self.id_map[unit_id] = Unit(unit_id, self.ct)
            position = self.id_map[unit_id].position
            self.map_matrix[position.x][position.y] = create_matrix_entry(unit_id, self.ct)

    def update_all(self):

        # creating a list to avoid "dictionary changed size during iteration"
        for unit_id in list(self.id_map.keys()):
            self.update_unit(unit_id)

        for unit_id in range(self.max_seen_id + 1, self.max_seen_id + self.buffer):
            self.update_unit(unit_id)
