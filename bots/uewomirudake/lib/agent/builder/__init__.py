from collections.abc import Callable

from cambc import Direction, EntityType, Environment, GameConstants, Position

from lib.agent import Agent
from lib.map import Map


BB_ACTION_RADIUS_SQ = 2
BRIDGE_PREFERRED_DIST = 5
CHOKEPOINT_MIN_DIST_INCREASE = 4


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

    def u_infer_strategy_by_spawning_tile(self):
        # there should be a constant declared somewhere that
        # assigns each of the nine core tiles
        # a builder bot strategy that should be executed then
        pass

    def u_run(self):
        if not self.first_turn_initialized:
            self.u_first_turn_init()
        self.map.u_update_vision()
        self.u_handler()

    def u_handler(self):
        return self.u_execute_strategy()

    def u_get_sentinel_orientation(self, pos: Position) -> Direction:
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

    def u_is_chokepoint(
        self,
        pos: Position,
        min_dist_increase: int = CHOKEPOINT_MIN_DIST_INCREASE,
    ) -> bool:
        pass

    def u_get_supplier_build_plan(
        self,
        pos: Position,
    ) -> tuple[EntityType | None, Direction | Position | None]:
        """
        Return the supplier type to build at one tile plus its chosen target.

        Delegates candidate selection to the conveyor- and bridge-planning map
        helpers. If both plans exist, prefer the bridge only when it skips at
        least `BRIDGE_PREFERRED_DIST` cached core-distance steps.
        """
        conveyor_direction = self.map.u_best_conveyor_orientation(pos)
        bridge_target = self.map.u_best_bridge_target(pos)

        if conveyor_direction is None and bridge_target is None:
            return (None, None)
        if conveyor_direction is None:
            return (EntityType.BRIDGE, bridge_target)
        if bridge_target is None:
            return (EntityType.CONVEYOR, conveyor_direction)

        source_tile = self.map.u_get_pos_tile(pos)
        bridge_target_tile = self.map.u_get_pos_tile(bridge_target)
        bridge_dist_covered = (
            source_tile.own_core_dist - bridge_target_tile.own_core_dist
        )
        if bridge_dist_covered >= BRIDGE_PREFERRED_DIST:
            return (EntityType.BRIDGE, bridge_target)
        return (EntityType.CONVEYOR, conveyor_direction)

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

    def u_is_enemy_turret_target_tile(self, pos: Position) -> bool:
        target_tile = self.map.u_get_pos_tile(pos)
        return (
            target_tile.in_enemy_attack_range
            or target_tile.in_enemy_launcher_pickup_zone
        )

    def u_move_to(
        self,
        pos: Position,
        avoid_enemy_turrets: bool = True,
    ) -> bool:
        current_pos = self.map.current_pos
        candidate_moves: list[tuple[int, int, Direction]] = []
        current_distance_sq = current_pos.distance_squared(pos)
        for direction in Direction:
            if direction == Direction.CENTRE:
                continue
            if not self.ct.can_move(direction):
                continue
            next_pos = current_pos.add(direction)
            if (
                avoid_enemy_turrets
                and self.u_is_enemy_turret_target_tile(next_pos)
            ):
                continue
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

    def u_attack_passable(
        self,
        pos: Position,
        move_towards: bool,
        destroy_condition: Callable[[Position], bool] | None = None,
        avoid_enemy_turrets: bool = True,
    ) -> bool:
        current_pos = self.map.current_pos
        target_tile = self.map.u_get_pos_tile(pos)

        if current_pos == pos:
            if target_tile.building_id is None:
                return False
            if not self.ct.can_fire(current_pos):
                return False

            would_destroy = (
                self.ct.get_hp(target_tile.building_id)
                <= GameConstants.BUILDER_BOT_ATTACK_DAMAGE
            )
            if (
                would_destroy
                and destroy_condition is not None
                and not destroy_condition(pos)
            ):
                return False

            self.ct.fire(current_pos)
            return True

        if not move_towards:
            return False
        return self.u_move_to(
            pos,
            avoid_enemy_turrets=avoid_enemy_turrets,
        )

    def u_build_at(
        self,
        pos: Position,
        building_type: EntityType,
        hold: bool,
        move_towards: bool,
        attack_enemy_passable: bool,
        facing_direction: Direction | None = None,
        target_pos: Position | None = None,
        avoid_enemy_turrets: bool = True,
    ) -> bool:
        current_pos = self.map.current_pos
        target_tile = self.map.u_get_pos_tile(pos)

        if (
            avoid_enemy_turrets
            and self.u_is_enemy_turret_target_tile(pos)
        ):
            return False

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
                target_tile.building_team == self.map.own_team
                and target_tile.building_type in {EntityType.ROAD, EntityType.BARRIER}
                and target_tile.building_type != building_type
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
        ):
            return self.u_attack_passable(
                pos,
                move_towards=False,
                destroy_condition=lambda _: True,
                avoid_enemy_turrets=avoid_enemy_turrets,
            )

        if not move_towards:
            return False
        return self.u_move_to(
            pos,
            avoid_enemy_turrets=avoid_enemy_turrets,
        )

    def s_build_harvester_supply_link(
        self, move_towards: bool = True, hold: bool = True
    ):
        """
        Build the best missing supplier next to a visible own harvester.

        Skips harvesters that already have an adjacent own supplier, keeps one
        valid adjacent placement tile per remaining harvester by cached core
        distance, then prioritizes those tiles by squared distance to the
        builder and the own core. The supplier type and target are chosen by
        `u_get_supplier_build_plan(...)`.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team
        attack_enemy_passable = False
        supplier_plan_by_pos: dict[
            Position, tuple[EntityType | None, Direction | Position | None]
        ] = {}

        def is_own_supply_link(pos: Position) -> bool:
            target_tile = self.map.u_get_pos_tile(pos)
            return (
                target_tile.building_team == own_team
                and target_tile.building_type
                in {EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER}
            )

        def can_use_tile(pos: Position) -> bool:
            target_tile = self.map.u_get_pos_tile(pos)
            if target_tile.is_core_tile:
                return False
            if target_tile.building_id is None:
                return True
            return (
                target_tile.building_team == own_team
                and target_tile.building_type in {EntityType.ROAD, EntityType.BARRIER}
            )

        def has_supplier_plan(pos: Position) -> bool:
            if pos not in supplier_plan_by_pos:
                supplier_plan_by_pos[pos] = self.u_get_supplier_build_plan(pos)
            return supplier_plan_by_pos[pos][0] is not None

        candidate_positions: list[Position] = []
        for harvester_pos in self.map.own_harvesters_in_sight:
            adjacent_positions = [
                pos
                for pos in self.map.u_iter_adjacent_positions(harvester_pos)
                if not self.u_is_enemy_turret_target_tile(pos)
            ]
            if any(is_own_supply_link(pos) for pos in adjacent_positions):
                continue

            adjacent_positions = self.u_filter_tiles(
                adjacent_positions,
                can_use_tile,
                has_supplier_plan,
            )
            if not adjacent_positions:
                continue

            adjacent_positions = self.u_prioritize_tiles(
                adjacent_positions,
                lambda pos: self.map.u_get_pos_tile(pos).own_core_dist,
                lambda pos: current_pos.distance_squared(pos),
            )
            candidate_positions.append(adjacent_positions[0])

        if not candidate_positions:
            return False

        candidate_positions = self.u_prioritize_tiles(
            list(dict.fromkeys(candidate_positions)),
            lambda pos: current_pos.distance_squared(pos),
            lambda pos: self.map.u_get_pos_tile(pos).own_core_dist,
        )
        for target_pos in candidate_positions:
            supplier_type, supplier_target = supplier_plan_by_pos[target_pos]
            if supplier_type == EntityType.CONVEYOR:
                if self.u_build_at(
                    target_pos,
                    supplier_type,
                    hold=hold,
                    move_towards=move_towards,
                    attack_enemy_passable=attack_enemy_passable,
                    facing_direction=supplier_target,
                ):
                    return True
            elif supplier_type == EntityType.BRIDGE:
                if self.u_build_at(
                    target_pos,
                    supplier_type,
                    hold=hold,
                    move_towards=move_towards,
                    attack_enemy_passable=attack_enemy_passable,
                    target_pos=supplier_target,
                ):
                    return True

        return False

    def s_surround_harvester(self, move_towards: bool = True, hold: bool = True):
        """
        Secure visible own harvesters with nearby barriers.

        Considers empty or own-road tiles adjacent to visible own harvesters,
        prioritizes them by squared distance to the builder, and builds a
        barrier unless the tile is a chokepoint, in which case it tries to
        place a conveyor using the cached supplier-plan helper instead.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team
        conveyor_plan_by_pos: dict[Position, Direction | None] = {}

        def can_use_tile(pos: Position) -> bool:
            target_tile = self.map.u_get_pos_tile(pos)
            return target_tile.building_id is None or (
                target_tile.building_team == own_team
                and target_tile.building_type == EntityType.ROAD
            )

        def is_reachable_chokepoint_plan(pos: Position) -> bool:
            if not self.u_is_chokepoint(pos):
                return True
            if pos not in conveyor_plan_by_pos:
                conveyor_direction = self.map.u_best_conveyor_orientation(pos)
                conveyor_plan_by_pos[pos] = conveyor_direction
            return conveyor_plan_by_pos[pos] is not None

        candidate_positions: list[Position] = []
        for harvester_pos in self.map.own_harvesters_in_sight:
            for candidate_pos in self.map.u_iter_adjacent_positions(harvester_pos):
                candidate_positions.append(candidate_pos)

        candidate_positions = self.u_filter_tiles(
            list(dict.fromkeys(candidate_positions)),
            lambda pos: not self.u_is_enemy_turret_target_tile(pos),
            can_use_tile,
            is_reachable_chokepoint_plan,
        )
        if not candidate_positions:
            return False

        candidate_positions = self.u_prioritize_tiles(
            candidate_positions,
            lambda pos: current_pos.distance_squared(pos),
            lambda pos: 0 if self.map.u_get_pos_tile(pos).building_id is None else 1,
        )
        for target_pos in candidate_positions:
            if self.u_is_chokepoint(target_pos):
                conveyor_direction = conveyor_plan_by_pos[target_pos]
                if conveyor_direction is None:
                    continue
                if self.u_build_at(
                    target_pos,
                    EntityType.CONVEYOR,
                    hold=hold,
                    move_towards=move_towards,
                    attack_enemy_passable=False,
                    facing_direction=conveyor_direction,
                ):
                    return True
                continue

            if self.u_build_at(
                target_pos,
                EntityType.BARRIER,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=False,
            ):
                return True

        return False

    def s_build_missing_supply_link(
        self,
        move_towards: bool = True,
        hold: bool = True,
        attack_enemy_passable: bool = True,
    ):
        """
        Fill the highest-priority cached supply-link gap.

        Uses cached missing-link positions, keeps tiles that can host a new
        supplier, prioritizes gaps closer to the core and then the builder, and
        relies on the supplier-plan helper to choose whether the tile should
        become a conveyor or a bridge plus its optimal target.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team

        def can_use_tile(pos: Position) -> bool:
            target_tile = self.map.u_get_pos_tile(pos)
            if target_tile.is_core_tile:
                return False
            if target_tile.building_id is None:
                return True
            if (
                target_tile.building_team == own_team
                and target_tile.building_type in {EntityType.ROAD, EntityType.BARRIER}
            ):
                return True
            return (
                attack_enemy_passable
                and target_tile.building_team != own_team
                and target_tile.is_passable
            )

        candidate_positions = self.u_filter_tiles(
            list(dict.fromkeys(self.map.known_missing_supply_links)),
            can_use_tile,
        )
        if not candidate_positions:
            return False

        candidate_positions = self.u_prioritize_tiles(
            candidate_positions,
            lambda pos: self.map.u_get_pos_tile(pos).own_core_dist,
            lambda pos: current_pos.distance_squared(pos),
        )

        for target_pos in candidate_positions:
            supplier_type, supplier_target = self.u_get_supplier_build_plan(target_pos)
            if supplier_type is None:
                continue
            if supplier_type == EntityType.CONVEYOR:
                if self.u_build_at(
                    target_pos,
                    supplier_type,
                    hold=hold,
                    move_towards=move_towards,
                    attack_enemy_passable=attack_enemy_passable,
                    facing_direction=supplier_target,
                ):
                    return True
            elif supplier_type == EntityType.BRIDGE:
                if self.u_build_at(
                    target_pos,
                    supplier_type,
                    hold=hold,
                    move_towards=move_towards,
                    attack_enemy_passable=attack_enemy_passable,
                    target_pos=supplier_target,
                ):
                    return True

        return False

    def s_build_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
        attack_enemy_passable: bool = True,
        resource: Environment = Environment.ORE_TITANIUM,
    ):
        """
        Build a harvester on the safest high-priority visible ore tile.

        Uses the cached accessible ore list for the requested resource, skips
        tiles in enemy attack range or next to orthogonally adjacent enemy
        buildings, prioritizes by squared distance to the own core and then the
        builder, and delegates the actual build, replacement, movement, hold,
        and optional enemy-passable clearing to `u_build_at`.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team
        core_center_pos = self.map.core_center_pos
        if resource == Environment.ORE_TITANIUM:
            ore_positions = self.map.known_accessible_titanium_tiles
        elif resource == Environment.ORE_AXIONITE:
            ore_positions = self.map.known_accessible_axionite_tiles
        else:
            return False

        def has_orthogonally_adjacent_enemy_building(pos: Position) -> bool:
            adjacent_positions = self.map.u_iter_adjacent_positions(
                pos,
                consider_diagonal=False,
            )
            for adjacent_pos in adjacent_positions:
                adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
                if (
                    adjacent_tile.building_id is not None
                    and adjacent_tile.building_team != own_team
                ):
                    return True
            return False

        def can_use_tile(pos: Position) -> bool:
            target_tile = self.map.u_get_pos_tile(pos)
            if target_tile.building_id is None:
                return True
            if (
                target_tile.building_team == own_team
                and target_tile.building_type in {EntityType.ROAD, EntityType.BARRIER}
            ):
                return True
            return (
                attack_enemy_passable
                and target_tile.building_team != own_team
                and target_tile.is_passable
            )

        candidate_positions = self.u_filter_tiles(
            list(dict.fromkeys(ore_positions)),
            lambda pos: self.map.u_get_pos_tile(pos).environment == resource,
            can_use_tile,
            lambda pos: not self.map.u_get_pos_tile(pos).in_enemy_attack_range,
            lambda pos: not has_orthogonally_adjacent_enemy_building(pos),
        )
        if not candidate_positions:
            return False

        candidate_positions = self.u_prioritize_tiles(
            candidate_positions,
            lambda pos: (
                core_center_pos.distance_squared(pos)
                if core_center_pos is not None
                else 10**9
            ),
            lambda pos: current_pos.distance_squared(pos),
        )
        for target_pos in candidate_positions:
            if self.u_build_at(
                target_pos,
                EntityType.HARVESTER,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=attack_enemy_passable,
            ):
                return True

        return False

    def s_expand(self):
        """
        This will be the lowest priority method for scavenger builder bots.
        The purpose of this method is that they explore new area to potentially find new resources.
        # TODO: come up with a nice system for expansion / scouting
        """

    def s_destroy_hijacked_supplier(self, move_towards: bool = True):
        """
        Destroy the closest visible own harvester or supply-link tile that
        feeds an enemy turret.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team

        def points_at_enemy_turret(pos: Position) -> bool:
            source_tile = self.map.u_get_pos_tile(pos)
            target_pos = source_tile.resource_target
            if target_pos is None:
                return False
            target_tile = self.map.u_get_pos_tile(target_pos)
            return (
                target_tile.building_id is not None
                and target_tile.building_team != own_team
                and target_tile.building_type
                in {EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH}
            )

        candidate_positions = self.u_filter_tiles(
            list(
                dict.fromkeys(
                    self.map.own_supply_links_in_sight
                    + self.map.own_harvesters_in_sight
                )
            ),
            lambda pos: self.map.u_get_pos_tile(pos).building_team == own_team,
            lambda pos: self.map.u_get_pos_tile(pos).building_type
            in {
                EntityType.CONVEYOR,
                EntityType.BRIDGE,
                EntityType.SPLITTER,
                EntityType.HARVESTER,
            },
            points_at_enemy_turret,
        )
        if not candidate_positions:
            return False

        candidate_positions = self.u_prioritize_tiles(
            candidate_positions,
            lambda pos: current_pos.distance_squared(pos),
        )
        for target_pos in candidate_positions:
            if (
                current_pos.distance_squared(target_pos) <= BB_ACTION_RADIUS_SQ
                and self.ct.can_destroy(target_pos)
            ):
                self.ct.destroy(target_pos)
                return True
            if move_towards and self.u_move_to(target_pos):
                return True

        return False

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
            if self.u_attack_passable(
                target_pos,
                move_towards=move_towards,
                destroy_condition=lambda _: True,
            ):
                return True

        return False

    def s_attack_enemy_core_supply_link(self, move_towards: bool = True):
        """
        Attack the closest visible enemy supply link that directly feeds the enemy core.

        Uses cached enemy supply targets, filters to enemy conveyor or bridge
        tiles targeting the known enemy core and outside cached enemy threat
        zones, then either attacks from the current tile or moves toward the
        best remaining target.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team
        enemy_core_pos = self.map.enemy_core_center_pos
        if enemy_core_pos is None:
            return False

        candidate_positions = list(dict.fromkeys(self.map.enemy_supply_targets_in_vision))
        candidate_positions = self.u_filter_tiles(
            candidate_positions,
            lambda pos: self.map.u_get_pos_tile(pos).in_vision_radius,
            lambda pos: self.map.u_get_pos_tile(pos).building_team != own_team,
            lambda pos: self.map.u_get_pos_tile(pos).building_type
            in {EntityType.CONVEYOR, EntityType.BRIDGE},
            lambda pos: self.map.u_get_pos_tile(pos).resource_target == enemy_core_pos,
            lambda pos: not self.map.u_get_pos_tile(pos).in_enemy_launcher_pickup_zone,
            lambda pos: not self.map.u_get_pos_tile(pos).in_enemy_attack_range,
        )
        if not candidate_positions:
            return False

        candidate_positions = self.u_prioritize_tiles(
            candidate_positions,
            lambda pos: current_pos.distance_squared(pos),
        )

        for target_pos in candidate_positions:
            if self.u_attack_passable(
                target_pos,
                move_towards=move_towards,
                destroy_condition=lambda pos: (
                    not self.map.u_get_pos_tile(pos).is_in_enemy_bot_action_range
                ),
            ):
                return True

        return False


INITRES_STRATEGY = [
    (BuilderAgent.s_build_harvester, True, True, True, Environment.ORE_TITANIUM),
    (BuilderAgent.s_surround_harvester, True, True),
    (BuilderAgent.s_build_missing_supply_link, True, True, True),
    (BuilderAgent.s_build_harvester, True, True, True, Environment.ORE_TITANIUM),
    (BuilderAgent.s_expand,),
]

SCAVENGER_STRATEGY = [
    (BuilderAgent.s_destroy_hijacked_supplier, True),
    (BuilderAgent.s_build_harvester_supply_link, True, True),
    (BuilderAgent.s_surround_harvester, True, True),
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
    (BuilderAgent.s_surround_harvester, True, True),
    # BUILD MISSING AXIONITE SUPPLY LINK
    # BUILD AXIONITE HARVESTER
    # SCOUT (search for axionite)
]

# TODO
# SHOULD PATROL SUPPLY CHAINS AND REBUILD
# THINGS DESTROYED BY THE ENEMY
DEFENDER_STRATEGY = []
