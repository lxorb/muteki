from .types import BuilderExecutionSelf


class BuilderExecutionMixin(BuilderExecutionSelf):
    def u_execute_strategy(self) -> bool:
        """
        Execute this builder's ordered strategy methods.

        `self.strategy` is treated as a priority-ordered list of
        `BuilderAgent` methods, usually `s_...` methods. Each entry is bound to
        this builder instance and then executed. On a fresh turn the executor
        starts at index `0`. If the previous turn ended before this method
        returned, execution resumes at the first method that has not completed
        yet, which is the entry after `last_executed_index`. The index is only
        advanced after a method returns, so an interrupted step is retried on
        the next turn. Execution stops at the first truthy result and returns
        whether any strategy method acted.
        """
        if not self.strategy_methods:
            raise ValueError(
                "Should only be called when strategy methods is initialized."
            )

        if self.last_turn_completed:
            self.last_strategy_index = -1
            start_index = 0
        else:
            start_index = self.last_strategy_index + 1
            if start_index >= len(self.strategy_methods):
                start_index = 0

        self.last_turn_completed = False
        self.bb_last_turn_completed = False
        for idx in range(start_index, len(self.strategy_methods)):
            strategy_method, strategy_args = self.c_get_bound_method_and_args(
                self.strategy_methods[idx]
            )
            acted = bool(strategy_method(*strategy_args))
            self.last_strategy_index = idx
            if acted:
                self.last_turn_completed = True
                self.bb_last_turn_completed = True
                return True

        self.last_turn_completed = True
        self.bb_last_turn_completed = True
        return False
