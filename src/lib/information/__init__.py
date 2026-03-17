# Let's create a new information-class, combining previous ideas of id_map and map_matrx
from cambc import *
from src.lib.information.map_matrix import create_matrix_entry, DEFAULT_ENTRY
from src.lib.information.map_matrix.field import Field
from src.lib.information.id_map.unit import Unit



class Information:
    max_seen_id: int = -1
    buffer: int = 100
    id_map: dict[int, Unit] = {}
    map_matrix: list = []


    def __init__(self, ct: Controller):

        width = ct.get_map_width()
        height = ct.get_map_height()

        # initialize map matrix
        self.map_matrix = [[DEFAULT_ENTRY] * height for h in range(width)]

    def exists(self, unit_id: int, ct: Controller):
        try:
            ct.get_position(unit_id)
        except GameError:
            return False
        else:
            return True

    def remove_Id(self, unit_id : int, ct: Controller):
        if unit_id not in self.id_map:
            return

        position = self.id_map[unit_id].position
        self.map_matrix[position.x][position.y] = DEFAULT_ENTRY
        self.id_map.pop(unit_id)



    def update_unit(self, unit_id: int, ct: Controller):

        if not self.exists(unit_id, ct):
            self.remove_Id(unit_id, ct)
            return

        if unit_id <= self.max_seen_id:
            self.id_map[unit_id].updateUnit(ct)
        else:
            self.max_seen_id = unit_id
            self.id_map[unit_id] = Unit(unit_id, ct)
            position = self.id_map[unit_id].position
            self.map_matrix[position.x][position.y] = create_matrix_entry(unit_id, ct)


    def update_all(self, ct: Controller):

        # creating list to avoid "dictionary changed size during iteration"
        for unit_id in list(self.id_map.keys()):
            self.update_unit(unit_id, ct)

        for unit_id in range(self.max_seen_id + 1, self.max_seen_id + self.buffer):
            self.update_unit(unit_id, ct)