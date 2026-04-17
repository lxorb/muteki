from lib.agent.builder.strategies import STRATEGIES
from lib.debug import Stopwatch
from lib.agent.constants import (
    HARASSMENT_STRATEGY_ID,
)
from lib.map.constants import MARKER_SYMMETRY_LIST
from cambc import Position, EntityType


class BuilderExecutionMixin:
    def u_execute_strategy(self) -> bool:
        """
        Execute this builder's ordered strategy methods.

        `self.strategy` is treated as a priority-ordered list of
        `BuilderAgent` strategy methods (hence starting with s_). Each entry is bound to
        this builder instance and then executed. On a fresh turn the executor
        starts at index `0`. If the previous turn ended before this method
        returned, execution resumes at the first method that has not completed
        yet, which is the entry after `last_strategy_index`. The index is only
        advanced after a method returns, so an interrupted step is retried on
        the next turn. Execution stops at the first truthy result and returns
        whether any strategy method acted.
        """

        stopwatch = Stopwatch("Builder strats")
        stopwatch.start()

        strategy_steps = STRATEGIES.get(self.strategy, [])

        if self.last_turn_completed:
            self.last_strategy_index = -1
            start_index = 0
        else:
            start_index = self.last_strategy_index + 1
            if start_index >= len(strategy_steps):
                start_index = 0

        stopwatch.lap("Init logic")

        self.last_turn_completed = False

        # PROVISORISCH
        if self.ct.get_current_round() % 15 == 0:
            action_radius = 2
            candidate_positions = self.ct.get_nearby_tiles(action_radius)
            pos_round = []
            for pos in candidate_positions:
                if self.ct.can_build_launcher(pos):
                    self.ct.build_launcher(pos)
                    self.after_strategy()
                    self.last_turn_completed = True
                    return True
                    

        for idx in range(start_index, len(strategy_steps)):
            if self.round_stopwatch.check_overtime():
                stopwatch.lap("Overtime")
                stopwatch.log()
                return False

            strategy_method, strategy_args = self.u_get_bound_method_and_args(
                strategy_steps[idx]
            )
            acted = bool(strategy_method(*strategy_args))
            self.last_strategy_index = idx

            stopwatch.lap(
                strategy_method.__name__[:16]
            )  # Truncate name so that we get nice lines in replay viewer

            if acted:
                self.last_turn_completed = True
                print(f"Executed strategy: {strategy_method.__name__}")
                stopwatch.log()
                self.after_strategy()
                return True

        self.last_turn_completed = True
        stopwatch.lap("Complete turn")
        stopwatch.log()


        self.after_strategy()

        return False

    def after_strategy(self):
        self.place_marker()






    
