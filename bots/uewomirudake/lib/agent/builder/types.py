from collections.abc import Callable
from typing import Protocol, TypeAlias

from cambc import Controller, Direction, EntityType, Environment, Position

from lib.map import Map


BuilderStrategyMethod: TypeAlias = Callable[..., object]
StrategyEntry: TypeAlias = (
    BuilderStrategyMethod | tuple[BuilderStrategyMethod, *tuple[object, ...]]
)
PositionPredicate: TypeAlias = Callable[[Position], bool]
PositionCriterion: TypeAlias = Callable[[Position], object]


class BuilderExecutionSelf(Protocol):
    strategy_methods: list[StrategyEntry]
    last_strategy_index: int
    last_turn_completed: bool
    bb_last_turn_completed: bool

    def c_get_bound_method_and_args(
        self,
        strategy_entry: StrategyEntry,
    ) -> tuple[BuilderStrategyMethod, tuple[object, ...]]: ...


class BuilderNavigationSelf(Protocol):
    ct: Controller
    map: Map


class BuilderStrategyMethodsSelf(Protocol):
    ct: Controller
    map: Map

    def u_filter_tiles(
        self,
        positions: list[Position],
        *predicates: PositionPredicate,
    ) -> list[Position]: ...

    def u_prioritize_tiles(
        self,
        positions: list[Position],
        *criteria: PositionCriterion,
    ) -> list[Position]: ...

    def u_get_supplier_build_plan(
        self,
        pos: Position,
    ) -> tuple[EntityType | None, Direction | Position | None]: ...

    def u_is_enemy_turret_target_tile(self, pos: Position) -> bool: ...
    def u_is_chokepoint(self, pos: Position, min_dist_increase: int = 4) -> bool: ...
    def u_get_sentinel_orientation(self, pos: Position) -> Direction: ...
    def u_move_to(self, pos: Position, avoid_enemy_turrets: bool = True) -> bool: ...

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
