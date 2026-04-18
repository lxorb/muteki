from cambc import EntityType, Environment, Position

from lib.agent import Agent
from lib.agent.constants import (
    ENABLE_PRINTING,
    ATTACK_TURRET_TYPES,
    CONVEYOR_ENTITY_TYPES,
    LAUNCHER_THROWABLE_PRIORITY_RANK,
    TURRET_TARGET_PRIORITY_RANK,
    LAUNCHER_YEET_AWAY_MIN_DISTANCE,
    LAUNCHER_YEET_TO_TARGET_MIN_DISTANCE,
)


class TurretAgent(Agent):
    def __init__(self):
        super().__init__()

    def u_handler(self) -> bool:
        """
        Dispatch turret behavior by turret type.
        """
        match self.ct.get_entity_type():
            case EntityType.LAUNCHER:
                return self.u_launcher_run()
            case EntityType.GUNNER:
                return self.u_gunner_attack()
            case EntityType.SENTINEL:
                return self.u_turret_attack()
            case EntityType.BREACH:
                return self.u_turret_attack()
        return False

    def u_launcher_run(self) -> bool:
        
        # priority list:
        # enemies into killer zone
        # enemies away from core
        # ally into safe zone (the closer the higher the better)

        if ENABLE_PRINTING: print("LAUNCHER PRINTS")

        if not self.map.launcher_action_radius_bots:
            if ENABLE_PRINTING: print("---------------")
            return False
        


        candidate_bots = sorted(self.map.launcher_action_radius_bots, key=lambda tile: tile.bot.team != self.map.enemy_team)

        if ENABLE_PRINTING: print("bot -> target:", [f"{bot_id}, {value[0]}" for bot_id, value in self.map.id_to_target_pos_round.items()])
        if ENABLE_PRINTING: print("candidate bots:", [f"id: {bot.bot.id}" for bot in candidate_bots])
        # print("seen markers:", self.map.seen_markers_for_debugging)
        if ENABLE_PRINTING: print("seen marker ids: ", self.map.seen_ids_for_debugging)

        if not self.map.own_core_center_pos:
            for id, value in self.map.id_to_target_pos_round.items():
                if self.map.tiles_by_index[value[0].y * self.map.INDEX_STRIDE + value[0].x] not in self.map.launcher_visible_tiles:
                    if ENABLE_PRINTING: print("UPDATING OWN CORE POS")
                    self.map.own_core_center_pos = value[0]
                    break


        for bot_tile in candidate_bots:
            if ENABLE_PRINTING: print("trying to send", bot_tile.bot.id, "somewhere")
            if bot_tile.bot.team == self.map.enemy_team:
                if self.launcher_handle_enemy(bot_tile): 
                    return True
            elif bot_tile.bot.team == self.map.own_team:
                if ENABLE_PRINTING: print("debug print AAA")
                if self.launcher_handle_own(bot_tile):
                    return True
                if ENABLE_PRINTING: print("not sent :(")
        
        return False

    def launcher_handle_own(self, bot_tile):
        if not self.map.launcher_own_reachable:
            if ENABLE_PRINTING: print("XXXXXXXXXXXXXXXXXXX")
            return False

        if not (bot_tile.bot.id & 0b111111 in self.map.id_to_target_pos_round):
            if ENABLE_PRINTING: print("YYYYYYYYYYYYYYYYYYY")
            if ENABLE_PRINTING: print(self.map.id_to_target_pos_round)
            return False

        written_position = self.map.id_to_target_pos_round[bot_tile.bot.id & 0b111111][0]
        written_idx = self.map.u_to_index(written_position)

        if self.map.tiles_by_index[written_idx] not in self.map.launcher_visible_tiles:
            if ENABLE_PRINTING: print("target position:", written_position)
            if ENABLE_PRINTING: print([tile.position for tile in self.map.launcher_visible_tiles])
            if ENABLE_PRINTING: print("ZZZZZZZZZZZZZZZ")
            return False

        if ENABLE_PRINTING: print("debug print: been here 1")
        reachable_safe = [tile for tile in self.map.launcher_own_reachable if tile in self.map.launcher_safe_zone_tiles]
        
        target_tile = self.map.tiles_by_index[written_idx]

        if not reachable_safe or target_tile not in reachable_safe:
            if ENABLE_PRINTING: print("sorry, can't take you to", target_tile.position)
            return False

        if not self.ct.can_launch(bot_tile.position, target_tile.position):
            if ENABLE_PRINTING: print("ERROR: Why can't I launch???")
            return False
        self.ct.launch(bot_tile.position, target_tile.position)
        return True

    def launcher_handle_enemy(self, bot_tile):

        if not self.map.launcher_enemy_reachable:
            return False

        if bot_tile.in_own_attack_range != 0:
            return False
            # already in killer zone

        if self.send_enemy_to_killer(bot_tile):
            return True
        
        if self.yeet_enemy_away(bot_tile):
            return True

        return False

    def send_enemy_to_killer(self, bot_tile):
        reachable_killer_candidates = [killer_tile for killer_tile in self.map.launcher_killer_zone_tiles if killer_tile in self.map.launcher_enemy_reachable]
        if not reachable_killer_candidates:
            return False
        reachable_killer_candidates = sorted(reachable_killer_candidates, key = lambda tile: -tile.in_own_attack_range)
        target = reachable_killer_candidates[0]
        if not self.ct.can_launch(bot_tile.position, target.position):
            if ENABLE_PRINTING: print("ERROR: Why can't I launch???")
            return False
        self.ct.launch(bot_tile.position, target.position)
        if ENABLE_PRINTING: print("LAUNCHER ACTION: let enemy burn")
        return True
    
    def yeet_enemy_away(self, bot_tile):
        yeet_from_pos = self.map.own_core_center_pos
        if self.map.enemy_core_center_pos and self.map.enemy_core_center_pos.distance_squared(self.map.current_pos) < 15: # MAGIC NUMBER SORRY
            yeet_from_pos = self.map.enemy_core_center_pos
        if not yeet_from_pos:
            return False
        sorted_reachable_tiles = sorted(self.map.launcher_enemy_reachable, key = lambda tile: -tile.position.distance_squared(yeet_from_pos))
        candidate_tile = sorted_reachable_tiles[0]
        dist_diff = candidate_tile.position.distance_squared(yeet_from_pos) - bot_tile.position.distance_squared(yeet_from_pos)
        if dist_diff >= LAUNCHER_YEET_AWAY_MIN_DISTANCE:
            if not self.ct.can_launch(bot_tile.position, candidate_tile.position):
                if ENABLE_PRINTING: print("ERROR: Why can't I launch???")
                return False
            self.ct.launch(bot_tile.position, candidate_tile.position)
            if ENABLE_PRINTING: print("LAUNCHER ACTION: yeet enemy away")
            return True
        return False



    def u_gunner_attack(self) -> bool:
        """
        Fire according to the engine's current gunner target selection.

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
            if ENABLE_PRINTING: print(
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
        ray_tiles = self.map.u_get_gunner_ray_tiles(
            current_pos,
            direction,
            vision_radius_sq,
        )
        target_tile = self.u_get_gunner_target_tile(ray_tiles, current_round)
        if ENABLE_PRINTING: print(
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

    def u_get_gunner_target_tile(
        self,
        ray_tiles,
        current_round: int,
    ):
        return self.u_get_gunner_first_targetable_tile(ray_tiles, current_round)

    def u_gunner_should_attack_target(self, target_tile) -> bool:
        return (
            (
                target_tile.bot.id is not None
                and target_tile.bot.team != self.map.own_team
            )
            or target_tile.is_core_of(self.map.enemy_team)
            or (
                target_tile.building.id is not None
                and target_tile.building.team != self.map.own_team
            )
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
        marker_entity_type = getattr(EntityType, "MARKER", None)
        return (
            (
                target_tile.bot.id is not None
                and target_tile.bot.team != self.map.own_team
            )
            or target_tile.is_core_of(self.map.enemy_team)
            or (
                target_tile.building.id is not None
                and target_tile.building.team != self.map.own_team
                and target_tile.building.entity_type != marker_entity_type
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

    def u_enemy_harvester_has_adjacent_own_turret(self, harvester_tile) -> bool:
        harvester_team = harvester_tile.building.team
        for adjacent_idx in self.map.u_iter_cardinal_neighbor_indices(
            harvester_tile.index
        ):
            adjacent_tile = self.map.tiles_by_index[adjacent_idx]
            if (
                adjacent_tile.building.team == harvester_team
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
        for building_tile in self.map.own_buildings_in_vision:
            building_pos = building_tile.position
            if building_tile.building.entity_type == EntityType.GUNNER:
                if self.map.u_gunner_covers_target(
                    building_pos,
                    building_tile.building.direction,
                    target_pos,
                    building_tile.building.vision_radius_sq,
                ):
                    return True
                continue
            if building_tile.building.entity_type == EntityType.SENTINEL:
                if self.map.u_sentinel_covers_target(
                    building_pos,
                    building_tile.building.direction,
                    target_pos,
                    building_tile.building.vision_radius_sq,
                ):
                    return True
                continue
            if building_tile.building.entity_type == EntityType.BREACH:
                if self.map.u_breach_covers_target(
                    building_pos,
                    building_tile.building.direction,
                    target_pos,
                ):
                    return True

            if self.round_stopwatch.check_overtime_interval():
                break

        return False

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
