from cambc import Controller, EntityType, Environment

from lib.agent import Agent
from lib.agent.builder.strategies import BUILDER_STRATEGY_BY_TILE
from lib.map import Map

from .execution import BuilderExecutionMixin
from .navigation import BuilderNavigationMixin
from .strategy_methods import BuilderStrategyMethodsMixin

from typing import override


class BuilderAgent(
    BuilderStrategyMethodsMixin,
    BuilderExecutionMixin,
    BuilderNavigationMixin,
    Agent,
):
    ct: Controller
    map: Map
    strategy: str
    last_strategy_index: int
    last_turn_completed: bool
    pending_missing_supply_link_index: int | None
    pending_missing_supply_link_resource: Environment | None
    pending_harvester_target_index: int | None
    pending_harvester_target_resource: Environment | None
    harvesters_built: int
    last_built_entity_type: EntityType | None

    def __init__(self, strategy: str = ""):
        Agent.__init__(self)
        self.strategy = strategy
        self.last_strategy_index = -1
        self.last_turn_completed = True

        self.supply_patrol_index = 0
        self.pending_missing_supply_link_index = None
        self.pending_missing_supply_link_resource = None
        self.pending_harvester_target_index = None
        self.pending_harvester_target_resource = None
        self.harvesters_built = 0
        self.last_built_entity_type = None

    def u_infer_strategy_by_spawning_tile(self):
        current_pos = self.map.current_pos
        core_center_pos = self.map.own_core_center_pos
        if core_center_pos is None:
            self.map.u_calc_core_center_positions()
            core_center_pos = self.map.own_core_center_pos
            if core_center_pos is None:
                self.strategy = ""
                return
        relative_tile = (
            current_pos.x - core_center_pos.x,
            current_pos.y - core_center_pos.y,
        )
        self.strategy = BUILDER_STRATEGY_BY_TILE.get(relative_tile, "")

    def u_get_strategy_name(self) -> str:
        return self.strategy or "unknown"

    @override
    def u_handler(self):
        if not self.strategy:
            self.u_infer_strategy_by_spawning_tile()
        print(f"Builder strategy: {self.u_get_strategy_name()}")

        handled = self.u_execute_strategy()
        return handled
