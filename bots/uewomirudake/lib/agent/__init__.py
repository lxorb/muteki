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

# every method that starts with u_ was initially creaetd by a user
# every method that was created by ai should start with c_
# this excludes some convention names like __init__ obviously
# methods starting with s_ are strategy submethods (as described later in this file)

class Agent:
    def __init__(self):
        self.bbs_spawned_by_type = dict()
        self.core_spawn_tile_usage_counts: dict[tuple[int, int], int] = {}
        self.core_previous_resources: tuple[int, int] | None = None
        # -> resources in last turn
        self.ct: Controller | None = None
        self.map: Map | None = None
        self.recource_increase_once = False
        # -> the first time the core registers an increase in it's resources
        #    this variable is set to true and then left at that value
        self.first_turn_initialized = False

        self.bb_last_turn_completed = True
        # this safes whether the last turn was completed or had TLE
        # basically set this to false at the beginning of each turn
        # and set it to True at the very end of each turn
        # use the general run method for that

        self.last_strategy_subaction = None
        # -> this is saved after one strategy method in the list of strategy elements
        #    finishes execution to be able to continue after TLE's
        self.last_strategy_index = -1
        
        # this saves the strategy of the builder bot
        self.t_start = 0

    def run(self, ct: Controller) -> None:
        """Provide the standard bot-facing entrypoint wrapper."""
        self.u_run(ct)

    def u_first_turn_init(self):
        # run the infer_strategy_by_spawning_tile
        pass
        """
        On the first turn, this does all the necessary init stuff. 
        For example here the map will be actually populated for the first time.
        But still, everything that can be initialized in the constructor should be initialized in the constructor
        as that does not count to the calculation time limit. 
        This is just for everything else that can only be initialized in the first ever turn.
        For that purpose, you should have an attribute of this class, that
        is initialized to false in the __init__ but set to true after the first ever turn.

        """

    def u_turn_init(self):
        ### this does standard init per turn like updating map with new visionn information 
        # (use the dedicated map method for this)
        pass

    def u_infer_strategy_by_spawning_tile(self):
        # there should be a constant declared somewhere that
        # assigns each of the nine core tiles 
        # a builder bot strategy that should be executed then
        pass

    def u_run(self, ct: Controller) -> None:
        # first safe the controller as self.ct
        # then run turn_init that runs the map initialization and other important init stuff
        # that needs to run every time like also updating the map with the new controller before
        # actually initializing it
        # make a match statement where you check for the type of this units
        # execute the corresponding handler function depending on the type of the unnit
        # at the end of this turn, execute the u_turn_post function
        pass

    def u_turn_post(self):
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
    
    def u_handler_bb(self):
        # just execute the corresponding strategy of the builder bot in here
        pass

    def u_handler_core(self):
        """
        there should be a constant declared in this file
        that sets the initial builder bots to spawn (see the framing bot to understand the idea behind it)
        basically this will be a list of either builder bot types 
        or of Events that you will then wait for until they complete
        
        """

    def u_handler_gunner(self):
        # look at the prioritizing system implemented in framing
        # use the same here
        # it should be also as modular so that priorities can be changed easily

        pass

    def u_handler_sentinel(self):
        # look at the prioritizing system implemented in framing
        # use the same here
        # it should be also as modular so that priorities can be changed easily
        
        pass

    def u_handler_launcher(self):
        # look at the prioritizing system implemented in framing
        # use the same here
        # it should be also as modular so that priorities can be changed easily
        
        pass

    def u_handler_breach(self):
        """ leaf this empty for now"""
        pass

    def s_build_harvester_supply_link(self, move_towards: bool = True, hold: bool = True):
        """
        move towards sets whether it will be allowed to move to be able to do
        this action 
        hold sets whether, for example if not enough resources, the bot
        will wait until the action can actually be executed
        This method should build a supply link element next to a harvestor if 
        there is no own supply link element adjacent to a harvestor
        If there are no tiles adjacent to a harvester in vision radius, return.
        But if so, then rank them as follows:
        ### we need a good priority for harvester supply link fields here
        # TODO: manually review the priority generated by ai here
        """

    def s_harvester_launcher(self, move_towards: bool = True, hold: bool = True):
        """
        The purpose of this method is to build a launcher next to a harvester if there
        is an adjacent tile next to a harvester that is empty and if there is no launcher already adjacent to that harvester
        Also, this should only be done if there is already a supply link next to that harvester
        and the launcher should have the supply link element of that harvester in it's range (should not be on the opposite side of that supply link element adjacent to the harvester)
        The purpose of this is to prevent enemy bots from destroying the supply link element adjacent to the harvestor\
        and then building a turret there.
        This is because this would force us to destroy our own harvestor so that the enemy turret does not have any ammo anymore
        but this is a very expensive price to pay as a harvester costs 80 titanium. 
        On the other hand, for example destroying just a conveyor to disconnect enemy turrets
        from ammo is a relatively cheap price to pay in comparison. 
        """

    def s_harvester_barrier(self, move_towards: bool = True, hold: bool = True):
        """
        The purpose of this method is to build a barrier next to a harvester if there
        is an adjacent tile next to a harvester that is empty
        The idea behind this is that enemy bots then can't build turrets next to our harvesters
        """

    def s_build_missing_supply_link(self, move_towards: bool = True, hold: bool = True, destroy_enemy_tile: bool = True):
        """
        The goal of this method is to ensure complete supply chains. 
        Basically, if there is some tile known to be pointed at by a conveyor or bridge but the tile itself
        is not a core tile, nor an own supply link tile itself, then we want to build a supply link
        at that location. This will then probably result in a new tile flagged as missing supply link resulting 
        in a chain-like behaviour till we reach the core with our supply link chain 

        """

    def s_build_harvester(self, move_towards: bool = True, hold: bool = True, destroy_enemy_tile: bool = True, resource: Environment = Environment.ORE_TITANIUM):
        """
        The goal of this method is to build new harvesters. 
        For all titanium tiles in sight, come up with a nice priority ordering that prefers specific tiles for
        harvester locations. 
        # TODO: manually review the priority generated by ai here
        """

    def s_expand(self):
        """ 
        This will be the lowest priority method for scavenger builder bots.
        The purpose of this method is that they explore new area to potentially find new resources. 
        # TODO: come up with a nice system for expansion / scouting
        """

    def s_destroy_hijacked_supply_link(self, move_towards: bool = True):
        """
        This method should destroy an own conveyor / bridge / splitter that points at an enemy 
        turret (gunner / sentinel / breach). 
        Come up with a good prioritzation system for hijacked supply link fields.
        # TODO: review the priority ordering here
        """

    def u_get_sentinel_orientation(self):
        """
        Assuming a sentinel should be placed on a specific tile, determine it's orientation.
        Most importantly, a sentinel should always be feeded with resources. (it can't be feeded from the direction it is pointing at).
        Then, it should point at the enemy core if possible. 
        Then, it should point at enemy turrets if possible. 
        Then, it should point at enemy bridges / conveyors.
        Make a priority ordering using this as the base idea.
        """

    def u_get_gunner_orientation(self):
        """
        Infer a similar priority ordering for the gunner based on the sentinel priority list. 
        """
