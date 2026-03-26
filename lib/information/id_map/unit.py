from cambc import *


class Unit:
    def __init__(self, unit_id: int, ct: Controller):
        self.ct = ct
        self.unit_id: int = unit_id

        self.team: Team = self.ct.get_team(self.unit_id)

        self.max_hp = self.ct.get_max_hp(self.unit_id)
        self.hp = 0

        self.entity_type: EntityType = self.ct.get_entity_type(self.unit_id)

        try:
            self.direction = self.ct.get_direction(self.unit_id)
        except GameError:
            self.direction = None

        try:
            self.vision_radius_sq = self.ct.get_vision_radius_sq(self.unit_id)
        except GameError:
            pass

        self.position = self.ct.get_position(self.unit_id)

        self.update_position = self.entity_type == EntityType.BUILDER_BOT

        if not self.update_position:
            self.position: Position = self.ct.get_position(self.unit_id)

    def __repr__(self):
        return f"{self.__dict__}"

    def __str__(self):
        return self.__repr__()

    def update_unit(self):
        if self.update_position:
            self.position = self.ct.get_position(self.unit_id)

        self.hp = self.ct.get_hp(self.unit_id)


def exists(id: int, ct: Controller):
    try:
        ct.get_position(id)
    except GameError:
        return False
    else:
        return True
