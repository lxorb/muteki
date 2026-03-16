from src.lib.information.id_map.unit import *

class IdMap:
    def __init__(self):
        self.MAX_IDS: int = 300

        # self.max_id: int = 1
        self.id_map: dict[int, Unit] = {}

    def __repr__(self):
        return f"{self.id_map}"

    def __str__(self):
        return self.__repr__()

    def _exists(self, id: int, ct: Controller):
        try:
            ct.get_position(id)
        except GameError:
            return False
        else:
            return True
    
    def _register(self, id: int, ct: Controller):
        self.id_map[id] = Unit(id, ct)
    
    def _check_lifetime(self, ct: Controller):
        self.id_map = {k: v for k, v in self.id_map.items() if self._exists(k, ct)}

    def _find_units(self, ct: Controller):
        for i in range(self.MAX_IDS):
            if self._exists(i, ct) and (i not in self.id_map.keys()):
                self.id_map[i] = Unit(i, ct)
        
        # i = self.max

        # while self._exists(i, ct):
        #     print("checking", i)
        #     self._register(i, ct)
        #     i += 1
        
        # self.max = i

    def _update_units(self, ct: Controller):
        for unit in self.id_map.values():
            unit.update(ct)

    def update(self, ct: Controller):
        self._check_lifetime(ct)
        self._find_units(ct)
        self._update_units(ct)
