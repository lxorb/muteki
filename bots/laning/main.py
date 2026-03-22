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
from cambc import Controller, Direction, EntityType
from lib.information import Information


class Bot:
    def __init__(self):
        self.num_spawned = 0  # number of builder bots spawned so far (core)
        self.information: Information | None = None

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
        if self.num_spawned < INITIAL_BB:
            spawn_pos = ct.get_position().add(random.choice(DIRECTIONS))
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                self.num_spawned += 1

    def run_bb(self, ct: Controller):
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
INITIAL_BB = 10
