import time
from abc import ABC, abstractmethod

from lib.map import Map

from cambc import (
    Controller,
    Direction,
    EntityType,
    Environment,
    Position,
    Team,
)


class Agent(ABC):
    def __init__(self, ct: Controller):
        # ----------- Attributes that are automatically updated (in this class) -----------

        # the controller that is used to communicate with the game
        self.ct: Controller = ct

        # unit id
        self.id: int = self.ct.get_id()

        # team: 'a' or 'b'
        self.team: Team = self.ct.get_team()

        # auto increased round counter
        self.round: int = self.ct.get_current_round()

        # the map that is used to store the map data
        self.map: Map = Map(self.ct)

        # None by constructor; False at the start of run; True at the end of run
        self.last_turn_completed: bool | None = None

        # time of run execution
        self.time_delta: float | None = None
        self.time_start: float | None = None
        self.time_end: float | None = None


        # global resources from previous round
        self.resources_prev: tuple[int, int] = self.ct.get_global_resources()

        # global resources from the current round
        self.resources_curr: tuple[int, int] = self.ct.get_global_resources()

        # global resource change relative to the previous round
        self.resources_change: tuple[int, int] = (0, 0)

        # turn number resource increase (titanium or axionite)
        self.last_turn_resource_decrease: int = 0


    def run(self) -> None:
        self.last_turn_completed = False
        self.time_start = time.perf_counter_ns()

        self.map.update()

        self.make_turn()

        self.round += 1
        self.time_end = time.perf_counter_ns()
        self.time_delta = (self.time_end or float('inf')) - (self.time_start or float('-inf'))
        self.last_turn_completed = True


    def remaining_time(self) -> float:
        """
        Estimate the remaining local nanosecond budget for the turn.

        The estimate is based on a 2 ms target and the same per-turn start time
        used by the elapsed-time helper.
        """
        return 2_000_000 - time.perf_counter_ns() + self.time_start


    @abstractmethod
    def make_turn(self) -> None:
        pass