from collections.abc import Callable
from typing import Protocol, TypeAlias

from cambc import Controller, Direction, EntityType, Environment, Position

from lib.map import Map
from lib.map.tile import Tile
from lib.map.types import SupplyChainLabel

BuilderActionResult: TypeAlias = bool | None
BuilderStrategyMethod: TypeAlias = Callable[..., BuilderActionResult] | str
StrategyEntry: TypeAlias = (
    BuilderStrategyMethod | tuple[BuilderStrategyMethod, *tuple[object, ...]]
)
TilePredicate: TypeAlias = Callable[[Tile], bool]
TileCriterion: TypeAlias = Callable[[Tile], object]
SupplierBuildPlan: TypeAlias = tuple[EntityType | None, Direction | Position | None]


class BuilderCommonSelf(Protocol):
    ct: Controller
    map: Map
    strategy: list[StrategyEntry]
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

    def u_filter_tiles(
        self,
        tiles: list[Tile],
        *predicates: TilePredicate,
    ) -> list[Tile]: ...

    def u_prioritize_tiles(
        self,
        tiles: list[Tile],
        *criteria: TileCriterion,
    ) -> list[Tile]: ...


class BuilderExecutionSelf(BuilderCommonSelf, Protocol):
    strategy: list[StrategyEntry]
    last_strategy_index: int
    last_turn_completed: bool

    def u_get_bound_method_and_args(
        self,
        strategy_entry: StrategyEntry,
    ) -> tuple[BuilderStrategyMethod, tuple[object, ...]]: ...

    def u_execute_strategy(self) -> bool: ...


class BuilderNavigationSelf(BuilderCommonSelf, Protocol):
    def u_can_afford_sentinel(
        self,
        respect_titanium_reserve: bool = False,
    ) -> bool: ...

    def u_move_with_target(
        self,
        direction: Direction,
        target_pos: Position,
    ) -> None: ...

    def u_get_sentinel_orientation(self, pos: Position) -> Direction: ...

    def u_get_useful_sentinel_direction(self, pos: Position) -> Direction | None: ...

    def u_get_gunner_orientation(self, pos: Position) -> Direction: ...

    def u_get_supplier_build_plan(
        self,
        pos: Position,
        resource: Environment = Environment.ORE_TITANIUM,
    ) -> SupplierBuildPlan: ...

    def u_get_transport_supplier_build_plan(
        self,
        pos: Position,
        resource: Environment = Environment.ORE_TITANIUM,
    ) -> SupplierBuildPlan: ...

    def u_get_surround_supplier_build_plan(
        self,
        pos: Position,
        surround_target_pos: Position,
        resource: Environment = Environment.ORE_TITANIUM,
    ) -> SupplierBuildPlan: ...

    def u_get_supply_chain_label_for_resource(
        self,
        resource: Environment,
    ) -> SupplyChainLabel: ...

    def u_best_conveyor_orientation(
        self,
        pos: Position,
        resource: Environment = Environment.ORE_TITANIUM,
        surround_target_pos: Position | None = None,
        allow_adjacent_resource_sink: bool = True,
    ) -> Direction | None: ...

    def u_best_bridge_target(
        self,
        pos: Position,
        resource: Environment = Environment.ORE_TITANIUM,
    ) -> Position | None: ...
    def u_move_to_astar(
        self,
        pos: Position,
        avoid_enemy_turrets: bool = True,
        build_new_roads: bool = False,
        allow_conveyor_building: bool = True,
        reach_builder_action_range: bool = False,
        respect_titanium_reserve_for_road_build: bool = False,
    ) -> bool: ...

    def u_move_to_bugnav(
        self,
        pos: Position,
        avoid_enemy_turrets: bool = True,
        build_new_roads: bool = False,
        allow_conveyor_building: bool = True,
        reach_builder_action_range: bool = False,
        respect_titanium_reserve_for_road_build: bool = False,
    ) -> bool: ...

    def u_move_to(
        self,
        pos: Position,
        avoid_enemy_turrets: bool = True,
        build_new_roads: bool = False,
        allow_conveyor_building: bool = True,
        reach_builder_action_range: bool = False,
        respect_titanium_reserve_for_road_build: bool = False,
    ) -> bool: ...

    def u_attack_passable(
        self,
        pos: Position,
        move_towards: bool,
        destroy_condition: Callable[[Position], bool] | None = None,
        avoid_enemy_turrets: bool = True,
        ignore_conveyor_reserve_if_target_damaged: bool = False,
    ) -> bool: ...

    def u_build_at(
        self,
        pos: Position,
        building_type: EntityType,
        hold: bool,
        move_towards: bool,
        attack_enemy_passable: bool,
        facing_direction: Direction | None = None,
        target_pos: Position | None = None,
        avoid_enemy_turrets: bool = True,
        allow_conveyor_building: bool = True,
        respect_titanium_reserve: bool = False,
        allow_sentinel_next_to_harvester_instead_conveyor: bool = True,
        safety_conveyor: bool = False,
    ) -> bool: ...

    def u_heal_at(
        self,
        pos: Position,
        move_towards: bool,
        avoid_enemy_turrets: bool = True,
    ) -> bool: ...


class BuilderStrategyMethodsSelf(BuilderNavigationSelf, Protocol):
    def s_turn_to_harassment(self) -> BuilderActionResult: ...

    def s_split_supply_sentinel(self) -> BuilderActionResult: ...

    def s_defend_attacked_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_heal_self(self) -> BuilderActionResult: ...

    def s_convert_to_defender(self) -> BuilderActionResult: ...

    def s_integrate_foundry(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_integrate_own_sentinel(
        self,
        move_towards: bool = True,
        hold: bool = True,
        candidate_radius: float | None = None,
    ) -> BuilderActionResult: ...

    def s_integrate_foundry_passing_splitter(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_swap_with_splitter(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    # DEPRECATED: kept only for legacy strategy compatibility.
    def s_build_harvester_supply_link(
        self,
        move_towards: bool = True,
        hold: bool = True,
        resource: Environment = Environment.ORE_TITANIUM,
    ) -> BuilderActionResult: ...

    def s_surround_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
        resource: Environment = Environment.ORE_TITANIUM,
    ) -> BuilderActionResult: ...

    def s_protect_own_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_build_missing_supply_link(
        self,
        move_towards: bool = True,
        hold: bool = True,
        attack_enemy_passable: bool = True,
    ) -> BuilderActionResult: ...

    def s_build_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
        attack_enemy_passable: bool = True,
        resource: Environment = Environment.ORE_TITANIUM,
        enforce_safe: bool = False,
        require_connected: bool = False,
    ) -> BuilderActionResult: ...

    def s_build_connected_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
        attack_enemy_passable: bool = True,
        resource: Environment = Environment.ORE_TITANIUM,
        enforce_safe: bool = False,
    ) -> BuilderActionResult: ...

    def s_frontier_expand(self) -> BuilderActionResult: ...

    def s_fix_conveyor(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_fix_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_destroy_hijacked_supplier(
        self,
        move_towards: bool = True,
        rebuild: bool = True,
    ) -> BuilderActionResult: ...

    def s_sentinel_next_to_enemy_harvester(
        self,
        move_towards: bool = True,
        attack_enemy_passable: bool = False,
        hold: bool = False,
    ) -> BuilderActionResult: ...

    def s_hijack_enemy_supply_chain(
        self,
        move_towards: bool = True,
        hold: bool = True,
        enable_barrier: bool = True,
    ) -> BuilderActionResult: ...

    def s_block_titanium(
        self,
        move_towards: bool = True,
        hold: bool = True,
        only_out_of_reach: bool = True,
    ) -> BuilderActionResult: ...

    def s_attack_enemy_harvester_supply_link(
        self,
        move_towards: bool = True,
        require_no_enemy_bbs_in_range: bool = True,
    ) -> BuilderActionResult: ...

    def s_attack_key_enemy_supply_chain(
        self,
        move_towards: bool = True,
        wait_if_enemy_builder_bots_in_range: bool = True,
    ) -> BuilderActionResult: ...

    def s_build_enemy_supplied_turret(
        self,
        move_towards: bool = True,
        hold: bool = True,
        candidate_radius: float | None = None,
    ) -> BuilderActionResult: ...

    def s_gunner_next_to_enemy_core(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_replace_damaged_conveyor(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_attack_enemy_core_supply_link(
        self,
        move_towards: bool = True,
        wait_if_enemy_builder_bots_in_range: bool = True,
    ) -> BuilderActionResult: ...

    def s_move_toward_enemy_core(self) -> BuilderActionResult: ...

    def s_checkpoint_move_toward_enemy_core(self) -> BuilderActionResult: ...

    def s_patrol_enemy_core(self) -> BuilderActionResult: ...
