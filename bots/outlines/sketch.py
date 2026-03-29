from cambc import (
    Controller,
    Direction,
    EntityType,
    Environment,
    Position,
    Team,
)
import time

# every method that starts with u_ was initially creaetd by a user
# every method that was created by ai should start with c_
# this excludes some convention names like __init__ obviously
# methods starting with s_ are strategy submethods (as described later in this file)

class Tile:
    def __init__(self):
        self.position: Position = Position(-1, -1)
        self.environment: Environment = Environment.EMPTY
        self.own_core_dist: int = 10**9
        self.enemy_core_dist: int = 10**9
        self.building_id: int | None = None
        self.building_type: EntityType | None = None
        self.building_team: Team | None = None
        self.builder_bot_id: int | None = None
        self.builder_bot_team: Team | None = None
        self.is_passable: bool = False
        # -> can a builder bot walk on this tile?
        self.last_seen_turn: int = -1
        self.in_enemy_launcher_pickup_zone: bool = False
        # -> can an enemy launcher pickup bots on this tile?
        self.in_action_radius: bool = False
        self.in_vision_radius: bool = False
        self.last_titanium_onit_turn: int = -1
        # -> the turn where there was titanium on this tile for the last time
        self.is_core_tile: bool = False
        self.resource_target: Position | None = None
        # -> target tile, i.e. which tile bridge or conveyor is pointing at
        self.in_enemy_attack_range: bool = False
        # -> this just considers enemy turrets that can attack, not enemy launchers
        self.is_in_enemy_bot_actiono_range: bool = False

        self.known_missing_supply_links: list[Position] = []
        # this keeps a list of missing supply link tiles
        # i.e. if there is an own conveyor or an own bridge that points onto a tile 
        # that is not a core tile and also not an own supply link tile then, the target field should be in this list
        # this list should be kept lazily

    def u_get_resource_targets(self, ct: Controller) -> list[Position]:
        pass
        # returns which tiles are the targets
        # e.g. where bridge or conveyor points at
        # or where supplier or harvester outputs
        # or where foundry outputs

    

class Map:
    def __init__(self, ct: Controller):
        """
        Create a map cache for a single bot instance.

        Here the whole map should be initialized, all tiles should be created
        and everything about the map in terms of metadata like width and height should be fetched.

        """
        self.u_change_controller(ct)
        self.width = ct.get_map_width()
        self.height = ct.get_map_height()
        self.matrix: list[list[Tile]] = [
            [Tile() for _ in range(self.height)] for _ in range(self.width)
        ]
        for x in range(self.width):
            for y in range(self.height):
                self.matrix[x][y].position = Position(x, y)
        self.core_center_pos: Position | None = None
        self.enemy_core_center_pos: Position | None = None
        # -> this only saves the enemy core pos if it is known (if there is just one candidate remaining)
        self.enemy_core_center_pos_candidates: list[Position] = []
        # save the following as attributes for better caching
        # (should of course be updated on update vision)
        # buildings in vision (list of Position)
        # orthogonally adjacent tiles (list of Position)
        # diagonally adjacent tiles (list of Position)
        # has enemy bot in vision
        # titanium tiles in vision (list of Position)
        # axionite tiles in vision (list of Position)
        # enemy harvesters in sight (list of Position)
        # own harvesters in sight (list of Position)
        self.buildings_in_vision: list[Position] = []
        self.orthogonally_adjacent_tiles: list[Position] = []
        self.diagonally_adjacent_tiles: list[Position] = []
        self.has_enemy_bot_in_vision: bool = False
        self.titanium_tiles_in_vision: list[Position] = []
        self.axionite_tiles_in_vision: list[Position] = []
        self.enemy_harvesters_in_sight: list[Position] = []
        self.own_harvesters_in_sight: list[Position] = []
        self.committed_path: list[Position] = []
        self.committed_path_allow_build_new_tiles: bool = True
        self.committed_path_allow_enemy_tiles: bool = True
        self.committed_path_destination: Position | None = None
        self.known_missing_supply_links: list[Position] = []
        

    def u_change_controller(self, ct: Controller):
        self.ct = ct

    def u_calc_core_center_pos(self):
        # you can use the self.ct here
        # assume the current builder bot is standing on some core tile
        # for this calculation
        # based on that, get the core and safe the core center pos in the corresponding attribute
        pass

    def u_update_vision(self):
        """
        using self.ct first, get the current vision radius
        then update all maps tile in vision radius with all available information
        For that purpose, take a look at the __init__ attributes of the tile class
        Then set everything to the corresponding value.
        Do one simple for loop first that updates all the easy stats like last_seen_turn or 
        in_action_radius and everything
        The distance to both the own as also to the enemy core should be updated in a lazy way.
        If distance is not known, initialize it to an infinite value, i.e. something like 10^5 should suffice.
        Then, using a queue-like behaviour, update all distances lazily to keep performance as optimal as possible.
        Still, distances should be all updated till they are correct for the current knowledge of the map. 
        
        Every attribute of the map and every attribute of tiles that can be initialized should be initialized for caching.
        
        This method should also update the candidates list of potential enemy core center candidates.
        I.e. either if we see the enemy core center then set the enemy core center position to that one.
        and if a tile is in sight from that we can infer that one of the candidates can't be the enemy core center, than
        remove that candidate from the candidates list
        if there is just one candidate left, that must be the enemy core center pos
        
        """
        pass
    
    def u_calc_enemy_core_center_candidates(self):
        # calculates candidates for enemy center core position
        # using the possible symmetry of the map (see the docs)
        pass

    # generally for all path findings, if there is a choice where there are tiles that seem equally good
    # then prioritize tiles of the own team
    # if there is still a tie then prioritize by bridges > conveyors > roads > core_tile
    # make this priority configurable easily and hence modular
    def u_calculate_shortest_walk_path_to(self, dest: Position, allow_enemy_tiles: bool = True, allow_build_new_tiles: bool = True, source: Position = None):
        """
        Calculates the shortest path to a specific target position. 
        Depending on the parameters, the output will vary a bit. For example, allow enemy tiles decides whether the bot is allowed to use enemy tiles.
        And allow_buid_new_tiles sets whether it is allowed to build new tiles for the path, i.e. then empty fields are treated like roads.
        If no source is specified, just use the current builder bots location as the source. 
        Return a list of positions as the output.
        Unknown tiles are just assumed to be empty tiles.
        """
        pass

    def u_calculate_all_shortest_walk_paths(self, allow_enemy_tiles: bool = True, allow_build_new_tiles: bool = True, source: Position = None):
        """
        This calculates the shortest paths to all tiles that have been in visoinn radius at least once or that are at least in one of the 8
        neighboring fields to a tile that has been visited before. 
        
        """
        pass

    def u_calculate_shortest_action_path_to(self, target: Position, action_radius_sq: int = 2, allow_enemy_tiles: bool = True, allow_build_new_tiles: bool = True, source: Position = None):
        """
        Similar to calculate_shortest_walk_path_to, but it only calculates the shortest path so that the target field will be in action range.
        I.e. this calculates the shortest path so that the builder bot is at the end of the path on one of the eight neighbor tiles of the target tile.

        """
        pass

    def u_commit_new_path(self, path):
        """
        This saves a specific path as an attribute with datatype list of positions.
        The first element of the list should always be the next tile of the path. 
        Basically the goal of this is to set a path and then the builder bot will pursue that path till it reaches the destination. 

        """
        pass

    def u_follow_commit_path(self):
        """
        This method goes along the currently active commited path. 
        This method of course validates whether the path is still possible.
        general Side note: there should be attributes for the commited path saving whether to
        build new roads or whether it is allowed to use enemy tiles
        these both should as the default be true 
        
        """
    
    def u_move_to(self, allow_build: bool = True):
        """
        This method is used to move to a new tile. 
        If the tile is already walkable, then just move there.
        If not, you should in the base case just build a road and then walk on that tile.
        There is an attribute of the tile object that saves whether 
        that tile is pointed on by a bridge or a conveyor. If that is the case,
        then instead of building a road, build either a conveyor or a bridge. 
        To decide which one to build use the c_build_supplier method. 
        """

    def u_build_supplier(self, pos: Position):
        """
        This method gets a position for a new supplier and is supposed to determine the target, which
        means it should determine first if a bridge or a conveyor or a splitter should be build and then 
        it should determine where to point it at, i.e. where it's target should be.
        That is for conveyors an orthogonally adjacent field and for a bridge a tile with max distance not over 
        the max target distance for the bridge. 
        First, using the methods 
        u_best_conveyor_orientation and u_best_bridge_target,
        determine the best locations for a potential bridge or conveyor
        If both are None, i.e. both do not make sense, don't build a supplier.
        If exactly one of them is none, build the other one with the corresponding target location.
        If both are not none, then you will have to decide which one makes more sense to build. 
        For that purpose, you should introduce a global constant BRIDGE_PREFERRED_DIST = 5.
        If the difference of the core distance between the bridge and the bridge target is at least that high, then
        build a bridge, otherwise build a conveyor. 
        """

    def u_best_conveyor_orientation(self, pos: Position):
        """
        Assuming that on the given position a conveyor should be build,
        return the best direction for the conveyor to point at or None, if it does not make 
        sense to build a conveyor here. 
        There are four possible tiles where the conveyor can point at. You should prioritze them as follows, ordered by precedence (descending, highest first):

        - if one of the neighbors is a core tile, early exist and return the corresponding orientation
        - filter out all neigbor tiles that would not decrease distance to the own core
        - then it should be prioritzed by tiles that already have a supply chain element (bridge /conveyor / splitter) on them
        -> if there are such tiles, just consider these
        -> if there are no such tiles, prioritize by tiles that are own barriers, then own roads, then empty tiles, then enemy roads (in this order)
        -> if there are none of these tiles, then return None
        - keep only the best of the beforementioned categories
        - if there are multiple tiles left, sort them by distance and pick the one with the lowest distance to the own core
        - if there are still multiple left, prioritize the ones that are in action radius of the current builder bot
        - 

        This prioritizing should be written in a modular way so that is easily adjustable.

        """

    def u_best_bridge_target(self, pos: Position):
        """
        Assuming that on the given position a bridge should be build,
        return the best direction for the bridge to point at or None, if it does not make 
        sense to build a bridge here. 
        Consider all tiles that the bridge can point at (see the docs for information on which these are).
        
        - filter out all tiles that are orthogonally adjacent to the source pos
        - filter out all tiles that would not decrease distance to the own core
        - then if one of the remaining possible target tiles is a core tile, then simply return the core tile with the smallest distance to the current tile
        - if that was not the case it should be prioritzed by tiles that already have a supply chain element (bridge /conveyor / splitter) on them
        -> if there are such tiles, just consider these
        -> if there are no such tiles, prioritize by tiles that are of the own team and either barriers / roads or empty >> then enemy roads
        -> if there are none of these tiles, then return None
        - keep only the best of the beforementioned categories
        - if there are multiple tiles left, sort them by distance and pick the one with the lowest distance to the own core
        - if there are still multiple left, prioritize the ones that are in action radius of the current builder bot
        

        This prioritizing should be written in a modular way so that is easily adjustable.

        """

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

class Bot:
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

        self.bb_strategy = None
        # this saves the strategy of the builder bot
        self.t_start = 0

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

    def s_sentinel_next_to_enemy_harvester(self, move_towards: bool = True, destroy_enemy_tile: bool = False, hold: bool = False):
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
