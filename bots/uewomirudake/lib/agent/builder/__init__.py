from lib.agent import Agent


class BuilderAgent(Agent):
    def __init__(self, strategy_methods):
        super().__init__()
        self.strategy_methods = list(strategy_methods or [])
        # -> ordered builder-agent methods to try for this builder, highest priority first
        self.last_executed_index = -1
        self.last_strategy_index = -1
        self.last_turn_completed = True
        self.bb_last_turn_completed = True

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
            strategy_method = self.c_get_bound_method(self.strategy_methods[idx])
            acted = bool(strategy_method())
            self.last_strategy_index = idx
            if acted:
                self.last_turn_completed = True
                self.bb_last_turn_completed = True
                return True

        self.last_turn_completed = True
        self.bb_last_turn_completed = True
        return False

    def c_get_bound_method(self, method):
        if getattr(method, "__self__", None) is self:
            return method
        return method.__get__(self, type(self))

    def s_sentinel_next_to_enemy_harvester(
        self,
        move_towards: bool = True,
        destroy_enemy_tile: bool = False,
        hold: bool = False,
    ):
        """
        If there is an empty or own road tile next to an enemy harvester, build a
        sentinel there.
        come up with priorities if there are multiple such fields here as well
        # TODO: review this priority ordering
        """

    def s_block_enemy_supply_chain(self, move_towards: bool = True):
        """
        Build a barrier at a tile where an enemy conveyor or bridge is pointing at.
        Also come up with a priority for such tiles. Distance should of course be very important
        to prevent builder bots from walking between the same two tiles all the time.
        # TODO: review this priority ordering
        """

    def s_block_titanium(self, move_towards: bool = True):
        """
        Build barriers on top of titanium tiles.
        The idea is that this does not prevent us from building an extractor over it later if we decide to do so
        but this keeps the opponent from building an own harvester or barrier and also could potentially
        deny resources for the opponent effectively cutting him off.
        """

    def s_attack_enemy_harvester_supply_link(self, move_towards: bool = True):
        """
        This makes the builder bot attack a conveyor or bridge that is next to an
        enemy harvester, cutting him off from resources. This later allows building a turret next to it.
        Come up with some priority ordering here.
        # TODO: review priority
        """

    def s_attack_enemy_core_supply_link(self, move_towards: bool = True):
        """
        This makes the builder bot attack a conveyor or bridge that is pointing
        to the enemy core. Also use a prioritization here. (come up with one)
        # TODO: review priority
        """


### HERE WILL BE A CONSTANT THAT IS A DICTIONARY FROM SUCH AN ENUM
# to a stretegy that sets the strategy per builder bot type.
# infer the strategies (i.e. the ordering of the strategy submethods from the old framing bot)

# strategy for initial res bot:
# s_build_harvester_supply_link
# s_harvester_launcher
# s_harvester_barrier
# s_build_missing_supply_link
# s_build_harvester
# s_expand

# strategy for scavenger:
# s_destroy_hijacked_supply_link
# s_build_harvester_supply_link
# s_harvester_launcher
# s_harvester_barrier
# s_build_missing_supply_link
# s_sentinel_next_to_enemy_harvester with true, false, false
# s_build_harvester
# s_expand

# strategy for harassment:
# s_sentinel_next_to_enemy_harvester with true, false, false
# s_block_enemy_supply_chain
# s_block_titanium
# s_attack_enemy_harvester_supply_link
# s_attack_enemy_core_supply_link

# foundry bot
# still TODO

# defender bot
# still TODO
