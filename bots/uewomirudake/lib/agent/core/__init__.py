from cambc import Direction

from lib.agent import Agent
from lib.agent.builder.types import StrategyEntry
from lib.agent.constants import INITIAL_BB_ORDER, STRATEGY_CORE_TILES


class CoreAgent(Agent):
    def __init__(self):
        super().__init__()
        self.spawn_tile_counts: dict[Direction, int] = dict.fromkeys(Direction, 0)
        self.spawn_bb_count = 0
        self.builder_bot_order: list[list[StrategyEntry]] = list(INITIAL_BB_ORDER)
        self.spawning_order_pos = 0

    def u_handler(self):
        if self.spawning_order_pos < len(self.builder_bot_order):
            builder_bot_strategy = self.builder_bot_order[self.spawning_order_pos]
            if self.u_spawn_builder(builder_bot_strategy):
                self.spawning_order_pos += 1

        self.u_convert_refined_axionite(self.map.axionite)

    def u_convert_refined_axionite(self, amount: int) -> bool:
        if amount <= 0 or amount > self.map.axionite:
            return False

        self.ct.convert(amount)
        return True

    def u_spawn_builder(self, builder_bot_strategy: list[StrategyEntry]) -> bool:
        candidate_directions = STRATEGY_CORE_TILES(builder_bot_strategy)
        spawn_direction = min(
            candidate_directions,
            key=lambda direction: self.spawn_tile_counts[direction],
        )
        spawn_pos = self.map.current_pos.add(spawn_direction)

        if not self.ct.can_spawn(spawn_pos):
            return False

        self.ct.spawn_builder(spawn_pos)
        self.spawn_bb_count += 1
        self.spawn_tile_counts[spawn_direction] += 1
        return True
