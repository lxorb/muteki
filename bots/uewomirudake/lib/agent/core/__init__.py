from cambc import Direction

from lib.agent import Agent
from lib.agent.builder.types import StrategyEntry
from lib.agent.constants import (
    BUILDER_STRATEGY_BY_TILE,
    DISABLE_HARASSMENT,
    HARASSMENT_STRATEGY,
    INITIAL_BB_ORDER,
    MAX_BOTS,
)


class CoreAgent(Agent):
    def __init__(self):
        super().__init__()
        self.spawn_tile_counts: dict[Direction, int] = dict.fromkeys(Direction, 0)
        self.spawn_bb_count = 0
        self.builder_bot_order: list[list[StrategyEntry]] = list(INITIAL_BB_ORDER)
        self.spawning_order_pos = 0

    def u_handler(self):
        self.u_convert_axionite()
        self.u_spawn_initial_bb()

    def u_convert_axionite(self) -> bool:
        self.ct.convert(self.map.axionite)
        return True

    def u_spawn_initial_bb(self) -> bool:
        if self.spawn_bb_count >= MAX_BOTS:
            return False

        while self.spawning_order_pos < len(self.builder_bot_order):
            builder_bot_strategy = self.builder_bot_order[self.spawning_order_pos]
            if DISABLE_HARASSMENT and builder_bot_strategy == HARASSMENT_STRATEGY:
                self.spawning_order_pos += 1
                continue

            if not self.u_spawn_builder(builder_bot_strategy):
                return False

            self.spawning_order_pos += 1
            return True

        return False

    def u_get_builder_spawn_candidates(
        self,
        builder_bot_strategy: list[StrategyEntry],
    ) -> list[tuple[int, int, int, Direction]]:
        core_center_pos = self.map.own_core_center_pos
        if core_center_pos is None:
            return []
        candidate_spawns: list[tuple[int, int, int, Direction]] = []

        for core_tile in self.map.u_get_core_footprint_positions(core_center_pos):
            relative_offset = (
                core_tile.position.x - core_center_pos.x,
                core_tile.position.y - core_center_pos.y,
            )
            if BUILDER_STRATEGY_BY_TILE.get(relative_offset) != builder_bot_strategy:
                continue
            if core_tile.bot.id is not None:
                continue

            spawn_direction = next(
                direction
                for direction in Direction
                if direction.delta() == relative_offset
            )
            if not self.ct.can_spawn(core_tile.position):
                continue

            candidate_spawns.append(
                (
                    self.spawn_tile_counts[spawn_direction],
                    core_tile.position.x,
                    core_tile.position.y,
                    spawn_direction,
                )
            )

        return candidate_spawns

    def u_spawn_builder(self, builder_bot_strategy: list[StrategyEntry]) -> bool:
        if self.spawn_bb_count >= MAX_BOTS:
            return False
        if DISABLE_HARASSMENT and builder_bot_strategy == HARASSMENT_STRATEGY:
            return False

        core_center_pos = self.map.own_core_center_pos
        if core_center_pos is None:
            return False
        candidate_spawns = self.u_get_builder_spawn_candidates(builder_bot_strategy)
        if not candidate_spawns:
            return False

        _, _, _, spawn_direction = min(
            candidate_spawns,
            key=lambda candidate: candidate[:3],
        )
        spawn_pos = core_center_pos.add(spawn_direction)
        self.ct.spawn_builder(spawn_pos)
        self.spawn_bb_count += 1
        self.spawn_tile_counts[spawn_direction] += 1
        return True
