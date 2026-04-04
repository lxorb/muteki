import time
from abc import ABC, abstractmethod
from typing import NamedTuple
import array
from functools import lru_cache
import heapq

from cambc import (
    Controller,
    EntityType,
    Team,
    Direction,
    Position,
    Environment,
)


class Player:
    def __init__(self):
        self.agent: Agent = Agent()

    def run(self, ct: Controller) -> None:
        if type(self.agent) is Agent:
            t = ct.get_entity_type()
            if t is EntityType.CORE:
                self.agent = CoreAgent(ct)
            elif t is EntityType.BUILDER_BOT:
                self.agent = BuilderAgent(ct)
            elif t in [EntityType.SENTINEL, EntityType.GUNNER, EntityType.BREACH]:
                self.agent = TurretAgent(ct)

        self.agent.run()


class Agent:
    def run(self):
        pass


class Resources(NamedTuple):
    ti: int
    ax: int

    def change_to(self, new: 'Resources') -> 'Resources':
        return Resources(
            ti=self.ti - new.ti,
            ax=self.ax - new.ax
        )

    def is_neg(self) -> bool:
        return self.ti <= 0 and self.ax <= 0


class DefaultAgent(ABC, Agent):
    def __init__(self, ct: Controller):
        self.ct: Controller = ct
        self.id: int = self.ct.get_id()
        self.team: Team = self.ct.get_team()
        self.birth: int = self.ct.get_current_round()
        self.round: int = self.ct.get_current_round()
        self.position: Position = self.ct.get_position()
        core = self.ct.get_nearby_buildings(1)
        self.core_pos: Position = self.ct.get_position(core[0])
        self.turn_last_completed: bool | None = None

        self.time_start: int = 0
        self.time_end: int = 0
        self.time_delta: int = 0
        self.time_delta_overall: int = 0

        _r = self.ct.get_global_resources()
        self.res_prev: Resources = Resources(_r[0], _r[1])
        self.res: Resources = Resources(0, 0)
        self.res_change: Resources = Resources(0, 0)
        self.res_last_dec: int = 0

    def run(self) -> None:
        self.turn_last_completed = False
        self.time_start = time.perf_counter_ns()
        # --------------------------------------------------------

        _r = self.ct.get_global_resources()
        self.res = Resources(_r[0], _r[1])
        self.res_change = self.res_prev.change_to(self.res)
        if self.res_change.is_neg():
            self.res_last_dec = self.round

        # --------------------------------------------------------
        self.make_turn()
        # --------------------------------------------------------

        self.res_prev = self.res
        self.round += 1

        # --------------------------------------------------------
        self.time_end = time.perf_counter_ns()
        self.time_delta = self.time_end - self.time_start
        print(f'run() took: {self.time_delta / 1_000_000:.4f} ms')
        self.time_start = self.time_end
        self.time_delta_overall += self.time_delta
        self.turn_last_completed = True

    @abstractmethod
    def make_turn(self) -> None:
        pass


# Todo: put the largest map size here
@lru_cache(maxsize=10000)
def neighbor_tiles(width: int, height: int, pos: Position) -> dict[Direction, Position]:
    neighbors = {}
    for d in Direction:
        if d is Direction.CENTRE:
            continue
        n = pos.add(d)
        if 0 <= n.x < width and 0 <= n.y < height:
            neighbors[d] = n
    return neighbors


TILE_WALK = 10
TILE_EMPTY = 11
TILE_UNKNOWN = 12
TILE_BLOCK = 10_000_000


class DStarLite:
    """D* Lite algorithm for incremental path planning with dynamic obstacles."""

    def __init__(self, agent: 'BuilderAgent'):
        self.agent = agent
        self.width = agent.width
        self.height = agent.height
        self.size = agent.size

        # D* Lite state using lists for performance
        self.g = [float(TILE_BLOCK)] * self.size
        self.rhs = [float(TILE_BLOCK)] * self.size
        self.U: list[tuple[tuple[float, float], Position]] = []
        self.km: float = 0.0

        self.s_start: Position | None = None
        self.s_goal: Position | None = None
        self.s_last: Position | None = None

        # in_queue tracks the key for each idx (lazy deletion)
        self.in_queue: list[tuple[float, float] | None] = [None] * self.size

        # Track which cells have changed since last replan
        self.changed_cells: set[Position] = set()

    def _heuristic(self, s1: Position, s2: Position) -> float:
        """Chebyshev distance heuristic for 8-directional movement with uniform cost."""
        return float(max(abs(s1.x - s2.x), abs(s1.y - s2.y)))

    def _calculate_key(self, s: Position) -> tuple[float, float]:
        idx = s.y * self.width + s.x
        g_val = self.g[idx]
        rhs_val = self.rhs[idx]
        min_val = min(g_val, rhs_val)
        h = float(max(abs(self.s_start.x - s.x), abs(self.s_start.y - s.y)))
        return (min_val + h + self.km, min_val)

    def _calculate_rhs(self, u: Position) -> float:
        """Calculate one-step lookahead value for vertex u."""
        if u == self.s_goal:
            return 0.0
        
        min_rhs = float(TILE_BLOCK)
        for s_prime in neighbor_tiles(self.width, self.height, u).values():
            idx = s_prime.y * self.width + s_prime.x
            cost = self.agent.map_walk[idx]
            if cost < TILE_BLOCK:
                candidate = cost + self.g[idx]
                if candidate < min_rhs:
                    min_rhs = candidate
        return min_rhs

    def _push_vertex(self, u: Position, key: tuple[float, float]) -> None:
        """Push u into the heap with the given key and record it in in_queue."""
        idx = u.y * self.width + u.x
        if self.in_queue[idx] == key:
            return
        self.in_queue[idx] = key
        heapq.heappush(self.U, (key, u))

    def _update_vertex(self, u: Position) -> None:
        """Update a vertex's rhs value and its position in the priority queue."""
        u_idx = u.y * self.width + u.x
        if u != self.s_goal:
            self.rhs[u_idx] = self._calculate_rhs(u)

        g_val = self.g[u_idx]
        rhs_val = self.rhs[u_idx]

        if g_val != rhs_val:
            self._push_vertex(u, self._calculate_key(u))
        else:
            self.in_queue[u_idx] = None

    def _compute_shortest_path(self) -> None:
        """Compute or update the shortest path (canonical D* Lite inner loop)."""
        max_iterations = self.size * 4
        start_idx = self.s_start.y * self.width + self.s_start.x

        for _ in range(max_iterations):
            if not self.U:
                break

            start_key = self._calculate_key(self.s_start)
            g_start = self.g[start_idx]
            rhs_start = self.rhs[start_idx]

            top_key, _ = self.U[0]
            if top_key >= start_key and rhs_start == g_start:
                break

            k_old, u = heapq.heappop(self.U)
            u_idx = u.y * self.width + u.x

            k_new = self._calculate_key(u)
            if k_old < k_new:
                if self.g[u_idx] != self.rhs[u_idx]:
                    self._push_vertex(u, k_new)
                continue

            self.in_queue[u_idx] = None
            g_val = self.g[u_idx]
            rhs_val = self.rhs[u_idx]

            if g_val == rhs_val:
                continue

            if g_val > rhs_val:
                self.g[u_idx] = rhs_val
                for s in neighbor_tiles(self.width, self.height, u).values():
                    self._update_vertex(s)
            else:
                self.g[u_idx] = float(TILE_BLOCK)
                self._update_vertex(u)
                for s in neighbor_tiles(self.width, self.height, u).values():
                    self._update_vertex(s)

    def initialize(self, start: Position, goal: Position) -> None:
        """Initialize D* Lite for a new goal."""
        self.s_start = start
        self.s_goal = goal
        self.s_last = start
        self.km = 0.0

        for i in range(self.size):
            self.g[i] = float(TILE_BLOCK)
            self.rhs[i] = float(TILE_BLOCK)
            self.in_queue[i] = None
        self.U.clear()
        self.changed_cells.clear()

        goal_idx = goal.y * self.width + goal.x
        self.rhs[goal_idx] = 0.0
        self._push_vertex(self.s_goal, self._calculate_key(self.s_goal))

        self._compute_shortest_path()

    def update_start(self, new_start: Position) -> None:
        """Update when the agent has moved to a new position."""
        if self.s_start is None or self.s_goal is None:
            return

        self.km += self._heuristic(self.s_last, new_start)
        self.s_last = new_start
        self.s_start = new_start

    def update_cell(self, pos: Position) -> None:
        """Mark a cell as changed (obstacle detected/removed)."""
        self.changed_cells.add(pos)

    def replan(self) -> None:
        if self.s_start is None or self.s_goal is None:
            return

        affected: set[Position] = set()
        if self.changed_cells:
            for u in self.changed_cells:
                affected.add(u)
                for s in neighbor_tiles(self.width, self.height, u).values():
                    affected.add(s)
            self.changed_cells.clear()

            for u in affected:
                self._update_vertex(u)

        self._compute_shortest_path()

    def get_next_direction(self) -> Direction:
        """Return the next direction the robot should move toward the goal."""
        if self.s_start is None or self.s_goal is None:
            return Direction.CENTRE

        if self.s_start == self.s_goal:
            return Direction.CENTRE

        start_idx = self.s_start.y * self.width + self.s_start.x
        if self.rhs[start_idx] >= TILE_BLOCK:
            return Direction.CENTRE

        best_cost = float(TILE_BLOCK)
        best_dir = Direction.CENTRE

        for direction, neighbor in neighbor_tiles(self.width, self.height, self.s_start).items():
            idx = neighbor.y * self.width + neighbor.x
            cost = self.agent.map_walk[idx]
            if cost < TILE_BLOCK:
                neighbor_cost = min(self.g[idx], self.rhs[idx])
                total = cost + neighbor_cost
                if total < best_cost:
                    best_cost = total
                    best_dir = direction

        return best_dir

    def has_path(self) -> bool:
        """Check if a valid path exists to the goal."""
        if self.s_start is None:
            return False
        start_idx = self.s_start.y * self.width + self.s_start.x
        return self.rhs[start_idx] < TILE_BLOCK


TASK_STALE = -1
TASK_EXPLORE = 0


class BuilderAgent(DefaultAgent):
    def __init__(self, ct: Controller):
        super().__init__(ct)
        self.task: int = TASK_EXPLORE
        self.target_pos: Position = self.position
        self.target_pos_prev: Position | None = None
        self.direction: Direction = Direction.CENTRE

        self.width: int = self.ct.get_map_width()
        self.height: int = self.ct.get_map_height()
        self.size: int = self.width * self.height

        # two maps, one for passability and the other stores the round in which a tile was last seen
        self.map_walk = array.array('i', [TILE_UNKNOWN] * self.size)

        self.dstar: DStarLite = DStarLite(self)

    def choose_task(self):
        if self.position == self.target_pos and self.round != self.birth:
            self.task = TASK_STALE
        else:
            self.task = TASK_EXPLORE

    def make_turn(self):
        self.position = self.ct.get_position()

        self.update_on_view()

        self.choose_task()

        task = self.task
        if task == TASK_EXPLORE:
            self.explore()

    def explore(self):
        if self.round == self.birth:
            self.target_pos = Position(4, 21)

        self.d_star_next()
        self.move()

    def d_star_next(self):
        if self.target_pos != self.target_pos_prev:
            self.dstar.initialize(self.position, self.target_pos)
            self.target_pos_prev = self.target_pos
        else:
            self.dstar.update_start(self.position)
            self.dstar.replan()

        self.direction = self.dstar.get_next_direction()

    def move(self):
        d = self.direction
        next_pos = self.position.add(d)
        if self.ct.can_build_road(next_pos):
            self.ct.build_road(next_pos)
        if self.ct.can_move(d):
            self.ct.move(d)

    def update_on_view(self):
        ct = self.ct
        map_walk = self.map_walk
        width = self.width
        dstar_update = self.dstar.update_cell

        for pos in ct.get_nearby_tiles():
            if ct.is_tile_passable(pos):
                walk = TILE_WALK
            elif ct.get_tile_builder_bot_id(pos) is not None:
                walk = TILE_BLOCK
            elif ct.is_tile_empty(pos):
                walk = TILE_EMPTY
            elif ct.get_tile_env(pos) is Environment.WALL:
                walk = TILE_BLOCK
            elif ct.get_tile_building_id(pos) is not None:
                walk = TILE_BLOCK
            else:
                walk = TILE_UNKNOWN

            idx = pos.y * width + pos.x
            if walk != map_walk[idx]:
                dstar_update(pos)
                map_walk[idx] = walk


class CoreAgent(DefaultAgent):
    def __init__(self, ct: Controller):
        super().__init__(ct)
        self.spawn_bb_count: int = 0

    def make_turn(self) -> None:
        if self.spawn_bb_count < 3:
            self.spawn_bb()

    def spawn_bb(self) -> bool:
        pos = self.position

        if self.ct.can_spawn(pos):
            self.ct.spawn_builder(pos)
            self.spawn_bb_count += 1
            return True

        return False

    def convert_refined_ax(self, amount: int) -> bool:
        if 0 <= amount <= self.res.ax:
            self.ct.convert(amount)
            return True

        return False


class TurretAgent(DefaultAgent):
    def __init__(self, ct: Controller):
        super().__init__(ct)

    def make_turn(self):
        pass
