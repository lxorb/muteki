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
        
        # this saves the strategy of the builder bot
        self.t_start = 0

    def run(self, ct: Controller) -> None:
        """Provide the standard bot-facing entrypoint wrapper."""
        self.u_run(ct)

    def u_turn_init(self):
        ### this does standard init per turn like updating map with new visionn information 
        # (use the dedicated map method for this)
        pass

    def u_run(self, ct: Controller) -> None:
        # first safe the controller as self.ct
        # then run turn_init that runs the map initialization and other important init stuff
        # that needs to run every time like also updating the map with the new controller before
        # actually initializing it
        # make a match statement where you check for the type of this units
        # execute the corresponding handler function depending on the type of the unnit
        pass

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
    
    def u_handler(self):
        """
        Execute this agent's per-turn behavior.

        Concrete agent classes should implement their own handler logic.
        """
        raise NotImplementedError
