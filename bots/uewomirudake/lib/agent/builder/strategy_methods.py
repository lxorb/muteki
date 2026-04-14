from heapq import heapify, heappop
import time

from cambc import Direction, EntityType, Environment, GameConstants, Position

from lib.agent.constants import (
    AXIONITE_HARVESTER_MIN_TITANIUM,
    AXIONITE_HARVESTER_MIN_TURN,
    BUILDER_ACTION_RADIUS_SQ,
    CONVEYOR_ENTITY_TYPES,
    DEFENDER_STRATEGY_ID,
    DISABLE_CONVEYORS_POINTING_AT_HARVESTERS,
    FOUNDRY_CAN_REPLACE_BRIDGE,
    HARVESTERS_BUILT_BEFORE_CONVERT_TO_DEFENDER,
    MAX_CORE_ORE_DIRECT_DIST,
    PREVENT_SUPPLY_LINKS_TILL_HARVESTER,
    SCAVENGER_STRATEGY_ID,
    SURROUND_HARVESTER_ENTITY_TYPE,
)
from lib.map.constants import INF_DIST, SUPPLY_LINK_TYPES
from lib.map.types import SupplyChainLabel

_ENEMY_CORE_PATROL_OFFSETS = (
    (-2, -2),
    (-1, -2),
    (0, -2),
    (1, -2),
    (2, -2),
    (2, -1),
    (2, 0),
    (2, 1),
    (2, 2),
    (1, 2),
    (0, 2),
    (-1, 2),
    (-2, 2),
    (-2, 1),
    (-2, 0),
    (-2, -1),
)


class BuilderStrategyMethodsMixin:
    def s_integrate_foundry_passing_splitter(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ):
        own_team = self.map.own_team
        current_round = self.map.current_round
        current_pos = self.map.current_pos
        candidate_entries: list[tuple[tuple[int, int, int], Position, Direction]] = []

        def get_opposite_direction(direction: Direction) -> Direction:
            return (
                direction.rotate_left()
                .rotate_left()
                .rotate_left()
                .rotate_left()
            )

        def iter_hypothetical_splitter_targets(pos: Position, direction: Direction):
            for output_direction in (
                direction,
                direction.rotate_left().rotate_left(),
                direction.rotate_right().rotate_right(),
            ):
                target_idx = self.map.u_get_neighbor_index_by_direction(
                    self.map.u_to_index(pos),
                    output_direction,
                )
                if target_idx is None:
                    yield None
                    continue
                yield self.map.tiles_by_index[target_idx]

        for tile in self.map.own_supply_links_in_vision:
            if tile.last_seen_turn != current_round:
                continue
            if tile.building.team != own_team:
                continue
            if tile.building.entity_type not in CONVEYOR_ENTITY_TYPES:
                continue
            if tile.bot.id is not None and tile.position != current_pos:
                continue

            facing_direction = tile.building.direction
            if facing_direction is None or facing_direction == Direction.CENTRE:
                continue

            adjacent_foundry_tiles = []
            for adjacent_pos in self.map.u_iter_adjacent_cardinal_positions(tile.position):
                adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
                if (
                    adjacent_tile.last_seen_turn == current_round
                    and adjacent_tile.building.team == own_team
                    and adjacent_tile.building.entity_type == EntityType.FOUNDRY
                ):
                    adjacent_foundry_tiles.append(adjacent_tile)

            if not adjacent_foundry_tiles:
                continue

            valid_passing_foundry = None
            for foundry_tile in adjacent_foundry_tiles:
                direction_to_foundry = self.map.u_get_direction_between(
                    tile.position,
                    foundry_tile.position,
                )
                if direction_to_foundry is None or direction_to_foundry == Direction.CENTRE:
                    continue
                if facing_direction == direction_to_foundry:
                    continue
                if facing_direction == get_opposite_direction(direction_to_foundry):
                    continue

                splitter_targets = list(
                    iter_hypothetical_splitter_targets(tile.position, facing_direction)
                )
                if any(target_tile is None for target_tile in splitter_targets):
                    continue

                valid_outputs = True
                foundry_reached = False
                for target_tile in splitter_targets:
                    assert target_tile is not None
                    if target_tile.index == foundry_tile.index:
                        foundry_reached = True
                        continue
                    if not (
                        target_tile.building.team == own_team
                        and target_tile.building.entity_type
                        in CONVEYOR_ENTITY_TYPES | {EntityType.BRIDGE}
                    ):
                        valid_outputs = False
                        break

                if valid_outputs and foundry_reached:
                    valid_passing_foundry = foundry_tile
                    break

            if valid_passing_foundry is None:
                continue

            candidate_entries.append(
                (
                    (
                        tile.dist_to_self,
                        tile.own_core_dist,
                        tile.index,
                    ),
                    tile.position,
                    facing_direction,
                )
            )

            if self.round_stopwatch.check_overtime():
                break

        if not candidate_entries:
            return False

        _, target_pos, facing_direction = min(candidate_entries, key=lambda item: item[0])
        target_tile = self.map.u_get_pos_tile(target_pos)
        titanium_cost, axionite_cost = self.ct.get_splitter_cost()
        can_afford_splitter = (
            self.map.titanium >= titanium_cost and self.map.axionite >= axionite_cost
        )
        if not can_afford_splitter:
            return False

        if (
            current_pos.distance_squared(target_pos) <= BUILDER_ACTION_RADIUS_SQ
            and self.ct.can_destroy(target_pos)
        ):
            self.ct.destroy(target_pos)
            target_tile.clear_building()
            if self.ct.can_build_splitter(target_pos, facing_direction):
                self.ct.build_splitter(target_pos, facing_direction)
                self.last_built_entity_type = EntityType.SPLITTER
                return True
            return False

        if move_towards and self.u_move_to_astar(target_pos):
            return True
        if hold and current_pos.distance_squared(target_pos) <= BUILDER_ACTION_RADIUS_SQ:
            return True
        return False

    def s_swap_with_splitter(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ):
        own_team = self.map.own_team
        current_round = self.map.current_round
        candidate_entries: list[tuple[tuple[int, int, int], Position, Direction]] = []

        for tile in self.map.own_supply_links_in_vision:
            if tile.last_seen_turn != current_round:
                continue
            if tile.building.team != own_team:
                continue
            if tile.building.entity_type not in CONVEYOR_ENTITY_TYPES:
                continue
            if tile.bot.id is not None and tile.position != self.map.current_pos:
                continue

            foundry_targets = [
                target_tile
                for target_tile in tile.building.targets
                if (
                    target_tile.last_seen_turn == current_round
                    and target_tile.building.team == own_team
                    and target_tile.building.entity_type == EntityType.FOUNDRY
                )
            ]
            if not foundry_targets:
                continue

            facing_direction = tile.building.direction
            if facing_direction is None or facing_direction == Direction.CENTRE:
                continue

            candidate_entries.append(
                (
                    (
                        tile.dist_to_self,
                        tile.own_core_dist,
                        tile.index,
                    ),
                    tile.position,
                    facing_direction,
                )
            )

            if self.round_stopwatch.check_overtime():
                break

        if not candidate_entries:
            return False

        _, target_pos, facing_direction = min(candidate_entries, key=lambda item: item[0])
        target_tile = self.map.u_get_pos_tile(target_pos)
        titanium_cost, axionite_cost = self.ct.get_splitter_cost()
        can_afford_splitter = (
            self.map.titanium >= titanium_cost and self.map.axionite >= axionite_cost
        )
        if (
            target_tile.building.team == own_team
            and target_tile.building.entity_type in CONVEYOR_ENTITY_TYPES
        ):
            if not can_afford_splitter:
                if (
                    hold
                    and self.map.current_pos.distance_squared(target_pos)
                    <= BUILDER_ACTION_RADIUS_SQ
                ):
                    return True
                if move_towards and self.u_move_to_astar(target_pos):
                    return True
                return False
            if (
                self.map.current_pos.distance_squared(target_pos) <= BUILDER_ACTION_RADIUS_SQ
                and self.ct.can_destroy(target_pos)
            ):
                self.ct.destroy(target_pos)
                target_tile.clear_building()
                if self.ct.can_build_splitter(target_pos, facing_direction):
                    self.ct.build_splitter(target_pos, facing_direction)
                    self.last_built_entity_type = EntityType.SPLITTER
                    return True
                return False

            if move_towards and self.u_move_to_astar(target_pos):
                return True
            return False

        if (
            target_tile.building.team == own_team
            and target_tile.building.entity_type == EntityType.SPLITTER
            and target_tile.building.direction == facing_direction
        ):
            return False

        return bool(
            self.u_build_at(
                target_pos,
                EntityType.SPLITTER,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=False,
                facing_direction=facing_direction,
            )
        )

    def s_integrate_foundry(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ):
        own_team = self.map.own_team
        current_round = self.map.current_round
        current_pos = self.map.current_pos
        mixed_root_by_index: dict[int, int] = {}
        mixed_supply_tiles = []
        incoming_count_by_index: dict[int, int] = {}
        replaceable_supply_types = set(SUPPLY_LINK_TYPES)
        if not FOUNDRY_CAN_REPLACE_BRIDGE:
            replaceable_supply_types.discard(EntityType.BRIDGE)

        for tile in self.map.own_supply_links_in_vision:
            if tile.last_seen_turn != current_round:
                continue
            if tile.building.team != own_team:
                continue
            if (
                tile.building.entity_type not in SUPPLY_LINK_TYPES
                or tile.building.entity_type == EntityType.SPLITTER
            ):
                continue

            root = self.map.u_get_supply_chain_id_by_index(tile.index, own_team)
            if root is None:
                continue
            if not (
                self.map.u_supply_chain_has_titanium(tile.index, own_team)
                and self.map.u_supply_chain_has_raw_axionite(tile.index, own_team)
            ):
                continue

            mixed_root_by_index[tile.index] = root
            mixed_supply_tiles.append(tile)

            if self.round_stopwatch.check_overtime():
                break

        if not mixed_supply_tiles:
            return False

        for tile in mixed_supply_tiles:
            root = mixed_root_by_index[tile.index]
            for target_tile in tile.building.targets:
                if (
                    target_tile.last_seen_turn == current_round
                    and target_tile.building.team == own_team
                    and target_tile.building.entity_type in SUPPLY_LINK_TYPES
                    and target_tile.building.entity_type != EntityType.SPLITTER
                    and mixed_root_by_index.get(target_tile.index) == root
                ):
                    incoming_count_by_index[target_tile.index] = (
                        incoming_count_by_index.get(target_tile.index, 0) + 1
                    )

            if self.round_stopwatch.check_overtime():
                break

        candidate_entries: list[tuple[tuple[int, int, int, int], Position]] = []
        for tile in mixed_supply_tiles:
            if incoming_count_by_index.get(tile.index, 0) <= 1:
                continue
            if len(tile.building.targets) != 1:
                continue

            target_tile = tile.building.targets[0]
            if target_tile.is_core_of(own_team):
                continue
            if (
                target_tile.building.team == own_team
                and target_tile.building.entity_type == EntityType.HARVESTER
            ):
                continue

            candidate_entries.append(
                (
                    (
                        -tile.own_core_dist,
                        target_tile.dist_to_self,
                        target_tile.own_core_dist,
                        target_tile.index,
                    ),
                    target_tile.position,
                )
            )

            if self.round_stopwatch.check_overtime():
                break

        if not candidate_entries:
            return False

        for _, target_pos in sorted(candidate_entries, key=lambda item: item[0]):
            target_tile = self.map.u_get_pos_tile(target_pos)
            if (
                target_tile.building.team == own_team
                and target_tile.building.entity_type == EntityType.FOUNDRY
            ):
                continue

            titanium_cost, axionite_cost = self.ct.get_foundry_cost()
            affordable = (
                self.map.titanium >= titanium_cost and self.map.axionite >= axionite_cost
            )
            if (
                target_tile.building.team == own_team
                and target_tile.building.entity_type in replaceable_supply_types
            ):
                if not affordable:
                    if (
                        hold
                        and current_pos.distance_squared(target_pos)
                        <= BUILDER_ACTION_RADIUS_SQ
                    ):
                        return True
                    if not hold or not move_towards:
                        continue
                    if self.u_move_to_astar(target_pos):
                        return True
                    continue

                if (
                    current_pos.distance_squared(target_pos) <= BUILDER_ACTION_RADIUS_SQ
                    and self.ct.can_destroy(target_pos)
                ):
                    self.ct.destroy(target_pos)
                    target_tile.clear_building()
                    if self.ct.can_build_foundry(target_pos):
                        self.ct.build_foundry(target_pos)
                        self.last_built_entity_type = EntityType.FOUNDRY
                        return True
                    return False
                if move_towards and self.u_move_to_astar(target_pos):
                    return True
                continue

            if self.u_build_at(
                target_pos,
                EntityType.FOUNDRY,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=False,
            ):
                return True

            if self.round_stopwatch.check_overtime():
                break

        return False

    def u_get_harvester_adjacent_supplier_build_plan(
        self,
        harvester_tile,
        target_tile,
        resource: Environment,
        use_all_own_supply_link_targets_in_vision: bool = False,
    ) -> tuple[EntityType | None, Direction | Position | None]:
        """
        Return the supplier plan for a tile directly adjacent to `harvester_tile`.

        Exactly one adjacent tile, chosen by
        `map.u_get_harvester_best_supply_tile(...)`, is allowed to become the
        transport lane. Every other adjacent tile becomes a defensive conveyor
        that points back into the harvester.
        """
        if DISABLE_CONVEYORS_POINTING_AT_HARVESTERS:
            return self.u_get_transport_supplier_build_plan(
                target_tile.position,
                resource,
            )

        best_supply_idx = self.map.u_get_harvester_best_supply_tile(harvester_tile.index)
        if target_tile.index == best_supply_idx:
            return self.u_get_transport_supplier_build_plan(
                target_tile.position,
                resource,
            )

        own_supply_link_target_indices_in_vision = (
            self.map.all_own_supply_link_target_indices_in_vision
            if use_all_own_supply_link_targets_in_vision
            else self.map.own_supply_link_target_indices_in_vision
        )
        if target_tile.index in own_supply_link_target_indices_in_vision:
            return self.u_get_transport_supplier_build_plan(
                target_tile.position,
                resource,
            )

        facing_direction = self.map.u_get_direction_between(
            target_tile.position,
            harvester_tile.position,
        )
        if facing_direction is None:
            return (None, None)
        return (EntityType.CONVEYOR, facing_direction)

    def s_heal_self(self):
        """
        Heal this builder when its HP drops to the low-health threshold.
        """
        current_tile = self.map.u_get_pos_tile(self.map.current_pos)
        if current_tile.bot.id is None or current_tile.bot.hp is None:
            return False
        if current_tile.bot.hp > 16:
            return False
        return bool(self.u_heal_at(current_tile.position, move_towards=False))

    def s_convert_to_defender(self):
        if self.harvesters_built < HARVESTERS_BUILT_BEFORE_CONVERT_TO_DEFENDER:
            return False

        if self.strategy == DEFENDER_STRATEGY_ID:
            return False

        self.strategy = DEFENDER_STRATEGY_ID
        self.last_strategy_index = -1
        self.last_turn_completed = True
        return True

    # DEPRECATED: kept only for legacy strategy compatibility.
    def s_build_harvester_supply_link(
        self,
        move_towards: bool = True,
        hold: bool = True,
        resource: Environment = Environment.ORE_TITANIUM,
    ):
        """
        DEPRECATED.

        Build the best missing supplier next to a visible own harvester for
        `resource`.

        Skips harvesters that already have an adjacent compatible own supplier,
        keeps one valid adjacent placement tile per remaining harvester by
        cached core distance, then prioritizes those tiles by squared distance
        to the builder and the own core. The supplier type and target are
        chosen by `u_get_supplier_build_plan(...)`.
        """
        if PREVENT_SUPPLY_LINKS_TILL_HARVESTER and self.harvesters_built == 0:
            return False

        own_team = self.map.own_team
        attack_enemy_passable = False
        max_core_ore_direct_dist = (
            MAX_CORE_ORE_DIRECT_DIST if self.strategy == SCAVENGER_STRATEGY_ID else None
        )
        supply_chain_label = self.u_get_supply_chain_label_for_resource(resource)
        if supply_chain_label == SupplyChainLabel.NONE:
            return False
        tiles_by_index = self.map.tiles_by_index
        replaceable_building_types = {EntityType.ROAD, EntityType.BARRIER}
        supplier_plan_by_index: dict[
            int, tuple[EntityType | None, Direction | Position | None]
        ] = {}
        candidate_entries: list[tuple[tuple[int, int], int, int]] = []
        candidate_seen_indices: set[int] = set()

        def get_supplier_plan(
            tile_index: int,
        ) -> tuple[EntityType | None, Direction | Position | None]:
            if tile_index not in supplier_plan_by_index:
                supplier_plan_by_index[tile_index] = self.u_get_supplier_build_plan(
                    tiles_by_index[tile_index].position,
                    resource,
                )
            return supplier_plan_by_index[tile_index]

        for harvester_order, harvester_tile in enumerate(
            self.map.own_harvesters_in_vision
        ):
            if self.round_stopwatch.check_overtime():
                break
            if harvester_tile.environment != resource:
                continue
            if (
                max_core_ore_direct_dist is not None
                and harvester_tile.own_core_dist > max_core_ore_direct_dist
            ):
                continue

            adjacent_tiles = []
            has_own_supply_link = False

            for safe_order, adjacent_idx in enumerate(
                self.map.u_iter_cardinal_neighbor_indices(harvester_tile.index)
            ):
                adjacent_tile = tiles_by_index[adjacent_idx]
                if adjacent_tile.is_enemy_turret_target_tile:
                    continue
                adjacent_label = adjacent_tile.own_supply_chain_label
                if (
                    adjacent_tile.building.team == own_team
                    and adjacent_tile.building.entity_type in SUPPLY_LINK_TYPES
                    and adjacent_label & supply_chain_label
                ):
                    has_own_supply_link = True
                adjacent_tiles.append((safe_order, adjacent_tile))

            if has_own_supply_link or not adjacent_tiles:
                continue

            while adjacent_tiles:
                best_idx: int | None = None
                best_priority: tuple[int, int, int] | None = None

                for idx, (safe_order, target_tile) in enumerate(adjacent_tiles):
                    if target_tile.building.entity_type == EntityType.CORE:
                        continue
                    if target_tile.building.id is not None and not (
                        target_tile.building.team == own_team
                        and target_tile.building.entity_type
                        in replaceable_building_types
                    ):
                        continue

                    priority = (
                        target_tile.own_core_dist,
                        target_tile.dist_to_self,
                        safe_order,
                    )
                    if best_priority is None or priority < best_priority:
                        best_priority = priority
                        best_idx = idx

                if best_idx is None:
                    break

                _, target_tile = adjacent_tiles.pop(best_idx)
                supplier_type, _ = get_supplier_plan(target_tile.index)
                if supplier_type is None:
                    continue

                if target_tile.index not in candidate_seen_indices:
                    candidate_seen_indices.add(target_tile.index)
                    candidate_entries.append(
                        (
                            (target_tile.dist_to_self, target_tile.own_core_dist),
                            harvester_order,
                            target_tile.index,
                        )
                    )
                break

        if not candidate_entries:
            return False

        heapify(candidate_entries)
        while candidate_entries:
            _, _, target_idx = heappop(candidate_entries)
            target_tile = tiles_by_index[target_idx]
            supplier_type, supplier_target = supplier_plan_by_index[target_idx]
            if supplier_type in CONVEYOR_ENTITY_TYPES:
                if self.u_build_at(
                    target_tile.position,
                    supplier_type,
                    hold=hold,
                    move_towards=move_towards,
                    attack_enemy_passable=attack_enemy_passable,
                    facing_direction=supplier_target,
                ):
                    return True
            elif supplier_type == EntityType.BRIDGE:
                if self.u_build_at(
                    target_tile.position,
                    supplier_type,
                    hold=hold,
                    move_towards=move_towards,
                    attack_enemy_passable=attack_enemy_passable,
                    target_pos=supplier_target,
                ):
                    return True

            if self.round_stopwatch.check_overtime():
                break

        return False

    def s_surround_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
        resource: Environment = Environment.ORE_TITANIUM,
    ):
        current_pos = self.map.current_pos
        current_tile = self.map.u_get_pos_tile(current_pos)
        if current_tile.environment != resource:
            return False
        if (
            self.strategy == SCAVENGER_STRATEGY_ID
            and current_tile.own_core_dist > MAX_CORE_ORE_DIRECT_DIST
        ):
            return False

        empty_adjacent_tiles = []
        for adjacent_pos in self.map.u_iter_adjacent_cardinal_positions(
            current_pos,
        ):
            adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
            if (
                adjacent_tile.building.id is None
                and adjacent_tile.environment != Environment.WALL
            ):
                empty_adjacent_tiles.append(adjacent_tile)

        if not empty_adjacent_tiles:
            return False

        for target_tile in empty_adjacent_tiles:
            facing_direction = self.u_best_conveyor_orientation(
                target_tile.position,
                resource,
                surround_target_pos=current_pos,
            )
            if facing_direction is None:
                continue
            if self.u_build_at(
                target_tile.position,
                SURROUND_HARVESTER_ENTITY_TYPE,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=False,
                facing_direction=facing_direction,
            ):
                return True

        return False

    def s_protect_own_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ):
        total_start_ns = time.perf_counter_ns()
        map = self.map
        own_team = map.own_team
        current_round = map.current_round
        tiles_by_index = map.tiles_by_index
        all_own_supply_link_target_indices_in_vision = (
            map.all_own_supply_link_target_indices_in_vision
        )
        candidate_entries: list[
            tuple[
                tuple[int, int, int, int, int],
                int,
                int,
                Environment,
                bool,
                bool,
                Direction | None,
            ]
        ] = []
        harvester_best_supply_idx_by_index: dict[int, int | None] = {}
        harvester_order_by_index: dict[int, int] = {}
        resource_harvester_tiles = []

        def elapsed_ms(start_ns: int) -> float:
            return (time.perf_counter_ns() - start_ns) / 1_000_000

        candidate_scan_start_ns = time.perf_counter_ns()
        for harvester_order, harvester_tile in enumerate(map.own_harvesters_in_vision):
            if harvester_tile.last_seen_turn != current_round:
                continue

            resource = harvester_tile.environment
            if resource not in {Environment.ORE_TITANIUM, Environment.ORE_AXIONITE}:
                continue

            harvester_idx = harvester_tile.index
            preferred_idx = map.u_get_harvester_best_supply_tile(
                harvester_idx
            )
            harvester_best_supply_idx_by_index[harvester_idx] = preferred_idx
            harvester_order_by_index[harvester_idx] = harvester_order
            resource_harvester_tiles.append(harvester_tile)

            if self.round_stopwatch.check_overtime():
                break

        for harvester_tile in resource_harvester_tiles:
            harvester_idx = harvester_tile.index
            harvester_order = harvester_order_by_index[harvester_idx]
            preferred_idx = harvester_best_supply_idx_by_index.get(
                harvester_tile.index
            )
            force_point_at_harvester = False
            best_empty_tile = None
            best_empty_key = None
            best_empty_direction_to_harvester = None

            for safe_order, adjacent_idx in enumerate(
                map.u_iter_cardinal_neighbor_indices(harvester_idx)
            ):
                adjacent_tile = tiles_by_index[adjacent_idx]
                building = adjacent_tile.building
                building_type = building.entity_type

                if (
                    building.team == own_team
                    and building_type == EntityType.BRIDGE
                ):
                    force_point_at_harvester = True

                if (
                    building.team == own_team
                    and building_type in CONVEYOR_ENTITY_TYPES
                    and not any(
                        target.index == harvester_idx
                        for target in building.targets
                    )
                ):
                    force_point_at_harvester = True

                if adjacent_tile.environment == Environment.WALL:
                    continue
                if adjacent_tile.is_enemy_turret_target_tile:
                    continue
                if adjacent_tile.building.id is not None:
                    continue

                empty_key = (
                    0 if adjacent_idx == preferred_idx else 1,
                    adjacent_tile.own_core_dist,
                    adjacent_tile.dist_to_self,
                    safe_order,
                    adjacent_idx,
                )
                if best_empty_key is None or empty_key < best_empty_key:
                    best_empty_key = empty_key
                    best_empty_tile = adjacent_tile
                    best_empty_direction_to_harvester = map.u_get_direction_between(
                        adjacent_tile.position,
                        harvester_tile.position,
                    )

            if best_empty_tile is None:
                continue

            target_idx = best_empty_tile.index
            target_tile_is_resource = best_empty_tile.environment in {
                Environment.ORE_TITANIUM,
                Environment.ORE_AXIONITE,
            }
            should_build_harvester = False
            if target_tile_is_resource:
                has_empty_adjacent_tile = False
                is_best_supplier_tile_for_any_adjacent_harvester = False
                for adjacent_idx in map.u_iter_cardinal_neighbor_indices(target_idx):
                    adjacent_tile = tiles_by_index[adjacent_idx]
                    if (
                        not has_empty_adjacent_tile
                        and adjacent_tile.environment != Environment.WALL
                        and adjacent_tile.building.id is None
                    ):
                        has_empty_adjacent_tile = True
                    if (
                        not is_best_supplier_tile_for_any_adjacent_harvester
                        and adjacent_tile.building.team == own_team
                        and adjacent_tile.building.entity_type == EntityType.HARVESTER
                        and harvester_best_supply_idx_by_index.get(adjacent_tile.index)
                        == target_idx
                    ):
                        is_best_supplier_tile_for_any_adjacent_harvester = True
                    if (
                        has_empty_adjacent_tile
                        and is_best_supplier_tile_for_any_adjacent_harvester
                    ):
                        break

                should_build_harvester = (
                    not has_empty_adjacent_tile
                    and not is_best_supplier_tile_for_any_adjacent_harvester
                )

            needs_transport_supplier_plan = (
                target_idx == preferred_idx
                or target_idx in all_own_supply_link_target_indices_in_vision
            )
            candidate_entries.append(
                (
                    (
                        best_empty_tile.dist_to_self,
                        best_empty_tile.own_core_dist,
                        harvester_order,
                        0 if force_point_at_harvester else 1,
                        best_empty_tile.index,
                    ),
                    harvester_idx,
                    target_idx,
                    harvester_tile.environment,
                    should_build_harvester,
                    needs_transport_supplier_plan,
                    best_empty_direction_to_harvester,
                )
            )

            if self.round_stopwatch.check_overtime():
                break

        print(
            "Protect harvester timing: candidate scan",
            f"{elapsed_ms(candidate_scan_start_ns):.3f} ms,",
            "candidates",
            len(candidate_entries),
        )
        if not candidate_entries:
            print(
                "Protect harvester timing: total",
                f"{elapsed_ms(total_start_ns):.3f} ms",
            )
            return False

        sort_start_ns = time.perf_counter_ns()
        candidate_entries.sort(key=lambda entry: entry[0])
        print(
            "Protect harvester timing: sort",
            f"{elapsed_ms(sort_start_ns):.3f} ms",
        )
        for (
            _priority_key,
            harvester_idx,
            target_idx,
            resource,
            should_build_harvester,
            needs_transport_supplier_plan,
            harvester_direction,
        ) in candidate_entries:
            candidate_start_ns = time.perf_counter_ns()
            harvester_tile = tiles_by_index[harvester_idx]
            target_tile = tiles_by_index[target_idx]
            print(
                "Protect harvester timing: trying candidate",
                harvester_tile.position,
                "via",
                target_tile.position,
            )

            resource_tile_check_start_ns = time.perf_counter_ns()
            if (
                target_tile.environment in {
                    Environment.ORE_TITANIUM,
                    Environment.ORE_AXIONITE,
                }
                and should_build_harvester
            ):
                print(
                    "Protect harvester timing: resource-tile check",
                    f"{elapsed_ms(resource_tile_check_start_ns):.3f} ms",
                )
                build_start_ns = time.perf_counter_ns()
                if self.u_build_at(
                    target_tile.position,
                    EntityType.HARVESTER,
                    hold=hold,
                    move_towards=move_towards,
                    attack_enemy_passable=False,
                ):
                    print(
                        "Protect harvester timing: harvester build_at",
                        f"{elapsed_ms(build_start_ns):.3f} ms",
                    )
                    print(
                        "Protect harvester timing: candidate total",
                        f"{elapsed_ms(candidate_start_ns):.3f} ms",
                    )
                    print(
                        "Protect harvester timing: total",
                        f"{elapsed_ms(total_start_ns):.3f} ms",
                    )
                    return True
                print(
                    "Protect harvester timing: harvester build_at",
                    f"{elapsed_ms(build_start_ns):.3f} ms",
                )
                if self.round_stopwatch.check_overtime():
                    break
                continue
            print(
                "Protect harvester timing: resource-tile check",
                f"{elapsed_ms(resource_tile_check_start_ns):.3f} ms",
            )

            supplier_plan_start_ns = time.perf_counter_ns()
            if needs_transport_supplier_plan:
                supplier_type, supplier_target = self.u_get_transport_supplier_build_plan(
                    target_tile.position,
                    resource,
                )
            else:
                supplier_type, supplier_target = (
                    EntityType.CONVEYOR,
                    harvester_direction,
                )
            print(
                "Protect harvester timing: supplier plan",
                f"{elapsed_ms(supplier_plan_start_ns):.3f} ms",
            )
            if supplier_type is None or supplier_target is None:
                if self.round_stopwatch.check_overtime():
                    break
                continue

            if supplier_type in CONVEYOR_ENTITY_TYPES:
                retarget_start_ns = time.perf_counter_ns()
                if (
                    needs_transport_supplier_plan
                    and harvester_direction is not None
                    and supplier_target == harvester_direction
                    and target_idx in all_own_supply_link_target_indices_in_vision
                ):
                    supplier_target = self.u_best_conveyor_orientation(
                        target_tile.position,
                        resource,
                        allow_adjacent_resource_sink=False,
                    )
                    if supplier_target is None:
                        if self.round_stopwatch.check_overtime():
                            break
                        continue
                print(
                    "Protect harvester timing: conveyor retarget",
                    f"{elapsed_ms(retarget_start_ns):.3f} ms",
                )

                build_start_ns = time.perf_counter_ns()
                if self.u_build_at(
                    target_tile.position,
                    supplier_type,
                    hold=hold,
                    move_towards=move_towards,
                    attack_enemy_passable=False,
                    facing_direction=supplier_target,
                ):
                    print(
                        "Protect harvester timing: conveyor build_at",
                        f"{elapsed_ms(build_start_ns):.3f} ms",
                    )
                    print(
                        "Protect harvester timing: candidate total",
                        f"{elapsed_ms(candidate_start_ns):.3f} ms",
                    )
                    print(
                        "Protect harvester timing: total",
                        f"{elapsed_ms(total_start_ns):.3f} ms",
                    )
                    return True
                print(
                    "Protect harvester timing: conveyor build_at",
                    f"{elapsed_ms(build_start_ns):.3f} ms",
                )
            elif supplier_type == EntityType.BRIDGE:
                build_start_ns = time.perf_counter_ns()
                if self.u_build_at(
                    target_tile.position,
                    supplier_type,
                    hold=hold,
                    move_towards=move_towards,
                    attack_enemy_passable=False,
                    target_pos=supplier_target,
                ):
                    print(
                        "Protect harvester timing: bridge build_at",
                        f"{elapsed_ms(build_start_ns):.3f} ms",
                    )
                    print(
                        "Protect harvester timing: candidate total",
                        f"{elapsed_ms(candidate_start_ns):.3f} ms",
                    )
                    print(
                        "Protect harvester timing: total",
                        f"{elapsed_ms(total_start_ns):.3f} ms",
                    )
                    return True
                print(
                    "Protect harvester timing: bridge build_at",
                    f"{elapsed_ms(build_start_ns):.3f} ms",
                )

            print(
                "Protect harvester timing: candidate total",
                f"{elapsed_ms(candidate_start_ns):.3f} ms",
            )

            if self.round_stopwatch.check_overtime():
                break

        print(
            "Protect harvester timing: total",
            f"{elapsed_ms(total_start_ns):.3f} ms",
        )
        return False

    def s_build_missing_supply_link(
        self,
        move_towards: bool = True,
        hold: bool = True,
        attack_enemy_passable: bool = True,
    ):
        """
        Fill the highest-priority cached supply-link gap for either resource.

        Uses cached missing-link positions plus any builder-local pending gap
        target, keeps tiles that can host a new supplier, filters to the
        relevant supply chain(s), prioritizes gaps closer to the core and then
        the builder, and relies on the transport supplier planner to choose
        whether the tile should become a conveyor or a bridge plus its optimal
        target for the inferred resource.
        """
        if PREVENT_SUPPLY_LINKS_TILL_HARVESTER and self.harvesters_built == 0:
            return False

        own_team = self.map.own_team
        tiles_by_index = self.map.tiles_by_index
        get_own_core_dist = self.map.u_get_own_core_dist_by_index
        current_round = self.map.current_round

        def can_use_tile(target_tile) -> bool:
            if target_tile.environment == Environment.WALL:
                return False
            if target_tile.building.entity_type == EntityType.CORE:
                return False
            if target_tile.building.id is None:
                return True
            if (
                target_tile.building.team == own_team
                and target_tile.building.entity_type
                in {EntityType.ROAD, EntityType.BARRIER}
            ):
                return True
            return (
                attack_enemy_passable
                and target_tile.building.team != own_team
                and target_tile.is_passable
            )

        def clear_pending_target() -> None:
            self.pending_missing_supply_link_index = None
            self.pending_missing_supply_link_resource = None

        def u_get_candidate_resources(
            target_tile,
            supply_chain_label: SupplyChainLabel,
        ) -> list[Environment]:
            resources: list[Environment] = []
            if (
                target_tile.environment == Environment.ORE_AXIONITE
                and supply_chain_label & SupplyChainLabel.AXIONITE
            ):
                resources.append(Environment.ORE_AXIONITE)
            if supply_chain_label & SupplyChainLabel.TITANIUM:
                resources.append(Environment.ORE_TITANIUM)
            if (
                supply_chain_label & SupplyChainLabel.AXIONITE
                and Environment.ORE_AXIONITE not in resources
            ):
                resources.append(Environment.ORE_AXIONITE)
            if not resources:
                resources.append(
                    Environment.ORE_AXIONITE
                    if target_tile.environment == Environment.ORE_AXIONITE
                    else Environment.ORE_TITANIUM
                )
            return resources

        candidate_entries: list[tuple[tuple[int, int], int, int, int]] = []
        candidate_seen_indices: set[int] = set()
        pending_target_idx: int | None = None
        pending_resource = self.pending_missing_supply_link_resource
        if pending_resource is not None:
            pending_target_idx = self.pending_missing_supply_link_index

        if pending_target_idx is not None:
            pending_target_tile = tiles_by_index[pending_target_idx]
            if (
                pending_target_tile.last_seen_turn == current_round
                and not can_use_tile(pending_target_tile)
            ):
                clear_pending_target()
                pending_target_idx = None

        if pending_target_idx is not None:
            pending_target_tile = tiles_by_index[pending_target_idx]
            if can_use_tile(pending_target_tile):
                candidate_seen_indices.add(pending_target_idx)
                pending_label = (
                    self.u_get_supply_chain_label_for_resource(pending_resource)
                    if pending_resource is not None
                    else pending_target_tile.own_supply_chain_label
                )
                candidate_entries.append(
                    ((-1, -1), -1, pending_target_idx, int(pending_label))
                )

        for encounter_order, target_tile in enumerate(
            self.map.own_missing_supply_links
        ):
            if self.round_stopwatch.check_overtime():
                break
            target_label = target_tile.own_supply_chain_label
            if target_label == SupplyChainLabel.NONE:
                continue
            if not can_use_tile(target_tile):
                continue

            target_idx = target_tile.index
            if target_idx in candidate_seen_indices:
                continue
            candidate_seen_indices.add(target_idx)
            candidate_entries.append(
                (
                    (
                        get_own_core_dist(target_idx),
                        self.map.u_get_estimated_dist_to_self_by_index(target_idx),
                    ),
                    encounter_order,
                    target_idx,
                    int(target_label),
                )
            )

        splitter_encounter_order = len(candidate_entries)
        for splitter_tile in self.map.own_supply_links_in_vision:
            if self.round_stopwatch.check_overtime():
                break
            if (
                splitter_tile.building.team != own_team
                or splitter_tile.building.entity_type != EntityType.SPLITTER
                or splitter_tile.own_supply_chain_label == SupplyChainLabel.NONE
            ):
                continue

            for target_tile in splitter_tile.building.targets:
                if target_tile.last_seen_turn != current_round:
                    continue
                if not (
                    target_tile.building.id is None
                    or (
                        target_tile.building.team == own_team
                        and target_tile.building.entity_type
                        in {EntityType.ROAD, EntityType.BARRIER}
                    )
                ):
                    continue
                if not can_use_tile(target_tile):
                    continue

                target_idx = target_tile.index
                if target_idx in candidate_seen_indices:
                    continue
                candidate_seen_indices.add(target_idx)
                candidate_entries.append(
                    (
                        (
                            get_own_core_dist(target_idx),
                            self.map.u_get_estimated_dist_to_self_by_index(target_idx),
                        ),
                        splitter_encounter_order,
                        target_idx,
                        int(splitter_tile.own_supply_chain_label),
                    )
                )
                splitter_encounter_order += 1

        if not candidate_entries:
            return False

        attempted_target_positions: list[Position] = []
        heapify(candidate_entries)
        while candidate_entries:
            _, _, target_idx, target_label = heappop(candidate_entries)
            target_tile = tiles_by_index[target_idx]
            attempted_target_positions.append(target_tile.position)
            for resource in u_get_candidate_resources(
                target_tile,
                SupplyChainLabel(target_label),
            ):
                supplier_type, supplier_target = self.u_get_transport_supplier_build_plan(
                    target_tile.position,
                    resource,
                )
                if supplier_type is None or supplier_target is None:
                    continue
                if supplier_type in CONVEYOR_ENTITY_TYPES:
                    if self.u_build_at(
                        target_tile.position,
                        supplier_type,
                        hold=hold,
                        move_towards=move_towards,
                        attack_enemy_passable=attack_enemy_passable,
                        facing_direction=supplier_target,
                    ):
                        self.pending_missing_supply_link_index = target_idx
                        self.pending_missing_supply_link_resource = resource
                        return True
                elif supplier_type == EntityType.BRIDGE:
                    if self.u_build_at(
                        target_tile.position,
                        supplier_type,
                        hold=hold,
                        move_towards=move_towards,
                        attack_enemy_passable=attack_enemy_passable,
                        target_pos=supplier_target,
                    ):
                        self.pending_missing_supply_link_index = target_idx
                        self.pending_missing_supply_link_resource = resource
                        return True

            if self.round_stopwatch.check_overtime():
                break

        if not candidate_entries and attempted_target_positions:
            print(
                "Build missing supply link: no valid conveyor or bridge for",
                attempted_target_positions,
            )
        return False

    def s_build_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
        attack_enemy_passable: bool = True,
        resource: Environment = Environment.ORE_TITANIUM,
        enforce_safe: bool = False,
        require_connected: bool = False,
    ):
        """
        Build a harvester on the safest high-priority visible ore tile.

        Uses the cached accessible ore list for the requested resource, skips
        tiles in enemy attack range or next to orthogonally adjacent enemy
        buildings, prioritizes by cached distance to the own core and then the
        builder, and delegates the actual build, replacement, movement, hold,
        and optional enemy-passable clearing to `u_build_at`. With
        `enforce_safe=True`, the builder first tries to close any orthogonally
        adjacent empty tiles around the target ore and otherwise moves onto the
        ore tile before allowing the harvester build. With
        `require_connected=True`, only ore tiles that already have at least one
        orthogonally adjacent own supply-link tile are considered.
        """

        current_pos = self.map.current_pos
        if (
            resource == Environment.ORE_AXIONITE
            and (
                self.map.current_round < AXIONITE_HARVESTER_MIN_TURN
                or self.map.titanium < AXIONITE_HARVESTER_MIN_TITANIUM
            )
        ):
            return False
        if (
            self.pending_missing_supply_link_index is not None
            and self.pending_missing_supply_link_resource == resource
        ):
            return False
        max_core_ore_direct_dist = (
            MAX_CORE_ORE_DIRECT_DIST if self.strategy == SCAVENGER_STRATEGY_ID else None
        )

        own_team = self.map.own_team
        if resource == Environment.ORE_TITANIUM:
            ore_indices = self.map.known_accessible_titanium_indices
        elif resource == Environment.ORE_AXIONITE:
            ore_indices = self.map.known_accessible_axionite_indices
        else:
            return False
        current_tile = self.map.u_get_pos_tile(current_pos)
        tiles_by_index = self.map.tiles_by_index

        def clear_pending_harvester_target() -> None:
            if self.pending_harvester_target_resource == resource:
                self.pending_harvester_target_index = None
                self.pending_harvester_target_resource = None

        def remember_pending_harvester_target(tile_index: int) -> None:
            self.pending_harvester_target_index = tile_index
            self.pending_harvester_target_resource = resource

        def finish_with_harvester_target(result: bool, harvester_tile) -> bool:
            if result:
                print("Build harvester strategy target:", harvester_tile.position)
            return result

        def has_orthogonally_adjacent_enemy_building(pos: Position) -> bool:
            adjacent_positions = self.map.u_iter_adjacent_cardinal_positions(
                pos,
            )
            for adjacent_pos in adjacent_positions:
                adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
                if (
                    adjacent_tile.building.id is not None
                    and adjacent_tile.building.team != own_team
                ):
                    return True
            return False

        def has_orthogonally_adjacent_supply_link(tile_index: int) -> bool:
            for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(tile_index):
                adjacent_tile = tiles_by_index[adjacent_idx]
                if adjacent_tile.building.entity_type in SUPPLY_LINK_TYPES:
                    return True
            return False

        def has_orthogonally_adjacent_own_supply_link(tile_index: int) -> bool:
            for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(tile_index):
                adjacent_tile = tiles_by_index[adjacent_idx]
                if (
                    adjacent_tile.building.team == own_team
                    and adjacent_tile.building.entity_type in SUPPLY_LINK_TYPES
                ):
                    return True
            return False

        def get_empty_orthogonally_adjacent_tiles(tile_index: int) -> list:
            empty_adjacent_tiles = []
            for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(tile_index):
                adjacent_tile = tiles_by_index[adjacent_idx]
                if (
                    adjacent_tile.building.id is None
                    and adjacent_tile.environment != Environment.WALL
                ):
                    empty_adjacent_tiles.append(adjacent_tile)
            return empty_adjacent_tiles

        def has_other_conveyor_pointing_at(tile_index: int) -> bool:
            for other_tile in self.map.own_supply_links_in_vision:
                if other_tile.building.team != own_team:
                    continue
                if other_tile.building.entity_type not in CONVEYOR_ENTITY_TYPES:
                    continue
                for target in other_tile.building.targets:
                    if target.index == tile_index:
                        return True
            return False

        def get_harvester_safety_build_plan(
            harvester_tile,
            adjacent_tile,
        ) -> tuple[EntityType | None, Direction | Position | None]:
            best_supply_idx = self.map.u_get_harvester_best_supply_tile(
                harvester_tile.index
            )
            is_best_supply_tile = adjacent_tile.index == best_supply_idx

            def get_non_bridge_transport_conveyor_plan():
                conveyor_direction = self.u_best_conveyor_orientation(
                    adjacent_tile.position,
                    resource,
                    allow_adjacent_resource_sink=False,
                )
                if conveyor_direction is None:
                    return (None, None)
                return (EntityType.CONVEYOR, conveyor_direction)

            if is_best_supply_tile:
                supplier_type, supplier_target = (
                    self.u_get_harvester_adjacent_supplier_build_plan(
                        harvester_tile,
                        adjacent_tile,
                        resource,
                    )
                )
            elif DISABLE_CONVEYORS_POINTING_AT_HARVESTERS:
                supplier_type, supplier_target = (
                    get_non_bridge_transport_conveyor_plan()
                )
            else:
                supplier_type, supplier_target = (
                    self.u_get_harvester_adjacent_supplier_build_plan(
                        harvester_tile,
                        adjacent_tile,
                        resource,
                    )
                )

            if not is_best_supply_tile and supplier_type == EntityType.BRIDGE:
                return get_non_bridge_transport_conveyor_plan()

            if supplier_type not in CONVEYOR_ENTITY_TYPES:
                return (supplier_type, supplier_target)
            if adjacent_tile.environment not in {
                Environment.ORE_TITANIUM,
                Environment.ORE_AXIONITE,
            }:
                return (supplier_type, supplier_target)

            harvester_direction = self.map.u_get_direction_between(
                adjacent_tile.position,
                harvester_tile.position,
            )
            if (
                harvester_direction is not None
                and supplier_target == harvester_direction
                and has_other_conveyor_pointing_at(adjacent_tile.index)
            ):
                supplier_type, supplier_target = (
                    self.u_get_harvester_adjacent_supplier_build_plan(
                        harvester_tile,
                        adjacent_tile,
                        resource,
                    )
                )
                if not is_best_supply_tile and supplier_type == EntityType.BRIDGE:
                    return get_non_bridge_transport_conveyor_plan()
                return (supplier_type, supplier_target)
            if harvester_direction is not None and supplier_target == harvester_direction:
                return (EntityType.BARRIER, None)
            return (supplier_type, supplier_target)

        def can_use_tile(target_tile) -> bool:
            if target_tile.building.id is None:
                return True
            if (
                target_tile.building.team == own_team
                and target_tile.building.entity_type
                in {EntityType.ROAD, EntityType.BARRIER}
            ):
                return True
            if (
                target_tile.building.team == own_team
                and target_tile.building.entity_type in CONVEYOR_ENTITY_TYPES
                and target_tile.conveyor_targets_harvester
            ):
                return True
            return (
                attack_enemy_passable
                and target_tile.building.team != own_team
                and target_tile.is_passable
            )

        def can_still_move() -> bool:
            for direction in Direction:
                if direction != Direction.CENTRE and self.ct.can_move(direction):
                    return True
            return False

        def get_discontinued_adjacent_supply_tile(harvester_tile):
            candidate_tile = None
            candidate_key = None

            for safe_order, adjacent_idx in enumerate(
                self.map.u_iter_cardinal_neighbor_indices(harvester_tile.index)
            ):
                adjacent_tile = tiles_by_index[adjacent_idx]
                if adjacent_tile.building.team != own_team:
                    continue
                if adjacent_tile.building.entity_type not in {
                    *CONVEYOR_ENTITY_TYPES,
                    EntityType.BRIDGE,
                }:
                    continue

                is_connected = False
                for output_tile in adjacent_tile.building.targets:
                    output_type = output_tile.building.entity_type
                    if output_tile.index == harvester_tile.index:
                        is_connected = True
                        break
                    if (
                        output_type in SUPPLY_LINK_TYPES
                        or output_type == EntityType.HARVESTER
                    ):
                        is_connected = True
                        break

                if is_connected:
                    continue

                key = (
                    0 if adjacent_tile.position == current_pos else 1,
                    current_pos.distance_squared(adjacent_tile.position),
                    safe_order,
                    adjacent_tile.index,
                )
                if candidate_key is None or key < candidate_key:
                    candidate_key = key
                    candidate_tile = adjacent_tile

            return candidate_tile

        def move_towards_tile(target_tile) -> bool:
            if target_tile is None:
                return False
            if current_pos == target_tile.position:
                return True

            move_direction = self.map.u_get_direction_between(
                current_pos,
                target_tile.position,
            )
            if move_direction is not None and self.ct.can_move(move_direction):
                self.u_move_with_target(move_direction, target_tile.position)
                return True

            current_distance_sq = current_pos.distance_squared(target_tile.position)
            best_direction = None
            best_key = None

            for direction_order, direction in enumerate(Direction):
                if direction == Direction.CENTRE or not self.ct.can_move(direction):
                    continue

                next_idx = self.map.u_get_neighbor_index_by_direction(
                    current_tile.index,
                    direction,
                )
                if next_idx is None:
                    continue

                next_tile = tiles_by_index[next_idx]
                next_distance_sq = next_tile.position.distance_squared(
                    target_tile.position
                )
                if next_distance_sq >= current_distance_sq:
                    continue

                key = (
                    next_distance_sq,
                    direction_order,
                )
                if best_key is None or key < best_key:
                    best_key = key
                    best_direction = direction

            if best_direction is None:
                return False

            self.u_move_with_target(best_direction, target_tile.position)
            return True

        def step_off_current_ore_tile() -> bool:
            candidate_entries: list[
                tuple[tuple[int, int, int, int, int], Direction]
            ] = []

            for safe_order, adjacent_pos in enumerate(
                self.map.u_iter_adjacent_cardinal_positions(
                    current_pos,
                )
            ):
                adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
                if adjacent_tile.is_enemy_turret_target_tile:
                    continue
                if adjacent_tile.bot.id is not None:
                    continue

                adjacent_building = adjacent_tile.building
                if (
                    adjacent_building.team == own_team
                    and adjacent_building.entity_type in SUPPLY_LINK_TYPES
                ):
                    walkable_rank = 0
                elif adjacent_building.entity_type == EntityType.CORE and (
                    adjacent_building.team == own_team
                ):
                    walkable_rank = 1
                elif (
                    adjacent_building.entity_type == EntityType.ROAD
                    and adjacent_building.team == own_team
                ):
                    walkable_rank = 2
                else:
                    continue

                move_direction = self.map.u_get_direction_between(
                    current_pos,
                    adjacent_pos,
                )
                if move_direction is None:
                    continue

                candidate_entries.append(
                    (
                        (
                            walkable_rank,
                            adjacent_tile.own_core_dist,
                            adjacent_tile.dist_to_self,
                            safe_order,
                            adjacent_tile.index,
                        ),
                        move_direction,
                    )
                )

            if not candidate_entries:
                return False
            _, move_direction = min(candidate_entries)
            if self.ct.can_move(move_direction):
                self.u_move_with_target(move_direction, current_pos)
                return True
            return hold

        def is_valid_harvester_target(target_tile) -> bool:
            if target_tile.environment != resource:
                return False
            if not can_use_tile(target_tile):
                return False
            if (
                require_connected
                and not has_orthogonally_adjacent_own_supply_link(target_tile.index)
            ):
                return False
            if target_tile.bot.id is not None and target_tile.position != current_pos:
                return False
            if target_tile.in_enemy_attack_range:
                return False
            if has_orthogonally_adjacent_enemy_building(target_tile.position):
                return False
            return not (
                max_core_ore_direct_dist is not None
                and target_tile.own_core_dist > max_core_ore_direct_dist
            )

        def try_progress_harvester_target(
            target_tile,
            require_surround: bool,
        ) -> bool:
            if require_surround:
                empty_adjacent_tiles = get_empty_orthogonally_adjacent_tiles(
                    target_tile.index
                )
                if empty_adjacent_tiles:
                    surround_candidates: list[tuple[tuple[int, int, int], object]] = []
                    for safe_order, adjacent_tile in enumerate(empty_adjacent_tiles):
                        if (
                            current_pos.distance_squared(adjacent_tile.position)
                            > BUILDER_ACTION_RADIUS_SQ
                        ):
                            continue
                        surround_candidates.append(
                            (
                                (
                                    adjacent_tile.own_core_dist,
                                    adjacent_tile.dist_to_self,
                                    safe_order,
                                ),
                                adjacent_tile,
                            )
                        )

                    if surround_candidates:
                        _, surround_tile = min(surround_candidates)
                        supplier_type, supplier_target = get_harvester_safety_build_plan(
                            target_tile,
                            surround_tile,
                        )
                        if supplier_type in CONVEYOR_ENTITY_TYPES:
                            if self.u_build_at(
                                surround_tile.position,
                                supplier_type,
                                hold=hold,
                                move_towards=move_towards,
                                attack_enemy_passable=False,
                                facing_direction=supplier_target,
                            ):
                                remember_pending_harvester_target(target_tile.index)
                                return finish_with_harvester_target(True, target_tile)
                        elif supplier_type == EntityType.BRIDGE:
                            if self.u_build_at(
                                surround_tile.position,
                                supplier_type,
                                hold=hold,
                                move_towards=move_towards,
                                attack_enemy_passable=False,
                                target_pos=supplier_target,
                            ):
                                remember_pending_harvester_target(target_tile.index)
                                return finish_with_harvester_target(True, target_tile)
                        elif supplier_type == EntityType.BARRIER:
                            if self.u_build_at(
                                surround_tile.position,
                                supplier_type,
                                hold=hold,
                                move_towards=move_towards,
                                attack_enemy_passable=False,
                            ):
                                remember_pending_harvester_target(target_tile.index)
                                return finish_with_harvester_target(True, target_tile)

                    if current_pos != target_tile.position:
                        if not move_towards:
                            return False
                        moved = self.u_move_to_astar(target_tile.position)
                        if moved:
                            remember_pending_harvester_target(target_tile.index)
                        return finish_with_harvester_target(moved, target_tile)

            if self.u_build_at(
                target_tile.position,
                EntityType.HARVESTER,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=attack_enemy_passable,
            ):
                if self.last_built_entity_type == EntityType.HARVESTER:
                    clear_pending_harvester_target()
                    self.harvesters_built += 1
                    if can_still_move():
                        discontinued_tile = get_discontinued_adjacent_supply_tile(
                            target_tile
                        )
                        if discontinued_tile is not None:
                            move_towards_tile(discontinued_tile)
                else:
                    remember_pending_harvester_target(target_tile.index)
                return finish_with_harvester_target(True, target_tile)

            return False

        pending_target_idx: int | None = None
        if self.pending_harvester_target_resource == resource:
            pending_target_idx = self.pending_harvester_target_index
        if pending_target_idx is not None:
            pending_target_tile = tiles_by_index[pending_target_idx]
            if is_valid_harvester_target(pending_target_tile):
                return finish_with_harvester_target(
                    try_progress_harvester_target(
                        pending_target_tile,
                        require_surround=True,
                    ),
                    pending_target_tile,
                )
            clear_pending_harvester_target()

        target_tile = None
        target_key = None
        for tile in dict.fromkeys(tiles_by_index[idx] for idx in ore_indices):
            if self.round_stopwatch.check_overtime_interval():
                return False
            if tile.environment != resource:
                continue
            if not can_use_tile(tile):
                continue
            if (
                require_connected
                and not has_orthogonally_adjacent_own_supply_link(tile.index)
            ):
                continue
            if tile.bot.id is not None and tile.position != current_pos:
                continue
            if tile.in_enemy_attack_range:
                continue
            if has_orthogonally_adjacent_enemy_building(tile.position):
                continue
            if (
                max_core_ore_direct_dist is not None
                and tile.own_core_dist > max_core_ore_direct_dist
            ):
                continue
            key = (tile.dist_to_self, tile.own_core_dist)
            if target_key is None or key < target_key:
                target_key = key
                target_tile = tile

        if target_tile is None:
            return False

        if enforce_safe:
            empty_adjacent_tiles = get_empty_orthogonally_adjacent_tiles(
                target_tile.index
            )
            target_is_safe = (
                not empty_adjacent_tiles
                and not has_orthogonally_adjacent_enemy_building(target_tile.position)
            )
            if not target_is_safe:
                road_candidates: list[tuple[tuple[int, int, int], object]] = []
                for safe_order, adjacent_tile in enumerate(empty_adjacent_tiles):
                    if (
                        current_pos.distance_squared(adjacent_tile.position)
                        > BUILDER_ACTION_RADIUS_SQ
                    ):
                        continue
                    road_candidates.append(
                        (
                            (
                                adjacent_tile.own_core_dist,
                                adjacent_tile.dist_to_self,
                                safe_order,
                            ),
                            adjacent_tile,
                        )
                    )

                if road_candidates:
                    _, road_target_tile = min(road_candidates)
                    supplier_type, supplier_target = get_harvester_safety_build_plan(
                        target_tile,
                        road_target_tile,
                    )
                    if supplier_type in CONVEYOR_ENTITY_TYPES:
                        if self.u_build_at(
                            road_target_tile.position,
                            supplier_type,
                            hold=hold,
                            move_towards=move_towards,
                            attack_enemy_passable=False,
                            facing_direction=supplier_target,
                        ):
                            remember_pending_harvester_target(target_tile.index)
                            return finish_with_harvester_target(True, target_tile)
                    elif supplier_type == EntityType.BRIDGE:
                        if self.u_build_at(
                            road_target_tile.position,
                            supplier_type,
                            hold=hold,
                            move_towards=move_towards,
                            attack_enemy_passable=False,
                            target_pos=supplier_target,
                        ):
                            remember_pending_harvester_target(target_tile.index)
                            return finish_with_harvester_target(True, target_tile)
                    elif supplier_type == EntityType.BARRIER:
                        if self.u_build_at(
                            road_target_tile.position,
                            supplier_type,
                            hold=hold,
                            move_towards=move_towards,
                            attack_enemy_passable=False,
                        ):
                            remember_pending_harvester_target(target_tile.index)
                            return finish_with_harvester_target(True, target_tile)

                if current_pos != target_tile.position:
                    if not move_towards:
                        return False
                    moved = self.u_move_to_astar(target_tile.position)
                    if moved:
                        remember_pending_harvester_target(target_tile.index)
                    return finish_with_harvester_target(moved, target_tile)

        if (
            current_tile.environment == resource
            and not has_orthogonally_adjacent_supply_link(current_tile.index)
        ):
            replaceable_building_types = {EntityType.ROAD, EntityType.BARRIER}
            candidate_entries: list[tuple[tuple[int, int, int], int]] = []
            harvester_tile = current_tile

            for safe_order, adjacent_idx in enumerate(
                self.map.u_iter_cardinal_neighbor_indices(current_tile.index)
            ):
                adjacent_tile = tiles_by_index[adjacent_idx]
                if adjacent_tile.is_enemy_turret_target_tile:
                    continue
                if adjacent_tile.building.entity_type == EntityType.CORE:
                    continue
                if adjacent_tile.building.id is not None and not (
                    adjacent_tile.building.team == own_team
                    and adjacent_tile.building.entity_type in replaceable_building_types
                ):
                    continue

                supplier_type, _ = get_harvester_safety_build_plan(
                    harvester_tile,
                    adjacent_tile,
                )
                if supplier_type is None:
                    continue

                candidate_entries.append(
                    (
                        (
                            adjacent_tile.own_core_dist,
                            adjacent_tile.dist_to_self,
                            safe_order,
                        ),
                        adjacent_idx,
                    )
                )

            if candidate_entries:
                _, target_idx = min(candidate_entries)
                target_tile = tiles_by_index[target_idx]
                supplier_type, supplier_target = get_harvester_safety_build_plan(
                    harvester_tile,
                    target_tile,
                )
                if supplier_type in CONVEYOR_ENTITY_TYPES:
                    if self.u_build_at(
                        target_tile.position,
                        supplier_type,
                        hold=hold,
                        move_towards=move_towards,
                        attack_enemy_passable=False,
                        facing_direction=supplier_target,
                    ):
                        remember_pending_harvester_target(current_tile.index)
                        return finish_with_harvester_target(True, current_tile)
                elif supplier_type == EntityType.BRIDGE:
                    if self.u_build_at(
                        target_tile.position,
                        supplier_type,
                        hold=hold,
                        move_towards=move_towards,
                        attack_enemy_passable=False,
                        target_pos=supplier_target,
                    ):
                        remember_pending_harvester_target(current_tile.index)
                        next_direction = self.map.u_get_direction_between(
                            current_pos,
                            target_tile.position,
                        )
                        if next_direction is not None and self.ct.can_move(
                            next_direction
                        ):
                            self.u_move_with_target(
                                next_direction,
                                target_tile.position,
                            )
                        return finish_with_harvester_target(True, current_tile)
                elif supplier_type == EntityType.BARRIER:
                    if self.u_build_at(
                        target_tile.position,
                        supplier_type,
                        hold=hold,
                        move_towards=move_towards,
                        attack_enemy_passable=False,
                    ):
                        remember_pending_harvester_target(current_tile.index)
                        return finish_with_harvester_target(True, current_tile)

        if (
            current_tile.environment == resource
            and has_orthogonally_adjacent_supply_link(current_tile.index)
            and step_off_current_ore_tile()
        ):
            remember_pending_harvester_target(current_tile.index)
            return finish_with_harvester_target(True, current_tile)

        return finish_with_harvester_target(
            try_progress_harvester_target(
                target_tile,
                require_surround=enforce_safe,
            ),
            target_tile,
        )

    def s_build_connected_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
        attack_enemy_passable: bool = True,
        resource: Environment = Environment.ORE_TITANIUM,
        enforce_safe: bool = False,
    ):
        """
        Build a harvester only on ore tiles that already touch an own
        orthogonally adjacent supply-link tile.
        """
        return self.s_build_harvester(
            move_towards=move_towards,
            hold=hold,
            attack_enemy_passable=attack_enemy_passable,
            resource=resource,
            enforce_safe=enforce_safe,
            require_connected=True,
        )

    def s_frontier_expand(self):
        """
        Move toward the nearest reachable unseen frontier tile.

        Uses a single BFS from the builder to find the closest frontier layer,
        preferring lower own-core distance and stable coordinates among ties.
        If the builder is already standing in enemy turret range, retry once
        without turret avoidance so it does not freeze in place.
        """
        current_tile = self.map.u_get_pos_tile(self.map.current_pos)

        def move_along_frontier_path(avoid_enemy_turrets: bool) -> bool:
            shortest_path = self.map.u_calculate_shortest_path_to_frontier(
                self.map.current_pos,
                avoid_enemy_turrets=avoid_enemy_turrets,
            )
            if len(shortest_path) < 2:
                return False

            next_tile = shortest_path[1]
            next_direction = self.map.u_get_direction_between(
                self.map.current_pos,
                next_tile.position,
            )
            if next_direction is not None and self.ct.can_move(next_direction):
                self.u_move_with_target(next_direction, next_tile.position)
                return True
            if self.ct.can_build_road(next_tile.position):
                self.ct.build_road(next_tile.position)
                if next_direction is not None and self.ct.can_move(next_direction):
                    self.u_move_with_target(next_direction, next_tile.position)
                return True
            return False

        if move_along_frontier_path(avoid_enemy_turrets=True):
            return True
        if (
            not current_tile.is_enemy_turret_target_tile
            or self.round_stopwatch.check_overtime()
        ):
            return False
        return move_along_frontier_path(avoid_enemy_turrets=False)

    def s_fix_conveyor(self, move_towards: bool = True, hold: bool = True):
        """
        Replace titanium-carrying own conveyors that currently feed a harvester.

        Targets visible own conveyors that have titanium on them this turn and
        point directly at an own harvester, then destroys and rebuilds that
        tile immediately using the normal titanium transport supplier planner to
        remove the bottleneck.
        """
        current_pos = self.map.current_pos
        current_round = self.map.current_round
        own_team = self.map.own_team

        def has_other_supplier_pointing_at(tile) -> bool:
            for other_tile in self.map.own_supply_links_in_vision:
                if other_tile.index == tile.index:
                    continue
                if other_tile.last_seen_turn != current_round:
                    continue
                if other_tile.building.team != own_team:
                    continue
                if other_tile.building.entity_type not in {
                    *CONVEYOR_ENTITY_TYPES,
                    EntityType.BRIDGE,
                    EntityType.SPLITTER,
                }:
                    continue
                for target in other_tile.building.targets:
                    if target.index == tile.index:
                        return True
            return False

        target_tile = None
        target_supplier_type = None
        target_supplier_target = None
        target_key = None

        for tile in dict.fromkeys(self.map.own_supply_links_in_vision):
            if tile.last_seen_turn != current_round:
                continue
            if tile.building.team != own_team:
                continue
            if tile.building.entity_type not in CONVEYOR_ENTITY_TYPES:
                continue
            if tile.building.last_titanium_onit_turn != current_round:
                continue
            if tile.is_enemy_turret_target_tile:
                continue
            if tile.bot.id is not None and tile.position != current_pos:
                continue
            if not any(
                target.building.team == own_team
                and target.building.entity_type == EntityType.HARVESTER
                for target in tile.building.targets
            ):
                continue
            if not has_other_supplier_pointing_at(tile):
                continue

            supplier_type, supplier_target = self.u_get_transport_supplier_build_plan(
                tile.position,
                Environment.ORE_TITANIUM,
            )
            if supplier_type is None:
                continue

            key = (
                0 if tile.position == current_pos else 1,
                tile.dist_to_self,
                tile.own_core_dist,
                tile.index,
            )
            if target_key is None or key < target_key:
                target_key = key
                target_tile = tile
                target_supplier_type = supplier_type
                target_supplier_target = supplier_target

        if target_tile is None or target_supplier_type is None:
            return False

        if current_pos.distance_squared(target_tile.position) > BUILDER_ACTION_RADIUS_SQ:
            if not move_towards:
                return False
            return self.u_move_to_astar(target_tile.position)

        titanium_cost, axionite_cost = getattr(
            self.ct, f"get_{target_supplier_type.value}_cost"
        )()
        if self.map.titanium < titanium_cost or self.map.axionite < axionite_cost:
            return hold

        if self.ct.get_action_cooldown() != 0 or not self.ct.can_destroy(
            target_tile.position
        ):
            return False

        self.ct.destroy(target_tile.position)
        target_tile.clear_building()

        if target_supplier_type in CONVEYOR_ENTITY_TYPES:
            return bool(
                self.u_build_at(
                    target_tile.position,
                    target_supplier_type,
                    hold=False,
                    move_towards=False,
                    attack_enemy_passable=False,
                    facing_direction=target_supplier_target,
                )
            )
        if target_supplier_type == EntityType.BRIDGE:
            return bool(
                self.u_build_at(
                    target_tile.position,
                    target_supplier_type,
                    hold=False,
                    move_towards=False,
                    attack_enemy_passable=False,
                    target_pos=target_supplier_target,
                )
            )
        return False

    def s_fix_harvester(self, move_towards: bool = True, hold: bool = True):
        """
        Rebuild the harvester's designated best supply tile when it currently
        points into any harvester instead of transporting outward.
        """
        current_pos = self.map.current_pos
        current_round = self.map.current_round
        own_team = self.map.own_team
        tiles_by_index = self.map.tiles_by_index

        target_tile = None
        target_supplier_type = None
        target_supplier_target = None
        target_key = None

        for harvester_tile in dict.fromkeys(self.map.own_harvesters_in_vision):
            if harvester_tile.last_seen_turn != current_round:
                continue
            if harvester_tile.building.team != own_team:
                continue

            resource = harvester_tile.environment
            if resource not in {Environment.ORE_TITANIUM, Environment.ORE_AXIONITE}:
                continue

            best_supply_idx = self.map.u_get_harvester_best_supply_tile(
                harvester_tile.index
            )
            if best_supply_idx is None:
                continue

            rebuild_tile = tiles_by_index[best_supply_idx]
            rebuild_building_type = rebuild_tile.building.entity_type
            if rebuild_tile.building.team != own_team:
                continue
            if rebuild_building_type not in SUPPLY_LINK_TYPES | {EntityType.ROAD}:
                continue
            if (
                rebuild_building_type in SUPPLY_LINK_TYPES
                and not any(
                    target.building.entity_type == EntityType.HARVESTER
                    for target in rebuild_tile.building.targets
                )
            ):
                continue
            supplier_type, supplier_target = (
                self.u_get_harvester_adjacent_supplier_build_plan(
                    harvester_tile,
                    rebuild_tile,
                    resource,
                )
            )
            if supplier_type is None:
                continue
            if rebuild_tile.is_enemy_turret_target_tile:
                continue
            if rebuild_tile.bot.id is not None and rebuild_tile.position != current_pos:
                continue

            key = (
                0 if rebuild_tile.position == current_pos else 1,
                rebuild_tile.dist_to_self,
                rebuild_tile.own_core_dist,
                rebuild_tile.index,
            )
            if target_key is None or key < target_key:
                target_key = key
                target_tile = rebuild_tile
                target_supplier_type = supplier_type
                target_supplier_target = supplier_target

        if target_tile is None or target_supplier_type is None:
            return False

        if current_pos.distance_squared(target_tile.position) > BUILDER_ACTION_RADIUS_SQ:
            if not move_towards:
                return False
            return self.u_move_to_astar(target_tile.position)

        titanium_cost, axionite_cost = getattr(
            self.ct, f"get_{target_supplier_type.value}_cost"
        )()
        if self.map.titanium < titanium_cost or self.map.axionite < axionite_cost:
            return hold

        if self.ct.get_action_cooldown() != 0 or not self.ct.can_destroy(
            target_tile.position
        ):
            return False

        self.ct.destroy(target_tile.position)
        target_tile.clear_building()

        if target_supplier_type in CONVEYOR_ENTITY_TYPES:
            return bool(
                self.u_build_at(
                    target_tile.position,
                    target_supplier_type,
                    hold=False,
                    move_towards=False,
                    attack_enemy_passable=False,
                    facing_direction=target_supplier_target,
                )
            )
        if target_supplier_type == EntityType.BRIDGE:
            return bool(
                self.u_build_at(
                    target_tile.position,
                    target_supplier_type,
                    hold=False,
                    move_towards=False,
                    attack_enemy_passable=False,
                    target_pos=target_supplier_target,
                )
            )
        return False

    def s_destroy_hijacked_supplier(
        self,
        move_towards: bool = True,
        rebuild: bool = True,
    ):
        """
        Destroy the closest visible own harvester or supply-link tile that
        feeds an enemy turret.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team

        def infer_resource(tile) -> Environment:
            supply_chain_label = tile.own_supply_chain_label
            if (
                supply_chain_label & SupplyChainLabel.AXIONITE
                and not (supply_chain_label & SupplyChainLabel.TITANIUM)
            ):
                return Environment.ORE_AXIONITE
            if tile.environment == Environment.ORE_AXIONITE:
                return Environment.ORE_AXIONITE
            return Environment.ORE_TITANIUM

        def points_at_enemy_turret(source_tile) -> bool:
            return any(
                target_tile.building.id is not None
                and target_tile.building.team != own_team
                and target_tile.building.entity_type
                in {EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH}
                for target_tile in source_tile.building.targets
            )

        target_tile = None
        target_dist = None
        for tile in dict.fromkeys(
            self.map.own_supply_links_in_vision + self.map.own_harvesters_in_vision
        ):
            if tile.building.team != own_team:
                continue
            if tile.building.entity_type not in SUPPLY_LINK_TYPES | {
                EntityType.HARVESTER
            }:
                continue
            if not points_at_enemy_turret(tile):
                continue
            if target_dist is None or tile.dist_to_self < target_dist:
                target_dist = tile.dist_to_self
                target_tile = tile

        if target_tile is None:
            return False

        target_pos = target_tile.position
        if current_pos.distance_squared(
            target_pos
        ) <= GameConstants.ACTION_RADIUS_SQ and self.ct.can_destroy(target_pos):
            self.ct.destroy(target_pos)
            target_tile.clear_building()

            if rebuild:
                resource = infer_resource(target_tile)
                supplier_type, supplier_target = self.u_get_transport_supplier_build_plan(
                    target_pos,
                    resource,
                )
                if supplier_type in CONVEYOR_ENTITY_TYPES:
                    if self.u_build_at(
                        target_pos,
                        supplier_type,
                        hold=False,
                        move_towards=False,
                        attack_enemy_passable=False,
                        facing_direction=supplier_target,
                    ):
                        return True
                elif supplier_type == EntityType.BRIDGE:
                    if self.u_build_at(
                        target_pos,
                        supplier_type,
                        hold=False,
                        move_towards=False,
                        attack_enemy_passable=False,
                        target_pos=supplier_target,
                    ):
                        return True

            return False
        if move_towards and self.u_move_to_astar(target_pos):
            return False

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

        enemy_harvesters = self.map.enemy_harvesters_in_vision
        if not enemy_harvesters:
            return False

        def is_next_to_enemy_harvester(pos: Position) -> bool:
            for harvester_tile in enemy_harvesters:
                if harvester_tile.position.distance_squared(pos) == 1:
                    return True
            return False

        def try_step_off_and_build_current_tile() -> bool:
            current_tile = self.map.u_get_pos_tile(current_pos)
            if (
                current_tile.building.id is not None
                or current_tile.environment != Environment.EMPTY
                or not is_next_to_enemy_harvester(current_pos)
            ):
                return False

            titanium_cost, axionite_cost = self.ct.get_sentinel_cost()
            if (
                self.ct.get_action_cooldown() != 0
                or self.map.titanium < titanium_cost
                or self.map.axionite < axionite_cost
            ):
                return False

            sentinel_direction = self.u_get_sentinel_orientation(current_pos)
            enemy_core_center_pos = self.map.enemy_core_center_pos
            candidate_entries: list[tuple[tuple[int, int, int, int], Direction]] = []

            for direction_order, direction in enumerate(Direction):
                if direction == Direction.CENTRE or not self.ct.can_move(direction):
                    continue

                next_pos = current_pos.add(direction)
                if not self.map.u_is_in_bounds(next_pos):
                    continue

                candidate_entries.append(
                    (
                        (
                            (
                                next_pos.distance_squared(enemy_core_center_pos)
                                if enemy_core_center_pos is not None
                                else 0
                            ),
                            self.map.u_get_pos_tile(next_pos).own_core_dist,
                            direction_order,
                            self.map.u_to_index(next_pos),
                        ),
                        direction,
                    )
                )

            if not candidate_entries:
                return False

            _, move_direction = min(candidate_entries)
            self.u_move_with_target(move_direction, current_pos)
            if self.ct.can_build_sentinel(current_pos, sentinel_direction):
                self.ct.build_sentinel(current_pos, sentinel_direction)
                self.last_built_entity_type = EntityType.SENTINEL
                return True
            return True

        if try_step_off_and_build_current_tile():
            return True

        tile_kind_by_pos: dict[Position, str | None] = {}

        def get_tile_kind(pos: Position) -> str | None:
            if pos not in tile_kind_by_pos:
                candidate_tile = self.map.u_get_pos_tile(pos)
                if candidate_tile.building.id is None:
                    tile_kind_by_pos[pos] = (
                        "empty"
                        if candidate_tile.environment == Environment.EMPTY
                        else None
                    )
                elif (
                    candidate_tile.building.entity_type == EntityType.ROAD
                    and candidate_tile.building.team == own_team
                ):
                    tile_kind_by_pos[pos] = "own_road"
                elif (
                    attack_enemy_passable
                    and candidate_tile.building.team != own_team
                    and candidate_tile.is_passable
                ):
                    tile_kind_by_pos[pos] = "enemy_passable"
                else:
                    tile_kind_by_pos[pos] = None
            return tile_kind_by_pos[pos]

        candidate_tiles = []
        for harvester_tile in enemy_harvesters:
            harvester_pos = harvester_tile.position
            for candidate_pos in self.map.u_iter_adjacent_cardinal_positions(
                harvester_pos,
            ):
                candidate_tiles.append(self.map.u_get_pos_tile(candidate_pos))

            if self.round_stopwatch.check_overtime():
                break

        current_round = self.ct.get_current_round()
        target_tile = None
        target_key = None
        for tile in dict.fromkeys(candidate_tiles):
            if tile.last_seen_turn != current_round:
                continue
            if tile.bot.id is not None and tile.position != current_pos:
                continue
            kind = get_tile_kind(tile.position)
            if kind is None:
                continue
            kind_rank = 0 if kind == "empty" else 1 if kind == "own_road" else 2
            key = (tile.dist_to_self, kind_rank)
            if target_key is None or key < target_key:
                target_key = key
                target_tile = tile

        if target_tile is None:
            return False

        sentinel_direction = self.u_get_sentinel_orientation(target_tile.position)
        return bool(
            self.u_build_at(
                target_tile.position,
                EntityType.SENTINEL,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=attack_enemy_passable,
                facing_direction=sentinel_direction,
            )
        )

    def s_block_enemy_supply_chain(self, move_towards: bool = True, hold: bool = True):
        """
        Build a barrier on the closest visible enemy resource target.

        Uses cached map targets, prefers shorter squared distance, and
        delegates build, attack, movement, and hold handling to `u_build_at`.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team

        target_tile = None
        target_key = None
        for tile in dict.fromkeys(self.map.enemy_supply_targets_in_vision):
            if not (
                tile.building.id is None
                or (
                    tile.building.entity_type == EntityType.ROAD
                    and tile.building.team == own_team
                )
            ):
                continue
            key = (tile.dist_to_self, 0 if tile.building.id is None else 1)
            if target_key is None or key < target_key:
                target_key = key
                target_tile = tile

        if target_tile is None:
            return False

        return bool(
            self.u_build_at(
                target_tile.position,
                EntityType.BARRIER,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=True,
            )
        )

    def s_block_titanium(
        self,
        move_towards: bool = True,
        hold: bool = True,
        only_out_of_reach: bool = True,
    ):
        """
        Build a barrier on the closest known empty titanium tile.

        Uses cached titanium targets from the map, ranks them by squared
        distance, and delegates build, movement, and hold handling to
        `u_build_at`.
        """
        current_pos = self.map.current_pos

        target_tile = None
        target_dist = None
        for tile in dict.fromkeys(
            self.map.tiles_by_index[idx]
            for idx in self.map.known_accessible_titanium_indices
        ):
            if tile.environment != Environment.ORE_TITANIUM:
                continue
            if tile.building.id is not None:
                continue
            if only_out_of_reach and tile.own_core_dist <= MAX_CORE_ORE_DIRECT_DIST:
                continue
            if target_dist is None or tile.dist_to_self < target_dist:
                target_dist = tile.dist_to_self
                target_tile = tile

        if target_tile is None:
            return False

        return bool(
            self.u_build_at(
                target_tile.position,
                EntityType.BARRIER,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=False,
            )
        )

    def s_patrol_supply_chains(self):
        """
        Patrol known allied supply links and rebuild visible damaged gaps.

        The builder stamps its current tile plus all adjacent tiles with its
        current patrol index whenever those tiles hold allied supply-link
        structures. If a visible supply gap can be rebuilt, this delegates to
        `s_build_missing_supply_link(...)`. Otherwise it moves toward the
        closest known allied supply-link tile whose stored patrol index is
        still lower than the builder's current patrol index. When the current
        patrol cycle is complete, the builder increments its patrol index and
        starts the next pass immediately.
        """
        own_team = self.map.own_team
        current_pos = self.map.current_pos
        current_idx = self.map.u_to_index(current_pos)
        tiles_by_index = self.map.tiles_by_index
        known_own_supply_link_indices = self.map.known_own_supply_link_indices
        get_own_core_dist = self.map.u_get_own_core_dist_by_index

        def stamp_local_patrol_coverage() -> None:
            current_tile = tiles_by_index[current_idx]
            if (
                current_tile.building.team == own_team
                and current_tile.building.entity_type in SUPPLY_LINK_TYPES
            ):
                current_tile.last_patrolled_index = self.supply_patrol_index

            for adjacent_idx in self.map.u_iter_neighbor_indices(current_idx):
                adjacent_tile = tiles_by_index[adjacent_idx]
                if (
                    adjacent_tile.building.team == own_team
                    and adjacent_tile.building.entity_type in SUPPLY_LINK_TYPES
                ):
                    adjacent_tile.last_patrolled_index = self.supply_patrol_index

        def get_unpatrolled_target_indices() -> list[int]:
            supply_patrol_index = self.supply_patrol_index
            candidate_entries: list[tuple[int, int, int, int]] = []

            for idx in known_own_supply_link_indices:
                if self.round_stopwatch.check_overtime():
                    break
                target_tile = tiles_by_index[idx]
                last_patrolled_index = target_tile.last_patrolled_index
                if last_patrolled_index >= supply_patrol_index:
                    continue
                dist_to_self = self.map.u_get_estimated_dist_to_self_by_index(idx)

                candidate_entries.append(
                    (
                        dist_to_self,
                        last_patrolled_index,
                        get_own_core_dist(idx),
                        idx,
                    )
                )

            candidate_entries.sort()
            return [idx for _, _, _, idx in candidate_entries]

        stamp_local_patrol_coverage()

        if self.s_build_missing_supply_link(
            move_towards=True,
            hold=True,
            attack_enemy_passable=True,
        ):
            return True

        patrol_target_indices = get_unpatrolled_target_indices()
        if not patrol_target_indices:
            self.supply_patrol_index += 1
            stamp_local_patrol_coverage()
            patrol_target_indices = get_unpatrolled_target_indices()

        for target_idx in patrol_target_indices:
            if self.u_move_to_astar(tiles_by_index[target_idx].position):
                return True

            if self.round_stopwatch.check_overtime():
                break

        # Second pass: if we still haven't found a valid move, allow the bot to travel near enemy turrets
        for target_idx in patrol_target_indices:
            if self.u_move_to_astar(
                tiles_by_index[target_idx].position, avoid_enemy_turrets=False
            ):
                return True

            if self.round_stopwatch.check_overtime():
                break

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

        candidate_tiles = []
        for harvester_tile in self.map.enemy_harvesters_in_vision:
            harvester_pos = harvester_tile.position
            for candidate_pos in self.map.u_iter_adjacent_cardinal_positions(
                harvester_pos,
            ):
                candidate_tiles.append(self.map.u_get_pos_tile(candidate_pos))

            if self.round_stopwatch.check_overtime():
                break

        current_round = self.ct.get_current_round()
        target_tile = None
        target_dist = None
        for tile in dict.fromkeys(candidate_tiles):
            if tile.last_seen_turn != current_round:
                continue
            if tile.building.team == own_team:
                continue
            if tile.building.entity_type not in SUPPLY_LINK_TYPES:
                continue
            if not tile.is_passable:
                continue
            if target_dist is None or tile.dist_to_self < target_dist:
                target_dist = tile.dist_to_self
                target_tile = tile

        if target_tile is None:
            return False

        return bool(
            self.u_attack_passable(
                target_tile.position,
                move_towards=move_towards,
                destroy_condition=lambda _: True,
            )
        )

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

        current_round = self.ct.get_current_round()
        target_tile = None
        target_dist = None
        for tile in dict.fromkeys(self.map.enemy_supply_links_in_vision):
            if tile.last_seen_turn != current_round:
                continue
            if tile.building.team == own_team:
                continue
            if tile.building.entity_type not in SUPPLY_LINK_TYPES:
                continue
            if not any(
                target.position == enemy_core_pos for target in tile.building.targets
            ):
                continue
            if tile.in_enemy_launcher_pickup_zone:
                continue
            if tile.in_enemy_attack_range:
                continue
            if target_dist is None or tile.dist_to_self < target_dist:
                target_dist = tile.dist_to_self
                target_tile = tile

        if target_tile is None:
            return False

        return bool(
            self.u_attack_passable(
                target_tile.position,
                move_towards=move_towards,
                destroy_condition=lambda pos: (
                    self.map.u_get_pos_tile(pos).in_enemy_bot_action_range_turn
                    != current_round
                ),
            )
        )

    def s_attack_key_enemy_supply_chain(self, move_towards: bool = True):
        """
        Attack enemy supply links that matter for core-facing sentinel positions.

        If the builder is already standing on an enemy supply-link tile where a
        sentinel built on that tile would face the enemy core, attack that tile
        immediately. Otherwise target the closest visible enemy supply-link tile
        that had titanium on it within the last three turns and from which a
        built sentinel would face the enemy core.
        """
        current_pos = self.map.current_pos
        current_round = self.map.current_round
        enemy_core_center_pos = self.map.enemy_core_center_pos
        if enemy_core_center_pos is None:
            return False

        current_tile = self.map.u_get_pos_tile(current_pos)
        enemy_core_tiles = self.map.u_get_core_footprint_positions(
            enemy_core_center_pos
        )
        sentinel_targets_enemy_core_by_index: dict[int, bool] = {}

        def sentinel_targets_enemy_core(tile) -> bool:
            cached_value = sentinel_targets_enemy_core_by_index.get(tile.index)
            if cached_value is not None:
                return cached_value

            sentinel_direction = self.u_get_sentinel_orientation(tile.position)
            cached_value = any(
                self.map.u_sentinel_covers_target(
                    tile.position,
                    sentinel_direction,
                    core_tile.position,
                    GameConstants.SENTINEL_VISION_RADIUS_SQ,
                )
                for core_tile in enemy_core_tiles
            )
            sentinel_targets_enemy_core_by_index[tile.index] = cached_value
            return cached_value

        if (
            current_tile.building.team == self.map.enemy_team
            and current_tile.building.entity_type in SUPPLY_LINK_TYPES
            and sentinel_targets_enemy_core(current_tile)
        ):
            return bool(
                self.u_attack_passable(
                    current_pos,
                    move_towards=False,
                    destroy_condition=lambda _: True,
                    avoid_enemy_turrets=False,
                )
            )

        target_tile = None
        target_key = None
        for tile in dict.fromkeys(self.map.enemy_supply_links_in_vision):
            if tile.last_seen_turn != current_round:
                continue
            if tile.building.team != self.map.enemy_team:
                continue
            if tile.building.entity_type not in SUPPLY_LINK_TYPES:
                continue
            if not tile.is_passable:
                continue

            last_titanium_turn = tile.building.last_titanium_onit_turn
            if (
                last_titanium_turn is None
                or current_round - last_titanium_turn > 3
                or not sentinel_targets_enemy_core(tile)
            ):
                continue

            key = (
                tile.dist_to_self,
                current_round - last_titanium_turn,
                tile.own_core_dist,
                tile.index,
            )
            if target_key is None or key < target_key:
                target_key = key
                target_tile = tile

        if target_tile is None:
            return False

        return bool(
            self.u_attack_passable(
                target_tile.position,
                move_towards=move_towards,
                destroy_condition=lambda _: True,
            )
        )

    def s_build_enemy_supplied_sentinel(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ):
        """
        Build a sentinel on a tile currently fed by a recently active enemy supplier.

        Considers visible target tiles of enemy conveyors, splitters, armoured
        conveyors, and bridges whose last seen carried resource was within the
        last three turns. If the builder is already standing on the chosen build
        tile, it first steps off that tile so the sentinel can be built from the
        new position on the following turn.
        """
        current_pos = self.map.current_pos
        current_round = self.map.current_round
        own_team = self.map.own_team
        enemy_team = self.map.enemy_team
        candidate_keys_by_index: dict[int, tuple[int, int, int, int, int]] = {}
        tiles_by_index = self.map.tiles_by_index

        def can_host_sentinel(target_tile) -> bool:
            if target_tile.last_seen_turn != current_round:
                return False
            if target_tile.bot.id is not None and target_tile.position != current_pos:
                return False
            if target_tile.building.id is None:
                return True
            return (
                target_tile.building.team == own_team
                and target_tile.building.entity_type
                in {EntityType.ROAD, EntityType.BARRIER}
            )

        def step_off_current_build_tile(target_tile) -> bool:
            candidate_entries: list[
                tuple[tuple[int, int, int, int, int, int], Direction]
            ] = []

            for safe_order, adjacent_pos in enumerate(
                self.map.u_iter_adjacent_cardinal_positions(current_pos)
            ):
                adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
                move_direction = self.map.u_get_direction_between(
                    current_pos,
                    adjacent_pos,
                )
                if move_direction is None or not self.ct.can_move(move_direction):
                    continue
                if (
                    adjacent_tile.position.distance_squared(target_tile.position)
                    > BUILDER_ACTION_RADIUS_SQ
                ):
                    continue

                if (
                    adjacent_tile.building.team == own_team
                    and adjacent_tile.building.entity_type in SUPPLY_LINK_TYPES
                ):
                    walkable_rank = 0
                elif adjacent_tile.is_core_of(own_team):
                    walkable_rank = 1
                elif (
                    adjacent_tile.building.entity_type == EntityType.ROAD
                    and adjacent_tile.building.team == own_team
                ):
                    walkable_rank = 2
                elif adjacent_tile.building.id is None:
                    walkable_rank = 3
                elif adjacent_tile.is_passable:
                    walkable_rank = 4
                else:
                    continue

                candidate_entries.append(
                    (
                        (
                            1 if adjacent_tile.is_enemy_turret_target_tile else 0,
                            walkable_rank,
                            adjacent_tile.own_core_dist,
                            adjacent_tile.dist_to_self,
                            safe_order,
                            adjacent_tile.index,
                        ),
                        move_direction,
                    )
                )

            if not candidate_entries:
                return False

            _, move_direction = min(candidate_entries)
            self.u_move_with_target(move_direction, current_pos)
            return True

        for supplier_tile in dict.fromkeys(self.map.enemy_supply_links_in_vision):
            if supplier_tile.last_seen_turn != current_round:
                continue
            if supplier_tile.building.team != enemy_team:
                continue
            if supplier_tile.building.entity_type not in SUPPLY_LINK_TYPES:
                continue

            last_resource_turn = supplier_tile.building.last_resource_onit_turn
            if last_resource_turn is None or current_round - last_resource_turn > 3:
                continue

            for target_tile in supplier_tile.building.targets:
                if not can_host_sentinel(target_tile):
                    continue

                key = (
                    0 if target_tile.position == current_pos else 1,
                    target_tile.dist_to_self,
                    current_round - last_resource_turn,
                    target_tile.own_core_dist,
                    target_tile.index,
                )
                existing_key = candidate_keys_by_index.get(target_tile.index)
                if existing_key is None or key < existing_key:
                    candidate_keys_by_index[target_tile.index] = key

            if self.round_stopwatch.check_overtime():
                break

        if not candidate_keys_by_index:
            return False

        target_indices = sorted(
            candidate_keys_by_index,
            key=lambda idx: candidate_keys_by_index[idx],
        )
        for target_idx in target_indices:
            target_tile = tiles_by_index[target_idx]
            if target_tile.position == current_pos:
                if move_towards and step_off_current_build_tile(target_tile):
                    print(
                        "Build enemy supplied sentinel: step off",
                        target_tile.position,
                    )
                    return True
                continue

            sentinel_direction = self.u_get_sentinel_orientation(target_tile.position)
            if self.u_build_at(
                target_tile.position,
                EntityType.SENTINEL,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=False,
                facing_direction=sentinel_direction,
            ):
                if self.last_built_entity_type == EntityType.SENTINEL:
                    print(
                        "Build enemy supplied sentinel: built at",
                        target_tile.position,
                        "facing",
                        sentinel_direction,
                    )
                elif (
                    current_pos.distance_squared(target_tile.position)
                    > BUILDER_ACTION_RADIUS_SQ
                ):
                    print(
                        "Build enemy supplied sentinel: move toward",
                        target_tile.position,
                    )
                else:
                    print(
                        "Build enemy supplied sentinel: hold for",
                        target_tile.position,
                    )
                return True

            if self.round_stopwatch.check_overtime():
                break

        return False

    def s_heal_own_building(self, move_towards: bool = True, hold: bool = True):
        """
        Heal the highest-priority damaged allied tile, preferring immediate heals.

        If any damaged allied tile is already healable this turn, only those
        in-range candidates are considered. Otherwise the builder targets the
        remaining visible damaged allied tiles and moves toward the best one.
        Priorities are: core first, then tiles with a damaged own builder bot
        standing on them, then by building type in this order: bridge,
        conveyor, road, foundry, harvester, armoured conveyor, splitter,
        sentinel, gunner, launcher, breach, barrier. Ties are broken by
        distance to self and then distance to own core.
        """
        own_team = self.map.own_team

        candidate_tiles = self.map.own_buildings_healable_in_action_range
        if not candidate_tiles:
            candidate_tiles = self.map.own_buildings_needing_heal
        if not candidate_tiles:
            return False

        building_type_rank = {
            EntityType.CORE: 0,
            EntityType.BRIDGE: 2,
            EntityType.CONVEYOR: 3,
            EntityType.ROAD: 4,
            EntityType.FOUNDRY: 5,
            EntityType.HARVESTER: 6,
            EntityType.ARMOURED_CONVEYOR: 3,
            EntityType.SPLITTER: 8,
            EntityType.SENTINEL: 9,
            EntityType.GUNNER: 10,
            EntityType.LAUNCHER: 11,
            EntityType.BREACH: 12,
            EntityType.BARRIER: 13,
        }

        def has_damaged_own_builder(tile) -> bool:
            return bool(
                tile.bot.id is not None
                and tile.bot.team == own_team
                and tile.bot.hp < self.ct.get_max_hp(tile.bot.id)
            )

        target_tile = min(
            dict.fromkeys(candidate_tiles),
            key=lambda tile: (
                (
                    0
                    if tile.building.entity_type == EntityType.CORE
                    else 1 if has_damaged_own_builder(tile) else 2
                ),
                building_type_rank.get(tile.building.entity_type, 99),
                tile.dist_to_self,
                tile.own_core_dist,
            ),
        )
        return bool(self.u_heal_at(target_tile.position, move_towards=move_towards))

    def s_move_toward_enemy_core(self):
        """
        Harassment step for advancing toward the enemy core.

        If the exact enemy core position is not known yet, move toward the
        nearest remaining symmetry candidate instead, using a single A* path
        search.
        """
        enemy_core_center_pos = self.map.enemy_core_center_pos

        if enemy_core_center_pos is not None:
            return bool(
                self.u_move_to_astar(
                    enemy_core_center_pos,
                    allow_conveyor_building=False,
                )
            )

        if (
            not self.map.enemy_core_center_pos_candidates
            and not self.map.u_calc_core_center_positions()
        ):
            return False

        target_pos = min(
            {
                pos for _, pos in self.map.enemy_core_center_pos_candidates
            },
            key=lambda pos: (
                self.map.u_get_estimated_dist_to_self(pos),
                pos.x,
                pos.y,
            ),
            default=None,
        )
        if target_pos is None:
            return False

        return bool(
            self.u_move_to_astar(
                target_pos,
                allow_conveyor_building=False,
            )
        )

    def s_checkpoint_move_toward_enemy_core(self):
        if (
            not self.map.map_json_fully_loaded
            or self.map.enemy_core_seen_in_vision
        ):
            return False

        checkpoint_positions = self.map.enemy_core_checkpoint_positions
        if not checkpoint_positions:
            return False

        next_checkpoint_index = self.enemy_core_checkpoint_index + 1
        while (
            next_checkpoint_index < len(checkpoint_positions)
            and self.map.current_pos == checkpoint_positions[next_checkpoint_index]
        ):
            self.enemy_core_checkpoint_index = next_checkpoint_index
            next_checkpoint_index += 1

        if next_checkpoint_index >= len(checkpoint_positions):
            return False

        return bool(
            self.u_move_to_astar(
                checkpoint_positions[next_checkpoint_index],
                allow_conveyor_building=False,
            )
        )

    def s_patrol_enemy_core(self):
        enemy_core_center_pos = self.map.enemy_core_center_pos
        if enemy_core_center_pos is None:
            return False

        waypoint_indices: list[int] = []
        active_mask_by_index = self.map.active_mask_by_index
        intrinsic_passable_by_index = self.map.intrinsic_passable_by_index
        tiles_by_index = self.map.tiles_by_index
        center_x = enemy_core_center_pos.x
        center_y = enemy_core_center_pos.y
        map_width = self.map.width
        map_height = self.map.height

        for dx, dy in _ENEMY_CORE_PATROL_OFFSETS:
            x = center_x + dx
            y = center_y + dy
            if x < 0 or y < 0 or x >= map_width or y >= map_height:
                continue
            waypoint_idx = self.map.u_to_index_xy(x, y)
            if (
                not active_mask_by_index[waypoint_idx]
                or not intrinsic_passable_by_index[waypoint_idx]
            ):
                continue
            waypoint_indices.append(waypoint_idx)

        if not waypoint_indices:
            return False

        current_idx = self.map.u_to_index(self.map.current_pos)
        waypoint_count = len(waypoint_indices)

        if current_idx in waypoint_indices:
            next_patrol_index = (
                waypoint_indices.index(current_idx) + 1
            ) % waypoint_count
        else:
            next_patrol_index = min(
                range(waypoint_count),
                key=lambda idx: (
                    self.map.u_get_estimated_dist_to_self_by_index(
                        waypoint_indices[idx]
                    ),
                    self.map.u_get_own_core_dist_by_index(waypoint_indices[idx]),
                    idx,
                ),
            )

        self.enemy_core_patrol_index = next_patrol_index
        return bool(
            self.u_move_to_astar(
                tiles_by_index[waypoint_indices[next_patrol_index]].position
            )
        )
