from cambc import Direction, EntityType, Environment, Position

from lib.agent.constants import BUILDER_ACTION_RADIUS_SQ
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
        current_pos = self.map.current_pos
        own_team = self.map.own_team
        attack_enemy_passable = False
        supplier_plan_by_pos: dict[
            Position, tuple[EntityType | None, Direction | Position | None]
        ] = {}

        def is_own_supply_link(target_tile) -> bool:
            return (
                target_tile.building.team == own_team
                and target_tile.building.entity_type in SUPPLY_LINK_TYPES
            )

        def can_use_tile(target_tile) -> bool:
            if target_tile.building.entity_type == EntityType.CORE:
                return False
            if target_tile.building.id is None:
                return True
            return (
                target_tile.building.team == own_team
                and target_tile.building.entity_type
                in {EntityType.ROAD, EntityType.BARRIER}
            )

        def has_supplier_plan(target_tile) -> bool:
            if target_tile.position not in supplier_plan_by_pos:
                supplier_plan_by_pos[target_tile.position] = (
                    self.u_get_supplier_build_plan(target_tile.position)
                )
            return supplier_plan_by_pos[target_tile.position][0] is not None

        candidate_tiles = []
        for harvester_tile in self.map.own_harvesters_in_vision:
            harvester_pos = harvester_tile.position
            adjacent_tiles = [
                self.map.u_get_pos_tile(pos)
                for pos in self.map.u_iter_adjacent_positions(
                    harvester_pos,
                    consider_diagonal=False,
                )
                if not self.map.u_get_pos_tile(pos).is_enemy_turret_target_tile
            ]
            if any(is_own_supply_link(tile) for tile in adjacent_tiles):
                continue

            adjacent_tiles = self.u_filter_tiles(
                adjacent_tiles,
                can_use_tile,
                has_supplier_plan,
            )
            if not adjacent_tiles:
                continue

            adjacent_tiles = self.u_prioritize_tiles(
                adjacent_tiles,
                lambda tile: tile.own_core_dist,
                lambda tile: tile.dist_to_self,
            )
            candidate_tiles.append(adjacent_tiles[0])

        if not candidate_tiles:
            return False

        candidate_tiles = self.u_prioritize_tiles(
            list(dict.fromkeys(candidate_tiles)),
            lambda tile: tile.dist_to_self,
            lambda tile: tile.own_core_dist,
        )
        for target_tile in candidate_tiles:
            supplier_type, supplier_target = supplier_plan_by_pos[target_tile.position]
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
        conveyor_plan_by_pos: dict[Position, Direction | None] = {}

        def can_use_tile(target_tile) -> bool:
            return target_tile.building.id is None or (
                target_tile.building.team == own_team
                and target_tile.building.entity_type == EntityType.ROAD
            )

        def is_reachable_chokepoint_plan(target_tile) -> bool:
            if not self.map.u_is_chokepoint(target_tile.position):
                return True
            if target_tile.position not in conveyor_plan_by_pos:
                conveyor_direction = self.u_best_conveyor_orientation(
                    target_tile.position
                )
                conveyor_plan_by_pos[target_tile.position] = conveyor_direction
            return conveyor_plan_by_pos[target_tile.position] is not None

        candidate_tiles = []
        for harvester_tile in self.map.own_harvesters_in_vision:
            harvester_pos = harvester_tile.position
            for candidate_pos in self.map.u_iter_adjacent_positions(
                harvester_pos,
                consider_diagonal=False,
            ):
                candidate_tile = self.map.u_get_pos_tile(candidate_pos)
                if candidate_tile.environment == Environment.WALL:
                    continue
                candidate_tiles.append(candidate_tile)

        candidate_tiles = self.u_filter_tiles(
            list(dict.fromkeys(candidate_tiles)),
            lambda tile: not tile.is_enemy_turret_target_tile,
            can_use_tile,
            is_reachable_chokepoint_plan,
        )
        if not candidate_tiles:
            return False

        candidate_tiles = self.u_prioritize_tiles(
            candidate_tiles,
            lambda tile: tile.dist_to_self,
            lambda tile: 0 if tile.building.id is None else 1,
        )
        for target_tile in candidate_tiles:
            if self.map.u_is_chokepoint(target_tile.position):
                conveyor_direction = conveyor_plan_by_pos[target_tile.position]
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
        buildings, prioritizes by squared distance to the own core and then the
        builder, and delegates the actual build, replacement, movement, hold,
        and optional enemy-passable clearing to `u_build_at`.
        """
        own_team = self.map.own_team
        core_center_pos = self.map.own_core_center_pos
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
            lambda tile: (
                core_center_pos.distance_squared(tile.position)
                if core_center_pos is not None
                else 10**9
            ),
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

    # TODO: implementation here is still very inefficient
#           i.e. does not use any caching whatsoever
    def s_frontier_expand(self):
        """
        Move toward the closest unseen frontier tile.
        """
        frontier_tiles = []
        seen_positions: set[tuple[int, int]] = set()

        for column in self.map.matrix:
            for tile in column:
                if tile.last_seen_turn == -1:
                    continue
                for adjacent_pos in self.map.u_iter_adjacent_positions(tile.position):
                    adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
                    if adjacent_tile.last_seen_turn != -1:
                        continue
                    key = (adjacent_pos.x, adjacent_pos.y)
                    if key in seen_positions:
                        continue
                    seen_positions.add(key)
                    frontier_tiles.append(adjacent_tile)

        frontier_tiles = self.u_filter_tiles(
            frontier_tiles,
            lambda tile: tile.dist_to_self < INF_DIST,
            lambda tile: not tile.is_enemy_turret_target_tile,
        )
        if not frontier_tiles:
            return False

        frontier_tiles = self.u_prioritize_tiles(
            frontier_tiles,
            lambda tile: tile.dist_to_self,
            lambda tile: tile.own_core_dist,
            lambda tile: tile.position.x,
            lambda tile: tile.position.y,
        )
        return self.u_move_to(frontier_tiles[0].position)

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
            ) <= BUILDER_ACTION_RADIUS_SQ and self.ct.can_destroy(target_pos):
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
