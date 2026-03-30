from cambc import (
    Controller,
    Direction,
    EntityType,
    Environment,
    Position,
    Team,
)
import time

from tile import Tile


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
