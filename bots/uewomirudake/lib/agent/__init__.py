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


class Agent:
    def __init__(self):
        self.ct: Controller | None = None
        self.map: Map | None = None
        self.first_turn_initialized = False
        self.last_strategy_subaction = None
        # -> this is saved after one strategy method in the list of strategy elements
        #    finishes execution to be able to continue after TLE's
        self.last_strategy_index = -1
        # -> this saves the strategy of the builder bot
        self.t_start = 0

    def u_run(self, ct: Controller) -> None:
        if not self.first_turn_initialized:
            self.map = Map(self.ct)
            # TODO: run the infer_strategy_by_spawning_tile
            self.first_turn_initialized = True
        self.ct = ct
        self.map.u_update_vision()
        self.u_handler()

    def u_get_ns_elapsed(self):
        """
        Return the nanoseconds spent so far in the current turn.

        The value is measured from the timestamp captured at the start of
        `run`, which makes it useful for lightweight runtime instrumentation.
        """
        return time.perf_counter_ns() - self.t_start

    def u_get_ns_remaining(self):
        """
        Estimate the remaining local nanosecond budget for the turn.

        The estimate is based on a 2 ms target and the same per-turn start time
        used by the elapsed-time helper.
        """
        return 2_000_000 - time.perf_counter_ns() + self.t_start

    def c_get_bound_method(self, method):
        if getattr(method, "__self__", None) is self:
            return method
        return method.__get__(self, type(self))

    def c_get_bound_method_and_args(self, strategy_entry):
        if isinstance(strategy_entry, tuple):
            method, *args = strategy_entry
        else:
            method = strategy_entry
            args = []
        return self.c_get_bound_method(method), tuple(args)

    def u_filter_tiles(
        self,
        positions: list[Position],
        *predicates: Callable[[Position], bool],
    ) -> list[Position]:
        filtered_positions = list(positions)
        for predicate in predicates:
            filtered_positions = [pos for pos in filtered_positions if predicate(pos)]
        return filtered_positions

    def u_prioritize_tiles(
        self,
        positions: list[Position],
        *criteria: Callable[[Position], object],
    ) -> list[Position]:
        if not criteria:
            return list(positions)
        return sorted(
            positions,
            key=lambda pos: tuple(criterion(pos) for criterion in criteria),
        )

    def u_handler(self):
        """
        Execute this agent's per-turn behavior.

        Concrete agent classes should implement their own handler logic.
        """
        raise NotImplementedError
