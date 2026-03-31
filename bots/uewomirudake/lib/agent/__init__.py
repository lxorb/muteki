from collections.abc import Callable

from cambc import (
    Controller,
    Direction,
    EntityType,
    Environment,
    Position,
    Team,
)
import time
from lib.map import Map
from lib.map.tile import Tile

from lib.debug import Stopwatch


class Agent:
    def __init__(self):
        self.ct: Controller | None = None
        self.map: Map | None = None
        self.first_turn_initialized = False

        # Debugging
        self.stopwatch = Stopwatch("Agent")

    def u_run(self, ct: Controller) -> None:
        self.stopwatch.start()

        self.ct = ct
        if not self.first_turn_initialized:
            self.map = Map(ct)
            self.first_turn_initialized = True
        else:
            self.map.ct = ct

        self.map.u_update_vision()
        self.stopwatch.lap("Map vision")

        self.u_handler()
        self.stopwatch.lap("Handle agent")

        self.stopwatch.log()

    def u_get_ns_elapsed(self):
        if not self.t_start:
            return 0
        return (self.t_end or time.perf_counter_ns()) - self.t_start

    def u_get_ns_remaining(self):
        from .constants import NS_PER_TURN

        return NS_PER_TURN - self.u_get_ns_elapsed()

    def u_get_bound_method(
        self,
        method: Callable[..., object] | str,
    ) -> Callable[..., object]:
        if isinstance(method, str):
            return getattr(self, method)
        if getattr(method, "__self__", None) is self:
            return method
        return method.__get__(self, type(self))

    def u_get_bound_method_and_args(
        self,
        strategy_entry: Callable[..., object] | str | tuple[object, ...],
    ) -> tuple[Callable[..., object], tuple[object, ...]]:
        if isinstance(strategy_entry, tuple):
            method, *args = strategy_entry
        else:
            method = strategy_entry
            args = []
        return self.u_get_bound_method(method), tuple(args)

    def u_filter_tiles(
        self,
        tiles: list[Tile],
        *predicates: Callable[[Tile], bool],
    ) -> list[Tile]:
        filtered_tiles = list(tiles)
        for predicate in predicates:
            filtered_tiles = [tile for tile in filtered_tiles if predicate(tile)]
        return filtered_tiles

    def u_prioritize_tiles(
        self,
        tiles: list[Tile],
        *criteria: Callable[[Tile], object],
    ) -> list[Tile]:
        if not criteria:
            return list(tiles)
        return sorted(
            tiles,
            key=lambda tile: tuple(criterion(tile) for criterion in criteria),
        )

    def u_handler(self):
        """
        Execute this agent's per-turn behavior.
        Should be overridden by each child.
        """
        raise NotImplementedError
