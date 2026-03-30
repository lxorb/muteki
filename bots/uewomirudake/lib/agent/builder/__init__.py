from cambc import Controller

from lib.agent import Agent
from lib.map import Map

from .execution import BuilderExecutionMixin
from .navigation import BuilderNavigationMixin
from .strategy_methods import BuilderStrategyMethodsMixin
from .types import StrategyEntry


class BuilderAgent(
    BuilderStrategyMethodsMixin,
    BuilderExecutionMixin,
    BuilderNavigationMixin,
    Agent,
):
    ct: Controller
    map: Map
    strategy_methods: list[StrategyEntry]
    last_executed_index: int
    last_strategy_index: int
    last_turn_completed: bool
    bb_last_turn_completed: bool

    def __init__(self, strategy_methods: list[StrategyEntry] | None):
        super().__init__()
        self.strategy_methods = list(strategy_methods or [])
        self.last_executed_index = -1
        self.last_strategy_index = -1
        self.last_turn_completed = True
        self.bb_last_turn_completed = True

    def u_infer_strategy_by_spawning_tile(self):
        # there should be a constant declared somewhere that
        # assigns each of the nine core tiles
        # a builder bot strategy that should be executed then
        pass

    def u_handler(self):
        return self.u_execute_strategy()


from .strategies import (
    DEFENDER_STRATEGY,
    FOUNDRY_STRATEGY,
    HARASSMENT_STRATEGY,
    INITRES_STRATEGY,
    SCAVENGER_STRATEGY,
)
