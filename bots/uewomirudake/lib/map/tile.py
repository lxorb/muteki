from cambc import (
    Controller,
    Direction,
    EntityType,
    Environment,
    Position,
    Team,
)

class Tile:
    def __init__(self):
        self.position: Position = Position(-1, -1)
        self.environment: Environment = Environment.EMPTY
        self.own_core_dist: int = 10**9
        self.enemy_core_dist: int = 10**9
        self.building_id: int | None = None
        self.building_type: EntityType | None = None
        self.building_team: Team | None = None
        self.builder_bot_id: int | None = None
        self.builder_bot_team: Team | None = None
        self.is_passable: bool = False
        # -> can a builder bot walk on this tile?
        self.last_seen_turn: int = -1
        self.in_enemy_launcher_pickup_zone: bool = False
        # -> can an enemy launcher pickup bots on this tile?
        self.in_action_radius: bool = False
        self.in_vision_radius: bool = False
        self.last_titanium_onit_turn: int = -1
        # -> the turn where there was titanium on this tile for the last time
        self.is_core_tile: bool = False
        self.resource_target: Position | None = None
        # -> target tile, i.e. which tile bridge or conveyor is pointing at
        self.in_enemy_attack_range: bool = False
        # -> this just considers enemy turrets that can attack, not enemy launchers
        self.is_in_enemy_bot_actiono_range: bool = False

        self.known_missing_supply_links: list[Position] = []
        # this keeps a list of missing supply link tiles
        # i.e. if there is an own conveyor or an own bridge that points onto a tile 
        # that is not a core tile and also not an own supply link tile then, the target field should be in this list
        # this list should be kept lazily

    def u_get_resource_targets(self, ct: Controller) -> list[Position]:
        pass
        # returns which tiles are the targets
        # e.g. where bridge or conveyor points at
        # or where supplier or harvester outputs
        # or where foundry outputs

    
