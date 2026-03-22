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
        self.core_bbs_spawned = 0  # number of builder bots spawned so far (core)
        self.ct: Controller | None = None
        self.information: Information | None = None
        self.bb_handler = None
        self.core_center_pos: Position | None = None

    def get_ns_elapsed(self):
        return time.perf_counter_ns() - self.t_start

    def get_ns_remaining(self):
        return 2_000_000 - time.perf_counter_ns() + self.t_start

    def run(self, ct: Controller) -> None:
        self.ct = ct
        self.t_start = time.perf_counter_ns()
        if self.information is None:
            self.information = Information(self.ct)
        self.information.update_all()
        print(f"Took {self.get_ns_elapsed() / 1000}mus for information fetching")

        # print(self.information.map_matrix)
        # print(self.information.id_map)

        etype = self.ct.get_entity_type()
        match etype:
            case EntityType.CORE:
                self.run_core()
            case EntityType.BUILDER_BOT:
                self.run_bb()
            case EntityType.GUNNER:
                self.run_gunner()
            case EntityType.SENTINEL:
                self.run_sentinel()
            case EntityType.BREACH:
                self.run_breach()
            case EntityType.LAUNCHER:
                self.run_launcher()

    def run_core(self):
        # spawn initial bb's
        if self.core_bbs_spawned < len(INITIAL_BB):
            spawn_pos = self.ct.get_position().add(random.choice(DIRECTIONS))
            if self.ct.can_spawn(spawn_pos):
                self.ct.spawn_builder(spawn_pos)
                self.core_bbs_spawned += 1

    def run_bb(self):
        if self.core_center_pos is None:
            self.find_core_center()

        if self.bb_handler is None:
            self.bb_handler = self.get_initial_bb_handler()

        self.bb_handler()

    def find_core_center(self) -> Position | None:
        current_pos = self.ct.get_position()
        building_id = self.ct.get_tile_building_id(current_pos)
        if (
            building_id is not None
            and self.ct.get_entity_type(building_id) == EntityType.CORE
            and self.ct.get_team(building_id) == self.ct.get_team()
        ):
            self.core_center_pos = self.ct.get_position(building_id)
            return self.core_center_pos

        for building_id in self.ct.get_nearby_buildings():
            if (
                self.ct.get_entity_type(building_id) == EntityType.CORE
                and self.ct.get_team(building_id) == self.ct.get_team()
            ):
                self.core_center_pos = self.ct.get_position(building_id)
                return self.core_center_pos

        return None

    def stands_on_core(self) -> bool:
        pos = self.ct.get_position()
        return (
            self.core_center_pos.x - 1 <= pos.x <= self.core_center_pos.x + 1
            and self.core_center_pos.y - 1 <= pos.y <= self.core_center_pos.y + 1
        )

    def get_initial_bb_handler(self):
        round_index = self.ct.get_current_round() - 1
        if 0 <= round_index < len(INITIAL_BB):
            return INITIAL_BB[round_index].__get__(self, type(self))
        return self.run_bb_unassigned

    def is_vertical_lane_tile(self, pos: Position) -> bool:
        xop = (pos.x - self.core_center_pos.x) % 6
        if xop not in [1, 4]:
            return False
        if pos.y == self.core_center_pos.y:
            return False

    # in work
    def get_lane_direction(self, pos: Position) -> Direction | None:
        xop = (pos.x - self.core_center_pos.x) % 6
        if self.stands_on_core():
            return None
        if pos.y == self.cor_center_pos.y:
            return None
        isupper = pos.y > self.cor_center_pos.y
        if self.is_vertical_lane_tile(pos) and isupper and xop == 1:
            return Direction.NORTH
        if self.is_vertical_lane_tile(pos) and isupper and xop == 4:
            return Direction.SOUTH
        if self.is_vertical_lane_tile(pos) and not isupper and xop == 1:
            return Direction.SOUTH
        if self.is_vertical_lane_tile(pos) and not isupper and xop == 4:
            return Direction.NORTH
        return Direction.EAST if isupper else Direction.WEST

    def run_bb_maintainer(self):
        pass

    def run_bb_scavenger(self):
        pass

    def run_bb_harrassment(self):
        pass

    def run_bb_unassigned(self):
        pass

    def run_gunner(self):
        pass

    def run_sentinel(self):
        pass

    def run_breach(self):
        pass

    def run_launcher(self):
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
