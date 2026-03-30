from cambc import Direction, EntityType, Environment, Position

from .navigation import BB_ACTION_RADIUS_SQ
from .types import BuilderStrategyMethodsSelf


class BuilderStrategyMethodsMixin(BuilderStrategyMethodsSelf):
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
                target_tile.building.team == own_team
                and target_tile.building.entity_type
                in {EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER}
            )

        def can_use_tile(pos: Position) -> bool:
            target_tile = self.map.u_get_pos_tile(pos)
            if target_tile.building.entity_type == EntityType.CORE:
                return False
            if target_tile.building.id is None:
                return True
            return (
                target_tile.building.team == own_team
                and target_tile.building.entity_type in {EntityType.ROAD, EntityType.BARRIER}
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
            return target_tile.building.id is None or (
                target_tile.building.team == own_team
                and target_tile.building.entity_type == EntityType.ROAD
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
            lambda pos: 0 if self.map.u_get_pos_tile(pos).building.id is None else 1,
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
            if target_tile.building.entity_type == EntityType.CORE:
                return False
            if target_tile.building.id is None:
                return True
            if (
                target_tile.building.team == own_team
                and target_tile.building.entity_type in {EntityType.ROAD, EntityType.BARRIER}
            ):
                return True
            return (
                attack_enemy_passable
                and target_tile.building.team != own_team
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
                    adjacent_tile.building.id is not None
                    and adjacent_tile.building.team != own_team
                ):
                    return True
            return False

        def can_use_tile(pos: Position) -> bool:
            target_tile = self.map.u_get_pos_tile(pos)
            if target_tile.building.id is None:
                return True
            if (
                target_tile.building.team == own_team
                and target_tile.building.entity_type in {EntityType.ROAD, EntityType.BARRIER}
            ):
                return True
            return (
                attack_enemy_passable
                and target_tile.building.team != own_team
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
            target_pos = source_tile.building.targets[0] if source_tile.building.targets else None
            if target_pos is None:
                return False
            target_tile = self.map.u_get_pos_tile(target_pos)
            return (
                target_tile.building.id is not None
                and target_tile.building.team != own_team
                and target_tile.building.entity_type
                in {EntityType.GUNNER, EntityType.SENTINEL, EntityType.BREACH}
            )

        candidate_positions = self.u_filter_tiles(
            list(
                dict.fromkeys(
                    self.map.own_supply_links_in_sight
                    + self.map.own_harvesters_in_sight
                )
            ),
            lambda pos: self.map.u_get_pos_tile(pos).building.team == own_team,
            lambda pos: self.map.u_get_pos_tile(pos).building.entity_type
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

        candidate_positions: list[Position] = []
        for harvester_pos in enemy_harvesters:
            for candidate_pos in self.map.u_iter_adjacent_positions(harvester_pos):
                candidate_positions.append(candidate_pos)

        candidate_positions = list(dict.fromkeys(candidate_positions))
        candidate_positions = self.u_filter_tiles(
            candidate_positions,
            lambda pos: (
                self.map.u_get_pos_tile(pos).last_seen_turn == self.ct.get_current_round()
            ),
            lambda pos: (
                self.map.u_get_pos_tile(pos).bot.id is None
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
                self.map.u_get_pos_tile(pos).building.id is None
                or (
                    self.map.u_get_pos_tile(pos).building.entity_type == EntityType.ROAD
                    and self.map.u_get_pos_tile(pos).building.team == own_team
                )
            ),
        )
        if not enemy_supply_targets:
            return False

        enemy_supply_targets = self.u_prioritize_tiles(
            enemy_supply_targets,
            lambda pos: current_pos.distance_squared(pos),
            lambda pos: 0 if self.map.u_get_pos_tile(pos).building.id is None else 1,
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
            lambda pos: self.map.u_get_pos_tile(pos).building.id is None,
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
            lambda pos: (
                self.map.u_get_pos_tile(pos).last_seen_turn == self.ct.get_current_round()
            ),
            lambda pos: self.map.u_get_pos_tile(pos).building.team != own_team,
            lambda pos: self.map.u_get_pos_tile(pos).building.entity_type
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
            lambda pos: (
                self.map.u_get_pos_tile(pos).last_seen_turn == self.ct.get_current_round()
            ),
            lambda pos: self.map.u_get_pos_tile(pos).building.team != own_team,
            lambda pos: self.map.u_get_pos_tile(pos).building.entity_type
            in {EntityType.CONVEYOR, EntityType.BRIDGE},
            lambda pos: (
                self.map.u_get_pos_tile(pos).building.targets[0]
                if self.map.u_get_pos_tile(pos).building.targets
                else None
            ) == enemy_core_pos,
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
                    self.map.u_get_pos_tile(pos).in_enemy_bot_action_range_turn
                    != self.ct.get_current_round()
                ),
            ):
                return True

        return False
