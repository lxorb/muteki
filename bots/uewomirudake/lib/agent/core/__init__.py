from cambc import Direction, EntityType

from lib.agent import Agent
from lib.agent.builder.strategies import (
    BUILDER_STRATEGY_BY_TILE,
    FURTHER_BB_MIN_TURN,
    FURTHER_BB_MIN_TITANIUM,
    FUTHER_BB_ROTATION,
    FURTHER_BB_TITANIUM_INCREASE_PER_SPAWN,
    INITIAL_BB_ORDER,
)
from lib.agent.constants import (
    AXIONITE_TO_TITANIUM_CONVERSION_MIN_ARMOURED_CONVEYORS,
    AXIONITE_TO_TITANIUM_CONVERSION_MIN_TITANIUM,
    CORE_DEFENDER_STRATEGY_ID,
    DISABLE_HARASSMENT,
    HARASSMENT_STRATEGY_ID,
    SURRENDER_AT_TURN,
)


class CoreAgent(Agent):
    def __init__(self):
        super().__init__()
        self.spawn_tile_counts: dict[Direction, int] = dict.fromkeys(Direction, 0)
        self.spawn_bb_count = 0
        self.builder_bot_order: list[str] = [
            strategy_id
            for strategy_id in INITIAL_BB_ORDER
            if not (
                DISABLE_HARASSMENT and strategy_id == HARASSMENT_STRATEGY_ID
            )
        ]
        self.further_builder_rotation: list[str] = [
            strategy_id
            for strategy_id in FUTHER_BB_ROTATION
            if not (
                DISABLE_HARASSMENT and strategy_id == HARASSMENT_STRATEGY_ID
            )
        ]
        self.spawning_order_pos = 0
        self.further_spawn_count = 0
        self.further_spawn_rotation_pos = 0
        self.core_defender_requested = False
        self.core_defender_spawned = False

    def u_handler(self):
        if self.ct.get_current_round() >= SURRENDER_AT_TURN:
            self.ct.resign()
            return True
        self.u_convert_axionite_if_low_on_titanium()
        self.u_request_core_defender_on_first_enemy_builder_seen()
        self.u_spawn_core_defender()
        self.u_spawn_initial_bb()
        self.u_spawn_further_bb()

    def u_request_core_defender_on_first_enemy_builder_seen(self) -> bool:
        if self.core_defender_requested or self.core_defender_spawned:
            return False

        for tile in self.map.tiles_in_vision:
            if (
                tile.bot.id is not None
                and tile.bot.team != self.map.own_team
                and tile.bot.entity_type == EntityType.BUILDER_BOT
            ):
                self.core_defender_requested = True
                return True

        return False

    def u_spawn_core_defender(self) -> bool:
        if not self.core_defender_requested or self.core_defender_spawned:
            return False
        if not self.u_spawn_builder(CORE_DEFENDER_STRATEGY_ID):
            return False

        self.core_defender_spawned = True
        return True

    def u_convert_axionite_if_low_on_titanium(self) -> bool:
        if self.map.titanium >= AXIONITE_TO_TITANIUM_CONVERSION_MIN_TITANIUM:
            return False
        _, armoured_conveyor_axionite_cost = getattr(
            self.ct,
            f"get_{EntityType.ARMOURED_CONVEYOR.value}_cost",
        )()
        reserved_axionite = max(
            1,
            armoured_conveyor_axionite_cost
            * AXIONITE_TO_TITANIUM_CONVERSION_MIN_ARMOURED_CONVEYORS,
        )
        if self.map.axionite <= reserved_axionite:
            return False
        self.ct.convert(self.map.axionite - reserved_axionite)
        return True

    def u_spawn_further_bb(self) -> bool:
        """
        Spawn additional builders from a configured rotation once enough titanium is available.
        """
        if not self.further_builder_rotation:
            return False
        if self.ct.get_current_round() < FURTHER_BB_MIN_TURN:
            return False

        required_titanium = (
            FURTHER_BB_MIN_TITANIUM
            + self.further_spawn_count * FURTHER_BB_TITANIUM_INCREASE_PER_SPAWN
        )
        if self.map.titanium < required_titanium:
            return False

        rotation_length = len(self.further_builder_rotation)
        for offset in range(rotation_length):
            rotation_idx = (self.further_spawn_rotation_pos + offset) % rotation_length
            builder_bot_strategy = self.further_builder_rotation[rotation_idx]
            if not self.u_spawn_builder(builder_bot_strategy):
                continue

            self.further_spawn_count += 1
            self.further_spawn_rotation_pos = (rotation_idx + 1) % rotation_length
            return True

        return False

    def u_spawn_initial_bb(self) -> bool:
        while self.spawning_order_pos < len(self.builder_bot_order):
            builder_bot_strategy = self.builder_bot_order[self.spawning_order_pos]
            if DISABLE_HARASSMENT and builder_bot_strategy == HARASSMENT_STRATEGY_ID:
                self.spawning_order_pos += 1
                continue

            if not self.u_spawn_builder(builder_bot_strategy):
                return False

            self.spawning_order_pos += 1
            return True

        return False

    def u_get_builder_spawn_candidates(
        self,
        builder_bot_strategy: str,
    ) -> list[tuple[int, int, int, Direction]]:
        core_center_pos = self.map.own_core_center_pos
        if core_center_pos is None:
            return []
        candidate_spawns: list[tuple[int, int, int, Direction]] = []

        for core_tile in self.map.u_get_core_footprint_positions(core_center_pos):
            relative_offset = (
                core_tile.position.x - core_center_pos.x,
                core_tile.position.y - core_center_pos.y,
            )
            if BUILDER_STRATEGY_BY_TILE.get(relative_offset) != builder_bot_strategy:
                continue
            if core_tile.bot.id is not None:
                continue

            spawn_direction = next(
                direction
                for direction in Direction
                if direction.delta() == relative_offset
            )
            if not self.ct.can_spawn(core_tile.position):
                continue

            candidate_spawns.append(
                (
                    self.spawn_tile_counts[spawn_direction],
                    core_tile.position.x,
                    core_tile.position.y,
                    spawn_direction,
                )
            )

        return candidate_spawns

    def u_spawn_builder(self, builder_bot_strategy: str) -> bool:
        if DISABLE_HARASSMENT and builder_bot_strategy == HARASSMENT_STRATEGY_ID:
            return False

        core_center_pos = self.map.own_core_center_pos
        if core_center_pos is None:
            return False
        candidate_spawns = self.u_get_builder_spawn_candidates(builder_bot_strategy)
        if not candidate_spawns:
            return False

        _, _, _, spawn_direction = min(
            candidate_spawns,
            key=lambda candidate: candidate[:3],
        )
        spawn_pos = core_center_pos.add(spawn_direction)
        self.ct.spawn_builder(spawn_pos)
        self.spawn_bb_count += 1
        self.spawn_tile_counts[spawn_direction] += 1
        return True
