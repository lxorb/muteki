from cambc import Direction, EntityType, Environment, Position

from lib.agent import Agent
from lib.agent.builder.navigation import BuilderNavigationMixin
from lib.agent.constants import (
    ATTACK_TURRET_TYPES,
    CONVEYOR_ENTITY_TYPES,
    LAUNCHER_THROWABLE_PRIORITY_RANK,
    LAUNCHER_YEET_AWAY_MIN_DISTANCE,
    LAUNCHER_YEET_TO_TARGET_MIN_DISTANCE,
    TURRET_TARGET_PRIORITY_RANK,
    TURRET_UNFED_SELF_DESTRUCT_ROUNDS,
)
from lib.map.constants import SUPPLY_LINK_TYPES


class TurretAgent(BuilderNavigationMixin, Agent):
    def __init__(self):
        super().__init__()
        self.served_ally_launch_round_by_owner_mod: dict[int, int] = {}
        self.unfed_rounds: int = 0

    def u_handler(self) -> bool:
        """
        Dispatch turret behavior by turret type.
        """
        if self._u_turret_is_fed():
            self.unfed_rounds = 0
        else:
            self.unfed_rounds += 1
        if self.unfed_rounds >= TURRET_UNFED_SELF_DESTRUCT_ROUNDS:
            return self.self_destruction()

        match self.ct.get_entity_type():
            case EntityType.LAUNCHER:
                return self.u_launcher_run()
            case EntityType.GUNNER:
                if self.useful_gunner():
                    return self.u_gunner_attack()
                else:
                    if self.safe_destruction_possible() and self._u_self_destruct_titanium_ok():
                        return self.self_destruction()
            case EntityType.SENTINEL:
                if self.useful_sentinel():
                    return self.u_sentinel_attack()
                else:
                    if self.safe_destruction_possible() and self._u_self_destruct_titanium_ok():
                        return self.self_destruction()
            case EntityType.BREACH:
                return self.u_turret_attack()
        return False
    

    def useful_gunner(self) -> bool:
        # Only consider self-destruction when fed by an own supply chain.
        # Otherwise (enemy-fed or unfed) the turret is always useful.
        if not self._u_turret_fed_by_non_harvester_own_supply():
            return True

        # Any enemy bot in vision radius keeps us useful (mobile threat).
        if self.map.enemy_team_bbs_in_vision_count > 0:
            return True

        # Gunners can rotate — useful iff some rotation has an attackable
        # enemy in its ray.
        current_pos = self.map.current_pos
        current_round = self.ct.get_current_round()
        vision_radius_sq = self._u_turret_vision_radius_sq()
        for direction in Direction:
            if direction == Direction.CENTRE:
                continue
            for tile in self.map.u_get_gunner_shootable_tiles(
                current_pos,
                direction,
                vision_radius_sq,
            ):
                if self.u_is_nontrivial_enemy_gunner_rotation_target(
                    tile,
                    current_round,
                ):
                    return True
        return False

    def useful_sentinel(self) -> bool:
        # Only consider self-destruction when fed by an own supply chain.
        # Otherwise (enemy-fed or unfed) the turret is always useful.
        if not self._u_turret_fed_by_non_harvester_own_supply():
            return True

        # Any enemy bot in vision radius keeps us useful (mobile threat).
        if self.map.enemy_team_bbs_in_vision_count > 0:
            return True

        # Sentinels are fixed-direction once built — useful iff any tile
        # they can currently fire at is a valid sentinel target.
        current_round = self.ct.get_current_round()
        enemy_chain_roots = (
            self.u_get_enemy_supply_chain_roots_feeding_enemy_turret(current_round)
        )
        for pos in self.ct.get_attackable_tiles():
            target_tile = self.map.u_get_pos_tile(pos)
            if self.u_get_sentinel_target_priority_key(
                target_tile,
                current_round,
                enemy_chain_roots,
            ) is not None:
                return True
        return False

    def safe_destruction_possible(self) -> bool:
        # return true IFF:
            # there is BFS-via-vision-field-reachable bot
            # meaning: a bot can get here without any problems very easily (e.g. no walls in the way)
        current_pos = self.map.current_pos
        vision_radius_sq = self._u_turret_vision_radius_sq()
        current_round = self.ct.get_current_round()
        tiles_by_index = self.map.tiles_by_index
        intrinsic_passable_by_index = self.map.intrinsic_passable_by_index
        current_idx = self.map.u_to_index(current_pos)

        visited = {current_idx}
        stack = [current_idx]
        while stack:
            idx = stack.pop()
            tile = tiles_by_index[idx]
            if (
                tile.last_seen_turn == current_round
                and tile.bot.id is not None
                and tile.bot.team == self.map.own_team
                and idx != current_idx
            ):
                return True
            for neighbor_idx in self.map.u_iter_cardinal_neighbor_indices(idx):
                if neighbor_idx in visited:
                    continue
                neighbor_tile = tiles_by_index[neighbor_idx]
                if current_pos.distance_squared(neighbor_tile.position) > vision_radius_sq:
                    continue
                if not intrinsic_passable_by_index[neighbor_idx]:
                    continue
                visited.add(neighbor_idx)
                stack.append(neighbor_idx)
        return False

    def _u_self_destruct_titanium_ok(self) -> bool:
        conveyor_titanium_cost, _ = self.ct.get_conveyor_cost()
        return self.map.titanium >= 1.5 * conveyor_titanium_cost

    def self_destruction(self) -> bool:
        # be creative: make python throw a funny runtime error :) (like a really stupid one hehe)
        raise RuntimeError(
            f"turret at {self.map.current_pos} self-destructed on turn "
            f"{self.ct.get_current_round()} (no useful targets in sight)"
        )

    def _u_turret_fed_by_non_harvester_own_supply(self) -> bool:
        current_idx = self.map.u_to_index(self.map.current_pos)
        return current_idx in self.map.own_supply_link_target_indices_in_vision

    def _u_turret_is_fed(self) -> bool:
        if self._u_turret_fed_by_non_harvester_own_supply():
            return True
        current_idx = self.map.u_to_index(self.map.current_pos)
        if current_idx in self.map.enemy_supply_link_target_indices_in_vision:
            return True
        own_team = self.map.own_team
        enemy_team = self.map.enemy_team
        current_round = self.map.current_round
        tiles_by_index = self.map.tiles_by_index
        for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(current_idx):
            adjacent_tile = tiles_by_index[adjacent_idx]
            if (
                adjacent_tile.last_seen_turn == current_round
                and adjacent_tile.building.entity_type == EntityType.HARVESTER
                and adjacent_tile.building.team in (own_team, enemy_team)
            ):
                return True
        return False

    def _u_turret_vision_radius_sq(self) -> int:
        current_tile = self.map.u_get_pos_tile(self.map.current_pos)
        vision_radius_sq = current_tile.building.vision_radius_sq
        if vision_radius_sq is None:
            vision_radius_sq = self.ct.get_vision_radius_sq()
        return vision_radius_sq

    def u_launcher_run(self) -> bool:
        launcher_pos = self.map.current_pos
        adjacent_bot_tiles = self.u_filter_tiles(
            [
                self.map.u_get_pos_tile(pos)
                for pos in self.map.u_iter_adjacent_all_positions(launcher_pos)
            ],
            lambda tile: tile.bot.id is not None,
        )

        print(
            f"[launcher-debug] pos={launcher_pos} adj_bots="
            + str([
                (t.bot.id, t.bot.id & 63, t.bot.team, t.position)
                for t in adjacent_bot_tiles
            ])
        )
        stored_markers = []
        for owner_mod in range(64):
            marker_payload = self.map.visible_marker_payload_by_owner_mod64[owner_mod]
            if marker_payload < 0:
                continue
            marker_action_type = self.map.visible_marker_action_type_by_owner_mod64[
                owner_mod
            ]
            marker_payload_value: Position | int = marker_payload
            if marker_action_type:
                marker_payload_value = self.map.tiles_by_index[marker_payload].position
            stored_markers.append((
                owner_mod,
                marker_payload_value,
                self.map.visible_marker_age_by_owner_mod64[owner_mod],
                marker_action_type,
            ))
        print(
            f"[launcher-debug] stored markers (owner_mod, payload, age, action): "
            f"{stored_markers}"
        )
        print(
            f"[launcher-debug] served_ally_launch_round_by_owner_mod="
            f"{dict(self.served_ally_launch_round_by_owner_mod)}"
        )
        mod_to_ids: dict[int, list[int]] = {}
        for t in adjacent_bot_tiles:
            if t.bot.team == self.map.own_team:
                mod_to_ids.setdefault(t.bot.id & 63, []).append(t.bot.id)
        collisions = {m: ids for m, ids in mod_to_ids.items() if len(ids) > 1}
        if collisions:
            print(f"[launcher-debug] owner_mod COLLISIONS among adjacent allies: {collisions}")

        enemy_bot_tiles = self.u_prioritize_tiles(
            self.u_filter_tiles(
                adjacent_bot_tiles,
                lambda tile: tile.bot.team != self.map.own_team,
            ),
            self.u_get_launcher_throwable_priority_key,
            lambda tile: tile.position.x,
            lambda tile: tile.position.y,
        )
        for bot_tile in enemy_bot_tiles:
            target_pos = self.u_get_launcher_enemy_throw_target(bot_tile)
            if target_pos is None:
                if self.round_stopwatch.check_overtime():
                    break
                continue
            self.ct.launch(bot_tile.position, target_pos)
            return True

        best_ally_entry = None
        for bot_tile in adjacent_bot_tiles:
            if bot_tile.bot.team != self.map.own_team:
                continue

            bot_id = bot_tile.bot.id
            owner_mod_local = bot_id & 63
            request_info = self.map.u_get_visible_marker_request_info(bot_id)
            if request_info is None:
                print(
                    f"[launcher-debug] ally id={bot_id} mod={owner_mod_local} "
                    f"pos={bot_tile.position} SKIP: no visible marker request"
                )
                continue
            owner_mod, request_round, marker_target_pos = request_info

            # Only skip the EXACT request we already served. Any marker placed
            # in a round STRICTLY AFTER last_served is a fresh request and must
            # be considered — including same-target repeats (a new round_mod
            # makes the request distinct) and same-round different-target
            # overrides (map caching surfaces the freshest).
            last_served = self.served_ally_launch_round_by_owner_mod.get(
                owner_mod, -1
            )
            if request_round <= last_served:
                print(
                    f"[launcher-debug] ally id={bot_id} mod={owner_mod} "
                    f"pos={bot_tile.position} marker_tgt={marker_target_pos} "
                    f"req_round={request_round} last_served={last_served} "
                    f"SKIP: already served (no newer marker seen)"
                )
                continue

            target_pos = self.u_get_launcher_ally_throw_target(
                bot_tile,
                marker_target_pos,
            )
            if target_pos is None:
                print(
                    f"[launcher-debug] ally id={bot_id} mod={owner_mod} "
                    f"pos={bot_tile.position} marker_tgt={marker_target_pos} "
                    f"req_round={request_round} SKIP: no legal throw target "
                    f"(filters: passable, no-bot, >2 away, can_launch, "
                    f"not in enemy attack range, not in enemy pickup zone, "
                    f"improvement >= {LAUNCHER_YEET_TO_TARGET_MIN_DISTANCE})"
                )
                if self.round_stopwatch.check_overtime():
                    break
                continue

            key = (
                marker_target_pos.distance_squared(target_pos),
                bot_tile.position.distance_squared(target_pos),
                target_pos.x,
                target_pos.y,
            )
            print(
                f"[launcher-debug] ally id={bot_id} mod={owner_mod} "
                f"pos={bot_tile.position} marker_tgt={marker_target_pos} "
                f"req_round={request_round} CANDIDATE throw_tgt={target_pos} key={key}"
            )
            if best_ally_entry is None or key < best_ally_entry[0]:
                best_ally_entry = (
                    key, bot_tile.position, target_pos, owner_mod, request_round
                )

        if best_ally_entry is None:
            print("[launcher-debug] no ally throw committed")
            return False

        _, bot_pos, target_pos, owner_mod, request_round = best_ally_entry
        print(
            f"[launcher-debug] LAUNCHING ally at {bot_pos} -> {target_pos} "
            f"(owner_mod={owner_mod}, request_round={request_round})"
        )
        self.ct.launch(bot_pos, target_pos)
        self.served_ally_launch_round_by_owner_mod[owner_mod] = request_round
        return True

    def u_get_launcher_legal_target_tiles(self, bot_pos: Position):
        launcher_pos = self.map.current_pos
        return self.u_filter_tiles(
            [self.map.u_get_pos_tile(pos) for pos in self.ct.get_attackable_tiles()],
            lambda tile: tile.building.id is not None,
            lambda tile: tile.is_passable,
            lambda tile: tile.bot.id is None,
            lambda tile: launcher_pos.distance_squared(tile.position) > 2,
            lambda tile: self.ct.can_launch(bot_pos, tile.position),
        )

    def u_get_launcher_enemy_throw_target(self, bot_tile) -> Position | None:
        candidate_tiles = self.u_get_launcher_legal_target_tiles(bot_tile.position)
        if not candidate_tiles:
            return None

        own_core_center_pos = self.map.own_core_center_pos
        enemy_core_center_pos = self.map.enemy_core_center_pos
        launcher_pos = self.map.current_pos

        if own_core_center_pos is not None and enemy_core_center_pos is not None:
            if (
                enemy_core_center_pos.distance_squared(launcher_pos) < 15
                and own_core_center_pos.distance_squared(launcher_pos) > 15
            ):
                yeet_from_pos = enemy_core_center_pos
            else:
                yeet_from_pos = own_core_center_pos
        elif own_core_center_pos is not None:
            yeet_from_pos = own_core_center_pos
        elif enemy_core_center_pos is not None:
            yeet_from_pos = enemy_core_center_pos
        else:
            yeet_from_pos = launcher_pos

        best_covered_entry = None
        for tile in candidate_tiles:
            coverage_rank = self.u_get_own_turret_coverage_rank(tile.position)
            if coverage_rank is None:
                continue
            key = (
                coverage_rank,
                -tile.position.distance_squared(yeet_from_pos),
                tile.position.x,
                tile.position.y,
            )
            if best_covered_entry is None or key < best_covered_entry[0]:
                best_covered_entry = (key, tile)

        if best_covered_entry is not None:
            return best_covered_entry[1].position

        candidate_tiles = self.u_prioritize_tiles(
            candidate_tiles,
            lambda tile: -tile.position.distance_squared(yeet_from_pos),
            lambda tile: tile.position.x,
            lambda tile: tile.position.y,
        )
        target_tile = candidate_tiles[0]

        target_dist = target_tile.position.distance_squared(yeet_from_pos)
        bot_dist = bot_tile.position.distance_squared(yeet_from_pos)
        if target_dist - bot_dist < LAUNCHER_YEET_AWAY_MIN_DISTANCE:
            print(
                "Launcher enemy throw skipped: bot",
                bot_tile.position,
                "ref",
                yeet_from_pos,
                "bot_dist",
                bot_dist,
                "target_dist",
                target_dist,
                "threshold",
                LAUNCHER_YEET_AWAY_MIN_DISTANCE,
            )
            return None
        return target_tile.position

    def u_get_own_turret_coverage_rank(self, target_pos: Position) -> int | None:
        for building_tile in self.map.own_buildings_in_vision:
            building = building_tile.building
            building_pos = building_tile.position

            if building.entity_type == EntityType.GUNNER:
                current_direction = building.direction
                if (
                    current_direction is not None
                    and current_direction != Direction.CENTRE
                    and self.map.u_gunner_covers_target(
                        building_pos,
                        current_direction,
                        target_pos,
                        building.vision_radius_sq,
                    )
                ):
                    return 0
                continue

            if building.entity_type == EntityType.SENTINEL:
                if self.map.u_sentinel_covers_target(
                    building_pos,
                    building.direction,
                    target_pos,
                    building.vision_radius_sq,
                ):
                    return 2
                continue

            if building.entity_type == EntityType.BREACH:
                if self.map.u_breach_covers_target(
                    building_pos,
                    building.direction,
                    target_pos,
                ):
                    return 2

            if self.round_stopwatch.check_overtime_interval():
                break

        for building_tile in self.map.own_buildings_in_vision:
            building = building_tile.building
            if building.entity_type != EntityType.GUNNER:
                continue

            building_pos = building_tile.position
            current_direction = building.direction
            for direction in Direction:
                if direction == Direction.CENTRE or direction == current_direction:
                    continue
                if self.map.u_gunner_covers_target(
                    building_pos,
                    direction,
                    target_pos,
                    building.vision_radius_sq,
                ):
                    return 1

            if self.round_stopwatch.check_overtime_interval():
                break

        return None

    def u_get_launcher_ally_throw_target(
        self,
        bot_tile,
        marker_target_pos: Position,
    ) -> Position | None:
        candidate_tiles = self.u_filter_tiles(
            self.u_get_launcher_legal_target_tiles(bot_tile.position),
            lambda tile: not tile.in_enemy_attack_range,
            lambda tile: not tile.in_enemy_launcher_pickup_zone,
        )
        if not candidate_tiles:
            return None

        current_dist_sq = bot_tile.position.distance_squared(marker_target_pos)
        candidate_tiles = self.u_prioritize_tiles(
            candidate_tiles,
            lambda tile: tile.position.distance_squared(marker_target_pos),
            lambda tile: tile.position.x,
            lambda tile: tile.position.y,
        )
        target_tile = candidate_tiles[0]
        if (
            current_dist_sq - target_tile.position.distance_squared(marker_target_pos)
            < LAUNCHER_YEET_TO_TARGET_MIN_DISTANCE
        ):
            return None
        return target_tile.position

    def u_gunner_attack(self) -> bool:
        """
        Rotate toward a better lane when justified, otherwise fire according to
        the engine's current gunner target selection.

        The engine's `get_gunner_target()` is used as one hint, but target
        selection is resolved locally from the firing ray so every tile in the
        enemy core footprint is treated like the center tile. Fire when the
        resolved target is an enemy tile with no allied builder on it, or when
        the tile contains an enemy builder. If the first target is an allied
        road, clear it only when the next targetable occupied tile behind it
        would be an enemy building or would contain an enemy builder bot.
        """
        current_round = self.ct.get_current_round()
        current_pos = self.map.current_pos
        current_tile = self.map.u_get_pos_tile(current_pos)
        direction = current_tile.building.direction
        if direction is None:
            direction = self.ct.get_direction()
        if direction is None:
            print(
                "Gunner next target:",
                None,
                "building:",
                None,
                "enemy_bot:",
                False,
            )
            return False

        vision_radius_sq = current_tile.building.vision_radius_sq
        if vision_radius_sq is None:
            vision_radius_sq = self.ct.get_vision_radius_sq()
        current_shootable_tiles = self.map.u_get_gunner_shootable_tiles(
            current_pos,
            direction,
            vision_radius_sq,
        )
        if self.u_try_rotate_gunner(
            current_pos,
            direction,
            current_shootable_tiles,
            vision_radius_sq,
            current_round,
        ):
            return True

        ray_tiles = self.map.u_get_gunner_ray_tiles(
            current_pos,
            direction,
            vision_radius_sq,
        )
        target_tile = self.u_get_gunner_target_tile(ray_tiles, current_round)
        print(
            "Gunner next target:",
            None if target_tile is None else target_tile.position,
            "building:",
            None if target_tile is None else target_tile.building.entity_type,
            "enemy_bot:",
            bool(
                target_tile is not None
                and target_tile.bot.id is not None
                and target_tile.bot.team != self.map.own_team
            ),
        )
        if target_tile is None:
            return False
        if target_tile.bot.id is not None and target_tile.bot.team == self.map.own_team:
            return False

        if self.u_gunner_should_attack_target(target_tile) and self.ct.can_fire(
            target_tile.position
        ):
            self.ct.fire(target_tile.position)
            return True

        if (
            target_tile.building.team == self.map.own_team
            and target_tile.building.entity_type == EntityType.ROAD
        ):
            target_index = next(
                (
                    idx
                    for idx, ray_tile in enumerate(ray_tiles)
                    if ray_tile.position == target_tile.position
                ),
                None,
            )
            if (
                target_index is not None
                and self.u_gunner_should_clear_own_road(
                    ray_tiles[target_index + 1 :],
                    current_round,
                )
                and self.ct.can_fire(target_tile.position)
            ):
                self.ct.fire(target_tile.position)
                return True

        return False

    def u_try_rotate_gunner(
        self,
        current_pos: Position,
        current_direction: Direction,
        current_shootable_tiles,
        vision_radius_sq: int,
        current_round: int,
    ) -> bool:
        enemy_building_in_current_direction = any(
            self.u_is_visible_enemy_building_tile(tile, current_round)
            for tile in current_shootable_tiles
        )
        enemy_turret_in_current_direction = any(
            self.u_is_visible_enemy_turret_tile(tile, current_round)
            for tile in current_shootable_tiles
        )
        should_try_rotate = not enemy_building_in_current_direction
        best_direction = None
        best_shootable_tiles = None

        if not should_try_rotate and not enemy_turret_in_current_direction:
            best_direction = self.u_get_gunner_orientation(current_pos)
            if best_direction != current_direction:
                best_shootable_tiles = self.map.u_get_gunner_rotation_target_tiles(
                    current_pos,
                    best_direction,
                    vision_radius_sq,
                )
                should_try_rotate = any(
                    self.u_is_enemy_turret_connected_to_supply_chain(
                        tile,
                        current_round,
                    )
                    for tile in best_shootable_tiles
                )

        if not should_try_rotate:
            return False

        if best_direction is None:
            best_direction = self.u_get_gunner_orientation(current_pos)
        if best_direction == current_direction or best_direction == Direction.CENTRE:
            return False
        if not self.ct.can_rotate(best_direction):
            return False

        if best_shootable_tiles is None:
            best_shootable_tiles = self.map.u_get_gunner_rotation_target_tiles(
                current_pos,
                best_direction,
                vision_radius_sq,
            )
        if not any(
            self.u_is_nontrivial_enemy_gunner_rotation_target(tile, current_round)
            for tile in best_shootable_tiles
        ):
            return False

        self.ct.rotate(best_direction)
        return True

    def u_is_visible_enemy_building_tile(
        self,
        tile,
        current_round: int,
    ) -> bool:
        if tile.is_core_of(self.map.enemy_team):
            return True
        return (
            tile.last_seen_turn == current_round
            and tile.building.id is not None
            and tile.building.team == self.map.enemy_team
        )

    def u_is_visible_enemy_turret_tile(
        self,
        tile,
        current_round: int,
    ) -> bool:
        return (
            tile.last_seen_turn == current_round
            and tile.building.id is not None
            and tile.building.team == self.map.enemy_team
            and tile.building.entity_type in ATTACK_TURRET_TYPES
        )

    def u_is_enemy_turret_connected_to_supply_chain(
        self,
        tile,
        current_round: int,
    ) -> bool:
        return self.u_is_visible_enemy_turret_tile(
            tile,
            current_round,
        ) and self._u_tile_is_targeted_by_supply_chain(tile.index)

    def u_is_nontrivial_enemy_gunner_rotation_target(
        self,
        tile,
        current_round: int,
    ) -> bool:
        if tile.is_core_of(self.map.enemy_team):
            return True
        if tile.last_seen_turn != current_round:
            return False
        if tile.bot.id is not None and tile.bot.team == self.map.enemy_team:
            return True
        return (
            tile.building.id is not None
            and tile.building.team == self.map.enemy_team
            and tile.building.entity_type
            not in (
                EntityType.ROAD,
                EntityType.BARRIER,
            )
        )

    def u_get_gunner_target_tile(
        self,
        ray_tiles,
        current_round: int,
    ):
        return self.u_get_gunner_first_targetable_tile(ray_tiles, current_round)

    def u_gunner_should_attack_target(self, target_tile) -> bool:
        if target_tile.bot.id is not None and target_tile.bot.team == self.map.own_team:
            return False
        if (
            target_tile.bot.id is not None
            and target_tile.bot.team != self.map.own_team
        ):
            return True
        if target_tile.is_core_of(self.map.enemy_team):
            return True
        return self.u_gunner_should_attack_enemy_building(
            target_tile,
            allow_marker=True,
        )

    def u_gunner_should_attack_enemy_building(
        self,
        target_tile,
        allow_marker: bool,
    ) -> bool:
        marker_entity_type = getattr(EntityType, "MARKER", None)
        if (
            target_tile.building.id is None
            or target_tile.building.team == self.map.own_team
        ):
            return False
        if (
            not allow_marker
            and target_tile.building.entity_type == marker_entity_type
        ):
            return False
        if (
            target_tile.bot.id is not None
            and target_tile.bot.team == self.map.own_team
        ):
            return False
        if (
            target_tile.building.entity_type == EntityType.HARVESTER
            and target_tile.environment == Environment.ORE_TITANIUM
            and self.u_enemy_harvester_has_adjacent_allied_turret(target_tile)
        ):
            return False
        if (
            target_tile.building.entity_type in SUPPLY_LINK_TYPES
            and self.map.u_enemy_supply_chain_feeds_own_turret(target_tile.index)
        ):
            return False
        return (
            target_tile.building.id is not None
            and target_tile.building.team != self.map.own_team
        )

    def u_gunner_should_clear_own_road(
        self,
        behind_tiles,
        current_round: int,
    ) -> bool:
        followup_target = self.u_get_gunner_followup_target(behind_tiles, current_round)
        if followup_target is None:
            return False
        return self.u_gunner_should_clear_for_followup_target(followup_target)

    def u_gunner_should_clear_for_followup_target(self, target_tile) -> bool:
        return (
            (
                target_tile.bot.id is not None
                and target_tile.bot.team != self.map.own_team
            )
            or target_tile.is_core_of(self.map.enemy_team)
            or self.u_gunner_should_attack_enemy_building(
                target_tile,
                allow_marker=False,
            )
        )

    def u_get_gunner_followup_target(
        self,
        behind_tiles,
        current_round: int,
    ):
        return self.u_get_gunner_first_targetable_tile(behind_tiles, current_round)

    def u_get_gunner_first_targetable_tile(
        self,
        ray_tiles,
        current_round: int,
    ):
        for tile in ray_tiles:
            if tile.environment == Environment.WALL:
                return None
            if tile.is_core_of(self.map.enemy_team) or tile.is_core_of(self.map.own_team):
                return tile
            if tile.last_seen_turn != current_round:
                continue
            if tile.bot.id is not None or tile.building.id is not None:
                return tile

        return None

    def u_sentinel_attack(self) -> bool:
        current_round = self.ct.get_current_round()
        enemy_chain_roots_feeding_enemy_turret = (
            self.u_get_enemy_supply_chain_roots_feeding_enemy_turret(current_round)
        )
        candidate_entries: list[tuple[tuple[int, ...], object]] = []

        for pos in self.ct.get_attackable_tiles():
            target_tile = self.map.u_get_pos_tile(pos)
            if target_tile.last_seen_turn != current_round:
                continue
            if not self.ct.can_fire(target_tile.position):
                continue

            priority_key = self.u_get_sentinel_target_priority_key(
                target_tile,
                current_round,
                enemy_chain_roots_feeding_enemy_turret,
            )
            if priority_key is None:
                continue

            candidate_entries.append((priority_key, target_tile))

            if self.round_stopwatch.check_overtime():
                break

        if not candidate_entries:
            return False

        _, target_tile = min(candidate_entries, key=lambda candidate: candidate[0])
        self.ct.fire(target_tile.position)
        return True

    def u_turret_attack(self) -> bool:
        """
        Fire at the best legal enemy tile from this turret's attackable pattern.

        The attack starts from `get_attackable_tiles()`, keeps only tiles this
        turret can currently fire at, and discards tiles without a visible enemy
        bot or enemy building. It then applies the configured category order.

        Within the attack-turret bucket, enemy turrets that can currently hit
        this turret are preferred, then lower remaining HP breaks ties.
        Unprotected enemy harvesters use their own bucket, then lower remaining
        HP breaks ties. Enemy bots on allied tiles and enemy bots elsewhere are
        separate priority buckets, and each bucket breaks ties by lower
        remaining HP. All later buckets also tie-break by lower remaining HP.
        The first tile after that ordering is fired at.
        """
        candidate_tiles = self.u_filter_tiles(
            [self.map.u_get_pos_tile(pos) for pos in self.ct.get_attackable_tiles()],
            lambda tile: tile.last_seen_turn == self.ct.get_current_round(),
            lambda tile: self.ct.can_fire(tile.position),
            lambda tile: self.u_get_target_priority_key(tile) is not None,
        )
        candidate_tiles = self.u_prioritize_tiles(
            candidate_tiles,
            self.u_get_target_priority_key,
            lambda tile: tile.position.x,
            lambda tile: tile.position.y,
        )
        if not candidate_tiles:
            return False

        self.ct.fire(candidate_tiles[0].position)
        return True

    def u_get_enemy_supply_chain_roots_feeding_enemy_turret(
        self,
        current_round: int,
    ) -> set[int]:
        enemy_team = self.map.enemy_team
        enemy_chain_roots_feeding_enemy_turret: set[int] = set()

        for tile in self.map.enemy_supply_links_in_vision:
            if (
                tile.last_seen_turn != current_round
                or tile.building.team != enemy_team
                or tile.building.entity_type not in SUPPLY_LINK_TYPES
            ):
                continue

            root = self.map.u_find_supply_chain_root_by_index(tile.index, enemy_team)
            if root is None:
                continue

            if any(
                target_tile.last_seen_turn == current_round
                and target_tile.building.team == enemy_team
                and target_tile.building.entity_type in ATTACK_TURRET_TYPES
                for target_tile in tile.building.targets
            ):
                enemy_chain_roots_feeding_enemy_turret.add(root)

            if self.round_stopwatch.check_overtime():
                break

        return enemy_chain_roots_feeding_enemy_turret

    def u_enemy_supply_chain_feeds_enemy_turret(
        self,
        tile,
        enemy_chain_roots_feeding_enemy_turret: set[int],
    ) -> bool:
        if (
            tile.building.team != self.map.enemy_team
            or tile.building.entity_type not in SUPPLY_LINK_TYPES
        ):
            return False

        root = self.map.u_find_supply_chain_root_by_index(
            tile.index,
            self.map.enemy_team,
        )
        return root is not None and root in enemy_chain_roots_feeding_enemy_turret

    def u_enemy_harvester_has_adjacent_own_turret(self, harvester_tile) -> bool:
        for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(
            harvester_tile.index
        ):
            adjacent_tile = self.map.tiles_by_index[adjacent_idx]
            if (
                adjacent_tile.building.team == self.map.own_team
                and adjacent_tile.building.entity_type in ATTACK_TURRET_TYPES
            ):
                return True
        return False

    def u_enemy_harvester_has_adjacent_enemy_turret(
        self,
        harvester_tile,
        current_round: int,
    ) -> bool:
        enemy_team = self.map.enemy_team
        for adjacent_idx in self.map.u_iter_neighbor_indices(harvester_tile.index):
            adjacent_tile = self.map.tiles_by_index[adjacent_idx]
            if (
                adjacent_tile.last_seen_turn == current_round
                and adjacent_tile.building.team == enemy_team
                and adjacent_tile.building.entity_type in ATTACK_TURRET_TYPES
            ):
                return True
        return False

    def u_enemy_harvester_connected_to_supply_chain_feeding_own_turret(
        self,
        harvester_tile,
    ) -> bool:
        for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(
            harvester_tile.index
        ):
            adjacent_tile = self.map.tiles_by_index[adjacent_idx]
            if (
                adjacent_tile.building.team == self.map.enemy_team
                and adjacent_tile.building.entity_type in SUPPLY_LINK_TYPES
                and self.map.u_enemy_supply_chain_feeds_own_turret(adjacent_tile.index)
            ):
                return True
        return False

    def u_enemy_harvester_connected_to_supply_chain_feeding_enemy_turret(
        self,
        harvester_tile,
        enemy_chain_roots_feeding_enemy_turret: set[int],
    ) -> bool:
        for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(
            harvester_tile.index
        ):
            adjacent_tile = self.map.tiles_by_index[adjacent_idx]
            if self.u_enemy_supply_chain_feeds_enemy_turret(
                adjacent_tile,
                enemy_chain_roots_feeding_enemy_turret,
            ):
                return True
        return False

    def u_enemy_harvester_has_adjacent_allied_turret(self, harvester_tile) -> bool:
        for adjacent_idx in self.map.u_iter_neighbor_indices(harvester_tile.index):
            adjacent_tile = self.map.tiles_by_index[adjacent_idx]
            if (
                adjacent_tile.building.team == self.map.own_team
                and adjacent_tile.building.entity_type in ATTACK_TURRET_TYPES
            ):
                return True
        return False

    def u_launcher_throw(self) -> bool:
        """
        Throw the best adjacent enemy builder bot to the best legal target tile.

        The launcher first chooses an adjacent enemy builder bot, preferring
        bots standing on allied bridges, conveyors, armoured conveyors, and
        roads before bots on empty or other tiles. It then chooses a legal
        destination from launcher range that is passable, has no builder bot on
        it, and lies outside the launcher's pickup radius. If any legal target
        is covered by an allied attack turret, only those covered tiles are
        considered. Among the remaining legal targets, it picks the tile
        farthest from the allied core and launches the chosen bot there.
        """
        bot_pos = self.u_get_launcher_throwable()
        if bot_pos is None:
            return False

        target_pos = self.u_get_launcher_throw_target(bot_pos)
        if target_pos is None:
            return False

        self.ct.launch(bot_pos, target_pos)
        return True

    def u_get_launcher_throwable(self) -> Position | None:
        launcher_pos = self.map.current_pos
        throwable_tiles = self.u_filter_tiles(
            [
                self.map.u_get_pos_tile(pos)
                for pos in self.map.u_iter_adjacent_all_positions(launcher_pos)
            ],
            lambda tile: tile.bot.id is not None,
            lambda tile: tile.bot.team != self.map.own_team,
        )
        throwable_tiles = self.u_prioritize_tiles(
            throwable_tiles,
            self.u_get_launcher_throwable_priority_key,
            lambda tile: tile.position.x,
            lambda tile: tile.position.y,
        )

        for bot_tile in throwable_tiles:
            if self.u_get_launcher_throw_target(bot_tile.position) is not None:
                return bot_tile.position
            if self.round_stopwatch.check_overtime():
                break
        return None

    def u_get_launcher_throwable_priority_key(
        self,
        target_tile,
    ) -> tuple[int, int | None]:
        if target_tile.building.team == self.map.own_team:
            if target_tile.building.entity_type == EntityType.BRIDGE:
                return (
                    LAUNCHER_THROWABLE_PRIORITY_RANK["enemy_bot_on_ally_bridge"],
                    target_tile.bot.hp,
                )
            if target_tile.building.entity_type in CONVEYOR_ENTITY_TYPES:
                return (
                    LAUNCHER_THROWABLE_PRIORITY_RANK["enemy_bot_on_ally_conveyor"],
                    target_tile.bot.hp,
                )
            if target_tile.building.entity_type == EntityType.ROAD:
                return (
                    LAUNCHER_THROWABLE_PRIORITY_RANK["enemy_bot_on_ally_road"],
                    target_tile.bot.hp,
                )

        if target_tile.building.id is None:
            return (
                LAUNCHER_THROWABLE_PRIORITY_RANK["enemy_bot_on_empty_tile"],
                target_tile.bot.hp,
            )

        return (
            LAUNCHER_THROWABLE_PRIORITY_RANK["enemy_bot_elsewhere"],
            target_tile.bot.hp,
        )

    def u_get_launcher_throw_target(self, bot_pos: Position) -> Position | None:
        launcher_pos = self.map.current_pos
        candidate_tiles = self.u_filter_tiles(
            [self.map.u_get_pos_tile(pos) for pos in self.ct.get_attackable_tiles()],
            lambda tile: tile.is_passable,
            lambda tile: tile.bot.id is None,
            lambda tile: launcher_pos.distance_squared(tile.position) > 2,
            lambda tile: self.ct.can_launch(bot_pos, tile.position),
        )
        turret_covered_tiles = self.u_filter_tiles(
            candidate_tiles,
            lambda tile: self.u_is_in_own_turret_attack_range(tile.position),
        )
        if turret_covered_tiles:
            candidate_tiles = turret_covered_tiles
        if not candidate_tiles:
            return None

        candidate_tiles = self.u_prioritize_tiles(
            candidate_tiles,
            lambda tile: -tile.own_core_dist,
            lambda tile: tile.position.x,
            lambda tile: tile.position.y,
        )
        return candidate_tiles[0].position

    def u_is_in_own_turret_attack_range(self, target_pos: Position) -> bool:
        return self.u_get_own_turret_coverage_rank(target_pos) is not None

    def u_get_target_priority_key(
        self,
        target_tile,
    ) -> tuple[int, ...] | None:
        own_team = self.map.own_team
        building_id = target_tile.building.id
        builder_bot_id = target_tile.bot.id

        if builder_bot_id is not None and target_tile.bot.team == own_team:
            return None

        enemy_building_id = None
        enemy_building_type = target_tile.building.entity_type
        if building_id is not None and target_tile.building.team != own_team:
            enemy_building_id = building_id

        enemy_builder_bot_id = None
        if builder_bot_id is not None and target_tile.bot.team != own_team:
            enemy_builder_bot_id = builder_bot_id

        if enemy_building_id is not None and enemy_building_type in ATTACK_TURRET_TYPES:
            return (
                TURRET_TARGET_PRIORITY_RANK[enemy_building_type],
                0 if self.map.u_enemy_turret_targets_self(enemy_building_id) else 1,
                target_tile.building.hp,
            )

        if (
            enemy_building_id is not None
            and enemy_building_type == EntityType.HARVESTER
            and not self.u_enemy_harvester_has_adjacent_own_turret(target_tile)
        ):
            return (
                TURRET_TARGET_PRIORITY_RANK[
                    "enemy_harvester_without_adjacent_own_turret"
                ],
                target_tile.building.hp,
            )

        if enemy_builder_bot_id is not None:
            return (
                TURRET_TARGET_PRIORITY_RANK[
                    (
                        "enemy_bot_on_ally_tile"
                        if self.map.u_is_enemy_bot_on_ally_tile(target_tile)
                        else "enemy_bot_on_non_ally_tile"
                    )
                ],
                target_tile.bot.hp,
            )

        if (
            enemy_building_id is None
            or enemy_building_type not in TURRET_TARGET_PRIORITY_RANK
        ):
            return None

        return (
            TURRET_TARGET_PRIORITY_RANK[enemy_building_type],
            target_tile.building.hp,
        )

    def u_get_sentinel_target_priority_key(
        self,
        target_tile,
        current_round: int,
        enemy_chain_roots_feeding_enemy_turret: set[int],
    ) -> tuple[int, ...] | None:
        own_team = self.map.own_team
        enemy_team = self.map.enemy_team
        building = target_tile.building
        building_type = building.entity_type
        building_hp = building.hp if building.hp is not None else 10**9
        own_builder_bot_present = (
            target_tile.bot.id is not None and target_tile.bot.team == own_team
        )
        enemy_builder_bot_present = (
            target_tile.bot.id is not None and target_tile.bot.team == enemy_team
        )
        enemy_builder_bot_hp = (
            target_tile.bot.hp
            if enemy_builder_bot_present and target_tile.bot.hp is not None
            else 10**9
        )
        enemy_supply_tile = (
            building.id is not None
            and building.team == enemy_team
            and building_type in SUPPLY_LINK_TYPES
        )
        enemy_titanium_chain_supply_tile = (
            enemy_supply_tile
            and self.map.u_supply_chain_has_titanium(target_tile.index, enemy_team)
        )
        low_hp_turret_type_key = (
            0
            if building_type == EntityType.SENTINEL
            else 1
            if building_type == EntityType.GUNNER
            else 2
        )
        low_hp_supply_key = (
            0
            if building_type == EntityType.BRIDGE
            else 1
            if building_type == EntityType.ARMOURED_CONVEYOR
            else 2
            if building_type == EntityType.CONVEYOR
            else 3
        )
        enemy_turret_feed_key = (
            0
            if building_type == EntityType.BRIDGE
            else 1
            if building_type == EntityType.CONVEYOR
            else 2
            if building_type == EntityType.SPLITTER
            else 3
        )
        damaged_own_supply_tile_with_enemy_builder_bot = (
            enemy_builder_bot_present
            and building.id is not None
            and building.team == own_team
            and building_type in SUPPLY_LINK_TYPES
            and building.hp is not None
            and building.hp < self.ct.get_max_hp(building.id)
        )

        if own_builder_bot_present:
            return None

        if building.team == own_team and not enemy_builder_bot_present:
            return None

        if enemy_supply_tile and self.map.u_enemy_supply_chain_feeds_own_turret(
            target_tile.index
        ):
            return None

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.HARVESTER
            and target_tile.environment == Environment.ORE_TITANIUM
            and (
                self.map.u_enemy_titanium_harvester_has_adjacent_own_turret(target_tile)
                or self.u_enemy_harvester_connected_to_supply_chain_feeding_own_turret(
                    target_tile
                )
            )
        ):
            return None

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type in ATTACK_TURRET_TYPES
            and building_hp <= 18
        ):
            return (
                0,
                building_hp,
                low_hp_turret_type_key,
                target_tile.position.x,
                target_tile.position.y,
            )

        if enemy_builder_bot_present and enemy_builder_bot_hp <= 18:
            return (
                1,
                enemy_builder_bot_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if enemy_titanium_chain_supply_tile and building_hp <= 18:
            return (
                2,
                building_hp,
                low_hp_supply_key,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.LAUNCHER
            and building_hp <= 18
        ):
            return (
                3,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.FOUNDRY
            and building_hp <= 18
        ):
            return (
                4,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.GUNNER
            and self._u_tile_is_targeted_by_titanium_supply_chain(target_tile.index)
        ):
            return (
                5,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.SENTINEL
            and self._u_tile_is_targeted_by_titanium_supply_chain(target_tile.index)
        ):
            return (
                6,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.BREACH
            and self._u_tile_is_targeted_by_titanium_supply_chain(target_tile.index)
        ):
            return (
                7,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.GUNNER
        ):
            return (
                8,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.SENTINEL
        ):
            return (
                9,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.BREACH
        ):
            return (
                10,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            enemy_titanium_chain_supply_tile
            and self.u_enemy_supply_chain_feeds_enemy_turret(
                target_tile,
                enemy_chain_roots_feeding_enemy_turret,
            )
        ):
            return (
                11,
                building_hp,
                enemy_turret_feed_key,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.HARVESTER
            and self.u_enemy_harvester_has_adjacent_enemy_turret(
                target_tile,
                current_round,
            )
        ):
            return (
                12,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.HARVESTER
            and self.u_enemy_harvester_connected_to_supply_chain_feeding_enemy_turret(
                target_tile,
                enemy_chain_roots_feeding_enemy_turret,
            )
        ):
            return (
                13,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if target_tile.is_core_of(enemy_team):
            return (
                14,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if damaged_own_supply_tile_with_enemy_builder_bot:
            return (
                15,
                building_hp,
                enemy_builder_bot_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.FOUNDRY
        ):
            return (
                16,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.BRIDGE
        ):
            return (
                17,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.CONVEYOR
        ):
            return (
                18,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.SPLITTER
        ):
            return (
                19,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.ARMOURED_CONVEYOR
        ):
            return (
                20,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.LAUNCHER
        ):
            return (
                21,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.HARVESTER
        ):
            return (
                22,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.BARRIER
        ):
            return (
                23,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if enemy_builder_bot_present:
            return (
                24,
                enemy_builder_bot_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        if (
            building.id is not None
            and building.team == enemy_team
            and building_type == EntityType.ROAD
        ):
            return (
                25,
                building_hp,
                target_tile.position.x,
                target_tile.position.y,
            )

        return None
