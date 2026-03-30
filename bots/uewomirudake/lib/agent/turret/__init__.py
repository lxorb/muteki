from cambc import EntityType, Position

from lib.agent import Agent


ATTACK_TURRET_TYPES = {
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
}

TURRET_TARGET_PRIORITY = (
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.BREACH,
    EntityType.LAUNCHER,
    "enemy_bot_on_ally_tile",
    "enemy_bot_on_non_ally_tile",
    EntityType.CORE,
    EntityType.HARVESTER,
    EntityType.BRIDGE,
    EntityType.CONVEYOR,
    EntityType.BARRIER,
    EntityType.SPLITTER,
    EntityType.FOUNDRY,
    EntityType.ROAD,
    EntityType.ARMOURED_CONVEYOR,
)

TURRET_TARGET_PRIORITY_RANK = {
    target_type: idx
    for idx, target_type in enumerate(TURRET_TARGET_PRIORITY)
}

LAUNCHER_THROWABLE_PRIORITY = (
    "enemy_bot_on_ally_bridge",
    "enemy_bot_on_ally_conveyor",
    "enemy_bot_on_ally_armoured_conveyor",
    "enemy_bot_on_ally_road",
    "enemy_bot_on_empty_tile",
    "enemy_bot_elsewhere",
)

LAUNCHER_THROWABLE_PRIORITY_RANK = {
    target_type: idx
    for idx, target_type in enumerate(LAUNCHER_THROWABLE_PRIORITY)
}


class TurretAgent(Agent):
    def __init__(self):
        super().__init__()

    def u_handler(self) -> bool:
        """
        Dispatch turret behavior by turret type.
        """
        match self.ct.get_entity_type():
            case EntityType.LAUNCHER:
                return self.u_launcher_throw()
            case EntityType.GUNNER:
                return self.u_turret_attack()
            case EntityType.SENTINEL:
                return self.u_turret_attack()
            case EntityType.BREACH:
                return self.u_turret_attack()
        return False

    def u_turret_attack(self) -> bool:
        """
        Fire at the best legal enemy tile from this turret's attackable pattern.

        The attack starts from `get_attackable_tiles()`, keeps only tiles this
        turret can currently fire at, and discards tiles without a visible enemy
        bot or enemy building. It then applies the configured category order.

        Within the attack-turret bucket, enemy turrets that can currently hit
        this turret are preferred, then lower remaining HP breaks ties. Enemy
        bots on allied tiles and enemy bots elsewhere are separate priority
        buckets, and each bucket breaks ties by lower remaining HP. All later
        buckets also tie-break by lower remaining HP. The first tile after that
        ordering is fired at.
        """
        candidate_targets = self.u_filter_tiles(
            self.ct.get_attackable_tiles(),
            lambda pos: self.map.u_get_pos_tile(pos).in_vision_radius,
            self.ct.can_fire,
            lambda pos: self.u_get_target_priority_key(pos) is not None,
        )
        candidate_targets = self.u_prioritize_tiles(
            candidate_targets,
            self.u_get_target_priority_key,
            lambda pos: pos.x,
            lambda pos: pos.y,
        )
        if not candidate_targets:
            return False

        self.ct.fire(candidate_targets[0])
        return True

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
        throwable_positions = self.u_filter_tiles(
            list(self.map.u_iter_adjacent_positions(launcher_pos)),
            lambda pos: self.map.u_get_pos_tile(pos).builder_bot_id is not None,
            lambda pos: (
                self.map.u_get_pos_tile(pos).builder_bot_team != self.map.own_team
            ),
        )
        throwable_positions = self.u_prioritize_tiles(
            throwable_positions,
            self.u_get_launcher_throwable_priority_key,
            lambda pos: pos.x,
            lambda pos: pos.y,
        )

        for bot_pos in throwable_positions:
            if self.u_get_launcher_throw_target(bot_pos) is not None:
                return bot_pos
        return None

    def u_get_launcher_throwable_priority_key(
        self,
        pos: Position,
    ) -> tuple[int, int | None]:
        target_tile = self.map.u_get_pos_tile(pos)
        if target_tile.building_team == self.map.own_team:
            if target_tile.building_type == EntityType.BRIDGE:
                return (
                    LAUNCHER_THROWABLE_PRIORITY_RANK["enemy_bot_on_ally_bridge"],
                    target_tile.builder_bot_hp,
                )
            if target_tile.building_type == EntityType.CONVEYOR:
                return (
                    LAUNCHER_THROWABLE_PRIORITY_RANK["enemy_bot_on_ally_conveyor"],
                    target_tile.builder_bot_hp,
                )
            if target_tile.building_type == EntityType.ARMOURED_CONVEYOR:
                return (
                    LAUNCHER_THROWABLE_PRIORITY_RANK[
                        "enemy_bot_on_ally_armoured_conveyor"
                    ],
                    target_tile.builder_bot_hp,
                )
            if target_tile.building_type == EntityType.ROAD:
                return (
                    LAUNCHER_THROWABLE_PRIORITY_RANK["enemy_bot_on_ally_road"],
                    target_tile.builder_bot_hp,
                )

        if target_tile.building_id is None:
            return (
                LAUNCHER_THROWABLE_PRIORITY_RANK["enemy_bot_on_empty_tile"],
                target_tile.builder_bot_hp,
            )

        return (
            LAUNCHER_THROWABLE_PRIORITY_RANK["enemy_bot_elsewhere"],
            target_tile.builder_bot_hp,
        )

    def u_get_launcher_throw_target(self, bot_pos: Position) -> Position | None:
        launcher_pos = self.map.current_pos
        candidate_targets = self.u_filter_tiles(
            self.ct.get_attackable_tiles(),
            lambda pos: self.map.u_get_pos_tile(pos).is_passable,
            lambda pos: self.map.u_get_pos_tile(pos).builder_bot_id is None,
            lambda pos: launcher_pos.distance_squared(pos) > 2,
            lambda pos: self.ct.can_launch(bot_pos, pos),
        )
        turret_covered_targets = self.u_filter_tiles(
            candidate_targets,
            self.u_is_in_own_turret_attack_range,
        )
        if turret_covered_targets:
            candidate_targets = turret_covered_targets
        if not candidate_targets:
            return None

        candidate_targets = self.u_prioritize_tiles(
            candidate_targets,
            lambda pos: -self.map.u_get_pos_tile(pos).own_core_dist,
            lambda pos: pos.x,
            lambda pos: pos.y,
        )
        return candidate_targets[0]

    def u_is_in_own_turret_attack_range(self, target_pos: Position) -> bool:
        for building_pos in self.map.buildings_in_vision:
            building_tile = self.map.u_get_pos_tile(building_pos)
            if building_tile.building_team != self.map.own_team:
                continue
            if building_tile.building_type == EntityType.GUNNER:
                if self.map.u_gunner_covers_target(
                    building_pos,
                    building_tile.building_direction,
                    target_pos,
                    building_tile.building_vision_radius_sq,
                ):
                    return True
                continue
            if building_tile.building_type == EntityType.SENTINEL:
                if self.map.u_sentinel_covers_target(
                    building_pos,
                    building_tile.building_direction,
                    target_pos,
                    building_tile.building_vision_radius_sq,
                ):
                    return True
                continue
            if building_tile.building_type == EntityType.BREACH:
                if self.map.u_breach_covers_target(
                    building_pos,
                    building_tile.building_direction,
                    target_pos,
                ):
                    return True

        return False
    
    def u_get_target_priority_key(
        self,
        pos: Position,
    ) -> tuple[int, ...] | None:
        target_tile = self.map.u_get_pos_tile(pos)
        own_team = self.map.own_team
        building_id = target_tile.building_id
        builder_bot_id = target_tile.builder_bot_id

        enemy_building_id = None
        enemy_building_type = target_tile.building_type
        if (
            building_id is not None
            and target_tile.building_team != own_team
        ):
            enemy_building_id = building_id

        enemy_builder_bot_id = None
        if (
            builder_bot_id is not None
            and target_tile.builder_bot_team != own_team
        ):
            enemy_builder_bot_id = builder_bot_id

        if (
            enemy_building_id is not None
            and enemy_building_type in ATTACK_TURRET_TYPES
        ):
            return (
                TURRET_TARGET_PRIORITY_RANK[enemy_building_type],
                0 if self.u_enemy_turret_targets_self(enemy_building_id) else 1,
                target_tile.building_hp,
            )

        if enemy_builder_bot_id is not None:
            return (
                TURRET_TARGET_PRIORITY_RANK[
                    "enemy_bot_on_ally_tile"
                    if self.c_is_enemy_bot_on_ally_tile(target_tile)
                    else "enemy_bot_on_non_ally_tile"
                ],
                target_tile.builder_bot_hp,
            )

        if (
            enemy_building_id is None
            or enemy_building_type not in TURRET_TARGET_PRIORITY_RANK
        ):
            return None

        return (
            TURRET_TARGET_PRIORITY_RANK[enemy_building_type],
            target_tile.building_hp,
        )

    def c_is_enemy_bot_on_ally_tile(self, target_tile) -> bool:
        if target_tile.building_id is None:
            return False
        return target_tile.building_team == self.map.own_team

    def u_enemy_turret_targets_self(self, enemy_turret_id: int) -> bool:
        enemy_turret_pos = self.ct.get_position(enemy_turret_id)
        enemy_turret_tile = self.map.u_get_pos_tile(enemy_turret_pos)
        turret_type = enemy_turret_tile.building_type
        target_pos = self.map.current_pos

        if turret_type == EntityType.GUNNER:
            return self.map.u_gunner_covers_target(
                enemy_turret_pos,
                enemy_turret_tile.building_direction,
                target_pos,
                enemy_turret_tile.building_vision_radius_sq,
            )
        if turret_type == EntityType.SENTINEL:
            return self.map.u_sentinel_covers_target(
                enemy_turret_pos,
                enemy_turret_tile.building_direction,
                target_pos,
                enemy_turret_tile.building_vision_radius_sq,
            )
        if turret_type == EntityType.BREACH:
            return self.map.u_breach_covers_target(
                enemy_turret_pos,
                enemy_turret_tile.building_direction,
                target_pos,
            )
        return False
