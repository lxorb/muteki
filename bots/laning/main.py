import sys
from pathlib import Path


def add_project_root_to_path() -> None:
    current = Path(__file__).resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / "lib").is_dir():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            return

    raise ModuleNotFoundError(
        "Could not find shared 'lib' package above bot entrypoint"
    )


add_project_root_to_path()

import random
import time
from cambc import Controller, Direction, EntityType, Position
from lib.information import Information


class Bot:
    def __init__(self):
        self.num_spawned = 0  # number of builder bots spawned so far (core)
        self.information: Information | None = None
        self.bb_handler = None
        self.core_center_pos: Position | None = None

    def get_ns_elapsed(self):
        return time.perf_counter_ns() - self.t_start

    def get_ns_remaining(self):
        return 2_000_000 - time.perf_counter_ns() + self.t_start

    def run(self, ct: Controller) -> None:
        self.t_start = time.perf_counter_ns()
        if self.information is None:
            self.information = Information(ct)
        self.information.update_all()
        print(f"Took {self.get_ns_elapsed() / 1000}mus for information fetching")

        # print(self.information.map_matrix)
        # print(self.information.id_map)

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
        # spawn initial bb's
        if self.num_spawned < len(INITIAL_BB):
            spawn_pos = ct.get_position().add(random.choice(DIRECTIONS))
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                self.num_spawned += 1

    def run_bb(self, ct: Controller):
        if self.core_center_pos is None:
            self.find_core_center(ct)

        if self.bb_handler is None:
            self.bb_handler = self.get_initial_bb_handler(ct)

        self.bb_handler(ct)

    def find_core_center(self, ct: Controller) -> Position | None:
        current_pos = ct.get_position()
        building_id = ct.get_tile_building_id(current_pos)
        if (
            building_id is not None
            and ct.get_entity_type(building_id) == EntityType.CORE
            and ct.get_team(building_id) == ct.get_team()
        ):
            self.core_center_pos = ct.get_position(building_id)
            return self.core_center_pos

        for building_id in ct.get_nearby_buildings():
            if (
                ct.get_entity_type(building_id) == EntityType.CORE
                and ct.get_team(building_id) == ct.get_team()
            ):
                self.core_center_pos = ct.get_position(building_id)
                return self.core_center_pos

        return None

    def get_initial_bb_handler(self, ct: Controller):
        round_index = ct.get_current_round() - 1
        if 0 <= round_index < len(INITIAL_BB):
            return INITIAL_BB[round_index].__get__(self, type(self))
        return self.run_bb_unassigned

    def run_bb_maintainer(self, ct: Controller):
        pass

    def run_bb_scavenger(self, ct: Controller):
        pass

    def run_bb_harrassment(self, ct: Controller):
        pass

    def run_bb_unassigned(self, ct: Controller):
        pass

    def run_gunner(self, ct: Controller):
        pass

    def run_sentinel(self, ct: Controller):
        pass

    def run_breach(self, ct: Controller):
        pass

    def run_launcher(self, ct: Controller):
        pass


class Player(Bot):
    pass


### constants ###
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
INITIAL_BB = [
    Bot.run_bb_maintainer,
    Bot.run_bb_maintainer,
    Bot.run_bb_maintainer,
    Bot.run_bb_maintainer,
    Bot.run_bb_maintainer,
    Bot.run_bb_maintainer,
    Bot.run_bb_maintainer,
    Bot.run_bb_maintainer,
    Bot.run_bb_maintainer,
]
