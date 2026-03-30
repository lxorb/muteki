from lib.agent import Agent
from constants import (
    BBType,
    BB_TYPE_CORE_TILE,

)

from cambc import Controller, Direction

from lib.agent.constants import INITIAL_BB_ORDER


class CoreAgent(Agent):
    def __init__(self, ct: Controller):
        super().__init__(ct)
        # spawn count per tile
        self.spawn_tile_counts: dict[Direction, int] = dict.fromkeys(Direction, 0)

        # builder bot spawn count by type
        self.spawn_type_counts: dict[BBType, int] = dict.fromkeys(BBType, 0)

        # bb spawn count - doesn't respect killed bb
        self.spawn_bb_count: int = 0

        # order in which builder bots should be spawned
        self.builder_bot_order: list[BBType] = INITIAL_BB_ORDER

        # position in spawning order
        self.spawning_order_pos: int = 0


    def make_turn(self) -> None:

        if self.spawning_order_pos < len(self.builder_bot_order):
            bot = self.builder_bot_order[self.spawning_order_pos]

            successful = self.spawn_bb(bot)

            if successful:
                self.spawning_order_pos += 1

        self.convert_refined_ax(self.map.axionite)

    def convert_refined_ax(self, amount: int) -> bool:
        if amount <= self.map.axionite:
            try:
                self.ct.convert(amount)
            finally:
                return True

        return False


    def spawn_bb(self, t: BBType) -> bool:
        dirs = BB_TYPE_CORE_TILE(t)

        tile = dirs[0]

        for d in dirs:
            if (self.spawn_tile_counts.get(d) or int('inf')) < (self.spawn_tile_counts.get(tile) or int('inf')):
                tile = d

        pos = self.map.current_pos.add(tile)

        if self.ct.can_spawn(pos):
            try:
                self.ct.spawn_builder(pos)
            finally:
                self.spawn_bb_count += 1
                self.spawn_tile_counts[tile] += 1
                self.spawn_type_counts[t] += 1
                return True

        return False
