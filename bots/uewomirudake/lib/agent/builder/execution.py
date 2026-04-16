from lib.agent.builder.strategies import STRATEGIES
from lib.debug import Stopwatch
from lib.map.constants import MARKER_SYMMETRY_LIST
from cambc import Position, EntityType


class BuilderExecutionMixin:
    def u_execute_strategy(self) -> bool:
        """
        Execute this builder's ordered strategy methods.

        `self.strategy` is treated as a priority-ordered list of
        `BuilderAgent` strategy methods (hence starting with s_). Each entry is bound to
        this builder instance and then executed. On a fresh turn the executor
        starts at index `0`. If the previous turn ended before this method
        returned, execution resumes at the first method that has not completed
        yet, which is the entry after `last_strategy_index`. The index is only
        advanced after a method returns, so an interrupted step is retried on
        the next turn. Execution stops at the first truthy result and returns
        whether any strategy method acted.
        """

        stopwatch = Stopwatch("Builder strats")
        stopwatch.start()

        strategy_steps = STRATEGIES.get(self.strategy, [])

        if self.last_turn_completed:
            self.last_strategy_index = -1
            start_index = 0
        else:
            start_index = self.last_strategy_index + 1
            if start_index >= len(strategy_steps):
                start_index = 0

        stopwatch.lap("Init logic")

        self.last_turn_completed = False

        # PROVISORISCH
        if self.ct.get_current_round() % 15 == 0:
            action_radius = 2
            candidate_positions = self.ct.get_nearby_tiles(action_radius)
            pos_round = []
            for pos in candidate_positions:
                if self.ct.can_build_launcher(pos):
                    self.ct.build_launcher(pos)
                    break

        for idx in range(start_index, len(strategy_steps)):
            if self.round_stopwatch.check_overtime():
                stopwatch.lap("Overtime")
                stopwatch.log()
                return False

            strategy_method, strategy_args = self.u_get_bound_method_and_args(
                strategy_steps[idx]
            )
            acted = bool(strategy_method(*strategy_args))
            self.last_strategy_index = idx

            stopwatch.lap(
                strategy_method.__name__[:16]
            )  # Truncate name so that we get nice lines in replay viewer

            if acted:
                self.last_turn_completed = True
                print(f"Executed strategy: {strategy_method.__name__}")
                stopwatch.log()
                self.after_strategy()
                return True

        self.last_turn_completed = True
        stopwatch.lap("Complete turn")
        stopwatch.log()


        self.after_strategy()

        return False

    def after_strategy(self):
        self.place_marker()

    def place_marker(self):
        symmetry_type = MARKER_SYMMETRY_LIST.index(self.map.symmetry_mode)
        # 2 bits
        own_id = self.ct.get_id() & 0b111111
        # 6 bits
        current_round = self.ct.get_current_round()
        # 11 bits
        target_position = self.map.own_core_center_pos # TODO
        target_index = target_position.y * self.map.INDEX_STRIDE + target_position.x
        # 12 bits

        result = 0
        result |= symmetry_type
        result |= own_id << 2
        result |= current_round << 8
        result |= target_index << 19

        # place a marker in the action radius where possible
        action_radius = 2
        candidate_positions = self.ct.get_nearby_tiles(action_radius)
        pos_round = []
        for pos in candidate_positions:
            if self.ct.can_place_marker(pos):
                # cannot use the information in the map, since we store marker as "nothing"
                # it is never possible that a marker we are building over contains better information about symmetry -> updated in update_vision
                building_id = self.ct.get_tile_building_id(pos)
                if building_id is not None and self.ct.get_entity_type(building_id) == EntityType.MARKER and self.ct.get_team(building_id) == self.ct.get_team():
                    content = self.ct.get_marker_value(building_id)
                    n_symmetry_mode, n_own_id, n_current_round, n_target_x, n_target_y = self.map.read_marker(content)
                    pos_round.append((pos, n_current_round))
                    continue
                self.ct.place_marker(pos, result)
                print(self.map.symmetry_mode, symmetry_type)
                return;
        if pos_round:
            pos_round = sorted(pos_round, key = lambda x: x[1])
            self.ct.place_marker(pos_round[0][0], result)



    
