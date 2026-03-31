from heapq import heapify, heappop

from cambc import Direction, EntityType, Environment, GameConstants, Position

from lib.map.constants import INF_DIST, SUPPLY_LINK_TYPES


class BuilderStrategyMethodsMixin:
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
        own_team = self.map.own_team
        attack_enemy_passable = False
        tiles_by_index = self.map.tiles_by_index
        cardinal_neighbor_indices_by_index = self.map.cardinal_neighbor_indices_by_index
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
                    tiles_by_index[tile_index].position
                )
            return supplier_plan_by_index[tile_index]

        for harvester_order, harvester_tile in enumerate(
            self.map.own_harvesters_in_vision
        ):
            adjacent_tiles = []
            has_own_supply_link = False

            for safe_order, adjacent_idx in enumerate(
                cardinal_neighbor_indices_by_index[harvester_tile.index]
            ):
                adjacent_tile = tiles_by_index[adjacent_idx]
                if adjacent_tile.is_enemy_turret_target_tile:
                    continue
                if (
                    adjacent_tile.building.team == own_team
                    and adjacent_tile.building.entity_type in SUPPLY_LINK_TYPES
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
            if supplier_type == EntityType.CONVEYOR:
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

        return False

    def s_surround_harvester(self, move_towards: bool = True, hold: bool = True):
        """
        Secure visible own harvesters with nearby barriers.

        Considers empty or own-road tiles adjacent to visible own harvesters,
        prioritizes them by squared distance to the builder, and builds a
        barrier unless the tile is a chokepoint, in which case it tries to
        place a conveyor using the cached supplier-plan helper instead.
        """
        own_team = self.map.own_team
        tiles_by_index = self.map.tiles_by_index
        dist_to_self_by_index = self.map.dist_to_self_by_index
        cardinal_neighbor_indices_by_index = self.map.cardinal_neighbor_indices_by_index
        build_plan_by_index: dict[int, tuple[EntityType | None, Direction | None]] = {}
        seen_candidate_indices: set[int] = set()
        candidate_entries: list[tuple[tuple[int, int], int, int]] = []
        encounter_order = 0

        def get_build_plan(
            tile_index: int,
        ) -> tuple[EntityType | None, Direction | None]:
            if tile_index not in build_plan_by_index:
                target_tile = tiles_by_index[tile_index]
                if not self.map.u_is_chokepoint(target_tile.position):
                    build_plan_by_index[tile_index] = (EntityType.BARRIER, None)
                else:
                    build_plan_by_index[tile_index] = (
                        EntityType.CONVEYOR,
                        self.u_best_conveyor_orientation(target_tile.position),
                    )
            return build_plan_by_index[tile_index]

        for harvester_tile in self.map.own_harvesters_in_vision:
            for adjacent_idx in cardinal_neighbor_indices_by_index[harvester_tile.index]:
                if adjacent_idx in seen_candidate_indices:
                    continue
                seen_candidate_indices.add(adjacent_idx)

                target_tile = tiles_by_index[adjacent_idx]
                if target_tile.environment == Environment.WALL:
                    continue
                candidate_order = encounter_order
                encounter_order += 1
                if target_tile.is_enemy_turret_target_tile:
                    continue
                if target_tile.building.id is not None and not (
                    target_tile.building.team == own_team
                    and target_tile.building.entity_type == EntityType.ROAD
                ):
                    continue

                candidate_entries.append(
                    (
                        (
                            dist_to_self_by_index[adjacent_idx],
                            0 if target_tile.building.id is None else 1,
                        ),
                        candidate_order,
                        adjacent_idx,
                    )
                )

        if not candidate_entries:
            return False

        heapify(candidate_entries)
        while candidate_entries:
            _, _, target_idx = heappop(candidate_entries)
            target_tile = tiles_by_index[target_idx]
            # Delay the expensive chokepoint/conveyor planning until this tile
            # is actually the best remaining cheap candidate.
            building_type, conveyor_direction = get_build_plan(target_idx)
            if building_type == EntityType.CONVEYOR:
                if conveyor_direction is None:
                    continue
                if self.u_build_at(
                    target_tile.position,
                    EntityType.CONVEYOR,
                    hold=hold,
                    move_towards=move_towards,
                    attack_enemy_passable=False,
                    facing_direction=conveyor_direction,
                ):
                    return True
                continue

            if self.u_build_at(
                target_tile.position,
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
        own_team = self.map.own_team

        def can_use_tile(target_tile) -> bool:
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

        candidate_tiles = self.u_filter_tiles(
            list(dict.fromkeys(self.map.own_missing_supply_links)),
            can_use_tile,
        )
        if not candidate_tiles:
            return False

        candidate_tiles = self.u_prioritize_tiles(
            candidate_tiles,
            lambda tile: tile.own_core_dist,
            lambda tile: tile.dist_to_self,
        )

        for target_tile in candidate_tiles:
            supplier_type, supplier_target = self.u_get_supplier_build_plan(
                target_tile.position
            )
            if supplier_type is None:
                continue
            if supplier_type == EntityType.CONVEYOR:
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
        buildings, prioritizes by cached distance to the own core and then the
        builder, and delegates the actual build, replacement, movement, hold,
        and optional enemy-passable clearing to `u_build_at`.
        """
        own_team = self.map.own_team
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
                    adjacent_tile.building.id is not None
                    and adjacent_tile.building.team != own_team
                ):
                    return True
            return False

        def can_use_tile(target_tile) -> bool:
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

        candidate_tiles = self.u_filter_tiles(
            list(dict.fromkeys(ore_positions)),
            lambda tile: tile.environment == resource,
            can_use_tile,
            lambda tile: not tile.in_enemy_attack_range,
            lambda tile: not has_orthogonally_adjacent_enemy_building(tile.position),
        )
        if not candidate_tiles:
            return False

        candidate_tiles = self.u_prioritize_tiles(
            candidate_tiles,
            lambda tile: tile.own_core_dist,
            lambda tile: tile.dist_to_self,
        )
        for target_tile in candidate_tiles:
            if self.u_build_at(
                target_tile.position,
                EntityType.HARVESTER,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=attack_enemy_passable,
            ):
                return True

        return False

    def s_frontier_expand(self):
        """
        Move toward the closest unseen frontier tile using the cached frontier set.
        """
        frontier_indices = self.map.frontier_expand_cached_unseen_indices
        if not frontier_indices:
            return False

        tiles_by_index = self.map.tiles_by_index
        dist_to_self_by_index = self.map.dist_to_self_by_index
        own_core_dist_by_index = self.map.own_core_dist_by_index
        best_target_pos: Position | None = None
        best_priority: tuple[int, int, int, int] | None = None

        for idx in frontier_indices:
            dist_to_self = dist_to_self_by_index[idx]
            if dist_to_self >= INF_DIST:
                continue

            frontier_tile = tiles_by_index[idx]
            if frontier_tile.is_enemy_turret_target_tile:
                continue

            target_pos = frontier_tile.position
            priority = (
                dist_to_self,
                own_core_dist_by_index[idx],
                target_pos.x,
                target_pos.y,
            )
            if best_priority is None or priority < best_priority:
                best_priority = priority
                best_target_pos = target_pos

        if best_target_pos is None:
            return False

        return self.u_move_to(best_target_pos)

    def s_destroy_hijacked_supplier(self, move_towards: bool = True):
        """
        Destroy the closest visible own harvester or supply-link tile that
        feeds an enemy turret.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team

        def points_at_enemy_turret(source_tile) -> bool:
            return any(
                target_tile.building.id is not None
                and target_tile.building.team != own_team
                and target_tile.building.entity_type
                in {EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH}
                for target_tile in source_tile.building.targets
            )

        candidate_tiles = self.u_filter_tiles(
            [
                tile
                for tile in dict.fromkeys(
                    self.map.own_supply_links_in_vision
                    + self.map.own_harvesters_in_vision
                )
            ],
            lambda tile: tile.building.team == own_team,
            lambda tile: tile.building.entity_type
            in SUPPLY_LINK_TYPES | {EntityType.HARVESTER},
            points_at_enemy_turret,
        )
        if not candidate_tiles:
            return False

        candidate_tiles = self.u_prioritize_tiles(
            candidate_tiles,
            lambda tile: tile.dist_to_self,
        )
        for target_tile in candidate_tiles:
            target_pos = target_tile.position
            if current_pos.distance_squared(
                target_pos
            ) <= GameConstants.ACTION_RADIUS_SQ and self.ct.can_destroy(target_pos):
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

        enemy_harvesters = self.map.enemy_harvesters_in_vision
        if not enemy_harvesters:
            return False

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
            for candidate_pos in self.map.u_iter_adjacent_positions(
                harvester_pos,
                consider_diagonal=False,
            ):
                candidate_tiles.append(self.map.u_get_pos_tile(candidate_pos))

        candidate_tiles = list(dict.fromkeys(candidate_tiles))
        candidate_tiles = self.u_filter_tiles(
            candidate_tiles,
            lambda tile: tile.last_seen_turn == self.ct.get_current_round(),
            lambda tile: (tile.bot.id is None or tile.position == current_pos),
            lambda tile: get_tile_kind(tile.position) is not None,
        )
        if not candidate_tiles:
            return False

        candidate_tiles = self.u_prioritize_tiles(
            candidate_tiles,
            lambda tile: tile.dist_to_self,
            lambda tile: (
                0
                if get_tile_kind(tile.position) == "empty"
                else 1 if get_tile_kind(tile.position) == "own_road" else 2
            ),
        )
        for candidate_tile in candidate_tiles:
            sentinel_direction = self.u_get_sentinel_orientation(
                candidate_tile.position
            )
            if self.u_build_at(
                candidate_tile.position,
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

        enemy_supply_tiles = self.u_filter_tiles(
            list(dict.fromkeys(self.map.enemy_supply_targets_in_vision)),
            lambda tile: (
                tile.building.id is None
                or (
                    tile.building.entity_type == EntityType.ROAD
                    and tile.building.team == own_team
                )
            ),
        )
        if not enemy_supply_tiles:
            return False

        enemy_supply_tiles = self.u_prioritize_tiles(
            enemy_supply_tiles,
            lambda tile: tile.dist_to_self,
            lambda tile: 0 if tile.building.id is None else 1,
        )
        for target_tile in enemy_supply_tiles:
            if self.u_build_at(
                target_tile.position,
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

        titanium_tiles = self.u_filter_tiles(
            list(dict.fromkeys(self.map.known_accessible_titanium_tiles)),
            lambda tile: tile.environment == Environment.ORE_TITANIUM,
            lambda tile: tile.building.id is None,
        )
        if not titanium_tiles:
            return False

        titanium_tiles = self.u_prioritize_tiles(
            titanium_tiles,
            lambda tile: tile.dist_to_self,
        )
        for target_tile in titanium_tiles:
            if self.u_build_at(
                target_tile.position,
                EntityType.BARRIER,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=False,
            ):
                return True

        return False

    def s_insert_core_splitter(self, move_towards: bool = True, hold: bool = True):
        """
        TODO: insert a splitter into the core supply chain.
        The splitter should replace a conveyor that is adjacent to the core. 
        """
        return False

    def s_build_foundry_next_to_splitter(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ):
        """
        TODO: build a foundry adjacent to the core splitter.
        Prioritize building the foundry on a non-supply-chain tile. 
        """
        return False

    def s_patrol_supply_chains(self):
        """
        TODO: patrol own supply chains and rebuild damaged sections.
        Should save a patrolling index. For every supply chain tile,
        save a last patrolled at value indicating which value the patrolling index had
        when last patrolled. That means, at the start of each turn set the last patrolled at 
        value to the current patrolling index for all tiles that are at least diagonally adjacent to the
        builder bot. Keep track of supplier tiles that have a lower patrolling index than the current value.
        Always go to the nearest one of these to the builder bot. 
        If there are no tiles left to patrol, just increment the patrolling index by one 
        beforehand. 
        """
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
            for candidate_pos in self.map.u_iter_adjacent_positions(
                harvester_pos,
                consider_diagonal=False,
            ):
                candidate_tiles.append(self.map.u_get_pos_tile(candidate_pos))

        candidate_tiles = list(dict.fromkeys(candidate_tiles))
        candidate_tiles = self.u_filter_tiles(
            candidate_tiles,
            lambda tile: tile.last_seen_turn == self.ct.get_current_round(),
            lambda tile: tile.building.team != own_team,
            lambda tile: tile.building.entity_type in SUPPLY_LINK_TYPES,
            lambda tile: tile.is_passable,
        )
        if not candidate_tiles:
            return False

        candidate_tiles = self.u_prioritize_tiles(
            candidate_tiles,
            lambda tile: tile.dist_to_self,
        )

        for target_tile in candidate_tiles:
            if self.u_attack_passable(
                target_tile.position,
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

        candidate_tiles = self.u_filter_tiles(
            list(dict.fromkeys(self.map.enemy_supply_links_in_vision)),
            lambda tile: tile.last_seen_turn == self.ct.get_current_round(),
            lambda tile: tile.building.team != own_team,
            lambda tile: tile.building.entity_type in SUPPLY_LINK_TYPES,
            lambda tile: any(
                target.position == enemy_core_pos for target in tile.building.targets
            ),
            lambda tile: not tile.in_enemy_launcher_pickup_zone,
            lambda tile: not tile.in_enemy_attack_range,
        )
        if not candidate_tiles:
            return False

        candidate_tiles = self.u_prioritize_tiles(
            candidate_tiles,
            lambda tile: tile.dist_to_self,
        )

        for target_tile in candidate_tiles:
            if self.u_attack_passable(
                target_tile.position,
                move_towards=move_towards,
                destroy_condition=lambda pos: (
                    self.map.u_get_pos_tile(pos).in_enemy_bot_action_range_turn
                    != self.ct.get_current_round()
                ),
            ):
                return True

        return False
