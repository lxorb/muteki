from cambc import Environment

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

        prioritize such tiles by:
        - distance
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


INITIAL_RES_STRATEGY = [
    (BuilderAgent.s_build_harvester, True, True, True, Environment.ORE_TITANIUM),
    (BuilderAgent.s_harvester_launcher, True, True),
    (BuilderAgent.s_harvester_barrier, True, True),
    (BuilderAgent.s_build_missing_supply_link, True, True, True),
    (BuilderAgent.s_build_harvester, True, True, True, Environment.ORE_TITANIUM),
    (BuilderAgent.s_expand,)
]

SCAVENGER_STRATEGY = [
    (BuilderAgent.s_destroy_hijacked_supply_link, True),
    (BuilderAgent.s_build_harvester_supply_link, True, True),
    (BuilderAgent.s_harvester_launcher, True, True),
    (BuilderAgent.s_harvester_barrier, True, True),
    (BuilderAgent.s_build_missing_supply_link, True, True, True),
    (BuilderAgent.s_sentinel_next_to_enemy_harvester, True, False, False),
    (BuilderAgent.s_build_harvester, True, True, True, Environment.ORE_TITANIUM),
    (BuilderAgent.s_expand,)
]

HARASSMENT_STRATEGY = [
    (BuilderAgent.s_sentinel_next_to_enemy_harvester, True, False, False),
    (BuilderAgent.s_block_enemy_supply_chain, True),
    (BuilderAgent.s_block_titanium, True),
    (BuilderAgent.s_attack_enemy_harvester_supply_link, True),
    (BuilderAgent.s_attack_enemy_core_supply_link, True)
]

# TODO
FOUNDRY_STRATEGY = [

]

# TODO
DEFENDER_STRATEGY = [

]
