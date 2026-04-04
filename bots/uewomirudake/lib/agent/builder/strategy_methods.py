from heapq import heapify, heappop

from cambc import Direction, EntityType, Environment, GameConstants, Position

from lib.debug import GlobalRoundStopwatch
from lib.map.constants import INF_DIST, SUPPLY_LINK_TYPES
from lib.map.types import SupplyChainLabel


class BuilderStrategyMethodsMixin:
    def s_convert_to_defender(self):
        from lib.agent.constants import HARVESTERS_BUILT_BEFORE_CONVERT_TO_DEFENDER

        if self.harvesters_built < HARVESTERS_BUILT_BEFORE_CONVERT_TO_DEFENDER:
            return False

        from .strategies import DEFENDER_STRATEGY

        if self.strategy == DEFENDER_STRATEGY:
            return False

        self.strategy = list(DEFENDER_STRATEGY)
        self.last_strategy_index = -1
        self.last_turn_completed = True
        return True

    def s_build_harvester_supply_link(
        self,
        move_towards: bool = True,
        hold: bool = True,
        resource: Environment = Environment.ORE_TITANIUM,
    ):
        """
        Build the best missing supplier next to a visible own harvester for
        `resource`.

        Skips harvesters that already have an adjacent compatible own supplier,
        keeps one valid adjacent placement tile per remaining harvester by
        cached core distance, then prioritizes those tiles by squared distance
        to the builder and the own core. The supplier type and target are
        chosen by `u_get_supplier_build_plan(...)`.
        """
        from lib.agent.constants import (
            MAX_CORE_ORE_DIRECT_DIST,
            PREVENT_SUPPLY_LINKS_TILL_HARVESTER,
        )
        from .strategies import SCAVENGER_STRATEGY

        if PREVENT_SUPPLY_LINKS_TILL_HARVESTER and self.harvesters_built == 0:
            return False

        own_team = self.map.own_team
        attack_enemy_passable = False
        max_core_ore_direct_dist = (
            MAX_CORE_ORE_DIRECT_DIST if self.strategy == SCAVENGER_STRATEGY else None
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
            if GlobalRoundStopwatch.is_overtime():
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
                    and not self.u_is_supply_tile_forbidden(
                        adjacent_tile.position,
                        resource,
                    )
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

            if GlobalRoundStopwatch.is_overtime():
                break

        return False

    def s_surround_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
        resource: Environment = Environment.ORE_TITANIUM,
    ):
        from lib.agent.constants import MAX_CORE_ORE_DIRECT_DIST
        from .strategies import SCAVENGER_STRATEGY

        current_pos = self.map.current_pos
        current_tile = self.map.u_get_pos_tile(current_pos)
        if current_tile.environment != resource:
            return False
        if (
            self.strategy == SCAVENGER_STRATEGY
            and current_tile.own_core_dist > MAX_CORE_ORE_DIRECT_DIST
        ):
            return False

        empty_adjacent_tiles = []
        for adjacent_pos in self.map.u_iter_adjacent_positions(
            current_pos,
            consider_diagonal=False,
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
            if self.u_build_at(
                target_tile.position,
                EntityType.ROAD,
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
        resource: Environment = Environment.ORE_TITANIUM,
    ):
        """
        Fill the highest-priority cached supply-link gap for `resource`.

        Uses cached missing-link positions plus any builder-local pending gap
        target, keeps tiles that can host a new supplier, filters to the
        requested resource chain, prioritizes gaps closer to the core and then
        the builder, and relies on the supplier-plan helper to choose whether
        the tile should become a conveyor or a bridge plus its optimal target.
        """
        from lib.agent.constants import PREVENT_SUPPLY_LINKS_TILL_HARVESTER

        if PREVENT_SUPPLY_LINKS_TILL_HARVESTER and self.harvesters_built == 0:
            return False

        own_team = self.map.own_team
        supply_chain_label = self.u_get_supply_chain_label_for_resource(resource)
        if supply_chain_label == SupplyChainLabel.NONE:
            return False
        tiles_by_index = self.map.tiles_by_index
        get_own_core_dist = self.map.u_get_own_core_dist_by_index
        current_round = self.map.current_round

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

        def clear_pending_target() -> None:
            if self.pending_missing_supply_link_resource == resource:
                self.pending_missing_supply_link_index = None
                self.pending_missing_supply_link_resource = None

        candidate_entries: list[tuple[tuple[int, int], int, int]] = []
        candidate_seen_indices: set[int] = set()
        pending_target_idx: int | None = None
        if self.pending_missing_supply_link_resource == resource:
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
                candidate_entries.append(((-1, -1), -1, pending_target_idx))

        for encounter_order, target_tile in enumerate(
            self.map.own_missing_supply_links
        ):
            if GlobalRoundStopwatch.is_overtime():
                break
            target_label = target_tile.own_supply_chain_label
            if not (target_label & supply_chain_label):
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
                )
            )

        if not candidate_entries:
            return False

        heapify(candidate_entries)
        while candidate_entries:
            _, _, target_idx = heappop(candidate_entries)
            target_tile = tiles_by_index[target_idx]
            supplier_type, supplier_target = self.u_get_supplier_build_plan(
                target_tile.position,
                resource,
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

            if GlobalRoundStopwatch.is_overtime():
                break

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
        and optional enemy-passable clearing to `u_build_at`. When the builder
        is already standing on the ore, it first seeds a missing supply link or
        steps off onto a nearby own walkable tile so the harvester can be
        placed from range instead of getting stuck on a same-tile build.
        """
        from lib.agent.constants import MAX_CORE_ORE_DIRECT_DIST
        from .strategies import SCAVENGER_STRATEGY

        current_pos = self.map.current_pos
        if (
            self.pending_missing_supply_link_index is not None
            and self.pending_missing_supply_link_resource == resource
        ):
            return False
        max_core_ore_direct_dist = (
            MAX_CORE_ORE_DIRECT_DIST if self.strategy == SCAVENGER_STRATEGY else None
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

        def has_orthogonally_adjacent_supply_link(tile_index: int) -> bool:
            for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(tile_index):
                adjacent_tile = tiles_by_index[adjacent_idx]
                if adjacent_tile.building.entity_type in SUPPLY_LINK_TYPES:
                    return True
            return False

        def step_off_current_ore_tile() -> bool:
            candidate_entries: list[
                tuple[tuple[int, int, int, int, int], Direction]
            ] = []

            for safe_order, adjacent_pos in enumerate(
                self.map.u_iter_adjacent_positions(
                    current_pos,
                    consider_diagonal=False,
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

            candidate_entries.sort()
            for _, move_direction in candidate_entries:
                if self.ct.can_move(move_direction):
                    self.ct.move(move_direction)
                    return True

            return hold and bool(candidate_entries)

        if (
            current_tile.environment == resource
            and not has_orthogonally_adjacent_supply_link(current_tile.index)
        ):
            replaceable_building_types = {EntityType.ROAD, EntityType.BARRIER}
            supplier_plan_by_index: dict[
                int, tuple[EntityType | None, Direction | Position | None]
            ] = {}
            candidate_entries: list[tuple[tuple[int, int, int], int]] = []

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

                supplier_plan_by_index[adjacent_idx] = self.u_get_supplier_build_plan(
                    adjacent_tile.position,
                    resource,
                )
                supplier_type, _ = supplier_plan_by_index[adjacent_idx]
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

            candidate_entries.sort()
            for _, target_idx in candidate_entries:
                target_tile = tiles_by_index[target_idx]
                supplier_type, supplier_target = supplier_plan_by_index[target_idx]
                if supplier_type == EntityType.CONVEYOR:
                    if self.u_build_at(
                        target_tile.position,
                        supplier_type,
                        hold=hold,
                        move_towards=move_towards,
                        attack_enemy_passable=False,
                        facing_direction=supplier_target,
                    ):
                        return True
                elif supplier_type == EntityType.BRIDGE:
                    if self.u_build_at(
                        target_tile.position,
                        supplier_type,
                        hold=hold,
                        move_towards=move_towards,
                        attack_enemy_passable=False,
                        target_pos=supplier_target,
                    ):
                        next_direction = self.map.u_get_direction_between(
                            current_pos,
                            target_tile.position,
                        )
                        if next_direction is not None and self.ct.can_move(
                            next_direction
                        ):
                            self.ct.move(next_direction)
                        return True

        if (
            current_tile.environment == resource
            and has_orthogonally_adjacent_supply_link(current_tile.index)
            and step_off_current_ore_tile()
        ):
            return True

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
            [tiles_by_index[idx] for idx in dict.fromkeys(ore_indices)],
            lambda tile: tile.environment == resource,
            can_use_tile,
            lambda tile: tile.bot.id is None or tile.position == current_pos,
            lambda tile: not tile.in_enemy_attack_range,
            lambda tile: not has_orthogonally_adjacent_enemy_building(tile.position),
            lambda tile: max_core_ore_direct_dist is None
            or tile.own_core_dist <= max_core_ore_direct_dist,
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
                if self.last_built_entity_type == EntityType.HARVESTER:
                    self.harvesters_built += 1
                return True

            if GlobalRoundStopwatch.is_overtime():
                break

        return False

    def s_frontier_expand(self):
        """
        Move toward a reachable unseen frontier tile using the cached frontier set.

        Prefer routes that stay outside enemy turret coverage. If the builder is
        already standing in enemy turret range, retry the same frontier targets
        without the turret-avoidance restriction so the bot does not freeze in
        place waiting for a fully safe path that may not exist.
        """
        frontier_indices = self.map.frontier_expand_cached_unseen_indices
        if not frontier_indices:
            return False

        current_tile = self.map.u_get_pos_tile(self.map.current_pos)
        tiles_by_index = self.map.tiles_by_index
        get_own_core_dist = self.map.u_get_own_core_dist_by_index
        candidate_entries: list[tuple[tuple[int, int, int, int], int]] = []

        for idx in frontier_indices:
            if GlobalRoundStopwatch.is_overtime_always_check():
                break
            dist_to_self = self.map.u_get_estimated_dist_to_self_by_index(idx)
            frontier_tile = tiles_by_index[idx]
            if frontier_tile.is_enemy_turret_target_tile:
                continue

            target_pos = frontier_tile.position
            candidate_entries.append(
                (
                    (
                        dist_to_self,
                        get_own_core_dist(idx),
                        target_pos.x,
                        target_pos.y,
                    ),
                    idx,
                )
            )

        if not candidate_entries:
            return False

        candidate_entries.sort()

        for _, idx in candidate_entries:
            if self.u_move_to(tiles_by_index[idx].position):
                return True

            if GlobalRoundStopwatch.is_overtime_always_check():
                break

        if current_tile.is_enemy_turret_target_tile:
            for _, idx in candidate_entries:
                if self.u_move_to(
                    tiles_by_index[idx].position,
                    avoid_enemy_turrets=False,
                ):
                    return True

                if GlobalRoundStopwatch.is_overtime_always_check():
                    break

        return False

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

            if GlobalRoundStopwatch.is_overtime():
                break

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

            if GlobalRoundStopwatch.is_overtime():
                break

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

            if GlobalRoundStopwatch.is_overtime_always_check():
                break

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

            if GlobalRoundStopwatch.is_overtime():
                break

        return False

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
        from lib.agent.constants import MAX_CORE_ORE_DIRECT_DIST

        current_pos = self.map.current_pos

        titanium_tiles = self.u_filter_tiles(
            [
                self.map.tiles_by_index[idx]
                for idx in dict.fromkeys(self.map.known_accessible_titanium_indices)
            ],
            lambda tile: tile.environment == Environment.ORE_TITANIUM,
            lambda tile: tile.building.id is None,
            lambda tile: (not only_out_of_reach)
            or tile.own_core_dist > MAX_CORE_ORE_DIRECT_DIST,
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

            if GlobalRoundStopwatch.is_overtime():
                break

        return False

    def s_insert_core_splitter(self, move_towards: bool = True, hold: bool = True):
        """
        Insert the planned core-facing splitter after the foundry exists, or
        wait near the foundry until a valid routed splitter slot becomes
        available.
        """
        from lib.agent.constants import FOUNDRY_WAIT_RADIUS_SQ

        foundry_pos = self.u_get_core_foundry_plan()
        if foundry_pos is None:
            return False

        if not self.map.has_built_foundry:
            foundry_tile = self.map.u_get_pos_tile(foundry_pos)
            if (
                foundry_tile.building.entity_type == EntityType.FOUNDRY
                and foundry_tile.building.team == self.map.own_team
            ):
                self.map.has_built_foundry = True
                self.map.built_foundry_index = foundry_tile.index
            else:
                return False
        else:
            if not self.u_foundry_site_has_visible_axionite_supply(foundry_pos):
                return False

        core_plan = self.u_get_core_splitter_foundry_plan()
        if core_plan is None:
            wait_pos = self.u_get_foundry_wait_position(foundry_pos)
            if wait_pos is None:
                return (
                    self.map.current_pos.distance_squared(foundry_pos)
                    <= FOUNDRY_WAIT_RADIUS_SQ
                )
            if self.map.current_pos == wait_pos:
                return True
            if move_towards and self.u_move_to(wait_pos):
                return True
            return (
                self.map.current_pos.distance_squared(foundry_pos)
                <= FOUNDRY_WAIT_RADIUS_SQ
            )

        splitter_pos, splitter_direction, _ = core_plan
        splitter_tile = self.map.u_get_pos_tile(splitter_pos)
        if (
            splitter_tile.building.entity_type == EntityType.SPLITTER
            and splitter_tile.building.team == self.map.own_team
            and splitter_tile.building.direction == splitter_direction
        ):
            return False

        return self.u_build_at(
            splitter_pos,
            EntityType.SPLITTER,
            hold=hold,
            move_towards=move_towards,
            attack_enemy_passable=False,
            facing_direction=splitter_direction,
        )

    def s_build_core_foundry(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ):
        """
        Build or confirm the planned core-side foundry before splitter work.
        """
        from lib.agent.constants import (
            BUILD_FOUNDRY_BEFORE_AXIONITE_SUPPLY_CHAIN,
            FOUNDRY_WAIT_RADIUS_SQ,
            MAX_TEMP_FOUNDRY_BARRIER_TITANIUM_COST,
        )

        foundry_pos = self.u_get_core_foundry_plan()
        if foundry_pos is None:
            return False
        foundry_tile = self.map.u_get_pos_tile(foundry_pos)
        if (
            foundry_tile.building.entity_type == EntityType.FOUNDRY
            and foundry_tile.building.team == self.map.own_team
        ):
            self.map.has_built_foundry = True
            self.map.built_foundry_index = foundry_tile.index
            return False
        if (
            not BUILD_FOUNDRY_BEFORE_AXIONITE_SUPPLY_CHAIN
            and not self.u_foundry_site_has_visible_axionite_supply(foundry_pos)
        ):
            return False
        titanium_cost, axionite_cost = self.ct.get_foundry_cost()
        can_afford_foundry = (
            self.map.titanium >= titanium_cost and self.map.axionite >= axionite_cost
        )
        can_build_now = (
            self.map.current_pos.distance_squared(foundry_pos)
            <= GameConstants.ACTION_RADIUS_SQ
            and can_afford_foundry
            and self.ct.can_build_foundry(foundry_pos)
        )

        if not can_afford_foundry:
            barrier_titanium_cost, _ = self.ct.get_barrier_cost()
            can_reserve_with_barrier = foundry_tile.building.id is None or (
                foundry_tile.building.entity_type == EntityType.ROAD
                and foundry_tile.building.team == self.map.own_team
            )
            if (
                barrier_titanium_cost <= MAX_TEMP_FOUNDRY_BARRIER_TITANIUM_COST
                and self.map.titanium >= barrier_titanium_cost
                and can_reserve_with_barrier
            ) and self.u_build_at(
                foundry_pos,
                EntityType.BARRIER,
                hold=False,
                move_towards=move_towards,
                attack_enemy_passable=False,
            ):
                self.map.built_foundry_index = foundry_tile.index
                return True
            if (
                foundry_tile.building.entity_type == EntityType.BARRIER
                and foundry_tile.building.team == self.map.own_team
            ):
                self.map.built_foundry_index = foundry_tile.index

            wait_pos = self.u_get_foundry_wait_position(foundry_pos)
            if wait_pos is None:
                return (
                    self.map.current_pos.distance_squared(foundry_pos)
                    <= FOUNDRY_WAIT_RADIUS_SQ
                )
            if self.map.current_pos == wait_pos:
                return True
            if move_towards and self.u_move_to(wait_pos):
                return True
            return (
                self.map.current_pos.distance_squared(foundry_pos)
                <= FOUNDRY_WAIT_RADIUS_SQ
            )

        if self.u_build_at(
            foundry_pos,
            EntityType.FOUNDRY,
            hold=hold,
            move_towards=move_towards,
            attack_enemy_passable=False,
        ):
            if can_build_now:
                self.map.has_built_foundry = True
                self.map.built_foundry_index = foundry_tile.index
            return True

        return False

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
                if GlobalRoundStopwatch.is_overtime():
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
            if self.u_move_to(tiles_by_index[target_idx].position):
                return True

            if GlobalRoundStopwatch.is_overtime():
                break

        # Second pass: if we still haven't found a valid move, allow the bot to travel near enemy turrets
        for target_idx in patrol_target_indices:
            if self.u_move_to(
                tiles_by_index[target_idx].position, avoid_enemy_turrets=False
            ):
                return True

            if GlobalRoundStopwatch.is_overtime():
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
            for candidate_pos in self.map.u_iter_adjacent_positions(
                harvester_pos,
                consider_diagonal=False,
            ):
                candidate_tiles.append(self.map.u_get_pos_tile(candidate_pos))

            if GlobalRoundStopwatch.is_overtime():
                break

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

            if GlobalRoundStopwatch.is_overtime():
                break

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

            if GlobalRoundStopwatch.is_overtime():
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
            EntityType.ARMOURED_CONVEYOR: 7,
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

        candidate_tiles = self.u_prioritize_tiles(
            list(dict.fromkeys(candidate_tiles)),
            lambda tile: (
                0
                if tile.building.entity_type == EntityType.CORE
                else 1 if has_damaged_own_builder(tile) else 2
            ),
            lambda tile: building_type_rank.get(tile.building.entity_type, 99),
            lambda tile: tile.dist_to_self,
            lambda tile: tile.own_core_dist,
        )

        for target_tile in candidate_tiles:
            if self.u_heal_at(target_tile.position, move_towards=move_towards):
                return True

            if GlobalRoundStopwatch.is_overtime():
                break

        return False

    def s_move_toward_enemy_core(self):
        """
        Harassment step for advancing toward the enemy core.
        """
        enemy_core_center_pos = self.map.enemy_core_center_pos

        if not enemy_core_center_pos:
            return False

        if self.u_move_to(self.map.enemy_core_center_pos):
            return True

        return False
