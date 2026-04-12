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
    harvesters_built: int
    last_built_entity_type: EntityType | None

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
    def u_get_core_foundry_plan(
        self,
    ) -> Position | None: ...

    def u_get_core_splitter_foundry_plan(
        self,
    ) -> tuple[Position, Direction, Position] | None: ...

    def u_get_foundry_wait_position(
        self,
        foundry_pos: Position,
    ) -> Position | None: ...

    def u_foundry_site_has_visible_axionite_supply(
        self,
        foundry_pos: Position,
    ) -> bool: ...

    def u_get_sentinel_orientation(self, pos: Position) -> Direction: ...

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

    def u_is_supply_tile_forbidden(
        self,
        pos: Position,
        resource: Environment,
    ) -> bool: ...

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
    def u_move_to(
        self,
        pos: Position,
        avoid_enemy_turrets: bool = True,
        build_new_roads: bool = False,
    ) -> bool: ...

    def u_move_to_astar(
        self,
        pos: Position,
        avoid_enemy_turrets: bool = True,
        build_new_roads: bool = False,
    ) -> bool: ...

    def u_attack_passable(
        self,
        pos: Position,
        move_towards: bool,
        destroy_condition: Callable[[Position], bool] | None = None,
        avoid_enemy_turrets: bool = True,
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
    ) -> bool: ...

    def u_heal_at(
        self,
        pos: Position,
        move_towards: bool,
        avoid_enemy_turrets: bool = True,
    ) -> bool: ...


class BuilderStrategyMethodsSelf(BuilderNavigationSelf, Protocol):
    def s_heal_self(self) -> BuilderActionResult: ...

    def s_convert_to_defender(self) -> BuilderActionResult: ...

    def s_insert_core_splitter(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_build_core_foundry(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

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

    def s_build_missing_supply_link(
        self,
        move_towards: bool = True,
        hold: bool = True,
        attack_enemy_passable: bool = True,
        resource: Environment = Environment.ORE_TITANIUM,
    ) -> BuilderActionResult: ...

    def s_build_harvester(
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

    def s_destroy_hijacked_supplier(
        self,
        move_towards: bool = True,
    ) -> BuilderActionResult: ...

    def s_sentinel_next_to_enemy_harvester(
        self,
        move_towards: bool = True,
        attack_enemy_passable: bool = False,
        hold: bool = False,
    ) -> BuilderActionResult: ...

    def s_block_enemy_supply_chain(
        self,
        move_towards: bool = True,
        hold: bool = True,
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
    ) -> BuilderActionResult: ...

    def s_attack_key_enemy_supply_chain(
        self,
        move_towards: bool = True,
    ) -> BuilderActionResult: ...

    def s_build_enemy_supplied_sentinel(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_attack_enemy_core_supply_link(
        self,
        move_towards: bool = True,
    ) -> BuilderActionResult: ...

    def s_move_toward_enemy_core(self) -> BuilderActionResult: ...
