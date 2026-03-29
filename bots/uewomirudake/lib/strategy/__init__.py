from cambc import (
    Controller,
    Direction,
    EntityType,
    Environment,
    Position,
    Team,
)
import time

### HERE YOU SHOULD CREATE AN ENUM FOR ALL POSSIBLE BUILDER BOT TYPES
# these are:
# scavenger
# harassment
# defender
# initial_res
# foundrybot

class Strategy:
    """
    A strategy is in a nutshell an ordered list of methods of the Bot class. 
    The idea is that these are the priorities for doing different actions. 
    A strategy object consists of three of these lists. 
    First one pre-strategy method list, then one main strategy ordered list as just described and then one post strategy ordered list.
    Every function, either pre or post or one of the elements of the strategy list should be saved as tuple of a string (the name for printing it out) and 
    the actual function which should be a method of Bot. 
    All of these should be passed when the strategy is created.
    There should be an execute strategy method but it needs to be passed a Bot insntance to work.
    First, execute the pre methods in order (all of them).
    Then, execute the main methods till the first one returns true.
    Then, execute the post methods in order (all of them).
    Also, if the last turn was not completed (i.e. TLE), then the execute_strategy method
    prints that it is resuming and at whicih method it is resuming and then it does exactly that. 
    Even when resuming, pre should be executed before actually resuming with the next main method.
    Also, of course post methods should be executed afterwards.
    Resuming is just for the main methods, not for pre or post. 
    """
    def __init__(self, pre_strategy_methods = None, strategy_methods = None, post_strategy_methods = None):
        self.pre_strategy_methods = pre_strategy_methods or []
        self.strategy_methods = strategy_methods or []
        self.post_strategy_methods = post_strategy_methods or []

    def u_execute_strategy(self, bot):
        pass

### CONSTANT THAT IS A DICTIONARY FROM SUCH AN ENUM
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
