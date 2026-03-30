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

    # TODO
    def u_launcher_throw(self) -> bool:
        raise NotImplementedError
    
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
