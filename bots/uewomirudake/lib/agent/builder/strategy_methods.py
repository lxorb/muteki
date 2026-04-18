from heapq import heapify, heappop
import math
import time

from cambc import Direction, EntityType, Environment, GameConstants, Position

from lib.agent.constants import (
    ATTACK_TURRET_TYPES,
    AXIONITE_HARVESTER_MIN_TITANIUM,
    AXIONITE_HARVESTER_MIN_TURN,
    BUILDER_ACTION_RADIUS_SQ,
    CONVEYOR_ENTITY_TYPES,
    DEFENDER_STRATEGY_ID,
    DISABLE_CONVEYORS_POINTING_AT_HARVESTERS,
    FOUNDRY_CAN_REPLACE_BRIDGE,
    HARASSMENT_STRATEGY_ID,
    HARVESTERS_BUILT_BEFORE_CONVERT_TO_DEFENDER,
    MAX_CORE_ORE_DIRECT_DIST,
    PREFER_SENTINEL_OVER_GUNNER_MIN_TITANIUM,
    PREVENT_SUPPLY_LINKS_TILL_HARVESTER,
    REPLACE_ATTACKED_CONVEYOR_MAX_HP,
    SCAVENGER_STRATEGY_ID,
    SURROUND_HARVESTER_ENTITY_TYPE,
)
from lib.map.constants import CARDINAL_DIRECTIONS, INF_DIST, SUPPLY_LINK_TYPES
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
_BRIDGE_R = int(GameConstants.BRIDGE_TARGET_RADIUS_SQ**0.5) + 1
_HIJACK_BRIDGE_TARGET_OFFSETS: tuple[tuple[int, int], ...] = tuple(
    (dx, dy)
    for dx in range(-_BRIDGE_R, _BRIDGE_R + 1)
    for dy in range(-_BRIDGE_R, _BRIDGE_R + 1)
    if 0 < dx * dx + dy * dy <= GameConstants.BRIDGE_TARGET_RADIUS_SQ
    and abs(dx) + abs(dy) != 1
)


class BuilderStrategyMethodsMixin:
    def s_return_to_core_center(self):
        own_core_center_pos = self.map.own_core_center_pos
        if own_core_center_pos is None:
            self.map.u_calc_core_center_positions()
            own_core_center_pos = self.map.own_core_center_pos
        if own_core_center_pos is None:
            return False
        return bool(self.u_move_to(own_core_center_pos))

    def s_step_off_core(self):
        own_core_center_pos = self.map.own_core_center_pos
        if own_core_center_pos is None:
            self.map.u_calc_core_center_positions()
            own_core_center_pos = self.map.own_core_center_pos
        if own_core_center_pos is None:
            return False

        current_pos = self.map.current_pos
        dx = current_pos.x - own_core_center_pos.x
        dy = current_pos.y - own_core_center_pos.y
        relative_offset = (dx, dy)
        if relative_offset not in {
            (-1, -1),
            (0, -1),
            (1, -1),
            (-1, 0),
            (1, 0),
            (-1, 1),
            (0, 1),
            (1, 1),
        }:
            return False

        if self.step_off_core_attempted:
            return False
        self.step_off_core_attempted = True

        target_pos = Position(current_pos.x + dx, current_pos.y + dy)
        if not self.map.u_is_in_bounds(target_pos):
            return False

        return bool(
            self.u_move_to(
                target_pos,
                build_new_roads=True,
                allow_conveyor_building=False,
            )
        )

    def _is_visible_building_damaged(self, tile) -> bool:
        building = tile.building
        return (
            building.id is not None
            and building.hp is not None
            and building.hp < self.ct.get_max_hp(building.id)
        )

    def u_get_splitter_direction_for_target_directions(
        self,
        *target_directions: Direction | None,
    ) -> Direction | None:
        desired_directions = tuple(
            dict.fromkeys(
                direction
                for direction in target_directions
                if direction is not None and direction != Direction.CENTRE
            )
        )
        if not desired_directions:
            return None

        for facing_direction in CARDINAL_DIRECTIONS:
            output_directions = {
                facing_direction,
                facing_direction.rotate_left().rotate_left(),
                facing_direction.rotate_right().rotate_right(),
            }
            if all(direction in output_directions for direction in desired_directions):
                return facing_direction

        return None

    def s_split_supply_sentinel(self):
        own_team = self.map.own_team
        current_round = self.map.current_round
        current_pos = self.map.current_pos
        all_own_supply_link_target_indices_in_vision = (
            self.map.all_own_supply_link_target_indices_in_vision
        )
        enemy_supply_link_target_indices_in_vision = (
            self.map.enemy_supply_link_target_indices_in_vision
        )
        splitter_titanium_cost, splitter_axionite_cost = self.ct.get_splitter_cost()
        can_afford_splitter = (
            self.map.titanium >= splitter_titanium_cost
            and self.map.axionite >= splitter_axionite_cost
        )
        conveyor_titanium_cost, conveyor_axionite_cost = self.ct.get_conveyor_cost()
        can_afford_conveyor = (
            self.map.titanium >= conveyor_titanium_cost
            and self.map.axionite >= conveyor_axionite_cost
        )
        candidate_entries: list[
            tuple[tuple[int, int, int, int], Position, EntityType, Direction]
        ] = []

        if not can_afford_splitter and not can_afford_conveyor:
            return False

        def is_currently_unsupplied_sentinel(tile) -> bool:
            return (
                tile.last_seen_turn == current_round
                and tile.building.team == own_team
                and tile.building.entity_type == EntityType.SENTINEL
                and tile.index not in all_own_supply_link_target_indices_in_vision
                and tile.index not in enemy_supply_link_target_indices_in_vision
            )

        for tile in self.map.own_supply_links_in_vision:
            if tile.last_seen_turn != current_round:
                continue
            if tile.building.team != own_team:
                continue
            if tile.building.entity_type not in CONVEYOR_ENTITY_TYPES:
                continue
            if tile.bot.id is not None and tile.position != current_pos:
                continue

            original_direction = tile.building.direction
            if original_direction is None or original_direction == Direction.CENTRE:
                continue

            adjacent_harvesters = []
            adjacent_sentinels = []
            for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(tile.index):
                adjacent_tile = self.map.tiles_by_index[adjacent_idx]
                if adjacent_tile.last_seen_turn != current_round:
                    continue
                if adjacent_tile.building.team != own_team:
                    continue
                if adjacent_tile.building.entity_type == EntityType.HARVESTER:
                    adjacent_harvesters.append(adjacent_tile)
                elif is_currently_unsupplied_sentinel(adjacent_tile):
                    adjacent_sentinels.append(adjacent_tile)

            if not adjacent_harvesters or not adjacent_sentinels:
                continue

            if tile.conveyor_targets_harvester:
                if not can_afford_conveyor:
                    continue
                harvester_index = min(
                    harvester_tile.index for harvester_tile in adjacent_harvesters
                )
                for sentinel_tile in adjacent_sentinels:
                    direction_to_sentinel = self.map.u_get_direction_between(
                        tile.position,
                        sentinel_tile.position,
                    )
                    if (
                        direction_to_sentinel is None
                        or direction_to_sentinel == Direction.CENTRE
                    ):
                        continue
                    candidate_entries.append(
                        (
                            (
                                tile.dist_to_self,
                                tile.index,
                                harvester_index,
                                sentinel_tile.index,
                            ),
                            tile.position,
                            EntityType.CONVEYOR,
                            direction_to_sentinel,
                        )
                    )
                continue

            if not can_afford_splitter:
                continue

            for harvester_tile in adjacent_harvesters:
                facing_direction = self.map.u_get_direction_between(
                    harvester_tile.position,
                    tile.position,
                )
                if facing_direction is None or facing_direction == Direction.CENTRE:
                    continue

                for sentinel_tile in adjacent_sentinels:
                    candidate_entries.append(
                        (
                            (
                                tile.dist_to_self,
                                tile.index,
                                harvester_tile.index,
                                sentinel_tile.index,
                            ),
                            tile.position,
                            EntityType.SPLITTER,
                            facing_direction,
                        )
                    )

            if self.round_stopwatch.check_overtime():
                break

        if not candidate_entries:
            return False

        _, target_pos, build_entity_type, facing_direction = min(
            candidate_entries,
            key=lambda item: item[0],
        )
        target_tile = self.map.u_get_pos_tile(target_pos)

        if (
            current_pos.distance_squared(target_pos) <= BUILDER_ACTION_RADIUS_SQ
            and self.ct.can_destroy(target_pos)
        ):
            self.ct.destroy(target_pos)
            target_tile.clear_building()
            if build_entity_type == EntityType.SPLITTER:
                if not self.ct.can_build_splitter(target_pos, facing_direction):
                    return False
                self.ct.build_splitter(target_pos, facing_direction)
                self.last_built_entity_type = EntityType.SPLITTER
                return True
            if not self.ct.can_build_conveyor(target_pos, facing_direction):
                return False
            self.ct.build_conveyor(target_pos, facing_direction)
            self.last_built_entity_type = EntityType.CONVEYOR
            return True

        return bool(self.u_move_to(target_pos))

    def s_defend_attacked_harvester(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ):
        current_pos = self.map.current_pos
        own_team = self.map.own_team
        current_round = self.map.current_round
        tiles_by_index = self.map.tiles_by_index
        sentinel_titanium_cost, sentinel_axionite_cost = self.ct.get_sentinel_cost()
        candidate_entries: list[tuple[tuple[int, int, int, int], int, int, Direction]] = []

        def enemy_adjacent_tile_needs_defense(tile) -> bool:
            return (
                tile.last_seen_turn == current_round
                and tile.bot.id is not None
                and tile.bot.team != own_team
                and not tile.in_own_attack_range
                and not tile.in_own_launcher_pickup_zone
            )

        def can_use_defender_sentinel_tile(tile) -> bool:
            if tile.environment == Environment.WALL:
                return False
            if tile.bot.id is not None:
                return False
            if tile.building.id is None:
                return True
            if tile.building.team != own_team:
                return False
            if tile.building.entity_type in {EntityType.ROAD, EntityType.BARRIER}:
                return True
            return (
                tile.building.entity_type in CONVEYOR_ENTITY_TYPES
                and tile.conveyor_targets_harvester
            )

        for harvester_tile in self.map.own_harvesters_in_vision:
            if harvester_tile.last_seen_turn != current_round:
                continue

            if not any(
                enemy_adjacent_tile_needs_defense(tiles_by_index[adjacent_idx])
                for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(
                    harvester_tile.index
                )
            ):
                continue

            best_supply_idx = self.map.u_get_harvester_best_supply_tile(harvester_tile.index)
            if best_supply_idx is None:
                continue

            supplier_tile = tiles_by_index[best_supply_idx]
            if supplier_tile.building.entity_type == EntityType.BRIDGE:
                continue
            if (
                supplier_tile.building.team != own_team
                or supplier_tile.building.entity_type not in CONVEYOR_ENTITY_TYPES
            ):
                continue

            supplier_direction = supplier_tile.building.direction
            if supplier_direction is None or supplier_direction == Direction.CENTRE:
                continue

            for passing_direction in dict.fromkeys(
                (
                    supplier_direction.rotate_left().rotate_left(),
                    supplier_direction.rotate_right().rotate_right(),
                )
            ):
                target_pos = supplier_tile.position.add(passing_direction)
                if not self.map.u_is_in_bounds(target_pos):
                    continue

                target_tile = self.map.u_get_pos_tile(target_pos)
                if not can_use_defender_sentinel_tile(target_tile):
                    continue

                sentinel_direction = self.map.u_get_direction_between(
                    target_tile.position,
                    harvester_tile.position,
                )
                if (
                    sentinel_direction is None
                    or sentinel_direction == Direction.CENTRE
                    or sum(abs(delta) for delta in sentinel_direction.delta()) != 2
                ):
                    continue

                candidate_entries.append(
                    (
                        (
                            harvester_tile.dist_to_self,
                            target_tile.dist_to_self,
                            harvester_tile.index,
                            target_tile.index,
                        ),
                        harvester_tile.index,
                        target_tile.index,
                        sentinel_direction,
                    )
                )

            if self.round_stopwatch.check_overtime():
                break

        if not candidate_entries:
            return False

        if self.map.titanium < sentinel_titanium_cost:
            return False

        _, _, target_idx, sentinel_direction = min(candidate_entries)
        target_tile = tiles_by_index[target_idx]
        affordable = (
            self.map.titanium >= sentinel_titanium_cost
            and self.map.axionite >= sentinel_axionite_cost
        )

        if (
            target_tile.building.team == own_team
            and target_tile.building.entity_type in CONVEYOR_ENTITY_TYPES
            and target_tile.conveyor_targets_harvester
        ):
            if not affordable:
                if (
                    hold
                    and current_pos.distance_squared(target_tile.position)
                    <= BUILDER_ACTION_RADIUS_SQ
                ):
                    return True
                if not move_towards:
                    return False
                return bool(
                    self.u_move_to(
                        target_tile.position,
                        reach_builder_action_range=True,
                    )
                )

            if (
                current_pos.distance_squared(target_tile.position)
                <= BUILDER_ACTION_RADIUS_SQ
                and self.ct.can_destroy(target_tile.position)
            ):
                self.ct.destroy(target_tile.position)
                target_tile.clear_building()
                return bool(
                    self.u_build_at(
                        target_tile.position,
                        EntityType.SENTINEL,
                        hold=False,
                        move_towards=False,
                        attack_enemy_passable=False,
                        facing_direction=sentinel_direction,
                    )
                )

            if not move_towards:
                return False
            return bool(
                self.u_move_to(
                    target_tile.position,
                    reach_builder_action_range=True,
                )
            )

        return bool(
            self.u_build_at(
                target_tile.position,
                EntityType.SENTINEL,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=False,
                facing_direction=sentinel_direction,
            )
        )

    def u_get_splitter_direction_for_replaced_conveyor(
        self,
        target_tile,
        fallback_direction: Direction | None = None,
    ) -> Direction | None:
        original_direction = target_tile.building.direction or fallback_direction
        if original_direction is None or original_direction == Direction.CENTRE:
            return original_direction

        def get_opposite_direction(direction: Direction) -> Direction:
            return (
                direction.rotate_left()
                .rotate_left()
                .rotate_left()
                .rotate_left()
            )

        current_round = self.map.current_round
        target_idx = target_tile.index

        def is_fed_from(direction: Direction) -> bool:
            feeder_idx = self.map.u_get_neighbor_index_by_direction(target_idx, direction)
            if feeder_idx is None:
                return False

            feeder_tile = self.map.tiles_by_index[feeder_idx]
            return (
                feeder_tile.last_seen_turn == current_round
                and feeder_tile.building.team == self.map.own_team
                and feeder_tile.building.entity_type in CONVEYOR_ENTITY_TYPES
                and any(target.index == target_idx for target in feeder_tile.building.targets)
            )

        opposite_direction = get_opposite_direction(original_direction)
        if is_fed_from(opposite_direction):
            return original_direction

        for direction in CARDINAL_DIRECTIONS:
            if direction in {original_direction, opposite_direction}:
                continue
            if is_fed_from(direction):
                return get_opposite_direction(direction)

        return original_direction

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
                break

            if self.round_stopwatch.check_overtime():
                break

        if not candidate_entries:
            return False

        _, target_pos, original_direction = min(
            candidate_entries,
            key=lambda item: item[0],
        )
        target_tile = self.map.u_get_pos_tile(target_pos)
        facing_direction = self.u_get_splitter_direction_for_replaced_conveyor(
            target_tile,
            fallback_direction=original_direction,
        )
        if facing_direction is None or facing_direction == Direction.CENTRE:
            return False
        titanium_cost, axionite_cost = self.ct.get_splitter_cost()
        can_afford_splitter = (
            self.u_can_spend_titanium_without_falling_below_reserve(titanium_cost)
            and self.map.titanium >= titanium_cost
            and self.map.axionite >= axionite_cost
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

        if move_towards and self.u_move_to(target_pos):
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

        _, target_pos, original_direction = min(
            candidate_entries,
            key=lambda item: item[0],
        )
        target_tile = self.map.u_get_pos_tile(target_pos)
        facing_direction = self.u_get_splitter_direction_for_replaced_conveyor(
            target_tile,
            fallback_direction=original_direction,
        )
        if facing_direction is None or facing_direction == Direction.CENTRE:
            return False
        titanium_cost, axionite_cost = self.ct.get_splitter_cost()
        can_afford_splitter = (
            self.u_can_spend_titanium_without_falling_below_reserve(titanium_cost)
            and self.map.titanium >= titanium_cost
            and self.map.axionite >= axionite_cost
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
                if move_towards and self.u_move_to(target_pos):
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

            if move_towards and self.u_move_to(target_pos):
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
        tiles_by_index = self.map.tiles_by_index
        own_supply_link_source_indices_by_target_index = (
            self.map.own_supply_link_source_indices_by_target_index_in_vision
        )
        candidate_entries: list[tuple[tuple[int, int, int], Position]] = []

        def get_opposite_direction(direction: Direction) -> Direction:
            return (
                direction.rotate_left()
                .rotate_left()
                .rotate_left()
                .rotate_left()
            )

        for tile in self.map.own_supply_links_in_vision:
            if tile.last_seen_turn != current_round:
                continue
            if tile.building.team != own_team:
                continue
            if tile.building.entity_type not in CONVEYOR_ENTITY_TYPES:
                continue
            if tile.bot.id is not None:
                continue
            if not any(target_tile.is_core_of(own_team) for target_tile in tile.building.targets):
                continue
            incoming_source_indices = own_supply_link_source_indices_by_target_index.get(
                tile.index,
                (),
            )
            if any(
                tiles_by_index[source_idx].building.entity_type == EntityType.SPLITTER
                for source_idx in incoming_source_indices
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

            passing_conveyor_count = 0
            for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(tile.index):
                adjacent_tile = tiles_by_index[adjacent_idx]
                if adjacent_tile.last_seen_turn != current_round:
                    continue
                if adjacent_tile.building.team != own_team:
                    continue
                if adjacent_tile.building.entity_type not in CONVEYOR_ENTITY_TYPES:
                    continue
                if (
                    self.map.u_get_supply_chain_id_by_index(adjacent_tile.index, own_team)
                    != root
                ):
                    continue
                if any(target.index == tile.index for target in adjacent_tile.building.targets):
                    continue

                direction_to_target = self.map.u_get_direction_between(
                    adjacent_tile.position,
                    tile.position,
                )
                facing_direction = adjacent_tile.building.direction
                if (
                    direction_to_target is None
                    or direction_to_target == Direction.CENTRE
                    or facing_direction is None
                    or facing_direction == Direction.CENTRE
                ):
                    continue
                if facing_direction == get_opposite_direction(direction_to_target):
                    continue

                passing_conveyor_count += 1

            candidate_entries.append(
                (
                    (
                        -passing_conveyor_count,
                        tile.dist_to_self,
                        tile.index,
                    ),
                    tile.position,
                )
            )

            if self.round_stopwatch.check_overtime():
                break

        if not candidate_entries:
            return False

        titanium_cost, axionite_cost = self.ct.get_foundry_cost()
        for _, target_pos in sorted(candidate_entries, key=lambda item: item[0]):
            target_tile = self.map.u_get_pos_tile(target_pos)
            affordable = (
                self.u_can_spend_titanium_without_falling_below_reserve(titanium_cost)
                and self.map.titanium >= titanium_cost
                and self.map.axionite >= axionite_cost
            )
            if not affordable:
                if (
                    hold
                    and current_pos.distance_squared(target_pos)
                    <= BUILDER_ACTION_RADIUS_SQ
                ):
                    return True
                if not move_towards:
                    continue
                if self.u_move_to(target_pos):
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

            if move_towards and self.u_move_to(target_pos):
                return True

            if self.round_stopwatch.check_overtime():
                break

        return False

    def s_integrate_own_turret(
        self,
        move_towards: bool = True,
        hold: bool = True,
        candidate_radius: float | None = None,
    ):
        """
        Replace a nearby titanium-harvester-adjacent support tile with a turret.
        """
        own_team = self.map.own_team
        current_pos = self.map.current_pos
        tiles_by_index = self.map.tiles_by_index
        if candidate_radius is None:
            candidate_radius = math.sqrt(self.ct.get_vision_radius_sq()) - 2
        if candidate_radius < 0:
            candidate_radius = 0
        candidate_radius_sq = candidate_radius * candidate_radius

        candidate_entries: list[
            tuple[
                tuple[int, int, int, int],
                Position,
                EntityType,
                Direction,
                bool,
            ]
        ] = []
        candidate_seen_indices: set[int] = set()

        def is_own_harvester_feeder_tile(tile) -> bool:
            return (
                tile.building.team == own_team
                and tile.building.entity_type in CONVEYOR_ENTITY_TYPES
                and any(
                    target_tile.building.team == own_team
                    and target_tile.building.entity_type == EntityType.HARVESTER
                    for target_tile in tile.building.targets
                )
            )

        for harvester_tile in tiles_by_index:
            if harvester_tile.last_seen_turn < 0:
                continue
            if (
                harvester_tile.building.team != own_team
                or harvester_tile.building.entity_type != EntityType.HARVESTER
                or harvester_tile.environment != Environment.ORE_TITANIUM
            ):
                continue

            for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(
                harvester_tile.index
            ):
                if adjacent_idx in candidate_seen_indices:
                    continue

                adjacent_tile = tiles_by_index[adjacent_idx]
                if adjacent_tile.last_seen_turn < 0:
                    continue
                if adjacent_tile.position == current_pos or adjacent_tile.bot.id is not None:
                    continue
                if current_pos.distance_squared(adjacent_tile.position) > candidate_radius_sq:
                    continue

                is_candidate_tile = (
                    adjacent_tile.building.id is None
                    or (
                        adjacent_tile.building.team == own_team
                        and adjacent_tile.building.entity_type == EntityType.ROAD
                    )
                    or is_own_harvester_feeder_tile(adjacent_tile)
                    or (
                        adjacent_tile.building.team == own_team
                        and adjacent_tile.building.entity_type == EntityType.BARRIER
                    )
                )
                if not is_candidate_tile:
                    continue

                affordable_turret_plan = (
                    self._u_get_harvester_adjacent_turret_substitution(
                        adjacent_tile.position,
                        True,
                    )
                )
                fallback_turret_plan = affordable_turret_plan or (
                    self._u_get_harvester_adjacent_turret_substitution(
                        adjacent_tile.position,
                        True,
                        require_affordable=False,
                    )
                )
                if fallback_turret_plan is None:
                    continue

                build_entity_type, turret_direction = fallback_turret_plan
                candidate_seen_indices.add(adjacent_idx)
                candidate_entries.append(
                    (
                        (
                            0
                            if current_pos.distance_squared(adjacent_tile.position)
                            <= BUILDER_ACTION_RADIUS_SQ
                            else 1,
                            adjacent_tile.dist_to_self,
                            adjacent_tile.own_core_dist,
                            adjacent_tile.index,
                        ),
                        adjacent_tile.position,
                        build_entity_type,
                        turret_direction,
                        affordable_turret_plan is not None,
                    )
                )

                if self.round_stopwatch.check_overtime():
                    break

            if self.round_stopwatch.check_overtime():
                break

        if not candidate_entries:
            return False

        for _, target_pos, build_entity_type, turret_direction, can_build_now in sorted(
            candidate_entries,
            key=lambda item: item[0],
        ):
            target_tile = self.map.u_get_pos_tile(target_pos)
            in_range = current_pos.distance_squared(target_pos) <= BUILDER_ACTION_RADIUS_SQ

            if not can_build_now:
                if hold and in_range:
                    return True
                if not move_towards:
                    continue
                if self.u_move_to(target_pos):
                    return True
                continue

            if in_range:
                if target_tile.building.id is not None:
                    if not self.ct.can_destroy(target_pos):
                        continue
                    self.ct.destroy(target_pos)
                    target_tile.clear_building()

                can_build_method = getattr(self.ct, f"can_build_{build_entity_type.value}")
                build_method = getattr(self.ct, f"build_{build_entity_type.value}")
                if can_build_method(target_pos, turret_direction):
                    build_method(target_pos, turret_direction)
                    self.last_built_entity_type = build_entity_type
                    return True
                continue

            if move_towards and self.u_move_to(target_pos):
                return True
            if hold and in_range:
                return True

            if self.round_stopwatch.check_overtime():
                break

        return False

    def s_integrate_foundry_old(
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
                    if self.u_move_to(target_pos):
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
                if move_towards and self.u_move_to(target_pos):
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
        best_supply_idx = self.map.u_get_harvester_best_supply_tile(harvester_tile.index)
        if target_tile.index == best_supply_idx:
            return self.u_get_transport_supplier_build_plan_for_supply_chain(
                target_tile.position,
                resource,
                self.u_get_supply_chain_label_for_resource(resource),
            )

        if DISABLE_CONVEYORS_POINTING_AT_HARVESTERS:
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

    def s_turn_to_harassment(self):
        enemy_core_center_pos = self.map.enemy_core_center_pos
        if enemy_core_center_pos is None:
            return False
        if self.strategy == HARASSMENT_STRATEGY_ID:
            return False

        current_pos = self.map.current_pos
        if not any(
            current_pos.distance_squared(core_tile.position) == 1
            for core_tile in self.map.u_get_core_footprint_positions(enemy_core_center_pos)
        ):
            return False

        self.strategy = HARASSMENT_STRATEGY_ID
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

        def can_use_protect_harvester_tile(tile) -> bool:
            if tile.environment == Environment.WALL:
                return False
            if tile.is_enemy_turret_target_tile:
                return False
            if tile.building.id is None:
                return True
            return (
                tile.building.team == own_team
                and tile.building.entity_type == EntityType.ROAD
            )

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

                if not can_use_protect_harvester_tile(adjacent_tile):
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
                        and can_use_protect_harvester_tile(adjacent_tile)
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
        relevant supply chain(s), prioritizes gaps closer to the builder and then
        the core, and relies on the transport supplier planner to choose
        whether the tile should become a conveyor or a bridge plus its optimal
        target for the inferred resource.
        """
        if PREVENT_SUPPLY_LINKS_TILL_HARVESTER and self.harvesters_built == 0:
            return False

        own_team = self.map.own_team
        tiles_by_index = self.map.tiles_by_index
        get_own_core_dist = self.map.u_get_own_core_dist_by_index
        current_round = self.map.current_round
        own_supply_link_sources_by_target_index = (
            self.map.own_supply_link_source_indices_by_target_index_in_vision
        )
        continuable_root_cache: dict[int, bool] = {}

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

        def u_get_continuable_supply_chain_label_for_target(
            target_idx: int,
        ) -> SupplyChainLabel:
            source_indices = own_supply_link_sources_by_target_index.get(target_idx)
            if not source_indices:
                return SupplyChainLabel.NONE

            qualified_label = SupplyChainLabel.NONE
            seen_roots: set[int] = set()
            for source_idx in source_indices:
                root_idx = self.map.u_get_supply_chain_id_by_index(source_idx, own_team)
                if root_idx is None or root_idx in seen_roots:
                    continue
                seen_roots.add(root_idx)

                is_continuable = continuable_root_cache.get(root_idx)
                if is_continuable is None:
                    is_continuable = self.map.u_supply_chain_is_continuable(
                        source_idx,
                        own_team,
                    )
                    continuable_root_cache[root_idx] = is_continuable
                if is_continuable:
                    qualified_label |= tiles_by_index[source_idx].own_supply_chain_label

            return qualified_label

        def u_get_continuable_supply_chain_label_for_supply_tile(
            source_idx: int,
        ) -> SupplyChainLabel:
            root_idx = self.map.u_get_supply_chain_id_by_index(source_idx, own_team)
            if root_idx is None:
                return SupplyChainLabel.NONE

            is_continuable = continuable_root_cache.get(root_idx)
            if is_continuable is None:
                is_continuable = self.map.u_supply_chain_is_continuable(
                    source_idx,
                    own_team,
                )
                continuable_root_cache[root_idx] = is_continuable
            if not is_continuable:
                return SupplyChainLabel.NONE
            return tiles_by_index[source_idx].own_supply_chain_label

        candidate_entries: list[tuple[tuple[int, int], int, int, int]] = []
        candidate_seen_indices: set[int] = set()
        pending_target_idx: int | None = None
        pending_candidate_entry: tuple[tuple[int, int], int, int, int] | None = None
        pending_preferred_entry: tuple[tuple[int, int], int, int, int] | None = None
        pending_estimated_dist_to_self: int | None = None
        lowest_candidate_estimated_dist_to_self: int | None = None
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
                pending_label = u_get_continuable_supply_chain_label_for_target(
                    pending_target_idx
                )
                if pending_label != SupplyChainLabel.NONE:
                    candidate_seen_indices.add(pending_target_idx)
                    pending_estimated_dist_to_self = (
                        self.map.u_get_estimated_dist_to_self_by_index(
                            pending_target_idx
                        )
                    )
                    lowest_candidate_estimated_dist_to_self = (
                        pending_estimated_dist_to_self
                    )
                    pending_candidate_entry = (
                        (
                            pending_estimated_dist_to_self,
                            get_own_core_dist(pending_target_idx),
                        ),
                        -1,
                        pending_target_idx,
                        int(pending_label),
                    )
                    pending_preferred_entry = (
                        (-1, -1),
                        -1,
                        pending_target_idx,
                        int(pending_label),
                    )

        for encounter_order, target_tile in enumerate(
            self.map.own_missing_supply_links
        ):
            if self.round_stopwatch.check_overtime():
                break
            target_label = u_get_continuable_supply_chain_label_for_target(
                target_tile.index
            )
            if target_label == SupplyChainLabel.NONE:
                continue
            if not can_use_tile(target_tile):
                continue

            target_idx = target_tile.index
            if target_idx in candidate_seen_indices:
                continue
            candidate_seen_indices.add(target_idx)
            estimated_dist_to_self = self.map.u_get_estimated_dist_to_self_by_index(
                target_idx
            )
            if (
                lowest_candidate_estimated_dist_to_self is None
                or estimated_dist_to_self < lowest_candidate_estimated_dist_to_self
            ):
                lowest_candidate_estimated_dist_to_self = estimated_dist_to_self
            candidate_entries.append(
                (
                    (
                        estimated_dist_to_self,
                        get_own_core_dist(target_idx),
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
            ):
                continue

            splitter_label = u_get_continuable_supply_chain_label_for_supply_tile(
                splitter_tile.index
            )
            if splitter_label == SupplyChainLabel.NONE:
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
                estimated_dist_to_self = self.map.u_get_estimated_dist_to_self_by_index(
                    target_idx
                )
                if (
                    lowest_candidate_estimated_dist_to_self is None
                    or estimated_dist_to_self < lowest_candidate_estimated_dist_to_self
                ):
                    lowest_candidate_estimated_dist_to_self = estimated_dist_to_self
                candidate_entries.append(
                    (
                        (
                            estimated_dist_to_self,
                            get_own_core_dist(target_idx),
                        ),
                        splitter_encounter_order,
                        target_idx,
                        int(splitter_label),
                    )
                )
                splitter_encounter_order += 1

        if pending_candidate_entry is not None:
            if (
                lowest_candidate_estimated_dist_to_self is None
                or pending_estimated_dist_to_self is None
                or pending_estimated_dist_to_self
                - lowest_candidate_estimated_dist_to_self
                < 2
            ):
                candidate_entries.append(pending_preferred_entry)
            else:
                candidate_entries.append(pending_candidate_entry)

        if not candidate_entries:
            return False

        attempted_target_positions: list[Position] = []
        heapify(candidate_entries)
        while candidate_entries:
            _, _, target_idx, target_label = heappop(candidate_entries)
            target_tile = tiles_by_index[target_idx]
            attempted_target_positions.append(target_tile.position)
            supply_chain_label = SupplyChainLabel(target_label)
            for resource in u_get_candidate_resources(
                target_tile,
                supply_chain_label,
            ):
                supplier_type, supplier_target = (
                    self.u_get_transport_supplier_build_plan_for_supply_chain(
                        target_tile.position,
                        resource,
                        supply_chain_label,
                    )
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
                        respect_titanium_reserve=True,
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
                        respect_titanium_reserve=True,
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
        harvester_best_supply_idx_by_index: dict[int, int | None] = {}

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

        def get_harvester_best_supply_idx(harvester_idx: int) -> int | None:
            if harvester_idx not in harvester_best_supply_idx_by_index:
                harvester_best_supply_idx_by_index[harvester_idx] = (
                    self.map.u_get_harvester_best_supply_tile(harvester_idx)
                )
            return harvester_best_supply_idx_by_index[harvester_idx]

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
        ) -> tuple[EntityType | None, Direction | Position | None, bool]:
            best_supply_idx = get_harvester_best_supply_idx(harvester_tile.index)
            is_best_supply_tile = adjacent_tile.index == best_supply_idx
            def get_non_bridge_transport_conveyor_plan():
                conveyor_direction = self.u_best_conveyor_orientation(
                    adjacent_tile.position,
                    resource,
                    allow_adjacent_resource_sink=False,
                )
                if conveyor_direction is None:
                    return (None, None, False)
                return (EntityType.CONVEYOR, conveyor_direction, False)

            if is_best_supply_tile:
                supplier_type, supplier_target = (
                    self.u_get_harvester_adjacent_supplier_build_plan(
                        harvester_tile,
                        adjacent_tile,
                        resource,
                    )
                )
            elif DISABLE_CONVEYORS_POINTING_AT_HARVESTERS:
                return get_non_bridge_transport_conveyor_plan()
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
                return (supplier_type, supplier_target, False)
            if adjacent_tile.environment not in {
                Environment.ORE_TITANIUM,
                Environment.ORE_AXIONITE,
            }:
                return (supplier_type, supplier_target, not is_best_supply_tile)

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
                return (supplier_type, supplier_target, not is_best_supply_tile)
            if harvester_direction is not None and supplier_target == harvester_direction:
                return (EntityType.BARRIER, None, False)
            return (supplier_type, supplier_target, not is_best_supply_tile)

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
            if get_harvester_best_supply_idx(target_tile.index) is None:
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
                        (
                            supplier_type,
                            supplier_target,
                            safety_conveyor,
                        ) = get_harvester_safety_build_plan(
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
                                respect_titanium_reserve=True,
                                safety_conveyor=safety_conveyor,
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
                                respect_titanium_reserve=True,
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
                                respect_titanium_reserve=True,
                            ):
                                remember_pending_harvester_target(target_tile.index)
                                return finish_with_harvester_target(True, target_tile)

                    if current_pos != target_tile.position:
                        if not move_towards:
                            return False
                        moved = self.u_move_to(target_tile.position)
                        if moved:
                            remember_pending_harvester_target(target_tile.index)
                        return finish_with_harvester_target(moved, target_tile)

            if self.u_build_at(
                target_tile.position,
                EntityType.HARVESTER,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=attack_enemy_passable,
                respect_titanium_reserve=True,
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
            if (
                pending_target_tile.last_seen_turn == self.map.current_round
                and is_valid_harvester_target(pending_target_tile)
            ):
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
            if get_harvester_best_supply_idx(tile.index) is None:
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
                    (
                        supplier_type,
                        supplier_target,
                        safety_conveyor,
                    ) = get_harvester_safety_build_plan(
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
                            respect_titanium_reserve=True,
                            safety_conveyor=safety_conveyor,
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
                            respect_titanium_reserve=True,
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
                            respect_titanium_reserve=True,
                        ):
                            remember_pending_harvester_target(target_tile.index)
                            return finish_with_harvester_target(True, target_tile)

                if current_pos != target_tile.position:
                    if not move_towards:
                        return False
                    moved = self.u_move_to(target_tile.position)
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

                supplier_type, _, _ = get_harvester_safety_build_plan(
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
                (
                    supplier_type,
                    supplier_target,
                    safety_conveyor,
                ) = get_harvester_safety_build_plan(
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
                        safety_conveyor=safety_conveyor,
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

    def s_frontier_expand(self, min_titanium: int = 0):
        """
        Move toward the nearest reachable unseen frontier tile.

        Uses a single BFS from the builder to find the closest frontier layer,
        preferring lower own-core distance and stable coordinates among ties.
        If the builder is already standing in enemy turret range, retry once
        without turret avoidance so it does not freeze in place.
        """
        if self.map.titanium < min_titanium:
            return False

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
            road_titanium_cost, _ = self.ct.get_road_cost()
            if (
                self.ct.can_build_road(next_tile.position)
                and self.u_can_spend_titanium_without_falling_below_reserve(
                    road_titanium_cost
                )
            ):
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
            return self.u_move_to(target_tile.position)

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
            return self.u_move_to(target_tile.position)

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
        feeds an enemy turret, or if none exists, an enemy supply-link tile.
        As a lower-priority fallback, own supply-chain tiles that feed enemy
        barriers, foundries, harvesters, or launchers are only considered when
        a replacement supplier is plausible.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team
        conveyor_titanium_cost, _ = self.ct.get_conveyor_cost()
        bridge_titanium_cost, _ = self.ct.get_bridge_cost()
        rebuildable_structure_candidate_by_index: dict[int, bool] = {}

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

        def points_at_enemy_supply_link(source_tile) -> bool:
            return any(
                target_tile.building.id is not None
                and target_tile.building.team != own_team
                and target_tile.building.entity_type in SUPPLY_LINK_TYPES
                for target_tile in source_tile.building.targets
            )

        def points_at_enemy_rebuildable_structure(source_tile) -> bool:
            return any(
                target_tile.building.id is not None
                and target_tile.building.team != own_team
                and target_tile.building.entity_type
                in {
                    EntityType.BARRIER,
                    EntityType.FOUNDRY,
                    EntityType.HARVESTER,
                    EntityType.LAUNCHER,
                }
                for target_tile in source_tile.building.targets
            )

        def can_consider_rebuildable_structure_candidate(source_tile) -> bool:
            cached_result = rebuildable_structure_candidate_by_index.get(
                source_tile.index
            )
            if cached_result is not None:
                return cached_result

            if (
                not rebuild
                or source_tile.building.entity_type not in SUPPLY_LINK_TYPES
                or source_tile.own_supply_chain_label == SupplyChainLabel.NONE
            ):
                rebuildable_structure_candidate_by_index[source_tile.index] = False
                return False

            resource = infer_resource(source_tile)
            conveyor_direction = self.u_best_conveyor_orientation(
                source_tile.position,
                resource,
                allow_adjacent_resource_sink=False,
            )
            if conveyor_direction is not None:
                result = self.map.titanium >= conveyor_titanium_cost
                rebuildable_structure_candidate_by_index[source_tile.index] = result
                return result

            bridge_target = self.u_best_bridge_target(
                source_tile.position,
                resource,
            )
            result = (
                bridge_target is not None
                and self.map.titanium >= bridge_titanium_cost
            )
            rebuildable_structure_candidate_by_index[source_tile.index] = result
            return result

        def try_build_barrier_fallback(target_pos: Position) -> bool:
            return self.u_build_at(
                target_pos,
                EntityType.BARRIER,
                hold=False,
                move_towards=False,
                attack_enemy_passable=False,
            )

        enemy_turret_bucket = []
        enemy_supply_link_bucket = []
        enemy_rebuildable_structure_bucket = []
        for tile in dict.fromkeys(
            self.map.own_supply_links_in_vision + self.map.own_harvesters_in_vision
        ):
            if tile.building.team != own_team:
                continue
            if tile.building.entity_type not in SUPPLY_LINK_TYPES | {
                EntityType.HARVESTER
            }:
                continue
            if points_at_enemy_turret(tile):
                enemy_turret_bucket.append(tile)
                continue
            if points_at_enemy_supply_link(tile):
                enemy_supply_link_bucket.append(tile)
                continue
            if (
                points_at_enemy_rebuildable_structure(tile)
                and can_consider_rebuildable_structure_candidate(tile)
            ):
                enemy_rebuildable_structure_bucket.append(tile)

        candidate_bucket = (
            enemy_turret_bucket
            or enemy_supply_link_bucket
            or enemy_rebuildable_structure_bucket
        )
        target_tile = min(
            candidate_bucket,
            key=lambda tile: tile.dist_to_self,
            default=None,
        )

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
                if supplier_type is None or supplier_target is None:
                    return try_build_barrier_fallback(target_pos)
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
                    bridge_titanium_cost, bridge_axionite_cost = self.ct.get_bridge_cost()
                    if (
                        self.map.titanium < bridge_titanium_cost
                        or self.map.axionite < bridge_axionite_cost
                    ):
                        return try_build_barrier_fallback(target_pos)
                    if self.u_build_at(
                        target_pos,
                        supplier_type,
                        hold=False,
                        move_towards=False,
                        attack_enemy_passable=False,
                        target_pos=supplier_target,
                    ):
                        return True
                else:
                    return try_build_barrier_fallback(target_pos)

            return False
        if move_towards and self.u_move_to(target_pos):
            return False

        return False

    def s_turret_next_to_enemy_harvester(
        self,
        move_towards: bool = True,
        attack_enemy_passable: bool = False,
        hold: bool = False,
    ):
        """
        Build a turret next to the closest visible enemy harvester on titanium.

        Prefer nearby empty tiles, own roads, and optionally passable enemy
        roads, bridges, or regular conveyors.
        If `move_towards` is false, only act on targets already in action range.
        If `hold` is true, keep the step active once a valid build target exists
        but the team cannot yet afford the chosen turret.
        """
        current_pos = self.map.current_pos
        own_team = self.map.own_team
        current_tile = self.map.u_get_pos_tile(current_pos)
        closest_enemy_builder_bot_pos = self.map.closest_enemy_builder_bot_in_vision_pos
        enemy_builder_close_enough_for_enemy_road_attack = (
            closest_enemy_builder_bot_pos is not None
            and current_pos.distance_squared(closest_enemy_builder_bot_pos) <= 8
        )
        if (
            enemy_builder_close_enough_for_enemy_road_attack
            and
            current_tile.building.team != own_team
            and current_tile.building.entity_type == EntityType.ROAD
            and current_tile.building.hp is not None
            and current_tile.building.hp <= 2
        ):
            return bool(
                self.u_attack_passable(
                    current_pos,
                    move_towards=False,
                    destroy_condition=lambda _: True,
                )
            )

        enemy_harvesters = [
            tile
            for tile in self.map.enemy_harvesters_in_vision
            if tile.environment == Environment.ORE_TITANIUM
        ]
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

            build_entity_type, turret_direction = self.u_get_turret_build_plan(current_pos)
            get_cost_method = getattr(self.ct, f"get_{build_entity_type.value}_cost")
            titanium_cost, axionite_cost = get_cost_method()
            if (
                self.ct.get_action_cooldown() != 0
                or self.map.titanium < titanium_cost
                or self.map.axionite < axionite_cost
            ):
                return False

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
            can_build_method = getattr(self.ct, f"can_build_{build_entity_type.value}")
            build_method = getattr(self.ct, f"build_{build_entity_type.value}")
            if can_build_method(current_pos, turret_direction):
                build_method(current_pos, turret_direction)
                self.last_built_entity_type = build_entity_type
                return True
            return True

        if try_step_off_and_build_current_tile():
            return True

        tile_kind_by_pos: dict[Position, str | None] = {}
        ignore_enemy_bridges_and_conveyors = self.map.has_enemy_bot_in_vision

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
                    if (
                        candidate_tile.building.entity_type == EntityType.ROAD
                        and enemy_builder_close_enough_for_enemy_road_attack
                    ):
                        tile_kind_by_pos[pos] = "enemy_road"
                    elif (
                        not ignore_enemy_bridges_and_conveyors
                        and candidate_tile.building.entity_type == EntityType.BRIDGE
                    ):
                        tile_kind_by_pos[pos] = "enemy_bridge"
                    elif (
                        not ignore_enemy_bridges_and_conveyors
                        and candidate_tile.building.entity_type == EntityType.CONVEYOR
                    ):
                        tile_kind_by_pos[pos] = "enemy_conveyor"
                    else:
                        tile_kind_by_pos[pos] = None
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
            kind_rank = {
                "empty": 0,
                "own_road": 1,
                "enemy_road": 2,
                "enemy_bridge": 3,
                "enemy_conveyor": 4,
            }[kind]
            key = (tile.dist_to_self, kind_rank)
            if target_key is None or key < target_key:
                target_key = key
                target_tile = tile

        if target_tile is None:
            return False

        return bool(
            self.u_build_turret(
                target_tile.position,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=attack_enemy_passable,
            )
        )

    def _u_tile_points_at_index(self, tile, target_idx: int) -> bool:
        return any(target_tile.index == target_idx for target_tile in tile.building.targets)

    def _u_supply_tile_transports_titanium(self, tile) -> bool:
        current_round = self.map.current_round

        if tile.building.entity_type == EntityType.SPLITTER:
            return tile.building.last_titanium_onit_turn == current_round

        return self.map.u_supply_chain_has_titanium(tile.index, self.map.enemy_team)

    def _u_target_has_titanium_enemy_supply(self, target_idx: int) -> bool:
        current_round = self.map.current_round
        enemy_team = self.map.enemy_team
        tiles_by_index = self.map.tiles_by_index
        source_indices = self.map.enemy_supply_link_source_indices_by_target_index_in_vision.get(
            target_idx,
        )
        if not source_indices:
            return False

        checked_root_indices: set[int] = set()
        found_source = False
        for source_idx in source_indices:
            source_tile = tiles_by_index[source_idx]
            if (
                source_tile.last_seen_turn != current_round
                or source_tile.building.team != enemy_team
                or source_tile.building.entity_type not in SUPPLY_LINK_TYPES
            ):
                continue

            if source_tile.building.entity_type != EntityType.SPLITTER:
                root_idx = self.map.u_find_supply_chain_root_by_index(
                    source_idx,
                    enemy_team,
                )
                if root_idx is None or root_idx in checked_root_indices:
                    continue
                checked_root_indices.add(root_idx)

            found_source = True
            if not self._u_supply_tile_transports_titanium(source_tile):
                return False

        return found_source

    def _u_tile_is_currently_fed(self, tile) -> bool:
        current_round = self.map.current_round
        if tile.last_seen_turn != current_round:
            return False
        if (
            tile.index in self.map.own_supply_link_target_indices_in_vision
            or tile.index in self.map.enemy_supply_link_target_indices_in_vision
        ):
            return True

        for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(tile.index):
            adjacent_tile = self.map.tiles_by_index[adjacent_idx]
            if adjacent_tile.last_seen_turn != current_round:
                continue
            if adjacent_tile.building.entity_type in {
                EntityType.HARVESTER,
                EntityType.FOUNDRY,
            }:
                return True
        return False

    def _u_supply_tile_feeds_own_turret(self, tile) -> bool:
        current_round = self.map.current_round
        own_team = self.map.own_team
        if (
            tile.last_seen_turn != current_round
            or tile.building.team != own_team
            or tile.building.entity_type not in SUPPLY_LINK_TYPES
        ):
            return False

        if tile.building.entity_type != EntityType.SPLITTER:
            return self.map.u_own_supply_chain_feeds_own_turret(tile.index)

        pending_indices = [tile.index]
        seen_indices: set[int] = set()
        while pending_indices:
            current_idx = pending_indices.pop()
            if current_idx in seen_indices:
                continue
            seen_indices.add(current_idx)

            current_tile = self.map.tiles_by_index[current_idx]
            for target_tile in current_tile.building.targets:
                target_building = target_tile.building
                if (
                    target_tile.last_seen_turn != current_round
                    or target_tile.environment == Environment.WALL
                ):
                    continue
                if (
                    target_building.team == own_team
                    and target_building.entity_type in ATTACK_TURRET_TYPES
                ):
                    return True
                if (
                    target_building.team == own_team
                    and target_building.entity_type in SUPPLY_LINK_TYPES
                ):
                    if target_building.entity_type == EntityType.SPLITTER:
                        pending_indices.append(target_tile.index)
                    elif self.map.u_own_supply_chain_feeds_own_turret(
                        target_tile.index
                    ):
                        return True

        return False

    def _u_splitter_targets_only_own_buildings_or_walls(
        self,
        pos: Position,
        facing_direction: Direction,
    ) -> bool:
        own_team = self.map.own_team
        source_idx = self.map.u_to_index(pos)
        for output_direction in dict.fromkeys(
            (
                facing_direction,
                facing_direction.rotate_left().rotate_left(),
                facing_direction.rotate_right().rotate_right(),
            )
        ):
            target_idx = self.map.u_get_neighbor_index_by_direction(
                source_idx,
                output_direction,
            )
            if target_idx is None:
                return False

            target_tile = self.map.tiles_by_index[target_idx]
            if target_tile.environment == Environment.WALL or target_tile.is_core_of(
                own_team
            ):
                continue
            if (
                target_tile.building.id is not None
                and target_tile.building.team == own_team
            ):
                continue
            return False

        return True

    def _u_get_hijack_adjacent_own_turrets(self, target_idx: int) -> list:
        current_round = self.map.current_round
        own_team = self.map.own_team
        adjacent_turrets = []
        for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(target_idx):
            adjacent_tile = self.map.tiles_by_index[adjacent_idx]
            if (
                adjacent_tile.last_seen_turn == current_round
                and adjacent_tile.building.team == own_team
                and adjacent_tile.building.entity_type in ATTACK_TURRET_TYPES
            ):
                adjacent_turrets.append(adjacent_tile)
        return adjacent_turrets

    def _u_get_hijack_incoming_conveyors(self, target_idx: int) -> list:
        current_round = self.map.current_round
        incoming_conveyors = []
        for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(target_idx):
            adjacent_tile = self.map.tiles_by_index[adjacent_idx]
            if (
                adjacent_tile.last_seen_turn != current_round
                or adjacent_tile.building.entity_type not in CONVEYOR_ENTITY_TYPES
            ):
                continue
            if self._u_tile_points_at_index(adjacent_tile, target_idx):
                incoming_conveyors.append(adjacent_tile)
        return incoming_conveyors

    def _u_get_best_hijack_adjacent_turret(self, adjacent_turrets: list):
        if not adjacent_turrets:
            return None
        return min(
            adjacent_turrets,
            key=lambda tile: (self._u_tile_is_currently_fed(tile), tile.index),
        )

    def _u_get_hijack_bridge_turret_target(self, source_pos: Position):
        current_round = self.map.current_round
        own_team = self.map.own_team
        enemy_team = self.map.enemy_team
        active_mask = self.map.active_mask_by_index
        tiles_by_index = self.map.tiles_by_index
        source_x = source_pos.x
        source_y = source_pos.y

        candidates = []
        for dx, dy in _HIJACK_BRIDGE_TARGET_OFFSETS:
            target_x = source_x + dx
            target_y = source_y + dy
            if (
                target_x < 0
                or target_y < 0
                or target_x >= self.map.width
                or target_y >= self.map.height
            ):
                continue
            target_idx = self.map.u_to_index_xy(target_x, target_y)
            if not active_mask[target_idx]:
                continue

            target_tile = tiles_by_index[target_idx]
            if (
                target_tile.last_seen_turn != current_round
                or target_tile.building.team != own_team
                or target_tile.building.entity_type not in ATTACK_TURRET_TYPES
                or not self.ct.can_build_bridge(source_pos, target_tile.position)
            ):
                continue
            candidates.append(target_tile)

        if not candidates:
            return None

        def narrow(predicate) -> bool:
            nonlocal candidates
            filtered_candidates = [tile for tile in candidates if predicate(tile)]
            if filtered_candidates:
                candidates = filtered_candidates
            return len(candidates) == 1

        if narrow(
            lambda tile: any(
                target_tile.is_core_of(enemy_team)
                for target_tile in tile.building.targets
            )
        ):
            return candidates[0]
        if narrow(lambda tile: not self._u_tile_is_currently_fed(tile)):
            return candidates[0]
        if narrow(lambda tile: tile.building.entity_type == EntityType.GUNNER):
            return candidates[0]

        return min(candidates, key=lambda tile: tile.index)

    def _u_get_hijack_bridge_supply_target(self, source_pos: Position):
        current_round = self.map.current_round
        own_team = self.map.own_team
        active_mask = self.map.active_mask_by_index
        tiles_by_index = self.map.tiles_by_index
        source_x = source_pos.x
        source_y = source_pos.y

        best_tile = None
        for dx, dy in _HIJACK_BRIDGE_TARGET_OFFSETS:
            target_x = source_x + dx
            target_y = source_y + dy
            if (
                target_x < 0
                or target_y < 0
                or target_x >= self.map.width
                or target_y >= self.map.height
            ):
                continue
            target_idx = self.map.u_to_index_xy(target_x, target_y)
            if not active_mask[target_idx]:
                continue

            target_tile = tiles_by_index[target_idx]
            if (
                target_tile.last_seen_turn != current_round
                or target_tile.building.team != own_team
                or target_tile.building.entity_type not in SUPPLY_LINK_TYPES
                or not self._u_supply_tile_feeds_own_turret(target_tile)
                or not self.ct.can_build_bridge(source_pos, target_tile.position)
            ):
                continue
            if best_tile is None or target_tile.index < best_tile.index:
                best_tile = target_tile

        return best_tile

    def _u_get_enemy_supply_target_tile(self):
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

        return target_tile

    def s_block_enemy_supply_chain(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ):
        """
        Block a hijackable enemy supply target by building a barrier on it.

        Uses the same target selection and titanium-presence gate as
        `s_hijack_enemy_supply_chain`, but once the tile qualifies it builds a
        barrier directly instead of considering allied supply-link builds.
        """
        target_tile = self._u_get_enemy_supply_target_tile()
        if target_tile is None:
            return False

        conveyor_titanium_cost, conveyor_axionite_cost = self.ct.get_conveyor_cost()
        can_afford_conveyor = (
            self.map.titanium >= conveyor_titanium_cost
            and self.map.axionite >= conveyor_axionite_cost
        )
        if not can_afford_conveyor or not self._u_target_has_titanium_enemy_supply(
            target_tile.index
        ):
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

    def s_hijack_enemy_supply_chain(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ):
        """
        Build on the closest visible enemy resource target, preferring a hijack.

        When the targeted enemy supply input is carrying titanium, try to
        convert that target tile into an allied supply tile that feeds nearby
        turrets or downstream allied turret chains. If no hijack build works,
        return `False` instead of building a barrier.
        """
        own_team = self.map.own_team
        current_round = self.map.current_round

        target_tile = self._u_get_enemy_supply_target_tile()
        if target_tile is None:
            return False

        conveyor_titanium_cost, conveyor_axionite_cost = self.ct.get_conveyor_cost()
        can_afford_conveyor = (
            self.map.titanium >= conveyor_titanium_cost
            and self.map.axionite >= conveyor_axionite_cost
        )
        if not can_afford_conveyor or not self._u_target_has_titanium_enemy_supply(
            target_tile.index
        ):
            return False

        adjacent_own_turrets = self._u_get_hijack_adjacent_own_turrets(target_tile.index)
        if len(adjacent_own_turrets) == 1:
            turret_tile = adjacent_own_turrets[0]
            turret_direction = self.map.u_get_direction_between(
                target_tile.position,
                turret_tile.position,
            )
            if turret_direction is not None and self.u_build_at(
                target_tile.position,
                EntityType.CONVEYOR,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=True,
                facing_direction=turret_direction,
            ):
                return True

        elif len(adjacent_own_turrets) == 3:
            splitter_titanium_cost, splitter_axionite_cost = self.ct.get_splitter_cost()
            can_afford_splitter = (
                self.map.titanium >= splitter_titanium_cost
                and self.map.axionite >= splitter_axionite_cost
            )
            if can_afford_splitter:
                incoming_conveyors = self._u_get_hijack_incoming_conveyors(
                    target_tile.index
                )
                if len(incoming_conveyors) == 1:
                    splitter_direction = self.map.u_get_direction_between(
                        incoming_conveyors[0].position,
                        target_tile.position,
                    )
                    exact_splitter_direction = (
                        self.u_get_splitter_direction_for_target_directions(
                            *(
                                self.map.u_get_direction_between(
                                    target_tile.position,
                                    turret_tile.position,
                                )
                                for turret_tile in adjacent_own_turrets
                            )
                        )
                    )
                    if (
                        splitter_direction is not None
                        and splitter_direction == exact_splitter_direction
                        and self._u_splitter_targets_only_own_buildings_or_walls(
                            target_tile.position,
                            splitter_direction,
                        )
                        and self.u_build_at(
                            target_tile.position,
                            EntityType.SPLITTER,
                            hold=hold,
                            move_towards=move_towards,
                            attack_enemy_passable=True,
                            facing_direction=splitter_direction,
                        )
                    ):
                        return True

            turret_tile = self._u_get_best_hijack_adjacent_turret(adjacent_own_turrets)
            if turret_tile is not None:
                turret_direction = self.map.u_get_direction_between(
                    target_tile.position,
                    turret_tile.position,
                )
                if turret_direction is not None and self.u_build_at(
                    target_tile.position,
                    EntityType.CONVEYOR,
                    hold=hold,
                    move_towards=move_towards,
                    attack_enemy_passable=True,
                    facing_direction=turret_direction,
                ):
                    return True

        if not adjacent_own_turrets:
            adjacent_supply_tile = None
            for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(
                target_tile.index
            ):
                candidate_tile = self.map.tiles_by_index[adjacent_idx]
                if (
                    candidate_tile.last_seen_turn != current_round
                    or candidate_tile.building.team != own_team
                    or candidate_tile.building.entity_type not in SUPPLY_LINK_TYPES
                    or not self._u_supply_tile_feeds_own_turret(candidate_tile)
                ):
                    continue
                if (
                    candidate_tile.building.entity_type
                    in CONVEYOR_ENTITY_TYPES | {EntityType.SPLITTER}
                    and self._u_tile_points_at_index(candidate_tile, target_tile.index)
                ):
                    continue
                if (
                    adjacent_supply_tile is None
                    or candidate_tile.index < adjacent_supply_tile.index
                ):
                    adjacent_supply_tile = candidate_tile

            if adjacent_supply_tile is not None:
                supply_direction = self.map.u_get_direction_between(
                    target_tile.position,
                    adjacent_supply_tile.position,
                )
                if supply_direction is not None and self.u_build_at(
                    target_tile.position,
                    EntityType.CONVEYOR,
                    hold=hold,
                    move_towards=move_towards,
                    attack_enemy_passable=True,
                    facing_direction=supply_direction,
                ):
                    return True

        bridge_titanium_cost, bridge_axionite_cost = self.ct.get_bridge_cost()
        can_afford_bridge = (
            self.map.titanium >= bridge_titanium_cost
            and self.map.axionite >= bridge_axionite_cost
        )

        if can_afford_bridge:
            bridge_turret_target = self._u_get_hijack_bridge_turret_target(
                target_tile.position
            )
            if bridge_turret_target is not None and self.u_build_at(
                target_tile.position,
                EntityType.BRIDGE,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=True,
                target_pos=bridge_turret_target.position,
            ):
                return True

            bridge_supply_target = self._u_get_hijack_bridge_supply_target(
                target_tile.position
            )
            if bridge_supply_target is not None and self.u_build_at(
                target_tile.position,
                EntityType.BRIDGE,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=True,
                target_pos=bridge_supply_target.position,
            ):
                return True

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
        Patrol known allied supply links.

        The builder stamps its current tile plus all adjacent tiles with its
        current patrol index whenever those tiles hold allied supply-link
        structures. If a visible supply gap can be rebuilt, this delegates to
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

        patrol_target_indices = get_unpatrolled_target_indices()
        if not patrol_target_indices:
            self.supply_patrol_index += 1
            stamp_local_patrol_coverage()
            patrol_target_indices = get_unpatrolled_target_indices()

        for target_idx in patrol_target_indices:
            if self.u_move_to(tiles_by_index[target_idx].position):
                return True

            if self.round_stopwatch.check_overtime():
                break

        if not any(self.map.enemy_turret_target_by_index):
            return False

        # Second pass: if we still haven't found a valid move, allow the bot to travel near enemy turrets
        for target_idx in patrol_target_indices:
            if self.u_move_to(
                tiles_by_index[target_idx].position, avoid_enemy_turrets=False
            ):
                return True

            if self.round_stopwatch.check_overtime():
                break

        return False

    def s_attack_enemy_harvester_supply_link(
        self,
        move_towards: bool = True,
        require_no_enemy_bbs_in_range: bool = True,
    ):
        """
        Attack the closest enemy supply link next to a visible enemy harvester.

        Uses cached enemy harvester positions, keeps only adjacent enemy
        conveyor or bridge tiles that the builder can stand on, and then either
        attacks from the current tile or moves toward the best target.
        """
        if require_no_enemy_bbs_in_range and self.map.has_enemy_bot_in_vision:
            return False

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

    def s_attack_enemy_core_supply_link(
        self,
        move_towards: bool = True,
        wait_if_enemy_builder_bots_in_range: bool = True,
    ):
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

        if (
            wait_if_enemy_builder_bots_in_range
            and self.map.has_enemy_bot_in_vision
            and current_pos == target_tile.position
            and not self._is_visible_building_damaged(target_tile)
        ):
            return True

        return bool(
            self.u_attack_passable(
                target_tile.position,
                move_towards=move_towards,
                destroy_condition=lambda _: True,
            )
        )

    def s_move_out_of_gunner_range(self):
        current_pos = self.map.current_pos
        current_tile = self.map.u_get_pos_tile(current_pos)
        if not current_tile.is_enemy_gunner_ray_first_target:
            return False

        respect_titanium_reserve_for_road_build = (
            self.u_should_respect_titanium_reserve_for_road_build(False)
        )
        road_titanium_cost, _ = self.ct.get_road_cost()
        best_candidate_tile = None
        best_candidate_direction = None
        best_candidate_key = None

        for safe_order, adjacent_pos in enumerate(
            self.map.u_iter_adjacent_all_positions(current_pos)
        ):
            adjacent_tile = self.map.u_get_pos_tile(adjacent_pos)
            if adjacent_tile.is_enemy_gunner_ray_first_target:
                continue

            move_direction = self.map.u_get_direction_between(
                current_pos,
                adjacent_pos,
            )
            if move_direction is None:
                continue

            can_move = self.ct.can_move(move_direction)
            can_build_road = (
                not can_move
                and self.ct.can_build_road(adjacent_pos)
                and (
                    not respect_titanium_reserve_for_road_build
                    or self.u_can_spend_titanium_without_falling_below_reserve(
                        road_titanium_cost
                    )
                )
            )
            if not can_move and not can_build_road:
                continue

            key = (
                1 if adjacent_tile.is_enemy_turret_target_tile else 0,
                0 if can_move else 1,
                adjacent_tile.own_core_dist,
                adjacent_tile.dist_to_self,
                safe_order,
                adjacent_tile.index,
            )
            if best_candidate_key is None or key < best_candidate_key:
                best_candidate_key = key
                best_candidate_tile = adjacent_tile
                best_candidate_direction = move_direction

        if best_candidate_tile is None or best_candidate_direction is None:
            return False

        return bool(
            self.u_try_progress_move_step(
                best_candidate_tile,
                best_candidate_direction,
                best_candidate_tile.position,
                build_new_roads=True,
                allow_conveyor_building=False,
                respect_titanium_reserve_for_road_build=False,
            )
        )

    def s_attack_key_enemy_supply_chain(
        self,
        move_towards: bool = True,
        wait_if_enemy_builder_bots_in_range: bool = True,
    ):
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
            and not current_tile.is_enemy_spin_gunner_ray_first_target
        ):
            if (
                wait_if_enemy_builder_bots_in_range
                and self.map.has_enemy_bot_in_vision
                and not self._is_visible_building_damaged(current_tile)
            ):
                return True
            return bool(
                self.u_attack_passable(
                    current_pos,
                    move_towards=False,
                    destroy_condition=lambda _: True,
                    avoid_enemy_turrets=False,
                    ignore_conveyor_reserve_if_target_damaged=True,
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
            if tile.is_enemy_spin_gunner_ray_first_target:
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

        if (
            wait_if_enemy_builder_bots_in_range
            and self.map.has_enemy_bot_in_vision
            and current_pos == target_tile.position
            and not self._is_visible_building_damaged(target_tile)
        ):
            return True

        return bool(
            self.u_attack_passable(
                target_tile.position,
                move_towards=move_towards,
                destroy_condition=lambda _: True,
                ignore_conveyor_reserve_if_target_damaged=True,
            )
        )

    def s_build_enemy_supplied_turret(
        self,
        move_towards: bool = True,
        hold: bool = True,
        candidate_radius: float | None = None,
    ):
        """
        Build a turret on a tile currently fed by a recently active enemy supplier.

        Considers visible target tiles of enemy conveyors, splitters, armoured
        conveyors, and bridges whose last seen carried resource was within the
        last three turns. If the builder is already standing on the chosen build
        tile, it first steps off that tile so the turret can be built from the
        new position on the following turn. Prefer a sentinel over a gunner only
        when the sentinel can target the enemy core while the gunner cannot, or
        once the scaled titanium preference threshold is reached. Candidate
        target tiles are limited to the configured radius around the builder.
        """
        current_pos = self.map.current_pos
        current_round = self.map.current_round
        own_team = self.map.own_team
        enemy_team = self.map.enemy_team
        candidate_keys_by_index: dict[int, tuple[int, int, int, int, int]] = {}
        tiles_by_index = self.map.tiles_by_index
        if candidate_radius is None:
            candidate_radius = math.sqrt(self.ct.get_vision_radius_sq()) - 2
        if candidate_radius < 0:
            candidate_radius = 0
        candidate_radius_sq = candidate_radius * candidate_radius
        scale_ratio = max(0.0001, self.ct.get_scale_percent() / 100.0)
        prefer_sentinel_over_gunner_min_titanium = int(
            math.ceil(PREFER_SENTINEL_OVER_GUNNER_MIN_TITANIUM * scale_ratio)
        )
        sentinel_titanium_cost, sentinel_axionite_cost = self.ct.get_sentinel_cost()

        enemy_core_tiles: list = []
        if self.map.enemy_core_center_pos is not None:
            enemy_core_tiles = self.map.u_get_core_footprint_positions(
                self.map.enemy_core_center_pos
            )
        elif self.map.enemy_core_center_pos_candidates:
            enemy_core_tile_by_index: dict[int, object] = {}
            for _, candidate_center_pos in self.map.enemy_core_center_pos_candidates:
                for core_tile in self.map.u_get_core_footprint_positions(
                    candidate_center_pos
                ):
                    enemy_core_tile_by_index.setdefault(core_tile.index, core_tile)
            enemy_core_tiles = list(enemy_core_tile_by_index.values())

        def can_host_turret(target_tile) -> bool:
            if target_tile.last_seen_turn != current_round:
                return False
            if target_tile.is_core_of(enemy_team):
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

        def sentinel_targets_enemy_core(
            pos: Position,
            facing_direction: Direction | None,
        ) -> bool:
            if (
                facing_direction is None
                or facing_direction == Direction.CENTRE
                or not enemy_core_tiles
            ):
                return False
            return any(
                self.map.u_sentinel_covers_target(
                    pos,
                    facing_direction,
                    core_tile.position,
                    GameConstants.SENTINEL_VISION_RADIUS_SQ,
                )
                for core_tile in enemy_core_tiles
            )

        def gunner_targets_enemy_core(
            pos: Position,
            facing_direction: Direction | None,
        ) -> bool:
            if (
                facing_direction is None
                or facing_direction == Direction.CENTRE
                or not enemy_core_tiles
            ):
                return False
            return any(
                self.map.u_gunner_covers_target(
                    pos,
                    facing_direction,
                    core_tile.position,
                    GameConstants.GUNNER_VISION_RADIUS_SQ,
                )
                for core_tile in enemy_core_tiles
            )

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
                if not can_host_turret(target_tile):
                    continue
                if (
                    current_pos.distance_squared(target_tile.position)
                    > candidate_radius_sq
                ):
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
                        "Build enemy supplied turret: step off",
                        target_tile.position,
                    )
                    return True
                continue

            build_entity_type = EntityType.GUNNER
            build_direction = self.u_get_gunner_orientation(target_tile.position)
            can_afford_sentinel = (
                self.map.titanium >= sentinel_titanium_cost
                and self.map.axionite >= sentinel_axionite_cost
            )
            if can_afford_sentinel:
                sentinel_direction = self.u_get_sentinel_orientation(
                    target_tile.position
                )
                if (
                    (
                        sentinel_targets_enemy_core(
                            target_tile.position,
                            sentinel_direction,
                        )
                        and not gunner_targets_enemy_core(
                            target_tile.position,
                            build_direction,
                        )
                    )
                    or self.map.titanium
                    >= prefer_sentinel_over_gunner_min_titanium
                ):
                    build_entity_type = EntityType.SENTINEL
                    build_direction = sentinel_direction

            if self.u_build_at(
                target_tile.position,
                build_entity_type,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=False,
                facing_direction=build_direction,
            ):
                if self.last_built_entity_type in {
                    EntityType.GUNNER,
                    EntityType.SENTINEL,
                }:
                    print(
                        "Build enemy supplied turret: built",
                        self.last_built_entity_type.value,
                        "at",
                        target_tile.position,
                        "facing",
                        build_direction,
                    )
                elif (
                    current_pos.distance_squared(target_tile.position)
                    > BUILDER_ACTION_RADIUS_SQ
                ):
                    print(
                        "Build enemy supplied turret: move toward",
                        target_tile.position,
                        "for",
                        build_entity_type.value,
                    )
                else:
                    print(
                        "Build enemy supplied turret: hold for",
                        target_tile.position,
                        "with",
                        build_entity_type.value,
                    )
                return True

            if self.round_stopwatch.check_overtime():
                break

        return False

    def s_gunner_next_to_enemy_core(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ):
        """
        Build a gunner on a tile currently fed by a recently active enemy supplier,
        but only when directly facing the enemy core would put the core on the
        gunner ray.
        """
        current_pos = self.map.current_pos
        current_round = self.map.current_round
        own_team = self.map.own_team
        enemy_team = self.map.enemy_team
        candidate_keys_by_index: dict[int, tuple[int, int, int, int, int]] = {}
        tiles_by_index = self.map.tiles_by_index
        all_own_supply_link_target_indices_in_vision = (
            self.map.all_own_supply_link_target_indices_in_vision
        )
        enemy_supply_link_target_indices_in_vision = (
            self.map.enemy_supply_link_target_indices_in_vision
        )

        enemy_core_tiles: list = []
        if self.map.enemy_core_center_pos is not None:
            enemy_core_tiles = self.map.u_get_core_footprint_positions(
                self.map.enemy_core_center_pos
            )
        elif self.map.enemy_core_center_pos_candidates:
            enemy_core_tile_by_index: dict[int, object] = {}
            for _, candidate_center_pos in self.map.enemy_core_center_pos_candidates:
                for core_tile in self.map.u_get_core_footprint_positions(
                    candidate_center_pos
                ):
                    enemy_core_tile_by_index.setdefault(core_tile.index, core_tile)
            enemy_core_tiles = list(enemy_core_tile_by_index.values())
        if not enemy_core_tiles:
            return False
        enemy_core_indices = {core_tile.index for core_tile in enemy_core_tiles}

        def can_host_gunner(target_tile) -> bool:
            if target_tile.last_seen_turn != current_round:
                return False
            if target_tile.is_core_of(enemy_team):
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

        def gunner_targets_enemy_core_directly(target_tile) -> bool:
            facing_direction = self.u_get_direction_toward_enemy_core_center(target_tile.position)
            if facing_direction == Direction.CENTRE:
                return False
            return any(
                self.map.u_gunner_covers_target(
                    target_tile.position,
                    facing_direction,
                    core_tile.position,
                    GameConstants.GUNNER_VISION_RADIUS_SQ,
                )
                for core_tile in enemy_core_tiles
            )

        def adjacent_turret_targets_enemy_core(adjacent_tile) -> bool:
            facing_direction = adjacent_tile.building.direction
            if facing_direction is None or facing_direction == Direction.CENTRE:
                return False

            if adjacent_tile.building.entity_type == EntityType.GUNNER:
                return any(
                    self.map.u_gunner_covers_target(
                        adjacent_tile.position,
                        facing_direction,
                        core_tile.position,
                        GameConstants.GUNNER_VISION_RADIUS_SQ,
                    )
                    for core_tile in enemy_core_tiles
                )

            return any(
                self.map.u_sentinel_covers_target(
                    adjacent_tile.position,
                    facing_direction,
                    core_tile.position,
                    GameConstants.SENTINEL_VISION_RADIUS_SQ,
                )
                for core_tile in enemy_core_tiles
            )

        def adjacent_turret_is_unfed_and_targets_enemy_core(adjacent_tile) -> bool:
            return (
                adjacent_tile.last_seen_turn == current_round
                and adjacent_tile.building.team == own_team
                and adjacent_tile.building.entity_type
                in {EntityType.GUNNER, EntityType.SENTINEL}
                and adjacent_tile.index
                not in all_own_supply_link_target_indices_in_vision
                and adjacent_tile.index
                not in enemy_supply_link_target_indices_in_vision
                and adjacent_turret_targets_enemy_core(adjacent_tile)
            )

        def try_feed_adjacent_core_turret(target_tile) -> bool:
            adjacent_gunner_tiles = []
            adjacent_sentinel_tiles = []

            for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(
                target_tile.index
            ):
                adjacent_tile = tiles_by_index[adjacent_idx]
                if not adjacent_turret_is_unfed_and_targets_enemy_core(adjacent_tile):
                    continue
                if adjacent_tile.building.entity_type == EntityType.GUNNER:
                    adjacent_gunner_tiles.append(adjacent_tile)
                else:
                    adjacent_sentinel_tiles.append(adjacent_tile)

            conveyor_target_tile = None
            if adjacent_gunner_tiles:
                conveyor_target_tile = min(
                    adjacent_gunner_tiles,
                    key=lambda tile: tile.index,
                )
            elif adjacent_sentinel_tiles:
                conveyor_target_tile = min(
                    adjacent_sentinel_tiles,
                    key=lambda tile: tile.index,
                )

            if conveyor_target_tile is None:
                return False

            conveyor_direction = self.map.u_get_direction_between(
                target_tile.position,
                conveyor_target_tile.position,
            )
            if conveyor_direction is None:
                return False

            if self.u_build_at(
                target_tile.position,
                EntityType.CONVEYOR,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=False,
                facing_direction=conveyor_direction,
            ):
                print(
                    "Gunner next to enemy core: feed adjacent",
                    conveyor_target_tile.building.entity_type.value,
                    conveyor_target_tile.position,
                    "from",
                    target_tile.position,
                )
                return True

            return False

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
                if not can_host_gunner(target_tile):
                    continue
                if not gunner_targets_enemy_core_directly(target_tile):
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
            if try_feed_adjacent_core_turret(target_tile):
                return True

            if target_tile.position == current_pos:
                if move_towards and step_off_current_build_tile(target_tile):
                    print(
                        "Gunner next to enemy core: step off",
                        target_tile.position,
                    )
                    return True
                continue

            gunner_direction = self.u_get_direction_toward_enemy_core_center(target_tile.position)
            if self.u_build_at(
                target_tile.position,
                EntityType.GUNNER,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=False,
                facing_direction=gunner_direction,
            ):
                if self.last_built_entity_type == EntityType.GUNNER:
                    print(
                        "Gunner next to enemy core: built at",
                        target_tile.position,
                        "facing",
                        gunner_direction,
                    )
                elif (
                    current_pos.distance_squared(target_tile.position)
                    > BUILDER_ACTION_RADIUS_SQ
                ):
                    print(
                        "Gunner next to enemy core: move toward",
                        target_tile.position,
                    )
                else:
                    print(
                        "Gunner next to enemy core: hold for",
                        target_tile.position,
                    )
                return True

            if self.round_stopwatch.check_overtime():
                break

        return False

    def s_replace_damaged_conveyor(
        self,
        move_towards: bool = True,
        hold: bool = True,
    ):
        own_team = self.map.own_team
        conveyor_titanium_cost, _ = self.ct.get_conveyor_cost()
        if self.map.titanium < conveyor_titanium_cost:
            return False

        candidate_tiles = self.map.own_buildings_healable_in_action_range
        if not candidate_tiles:
            candidate_tiles = self.map.own_buildings_needing_heal
        if not candidate_tiles:
            return False

        target_tile = min(
            (
                tile
                for tile in dict.fromkeys(candidate_tiles)
                if (
                    tile.building.team == own_team
                    and tile.building.entity_type == EntityType.CONVEYOR
                    and tile.building.hp is not None
                    and tile.building.hp <= REPLACE_ATTACKED_CONVEYOR_MAX_HP
                )
            ),
            key=lambda tile: (
                tile.dist_to_self,
                tile.own_core_dist,
            ),
            default=None,
        )
        if target_tile is None:
            return False

        facing_direction = target_tile.building.direction
        if facing_direction is None or facing_direction == Direction.CENTRE:
            return False

        if (
            self.map.current_pos.distance_squared(target_tile.position)
            <= BUILDER_ACTION_RADIUS_SQ
            and self.ct.can_destroy(target_tile.position)
        ):
            self.ct.destroy(target_tile.position)
            target_tile.clear_building()
            return bool(
                self.u_build_at(
                    target_tile.position,
                    EntityType.CONVEYOR,
                    hold=hold,
                    move_towards=False,
                    attack_enemy_passable=False,
                    facing_direction=facing_direction,
                )
            )

        return bool(
            self.u_build_at(
                target_tile.position,
                EntityType.CONVEYOR,
                hold=hold,
                move_towards=move_towards,
                attack_enemy_passable=False,
                facing_direction=facing_direction,
            )
        )

    def s_heal_own_building(
        self,
        move_towards: bool = True,
        hold: bool = True,
        candidate_radius: float | None = None,
    ):
        """
        Heal the highest-priority damaged allied tile, preferring immediate heals.

        If any damaged allied tile is already healable this turn, only those
        in-range candidates are considered. Otherwise the builder targets the
        remaining visible damaged allied tiles and moves toward the best one.
        Only tiles within `candidate_radius` Euclidean distance of the builder
        are considered; by default this is the builder's full vision radius.
        Priorities are: critically damaged core first (at or below one third of
        max HP), then tiles with a damaged own builder bot standing on them,
        then by building type in this order: bridge,
        conveyor, road, foundry, harvester, armoured conveyor, splitter,
        sentinel, gunner, launcher, breach, barrier, noncritical core. Ties
        are broken by distance to self and then distance to own core.
        """
        own_team = self.map.own_team
        current_pos = self.map.current_pos
        all_own_supply_link_target_indices_in_vision = (
            self.map.all_own_supply_link_target_indices_in_vision
        )
        enemy_supply_link_target_indices_in_vision = (
            self.map.enemy_supply_link_target_indices_in_vision
        )
        if candidate_radius is None:
            candidate_radius = math.sqrt(self.ct.get_vision_radius_sq())
        if candidate_radius < 0:
            candidate_radius = 0
        candidate_radius_sq = candidate_radius * candidate_radius

        def can_consider_heal_candidate(tile) -> bool:
            if tile.building.team != own_team:
                return False
            if tile.building.entity_type != EntityType.GUNNER:
                return True
            return (
                tile.index in all_own_supply_link_target_indices_in_vision
                or tile.index in enemy_supply_link_target_indices_in_vision
            )

        candidate_tiles = [
            tile
            for tile in self.map.own_buildings_healable_in_action_range
            if current_pos.distance_squared(tile.position) <= candidate_radius_sq
            and can_consider_heal_candidate(tile)
        ]
        if not candidate_tiles:
            candidate_tiles = [
                tile
                for tile in self.map.own_buildings_needing_heal
                if current_pos.distance_squared(tile.position) <= candidate_radius_sq
                and can_consider_heal_candidate(tile)
            ]
        if not candidate_tiles:
            return False

        building_type_rank = {
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
            EntityType.CORE: 14,
        }

        def has_damaged_own_builder(tile) -> bool:
            return bool(
                tile.bot.id is not None
                and tile.bot.team == own_team
                and tile.bot.hp < self.ct.get_max_hp(tile.bot.id)
            )

        def is_critical_core(tile) -> bool:
            if (
                tile.building.entity_type != EntityType.CORE
                or tile.building.id is None
                or tile.building.hp is None
            ):
                return False
            return tile.building.hp * 3 <= self.ct.get_max_hp(tile.building.id)

        target_tile = min(
            dict.fromkeys(candidate_tiles),
            key=lambda tile: (
                (
                    0
                    if is_critical_core(tile)
                    else 1 if has_damaged_own_builder(tile) else 2
                ),
                building_type_rank.get(tile.building.entity_type, 99),
                tile.dist_to_self,
                tile.own_core_dist,
            ),
        )
        return bool(
            self.u_heal_at(
                target_tile.position,
                move_towards=move_towards,
                allow_low_hp_building_replacement=True,
            )
        )

    def s_move_toward_enemy_core(self):
        """
        Harassment step for advancing toward the enemy core.

        If the exact enemy core position is not known yet, move toward the
        nearest remaining symmetry candidate instead, using a single A* path
        search. Once the center is known, move toward the closest in-bounds
        tile adjacent to the enemy core footprint that is either passable or
        still of unknown building type. When the chosen target has never been
        seen before, reuse a cached unseen proxy target on the Bresenham line
        toward that target until the proxy becomes stale or the underlying
        target changes.
        """
        enemy_core_center_pos = self.map.enemy_core_center_pos
        current_pos = self.map.current_pos

        def iter_bresenham_positions(source_pos: Position, target_pos: Position):
            x0, y0 = source_pos.x, source_pos.y
            x1, y1 = target_pos.x, target_pos.y
            dx = abs(x1 - x0)
            dy = abs(y1 - y0)
            step_x = 1 if x0 < x1 else -1
            step_y = 1 if y0 < y1 else -1
            error = dx - dy

            while x0 != x1 or y0 != y1:
                doubled_error = error * 2
                if doubled_error > -dy:
                    error -= dy
                    x0 += step_x
                if doubled_error < dx:
                    error += dx
                    y0 += step_y
                yield Position(x0, y0)

        def get_move_target(target_pos: Position) -> Position:
            if self.enemy_core_proxy_base_target_pos != target_pos:
                self.enemy_core_proxy_target_pos = None
                self.enemy_core_proxy_base_target_pos = target_pos

            proxy_target_pos = self.enemy_core_proxy_target_pos
            if proxy_target_pos is not None:
                proxy_tile = self.map.u_get_pos_tile(proxy_target_pos)
                if (
                    proxy_target_pos != current_pos
                    and proxy_tile.last_seen_turn == -1
                ):
                    return proxy_target_pos
                self.enemy_core_proxy_target_pos = None

            target_tile = self.map.u_get_pos_tile(target_pos)
            if target_tile.last_seen_turn != -1:
                return target_pos

            for next_pos in iter_bresenham_positions(current_pos, target_pos):
                next_tile = self.map.u_get_pos_tile(next_pos)
                if next_tile.last_seen_turn == -1:
                    self.enemy_core_proxy_target_pos = next_pos
                    return next_pos

            return target_pos

        if enemy_core_center_pos is not None:
            candidate_tiles = []
            center_x = enemy_core_center_pos.x
            center_y = enemy_core_center_pos.y
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if max(abs(dx), abs(dy)) != 2:
                        continue
                    candidate_pos = Position(center_x + dx, center_y + dy)
                    if not self.map.u_is_in_bounds(candidate_pos):
                        continue
                    candidate_tile = self.map.u_get_pos_tile(candidate_pos)
                    if (
                        candidate_tile.building.entity_type is not None
                        and not candidate_tile.is_passable
                    ):
                        continue
                    candidate_tiles.append(candidate_tile)

            target_pos = min(
                (tile.position for tile in candidate_tiles),
                key=lambda pos: (
                    abs(current_pos.x - pos.x) + abs(current_pos.y - pos.y),
                    pos.x,
                    pos.y,
                ),
                default=None,
            )
            if target_pos is None:
                return False
            move_target_pos = get_move_target(target_pos)
            return bool(
                self.u_move_to(
                    move_target_pos,
                    allow_conveyor_building=False,
                    respect_titanium_reserve_for_road_build=True,
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

        move_target_pos = get_move_target(target_pos)
        return bool(
            self.u_move_to(
                move_target_pos,
                allow_conveyor_building=False,
                respect_titanium_reserve_for_road_build=True,
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
            self.u_move_to(
                tiles_by_index[waypoint_indices[next_patrol_index]].position,
                allow_conveyor_building=False,
            )
        )
