import random
from cambc import Controller, Direction, EntityType
from src.lib.information import Information

# non-centre directions
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
INITIAL_BB = 3


class Bot:
    def __init__(self):
        self.num_spawned = 0  # number of builder bots spawned so far (core)
        self.information: Information | None = None

    def run(self, ct: Controller) -> None:
        if self.information is None:
            self.information = Information(ct)
            # initializing beforehand without ct doesn't work / make sense:
            # we need width and height for matrix!

        self.information.update_all()

        print(self.information.map_matrix)
        print(self.information.id_map)

        etype = ct.get_entity_type()
        match etype:
            case EntityType.CORE:
                self.run_core(ct)
            case EntityType.BUILDER_BOT:
                self.run_bb(ct)
            case EntityType.GUNNER:
                self.run_gunner(ct)
            case EntityType.SENTINEL:
                self.run_sentinel(ct)
            case EntityType.BREACH:
                self.run_breach(ct)
            case EntityType.LAUNCHER:
                self.run_launcher(ct)

    def run_core(self, ct: Controller):
        if self.num_spawned < INITIAL_BB:
            # if we haven't spawned 3 builder bots yet, try to spawn one on a random tile
            spawn_pos = ct.get_position().add(random.choice(DIRECTIONS))
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                self.num_spawned += 1

    def run_bb(self, ct: Controller):
        # if we are adjacent to an ore tile, build a harvester on it
        for d in Direction:
            check_pos = ct.get_position().add(d)
            if ct.can_build_harvester(check_pos):
                ct.build_harvester(check_pos)
                break

        # move in a random direction
        move_dir = random.choice(DIRECTIONS)
        move_pos = ct.get_position().add(move_dir)
        # we need to place a conveyor or road to stand on, before we can move onto a tile
        if ct.can_build_road(move_pos):
            ct.build_road(move_pos)
        if ct.can_move(move_dir):
            ct.move(move_dir)

        # place a marker on an adjacent tile with the current round number
        marker_pos = ct.get_position().add(random.choice(DIRECTIONS))
        if ct.can_place_marker(marker_pos):
            ct.place_marker(marker_pos, ct.get_current_round())

    def run_gunner(self, ct: Controller):
        pass

    def run_sentinel(self, ct: Controller):
        pass

    def run_breach(self, ct: Controller):
        pass

    def run_launcher(self, ct: Controller):
        pass
