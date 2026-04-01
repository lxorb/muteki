from collections.abc import Callable
from typing import Protocol, TypeAlias

from cambc import Controller, Direction, EntityType, Environment, Position

from lib.map import Map
from lib.map.tile import Tile


BuilderActionResult: TypeAlias = bool | None
BuilderStrategyMethod: TypeAlias = Callable[..., BuilderActionResult] | str
StrategyEntry: TypeAlias = (
    BuilderStrategyMethod | tuple[BuilderStrategyMethod, *tuple[object, ...]]
)
TilePredicate: TypeAlias = Callable[[Tile], bool]
TileCriterion: TypeAlias = Callable[[Tile], object]
DirectionScore: TypeAlias = tuple[tuple[int, ...], Direction]
SupplierBuildPlan: TypeAlias = tuple[EntityType | None, Direction | Position | None]


class BuilderCommonSelf(Protocol):
    ct: Controller
    map: Map

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
    def u_get_sentinel_orientation(self, pos: Position) -> Direction: ...

    def u_get_sentinel_direction_score(
        self,
        pos: Position,
        direction: Direction,
        enemy_core_tiles: list[Tile],
        enemy_turret_tiles: list[Tile],
        own_supplier_tiles: list[Tile],
        enemy_building_tiles: list[Tile],
        direction_order: dict[Direction, int],
    ) -> DirectionScore: ...

    def u_get_gunner_orientation(self, pos: Position) -> Direction: ...

    def u_get_supplier_build_plan(
        self,
        pos: Position,
    ) -> SupplierBuildPlan: ...

    def u_get_axionite_supplier_build_plan(
        self,
        pos: Position,
    ) -> SupplierBuildPlan: ...

    def u_best_conveyor_orientation(self, pos: Position) -> Direction | None: ...
    def u_best_bridge_target(self, pos: Position) -> Position | None: ...
    def u_move_to(
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


class BuilderStrategyMethodsSelf(BuilderNavigationSelf, Protocol):
    def s_insert_core_splitter(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_build_foundry_next_to_splitter(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_build_harvester_supply_link(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_build_axionite_harvester_supply_link(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ) -> BuilderActionResult: ...

    def s_surround_harvester(
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

    def s_build_missing_axionite_supply_link(
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
    ) -> BuilderActionResult: ...

    def s_frontier_expand(self) -> BuilderActionResult: ...

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
    ) -> BuilderActionResult: ...

    def s_attack_enemy_harvester_supply_link(
        self,
        move_towards: bool = True,
    ) -> BuilderActionResult: ...

    def s_attack_enemy_core_supply_link(
        self,
        move_towards: bool = True,
    ) -> BuilderActionResult: ...
