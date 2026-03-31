from cambc import Controller

from lib.agent import Agent
from lib.agent.constants import BUILDER_STRATEGY_BY_TILE
from lib.map import Map

from .execution import BuilderExecutionMixin
from .navigation import BuilderNavigationMixin
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

    def u_format_strategy_entry(self, strategy_entry: StrategyEntry) -> str:
        if isinstance(strategy_entry, tuple):
            method, *args = strategy_entry
        else:
            method = strategy_entry
            args = []

        method_name = method if isinstance(method, str) else method.__name__
        if not args:
            return method_name
        return f"{method_name}{tuple(args)}"

    @override
    def u_handler(self):
        if not self.strategy:
            self.u_infer_strategy_by_spawning_tile()
        print(
            "Builder strategy: "
            + ", ".join(
                self.u_format_strategy_entry(strategy_entry)
                for strategy_entry in self.strategy
            )
        )
        return self.u_execute_strategy()
