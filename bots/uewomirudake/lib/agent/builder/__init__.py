from cambc import Controller, Direction, EntityType, Environment, Position

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
    enemy_core_patrol_index: int
    enemy_core_checkpoint_index: int
    bugnav_target_key: tuple[object, ...] | None
    bugnav_follow_wall: bool
    bugnav_wall_on_left: bool
    bugnav_best_distance_sq: int
    bugnav_last_move_direction: Direction | None
    harvesters_built: int
    last_built_entity_type: EntityType | None
    enemy_core_proxy_target_pos: Position | None
    enemy_core_proxy_base_target_pos: Position | None

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
        self.enemy_core_patrol_index = 0
        self.enemy_core_checkpoint_index = -1
        self.bugnav_target_key = None
        self.bugnav_follow_wall = False
        self.bugnav_wall_on_left = True
        self.bugnav_best_distance_sq = 10**9
        self.bugnav_last_move_direction = None
        self.harvesters_built = 0
        self.last_built_entity_type = None
        self.enemy_core_proxy_target_pos = None
        self.enemy_core_proxy_base_target_pos = None

        self.awaiting_yeet_since = -1
        self.awaiting_yeet_pos = None


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
        if self.map.is_map_known:
            print(
                f"Inferred map: {self.map.known_map_path} "
                f"(map inference loading took "
                f"{self.map.map_inference_time_ns / 1_000_000:.2f} ms)."
            )
        if self.map.map_json_loaded_print_pending:
            print(
                "Finished loading parsed map data into map object. "
                f"Map updating took {self.map.map_update_time_ns / 1_000_000:.2f} ms."
            )
            self.map.map_json_loaded_print_pending = False
        print(f"Builder strategy: {self.u_get_strategy_name()}")

        if self.awaiting_yeet_since != -1:
            if self.awaiting_yeet_pos == self.ct.get_position():
                if self.awaiting_yeet_since < 2:
                    self.awaiting_yeet_since += 1
                    print("AWAITING YEET -> SKIP")
                    return
                else:
                    print("GIVING UP YEET :(")
            self.awaiting_yeet_since = -1
            self.awaiting_yeet_pos = None


        handled = self.u_execute_strategy()
        finished_loading_map = self.map.u_update_map()
        if finished_loading_map:
            print(
                "Finished loading parsed map data into map object. "
                f"Map updating took {self.map.map_update_time_ns / 1_000_000:.2f} ms."
            )
            self.map.map_json_loaded_print_pending = False
        return handled
