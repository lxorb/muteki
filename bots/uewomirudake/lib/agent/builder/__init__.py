from collections.abc import Callable

from cambc import Direction, EntityType, Environment, Position

from lib.agent import Agent
from lib.map import Map


BB_ACTION_RADIUS_SQ = 2


class BuilderAgent(Agent):
    def __init__(self, strategy_methods):
        super().__init__()
        self.strategy_methods = list(strategy_methods or [])
        self.last_executed_index = -1
        self.last_strategy_index = -1
        self.last_turn_completed = True
        self.bb_last_turn_completed = True

    # TODO
    def u_first_turn_init(self):
        self.map = Map(self.ct)
        # run the infer_strategy_by_spawning_tile
        self.first_turn_initialized = True

    def u_run(self):
        if not self.first_turn_initialized:
            self.u_first_turn_init()
        self.map.u_update_vision()
        self.u_handler()

    def u_handler(self):
        return self.u_execute_strategy()

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

    def u_filter_tiles(
        self,
        positions: list[Position],
        *predicates: Callable[[Position], bool],
    ) -> list[Position]:
        filtered_positions = list(positions)
        for predicate in predicates:
            filtered_positions = [
                pos for pos in filtered_positions if predicate(pos)
            ]
        return filtered_positions

    def u_prioritize_tiles(
        self,
        positions: list[Position],
        *criteria: Callable[[Position], object],
    ) -> list[Position]:
        if not criteria:
            return list(positions)
        return sorted(
            positions,
            key=lambda pos: tuple(criterion(pos) for criterion in criteria),
        )

    def u_move_to(self, pos: Position) -> bool:
        current_pos = self.map.current_pos
        candidate_moves: list[tuple[int, int, Direction]] = []
        current_distance_sq = current_pos.distance_squared(pos)
        for direction in Direction:
            if direction == Direction.CENTRE:
                continue
            if not self.ct.can_move(direction):
                continue
            next_pos = current_pos.add(direction)
            next_distance_sq = next_pos.distance_squared(pos)
            if next_distance_sq >= current_distance_sq:
                continue
            candidate_moves.append(
                (next_distance_sq, 0 if next_pos == pos else 1, direction)
            )

        if not candidate_moves:
            return False

        candidate_moves.sort(key=lambda move: move[:2])
        self.ct.move(candidate_moves[0][2])
        return True

    def u_build_at(
        self,
        pos: Position,
        building_type: EntityType,
        hold: bool,
        move_towards: bool,
        attack_enemy_passable: bool,
        facing_direction: Direction | None = None,
        target_pos: Position | None = None,
    ) -> bool:
        current_pos = self.map.current_pos
        target_tile = self.map.u_get_pos_tile(pos)

        titanium_cost, axionite_cost = getattr(
            self.ct, f"get_{building_type.value}_cost"
        )()
        affordable = (
            self.map.titanium >= titanium_cost and self.map.axionite >= axionite_cost
        )
        can_hold_build_target = (
            target_tile.building_id is None
            or (
                target_tile.building_type == EntityType.ROAD
                and target_tile.building_team == self.map.own_team
            )
            or (
                target_tile.building_type == EntityType.BARRIER
                and building_type != EntityType.BARRIER
            )
        )
        if hold and can_hold_build_target and not affordable:
            return True

        directional_buildings = {
            EntityType.CONVEYOR,
            EntityType.SPLITTER,
            EntityType.ARMOURED_CONVEYOR,
            EntityType.GUNNER,
            EntityType.SENTINEL,
            EntityType.BREACH,
        }
        nondirectional_buildings = {
            EntityType.HARVESTER,
            EntityType.ROAD,
            EntityType.BARRIER,
            EntityType.FOUNDRY,
            EntityType.LAUNCHER,
        }

        if current_pos.distance_squared(pos) <= BB_ACTION_RADIUS_SQ and pos != current_pos:
            if (
                target_tile.building_type == EntityType.ROAD
                and target_tile.building_team == self.map.own_team
                and self.ct.can_destroy(pos)
            ):
                self.ct.destroy(pos)
                return True

            if affordable:
                can_build_method = getattr(self.ct, f"can_build_{building_type.value}")
                build_method = getattr(self.ct, f"build_{building_type.value}")
                if building_type in directional_buildings:
                    if facing_direction is None:
                        return False
                    if not can_build_method(pos, facing_direction):
                        return False
                    build_method(pos, facing_direction)
                    return True

                if building_type == EntityType.BRIDGE:
                    if target_pos is None:
                        return False
                    if not can_build_method(pos, target_pos):
                        return False
                    build_method(pos, target_pos)
                    return True

                if building_type in nondirectional_buildings:
                    if not can_build_method(pos):
                        return False
                    build_method(pos)
                    return True

                raise ValueError(f"Unsupported builder target type: {building_type}")

        if (
            attack_enemy_passable
            and target_tile.is_passable
            and target_tile.building_team != self.map.own_team
            and pos == current_pos
            and self.ct.can_fire(current_pos)
        ):
            self.ct.fire(current_pos)
            return True

        if not move_towards:
            return False
        return self.u_move_to(pos)

    def s_build_harvester_supply_link(
        self, move_towards: bool = True, hold: bool = True
    ):
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

    def s_build_missing_supply_link(
        self,
        move_towards: bool = True,
        hold: bool = True,
        destroy_enemy_tile: bool = True,
    ):
        """
        The goal of this method is to ensure complete supply chains.
        Basically, if there is some tile known to be pointed at by a conveyor or bridge but the tile itself
        is not a core tile, nor an own supply link tile itself, then we want to build a supply link
        at that location. This will then probably result in a new tile flagged as missing supply link resulting
        in a chain-like behaviour till we reach the core with our supply link chain

        """

    def s_build_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
        destroy_enemy_tile: bool = True,
        resource: Environment = Environment.ORE_TITANIUM,
    ):
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

    def s_sentinel_next_to_enemy_harvester(
        self,
        move_towards: bool = True,
        attack_enemy_passable: bool = False,
        hold: bool = False,
    ):
        """
        Build a sentinel next to the closest visible enemy harvester.

        Prefer nearby empty tiles, own roads, and optionally passable enemy tiles.
        If `move_towards` is false, only act on targets already in action range.
        If `hold` is true, keep the step active once a valid build target exists
        but the team cannot yet afford the sentinel.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team

        enemy_harvesters = self.map.enemy_harvesters_in_sight
        if not enemy_harvesters:
            return False

        tile_kind_by_pos: dict[Position, str | None] = {}

        def get_tile_kind(pos: Position) -> str | None:
            if pos not in tile_kind_by_pos:
                candidate_tile = self.map.u_get_pos_tile(pos)
                if candidate_tile.building_id is None:
                    tile_kind_by_pos[pos] = (
                        "empty"
                        if candidate_tile.environment == Environment.EMPTY
                        else None
                    )
                elif (
                    candidate_tile.building_type == EntityType.ROAD
                    and candidate_tile.building_team == own_team
                ):
                    tile_kind_by_pos[pos] = "own_road"
                elif (
                    attack_enemy_passable
                    and candidate_tile.building_team != own_team
                    and candidate_tile.is_passable
                ):
                    tile_kind_by_pos[pos] = "enemy_passable"
                else:
                    tile_kind_by_pos[pos] = None
            return tile_kind_by_pos[pos]

        candidate_positions: list[Position] = []
        for harvester_pos in enemy_harvesters:
            for candidate_pos in self.map.u_iter_adjacent_positions(harvester_pos):
                candidate_positions.append(candidate_pos)

        candidate_positions = list(dict.fromkeys(candidate_positions))
        candidate_positions = self.u_filter_tiles(
            candidate_positions,
            lambda pos: self.map.u_get_pos_tile(pos).in_vision_radius,
            lambda pos: (
                self.map.u_get_pos_tile(pos).builder_bot_id is None
                or pos == current_pos
            ),
            lambda pos: get_tile_kind(pos) is not None,
        )
        if not candidate_positions:
            return False

        candidate_positions = self.u_prioritize_tiles(
            candidate_positions,
            lambda pos: current_pos.distance_squared(pos),
            lambda pos: (
                0
                if get_tile_kind(pos) == "empty"
                else 1 if get_tile_kind(pos) == "own_road" else 2
            ),
        )
        for candidate_pos in candidate_positions:
            sentinel_direction = self.u_get_sentinel_orientation(candidate_pos)
            if self.u_build_at(
                candidate_pos,
                EntityType.SENTINEL,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=attack_enemy_passable,
                facing_direction=sentinel_direction,
            ):
                return True

        return False

    def s_block_enemy_supply_chain(self, move_towards: bool = True, hold: bool = True):
        """
        Build a barrier on the closest visible enemy resource target.

        Uses cached map targets, prefers shorter squared distance, and
        delegates build, attack, movement, and hold handling to `u_build_at`.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team

        enemy_supply_targets = self.u_filter_tiles(
            list(dict.fromkeys(self.map.enemy_supply_targets_in_vision)),
            lambda pos: (
                self.map.u_get_pos_tile(pos).building_id is None
                or (
                    self.map.u_get_pos_tile(pos).building_type == EntityType.ROAD
                    and self.map.u_get_pos_tile(pos).building_team == own_team
                )
            ),
        )
        if not enemy_supply_targets:
            return False

        enemy_supply_targets = self.u_prioritize_tiles(
            enemy_supply_targets,
            lambda pos: current_pos.distance_squared(pos),
            lambda pos: 0 if self.map.u_get_pos_tile(pos).building_id is None else 1,
        )
        for target_pos in enemy_supply_targets:
            if self.u_build_at(
                target_pos,
                EntityType.BARRIER,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=True,
            ):
                return True

        return False

    def s_block_titanium(self, move_towards: bool = True, hold: bool = True):
        """
        Build a barrier on the closest known empty titanium tile.

        Uses cached titanium targets from the map, ranks them by squared
        distance, and delegates build, movement, and hold handling to
        `u_build_at`.
        """
        current_pos = self.map.current_pos

        titanium_targets = self.u_filter_tiles(
            list(dict.fromkeys(self.map.known_accessible_titanium_tiles)),
            lambda pos: (
                self.map.u_get_pos_tile(pos).environment == Environment.ORE_TITANIUM
            ),
            lambda pos: self.map.u_get_pos_tile(pos).building_id is None,
        )
        if not titanium_targets:
            return False

        titanium_targets = self.u_prioritize_tiles(
            titanium_targets,
            lambda pos: current_pos.distance_squared(pos),
        )
        for target_pos in titanium_targets:
            if self.u_build_at(
                target_pos,
                EntityType.BARRIER,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=False,
            ):
                return True

        return False

    def s_attack_enemy_harvester_supply_link(self, move_towards: bool = True):
        """
        Attack the closest enemy supply link next to a visible enemy harvester.

        Uses cached enemy harvester positions, keeps only adjacent enemy
        conveyor or bridge tiles that the builder can stand on, and then either
        attacks from the current tile or moves toward the best target.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team

        candidate_positions: list[Position] = []
        for harvester_pos in self.map.enemy_harvesters_in_sight:
            for candidate_pos in self.map.u_iter_adjacent_positions(harvester_pos):
                candidate_positions.append(candidate_pos)

        candidate_positions = list(dict.fromkeys(candidate_positions))
        candidate_positions = self.u_filter_tiles(
            candidate_positions,
            lambda pos: self.map.u_get_pos_tile(pos).in_vision_radius,
            lambda pos: self.map.u_get_pos_tile(pos).building_team != own_team,
            lambda pos: self.map.u_get_pos_tile(pos).building_type
            in {EntityType.CONVEYOR, EntityType.BRIDGE},
            lambda pos: self.map.u_get_pos_tile(pos).is_passable,
        )
        if not candidate_positions:
            return False

        candidate_positions = self.u_prioritize_tiles(
            candidate_positions,
            lambda pos: current_pos.distance_squared(pos),
        )

        for target_pos in candidate_positions:
            if target_pos != current_pos:
                continue
            if not self.ct.can_fire(current_pos):
                continue
            self.ct.fire(current_pos)
            return True

        if not move_towards:
            return False

        for target_pos in candidate_positions:
            if self.u_move_to(target_pos):
                return True

        return False

    # TODO
    def s_attack_enemy_core_supply_link(self, move_towards: bool = True):
        """
        This makes the builder bot attack a conveyor or bridge that is pointing
        to the enemy core.
        If the bot is already standing on a bridge or conveyor that is pointing to the enemy core, attack it.
        If this hit would destroy that tile, only attack it if it is not in action radius of an enemy bot.
        Use a method of the map to get all orthogonally adjacent fields to the enemy core in vision range.
        Filter out all that are not supplier tiles or that don't target the enemy core.
        Also filter out all that are in the range of enemy launchers or enemy turrets that have ammo.
        Then pick the one with the lowest distance.
        """


INITIAL_RES_STRATEGY = [
    (BuilderAgent.s_build_harvester, True, True, True, Environment.ORE_TITANIUM),
    (BuilderAgent.s_harvester_launcher, True, True),
    (BuilderAgent.s_harvester_barrier, True, True),
    (BuilderAgent.s_build_missing_supply_link, True, True, True),
    (BuilderAgent.s_build_harvester, True, True, True, Environment.ORE_TITANIUM),
    (BuilderAgent.s_expand,),
]

SCAVENGER_STRATEGY = [
    (BuilderAgent.s_destroy_hijacked_supply_link, True),
    (BuilderAgent.s_build_harvester_supply_link, True, True),
    (BuilderAgent.s_harvester_launcher, True, True),
    (BuilderAgent.s_harvester_barrier, True, True),
    (BuilderAgent.s_build_missing_supply_link, True, True, True),
    (BuilderAgent.s_sentinel_next_to_enemy_harvester, True, False, False),
    (BuilderAgent.s_build_harvester, True, True, True, Environment.ORE_TITANIUM),
    (BuilderAgent.s_expand,),
]

HARASSMENT_STRATEGY = [
    (BuilderAgent.s_sentinel_next_to_enemy_harvester, True, True, True),
    (BuilderAgent.s_block_enemy_supply_chain, True, True),
    (BuilderAgent.s_block_titanium, True),
    (BuilderAgent.s_attack_enemy_harvester_supply_link, True),
    (BuilderAgent.s_attack_enemy_core_supply_link, True),
]

# TODO
FOUNDRY_STRATEGY = [
    # INSERT SPLITTER
    # BUILD FOUNDRY (next to splitter)
    # BUILD AXIONITE HARVESTER SUPPLY LINK
    (BuilderAgent.s_harvester_barrier, True, True),
    # BUILD MISSING AXIONITE SUPPLY LINK
    # BUILD AXIONITE HARVESTER
    # SCOUT (search for axionite)
]

# TODO
# SHOULD PATROL SUPPLY CHAINS AND REBUILD
# THINGS DESTROYED BY THE ENEMY
DEFENDER_STRATEGY = []
