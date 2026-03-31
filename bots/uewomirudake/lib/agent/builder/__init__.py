from cambc import Controller
import time

from lib.agent import Agent
from lib.agent.constants import BUILDER_STRATEGY_BY_TILE
from lib.map import Map

from .execution import BuilderExecutionMixin
from .navigation import BuilderNavigationMixin
from .strategies import (
    DEFENDER_STRATEGY,
    FOUNDRY_STRATEGY,
    HARASSMENT_STRATEGY,
    INITRES_STRATEGY,
    SCAVENGER_STRATEGY,
)
from .strategy_methods import BuilderStrategyMethodsMixin
from .types import StrategyEntry

from typing import override


class BuilderAgent(
    BuilderStrategyMethodsMixin,
    BuilderExecutionMixin,
    BuilderNavigationMixin,
    Agent,
):
    ct: Controller
    map: Map
    strategy: list[StrategyEntry]
    last_strategy_index: int
    last_turn_completed: bool

    def __init__(self, strategy: list[StrategyEntry] | None):
        Agent.__init__(self)
        self.strategy = list(strategy or [])
        self.last_strategy_index = -1
        self.last_turn_completed = True

    def u_infer_strategy_by_spawning_tile(self):
        current_pos = self.map.current_pos
        core_center_pos = self.map.own_core_center_pos
        relative_tile = (
            current_pos.x - core_center_pos.x,
            current_pos.y - core_center_pos.y,
        )
        self.strategy = list(BUILDER_STRATEGY_BY_TILE.get(relative_tile, []))

    def u_get_strategy_name(self) -> str:
        strategy_by_name = {
            "INITRES_STRATEGY": INITRES_STRATEGY,
            "SCAVENGER_STRATEGY": SCAVENGER_STRATEGY,
            "HARASSMENT_STRATEGY": HARASSMENT_STRATEGY,
            "FOUNDRY_STRATEGY": FOUNDRY_STRATEGY,
            "DEFENDER_STRATEGY": DEFENDER_STRATEGY,
        }
        for strategy_name, strategy_entries in strategy_by_name.items():
            if self.strategy == strategy_entries:
                return strategy_name
        return "CUSTOM_STRATEGY"

    @override
    def u_handler(self):
        if not self.strategy:
            self.u_infer_strategy_by_spawning_tile()
        print(f"Builder strategy: {self.u_get_strategy_name()}")
        t_strategy_handler_start = time.perf_counter_ns()
        handled = self.u_execute_strategy()
        strategy_handler_time_mus = (
            time.perf_counter_ns() - t_strategy_handler_start
        ) // 1_000
        print(f"Builder strategy handler time: {strategy_handler_time_mus} mus")
        return handled
