from typing import TypedDict

from lib.agent import Agent
from constants import BBType, BB_TYPE_CORE_TILE, FOUNDRY_TURN, MIN_FOUNDRY_TITANIUM, AXIONITE_FARMING_BOTS_TO_SPAWN = 2

from cambc import Controller, Direction, EntityType, Position, Environment, Team


class PerViewIterStorage(TypedDict):
    enemy_detected: bool
    has_visible_allied_foundry: bool


class CoreAgent(Agent):
    def __init__(self, ct: Controller):
        super().__init__(ct)

        # performance variable is persistent across calc_per_view_field iterations
        # reset every round: not_iterative_update_at_turn_begin
        self.per_view_iter_storage: PerViewIterStorage = PerViewIterStorage(enemy_detected=False, has_visible_allied_foundry=False)

        # spawn count per tile
        self.spawn_tile_counts: dict[Direction, int] = dict.fromkeys(Direction, 0)

        # builder bot spawn count by type
        self.spawn_type_counts: dict[BBType, int] = dict.fromkeys(BBType, 0)

        # bb spawn count - doesn't respect killed bb
        self.spawn_bb_count: int = 0

        # history of resources acquisition
        self.resource_history: list[tuple[int, int]] = [self.ct.get_global_resources()]

        # turn number resource increase (titanium or axionite)
        self.last_turn_resource_increase: int = 0

        # turn number enemy in core vision range detected
        self.last_turn_enemy_detected: int = 0


    def cacl_per_view_field(
            self,
            i: int,
            pos: Position,
            bot: tuple[int, EntityType, Team] | None,
            building: tuple[int, EntityType, Team] | None,
            empty: bool,
            env: Environment,
            passable: bool,
    ) -> None:
        if not self.per_view_iter_storage['enemy_detected'] and bot and bot[2] != self.team:
            self.last_turn_enemy_detected = self.round
            self.per_view_iter_storage['enemy_detected'] = True

        if not self.per_view_iter_storage['has_visible_allied_foundry'] and building:
            temp = building[1] == EntityType.FOUNDRY and building[2] == self.team
            self.per_view_iter_storage['has_visible_allied_foundry'] = temp


    def not_iterative_update_at_turn_begin(self) -> None:
        self.per_view_iter_storage['enemy_detected'] = False
        self.per_view_iter_storage['has_visible_allied_foundry'] = False

        self.resource_history.append(self.ct.get_global_resources())


    def make_turn_on_calc(self) -> None:
        now = self.resource_history[-1]
        past = self.resource_history[-2]

        if now[0] > past[0] or now[1] > past[1]:
            self.last_turn_resource_increase = self.ct.get_current_round()


        force_foundry_spawn = (
            self.round >= FOUNDRY_TURN
            and self.resource_history[-1][0] >= MIN_FOUNDRY_TITANIUM
            and not self.per_view_iter_storage['has_visible_allied_foundry']
            and self.spawn_type_counts.get(BBType.FOUNDRY, int('inf')) < AXIONITE_FARMING_BOTS_TO_SPAWN
        )

        harassment_threshold = (
                HARASSMENT_SPAWN_BASE_TITANIUM_THRESHOLD
                + self.core_harassment_bbs_spawned * HARASSMENT_SPAWN_TITANIUM_STEP
        )

        force_harassment_spawn = (
                not DISABLE_HARASSMENT
                and titanium >= harassment_threshold
        )

        assigned_handler = Bot.run_bb_harassment
        should_spawn_from_initial_plan = False
        if force_foundry_spawn:
            assigned_handler = Bot.run_bb_foundry
        elif force_harassment_spawn:
            assigned_handler = Bot.run_bb_harassment
        else:
            if not self._advance_core_spawn_plan_until_next_builder():
                return

            should_spawn_from_initial_plan = (
                    self.core_spawn_plan_index < len(INITIAL_BB)
            )
            if not should_spawn_from_initial_plan:
                return

            if should_spawn_from_initial_plan:
                plan_entry = INITIAL_BB[self.core_spawn_plan_index]
                if callable(plan_entry):
                    assigned_handler = plan_entry

        core_pos = self.ct.get_position()
        preferred_offsets = [
            offset
            for offset, role_handler in CORE_TILE_BB_ROLE.items()
            if role_handler == assigned_handler
        ]
        if not preferred_offsets:
            return

        ordered_offsets = sorted(
            preferred_offsets,
            key=lambda offset: (
                self.core_spawn_tile_usage_counts.get(offset, 0),
                offset[0],
                offset[1],
            ),
        )
        for offset in ordered_offsets:
            dx, dy = offset
            spawn_pos = Position(core_pos.x + dx, core_pos.y + dy)
            if not self._is_in_bounds(spawn_pos):
                continue
            if not self.ct.can_spawn(spawn_pos):
                continue

            self.ct.spawn_builder(spawn_pos)
            self.core_bbs_spawned += 1
            self.core_spawn_tile_usage_counts[offset] = (
                    self.core_spawn_tile_usage_counts.get(offset, 0) + 1
            )
            if assigned_handler == Bot.run_bb_foundry:
                self.core_foundry_bbs_spawned += 1
            if assigned_handler == Bot.run_bb_harassment:
                self.core_harassment_bbs_spawned += 1
            if should_spawn_from_initial_plan:
                self.core_spawn_plan_index += 1
            self.last_action = BotAction.SPAWN_BUILDER
            return


    def spawn_bb(self, t: BBType) -> bool:
        dirs = BB_TYPE_CORE_TILE(t)

        pos = dirs[0]

        for d in dirs:
            if (self.spawn_tile_counts.get(d) or int('inf')) < (self.spawn_tile_counts.get(pos) or int('inf')):
                pos = d

        pos = self.position.add(pos)

        if self.ct.can_spawn(pos):
            self.ct.spawn_builder(pos)
            return True

        return False
