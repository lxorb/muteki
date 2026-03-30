from lib.agent import Agent

class CoreAgent(Agent):
    def __init__(self):
        super().__init__()
        self.spawn_tile_usage_counts: dict[tuple[int, int], int] = {}
        self.bbs_spawned_by_type = dict()
        self.core_last_turn_resources: tuple[int, int] | None = None
        self.recource_increase_once = False
        # -> the first time the core registers an increase in it's resources
        #    this variable is set to true and then left at that value

    def u_handler(self):
        """
        Execute the core agent's turn logic.

        This will later own spawning and core-specific orchestration.
        """
