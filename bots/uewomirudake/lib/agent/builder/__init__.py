from cambc import Controller, EntityType, Environment, Position

from lib.agent import Agent
from lib.agent.builder.strategies import BUILDER_STRATEGY_BY_TILE, FURTHER_BB_MIN_TURN
from lib.agent.constants import (
    CORE_DEFENDER_STRATEGY_ID,
    HARASSMENT_STRATEGY_ID,
    SCAVENGER_STRATEGY_ID,
    SAVER_TLE_RATIO,
    YEET_STUCK_OSCILLATION_ROUNDS,
)
from lib.map import Map
from lib.map.types import SupplyChainLabel

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
    pending_missing_supply_link_label: SupplyChainLabel | None
    pending_harvester_target_index: int | None
    pending_harvester_target_resource: Environment | None
    pending_delete_tile_index: int | None
    enemy_core_patrol_index: int
    enemy_core_checkpoint_index: int
    harvesters_built: int
    last_built_entity_type: EntityType | None
    enemy_core_proxy_target_pos: Position | None
    enemy_core_proxy_base_target_pos: Position | None
    marker_target_pos: Position | None
    marker_follow_enemy_builder_bot_id: int | None
    marker_placed_already: bool
    follow_enemy_builder_bot_id: int | None
    awaiting_yeet_from_pos: Position | None
    awaiting_yeet_rounds_waited: int
    recent_positions: list[Position]
    step_off_core_attempted: bool
    spawn_relative_tile: tuple[int, int] | None
    close_patrol_step: int
    tle_count: int
    turn_count: int
    is_tle_saver_mode: bool
    spawn_round_by_builder_id: dict[int, int]
    self_built_supply_link_indices_by_builder_id: dict[int, set[int]]
    self_patrol_defender_builder_ids: set[int]
    _d_star_lite_states_by_builder_id: dict[int, object]
    _lpa_star_states_by_builder_id: dict[int, object]

    def __init__(self, strategy: str = ""):
        Agent.__init__(self)
        self.strategy = strategy
        self.last_strategy_index = -1
        self.last_turn_completed = True

        self.supply_patrol_index = 0
        self.enemy_supply_patrol_index = 0
        self.pending_missing_supply_link_index = None
        self.pending_missing_supply_link_resource = None
        self.pending_missing_supply_link_label = None
        self.pending_harvester_target_index = None
        self.pending_harvester_target_resource = None
        self.pending_delete_tile_index = None
        self.enemy_core_patrol_index = 0
        self.enemy_core_checkpoint_index = -1
        self.harvesters_built = 0
        self.last_built_entity_type = None
        self.enemy_core_proxy_target_pos = None
        self.enemy_core_proxy_base_target_pos = None
        self.marker_target_pos = None
        self.marker_follow_enemy_builder_bot_id = None
        self.marker_placed_already = False
        self.follow_enemy_builder_bot_id = None
        self.awaiting_yeet_from_pos = None
        self.awaiting_yeet_rounds_waited = 0
        self.recent_positions = []
        self.step_off_core_attempted = False
        self.spawn_relative_tile = None
        self.close_patrol_step = 0
        self.tle_count = 0
        self.turn_count = 0
        self.is_tle_saver_mode = False
        self.spawn_round_by_builder_id = {}
        self.self_built_supply_link_indices_by_builder_id = {}
        self.self_patrol_defender_builder_ids = set()
        self._d_star_lite_states_by_builder_id = {}
        self._lpa_star_states_by_builder_id = {}

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
        self.spawn_relative_tile = relative_tile
        self.strategy = BUILDER_STRATEGY_BY_TILE.get(relative_tile, "")

    def u_get_strategy_name(self) -> str:
        return self.strategy or "unknown"

    def u_is_initial_scavenger(self) -> bool:
        if self.strategy != SCAVENGER_STRATEGY_ID:
            return False
        spawn_round = self.spawn_round_by_builder_id.get(self.ct.get_id())
        return spawn_round is not None and spawn_round < FURTHER_BB_MIN_TURN

    def u_is_self_patrol_defender(self) -> bool:
        return self.ct.get_id() in self.self_patrol_defender_builder_ids

    @override
    def u_before_vision_update(self) -> None:
        """
        Suppress the expensive frontier-expand cache population for the
        current turn when this builder will run as a harassment bot or a
        core-defender bot. Role is inferred from the bot's current position
        relative to the own core center (mirroring
        `u_infer_strategy_by_spawning_tile`). When the own core center is not
        yet known (e.g. very first turn), fall back to the default (no skip).
        """
        core_center_pos = self.map.own_core_center_pos
        if core_center_pos is None:
            return
        current_pos = self.ct.get_position()
        relative_tile = (
            current_pos.x - core_center_pos.x,
            current_pos.y - core_center_pos.y,
        )
        strategy = BUILDER_STRATEGY_BY_TILE.get(relative_tile, "")
        if strategy in {HARASSMENT_STRATEGY_ID, CORE_DEFENDER_STRATEGY_ID}:
            self.map.skip_frontier_expand_this_turn = True

    def u_is_stuck_oscillating(self) -> bool:
        window = YEET_STUCK_OSCILLATION_ROUNDS + 1
        if len(self.recent_positions) < window:
            return False
        return len(set(self.recent_positions[-window:])) <= 2

    def u_update_tle_tracking(self) -> None:
        """
        Detect TLE of the previous turn, update counters, and recompute the
        saver-mode flag. `last_turn_completed` is set to False at the start of
        strategy execution and back to True only after a strategy returns or
        the full list is scanned without overtime. If it is still False at the
        start of a new turn, the previous turn hit overtime / TLE.
        """
        self.turn_count += 1
        if not self.last_turn_completed:
            self.tle_count += 1
        if self.turn_count <= 0:
            self.is_tle_saver_mode = False
            return
        tle_ratio = self.tle_count / self.turn_count
        self.is_tle_saver_mode = tle_ratio >= SAVER_TLE_RATIO

    @override
    def u_handler(self):
        self.spawn_round_by_builder_id.setdefault(
            self.ct.get_id(),
            self.map.current_round,
        )
        self.u_update_tle_tracking()
        if not self.strategy:
            self.u_infer_strategy_by_spawning_tile()
        self.marker_target_pos = None
        self.marker_follow_enemy_builder_bot_id = None
        self.marker_placed_already = False

        fresh_pos = self.ct.get_position()
        self.recent_positions.append(fresh_pos)
        history_cap = YEET_STUCK_OSCILLATION_ROUNDS + 1
        if len(self.recent_positions) > history_cap:
            del self.recent_positions[: len(self.recent_positions) - history_cap]

        if self.awaiting_yeet_from_pos is not None:
            if fresh_pos != self.awaiting_yeet_from_pos:
                self.awaiting_yeet_from_pos = None
                self.awaiting_yeet_rounds_waited = 0
            elif self.awaiting_yeet_rounds_waited >= 2:
                print(
                    f"[yeet] giving up awaiting yeet at {fresh_pos} "
                    f"after {self.awaiting_yeet_rounds_waited} rounds"
                )
                self.awaiting_yeet_from_pos = None
                self.awaiting_yeet_rounds_waited = 0
            else:
                self.awaiting_yeet_rounds_waited += 1
                finished_loading_map = self.map.u_update_map()
                if finished_loading_map:
                    self.map.map_json_loaded_print_pending = False
                return False

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
        self.follow_enemy_builder_bot_id = self.map.u_refresh_follow_enemy_builder_tracking(
            self.ct.get_id(),
            self.follow_enemy_builder_bot_id,
        )
        if self.follow_enemy_builder_bot_id is not None:
            self.u_set_follow_enemy_builder_marker(
                self.follow_enemy_builder_bot_id,
            )

        handled = self.u_execute_strategy()
        finished_loading_map = self.map.u_update_map()
        if finished_loading_map:
            print(
                "Finished loading parsed map data into map object. "
                f"Map updating took {self.map.map_update_time_ns / 1_000_000:.2f} ms."
            )
            self.map.map_json_loaded_print_pending = False
        return handled
