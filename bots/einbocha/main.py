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

        _r = self.ct.get_global_resources()
        self.res_prev: Resources = Resources(_r[0], _r[1])
        self.res: Resources = Resources(0, 0)
        self.res_change: Resources = Resources(0, 0)
        self.res_last_dec: int = 0

    def run(self) -> None:
        self.turn_last_completed = False
        time_start = time.perf_counter_ns()
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
        time_end = time.perf_counter_ns()
        time_delta = time_end - time_start
        print(f'run() took: {time_delta / 1_000_000:.4f} ms')
        self.turn_last_completed = True

    @abstractmethod
    def make_turn(self) -> None:
        pass


TILE_WALK = 10
TILE_EMPTY = 11
TILE_UNKNOWN = 12
TILE_BLOCK = 10_000_000


class DStarLite:
    """D* Lite algorithm for incremental path planning with dynamic obstacles."""

    def __init__(self, agent: 'BuilderAgent'):
        time_init_start = time.perf_counter_ns()

        self.agent = agent
        self.width = agent.width
        self.height = agent.height
        self.size = agent.size

        # Precompute neighbors as indices for faster lookup
        self.neighbors: list[list[int]] = [[] for _ in range(self.size)]
        for y in range(self.height):
            for x in range(self.width):
                idx = y * self.width + x
                for dx in [-1, 0, 1]:
                    for dy in [-1, 0, 1]:
                        if dx == 0 and dy == 0:
                            continue
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < self.width and 0 <= ny < self.height:
                            self.neighbors[idx].append(ny * self.width + nx)

        # D* Lite state using lists for performance
        self.g = [float(TILE_BLOCK)] * self.size
        self.rhs = [float(TILE_BLOCK)] * self.size
        self.U: list[tuple[tuple[float, float], int]] = []
        self.km: float = 0.0

        self.s_start_idx: int = -1
        self.s_goal_idx: int = -1
        self.s_last_idx: int = -1

        # in_queue tracks the key for each idx (lazy deletion)
        self.in_queue: list[tuple[float, float] | None] = [None] * self.size

        # Track which cells have changed since last replan
        self.changed_cells: set[int] = set()

        time_init_end = time.perf_counter_ns()

        print(f'd star lite __init__() took: {(time_init_end - time_init_start) / 1_000_000:.4f} ms')

    def _heuristic(self, s1_idx: int, s2_idx: int) -> float:
        """Chebyshev distance heuristic for 8-directional movement with uniform cost."""
        x1, y1 = s1_idx % self.width, s1_idx // self.width
        x2, y2 = s2_idx % self.width, s2_idx // self.width
        return float(max(abs(x1 - x2), abs(y1 - y2)))

    def _calculate_key(self, s_idx: int) -> tuple[float, float]:
        g_val = self.g[s_idx]
        rhs_val = self.rhs[s_idx]
        min_val = min(g_val, rhs_val)
        
        # Inlined heuristic for speed
        # s_idx % self.width, s_idx // self.width
        # self.s_start_idx % self.width, self.s_start_idx // self.width
        h = float(max(abs((s_idx % self.width) - (self.s_start_idx % self.width)), 
                      abs((s_idx // self.width) - (self.s_start_idx // self.width))))
        
        return (min_val + h + self.km, min_val)

    def _calculate_rhs(self, u_idx: int) -> float:
        """Calculate one-step lookahead value for vertex u."""
        if u_idx == self.s_goal_idx:
            return 0.0
        
        min_rhs = float(TILE_BLOCK)
        map_walk = self.agent.map_walk
        g = self.g
        for s_prime_idx in self.neighbors[u_idx]:
            cost = map_walk[s_prime_idx]
            if cost < TILE_BLOCK:
                candidate = float(cost) + g[s_prime_idx]
                if candidate < min_rhs:
                    min_rhs = candidate
        return min_rhs

    def _push_vertex(self, u_idx: int, key: tuple[float, float]) -> None:
        """Push u into the heap with the given key and record it in in_queue."""
        if self.in_queue[u_idx] == key:
            return
        self.in_queue[u_idx] = key
        heapq.heappush(self.U, (key, u_idx))

    def _update_vertex(self, u_idx: int) -> None:
        """Update a vertex's rhs value and its position in the priority queue."""
        if u_idx != self.s_goal_idx:
            self.rhs[u_idx] = self._calculate_rhs(u_idx)

        g_val = self.g[u_idx]
        rhs_val = self.rhs[u_idx]

        if g_val != rhs_val:
            self._push_vertex(u_idx, self._calculate_key(u_idx))
        else:
            self.in_queue[u_idx] = None

    def _compute_shortest_path(self) -> None:
        """Compute or update the shortest path (canonical D* Lite inner loop)."""
        max_iterations = self.size * 4
        
        g = self.g
        rhs = self.rhs
        in_queue = self.in_queue
        U = self.U
        width = self.width
        s_start_idx = self.s_start_idx

        for _ in range(max_iterations):
            if not U:
                break

            # Inlined _calculate_key(self.s_start_idx)
            g_start = g[s_start_idx]
            rhs_start = rhs[s_start_idx]
            min_start = min(g_start, rhs_start)
            # h is 0 for start to start
            start_key = (min_start + self.km, min_start)

            top_key, _ = U[0]
            if top_key >= start_key and rhs_start == g_start:
                break

            k_old, u_idx = heapq.heappop(U)

            # Inlined _calculate_key(u_idx)
            g_u = g[u_idx]
            rhs_u = rhs[u_idx]
            min_u = min(g_u, rhs_u)
            h_u = float(max(abs((u_idx % width) - (s_start_idx % width)), 
                            abs((u_idx // width) - (s_start_idx // width))))
            k_new = (min_u + h_u + self.km, min_u)

            if k_old < k_new:
                if g[u_idx] != rhs[u_idx]:
                    self._push_vertex(u_idx, k_new)
                continue

            in_queue[u_idx] = None
            g_val = g[u_idx]
            rhs_val = rhs[u_idx]

            if g_val == rhs_val:
                continue

            if g_val > rhs_val:
                g[u_idx] = rhs_val
                for s_idx in self.neighbors[u_idx]:
                    self._update_vertex(s_idx)
            else:
                g[u_idx] = float(TILE_BLOCK)
                self._update_vertex(u_idx)
                for s_idx in self.neighbors[u_idx]:
                    self._update_vertex(s_idx)

    def initialize(self, start: Position, goal: Position) -> None:
        """Initialize D* Lite for a new goal."""
        time_init_start = time.perf_counter_ns()

        self.s_start_idx = start.y * self.width + start.x
        self.s_goal_idx = goal.y * self.width + goal.x
        self.s_last_idx = self.s_start_idx
        self.km = 0.0

        for i in range(self.size):
            self.g[i] = float(TILE_BLOCK)
            self.rhs[i] = float(TILE_BLOCK)
            self.in_queue[i] = None
        self.U.clear()
        self.changed_cells.clear()

        self.rhs[self.s_goal_idx] = 0.0
        self._push_vertex(self.s_goal_idx, self._calculate_key(self.s_goal_idx))

        self._compute_shortest_path()

        time_init_end = time.perf_counter_ns()

        print(f'd star lite initialize() took: {(time_init_end - time_init_start) / 1_000_000:.4f} ms')

    def update_start(self, new_start: Position) -> None:
        """Update when the agent has moved to a new position."""
        start = time.perf_counter_ns()
        new_start_idx = new_start.y * self.width + new_start.x
        if self.s_start_idx == -1 or self.s_goal_idx == -1:
            end = time.perf_counter_ns()
            print(f'd star lite update_start() took: {(end - start) / 1_000_000:.4f} ms')
            return

        # Inlined heuristic
        x1, y1 = self.s_last_idx % self.width, self.s_last_idx // self.width
        x2, y2 = new_start_idx % self.width, new_start_idx // self.width
        self.km += float(max(abs(x1 - x2), abs(y1 - y2)))
        
        self.s_last_idx = new_start_idx
        self.s_start_idx = new_start_idx
        end = time.perf_counter_ns()
        print(f'd star lite update_start() took: {(end - start) / 1_000_000:.4f} ms')

    def update_cell(self, pos: Position) -> None:
        """Mark a cell as changed (obstacle detected/removed)."""
        idx = pos.y * self.width + pos.x
        self.changed_cells.add(idx)

    def replan(self) -> None:
        start = time.perf_counter_ns()
        if self.s_start_idx == -1 or self.s_goal_idx == -1:
            end = time.perf_counter_ns()
            print(f'd star lite replan() took: {(end - start) / 1_000_000:.4f} ms')
            return

        if self.changed_cells:
            affected: set[int] = set()
            for u_idx in self.changed_cells:
                affected.add(u_idx)
                for s_idx in self.neighbors[u_idx]:
                    affected.add(s_idx)
            self.changed_cells.clear()

            for u_idx in affected:
                self._update_vertex(u_idx)

        self._compute_shortest_path()
        end = time.perf_counter_ns()
        print(f'd star lite replan() took: {(end - start) / 1_000_000:.4f} ms')

    def get_next_direction(self) -> Direction:
        """Return the next direction the robot should move toward the goal."""
        start = time.perf_counter_ns()
        if self.s_start_idx == -1 or self.s_goal_idx == -1:
            end = time.perf_counter_ns()
            print(f'd star lite get_next_direction() took: {(end - start) / 1_000_000:.4f} ms')
            return Direction.CENTRE

        if self.s_start_idx == self.s_goal_idx:
            end = time.perf_counter_ns()
            print(f'd star lite get_next_direction() took: {(end - start) / 1_000_000:.4f} ms')
            return Direction.CENTRE

        if self.rhs[self.s_start_idx] >= TILE_BLOCK:
            end = time.perf_counter_ns()
            print(f'd star lite get_next_direction() took: {(end - start) / 1_000_000:.4f} ms')
            return Direction.CENTRE

        best_cost = float(TILE_BLOCK)
        best_dir = Direction.CENTRE

        # Still need current Position to get coordinates for Direction calculation
        # but we can do it more efficiently
        curr_x, curr_y = self.s_start_idx % self.width, self.s_start_idx // self.width
        
        map_walk = self.agent.map_walk
        g = self.g
        rhs = self.rhs
        
        for neighbor_idx in self.neighbors[self.s_start_idx]:
            cost = map_walk[neighbor_idx]
            if cost < TILE_BLOCK:
                neighbor_cost = min(g[neighbor_idx], rhs[neighbor_idx])
                total = float(cost) + neighbor_cost
                if total < best_cost:
                    best_cost = total
                    
                    # Calculate direction from indices
                    nx, ny = neighbor_idx % self.width, neighbor_idx // self.width
                    dx, dy = nx - curr_x, ny - curr_y
                    
                    # Map dx, dy back to Direction
                    if dx == 0 and dy == -1: best_dir = Direction.NORTH
                    elif dx == 0 and dy == 1: best_dir = Direction.SOUTH
                    elif dx == 1 and dy == 0: best_dir = Direction.EAST
                    elif dx == -1 and dy == 0: best_dir = Direction.WEST
                    elif dx == 1 and dy == -1: best_dir = Direction.NORTHEAST
                    elif dx == -1 and dy == -1: best_dir = Direction.NORTHWEST
                    elif dx == 1 and dy == 1: best_dir = Direction.SOUTHEAST
                    elif dx == -1 and dy == 1: best_dir = Direction.SOUTHWEST

        end = time.perf_counter_ns()
        print(f'd star lite get_next_direction() took: {(end - start) / 1_000_000:.4f} ms')
        return best_dir

    def has_path(self) -> bool:
        """Check if a valid path exists to the goal."""
        start = time.perf_counter_ns()
        if self.s_start_idx == -1:
            end = time.perf_counter_ns()
            print(f'd star lite has_path() took: {(end - start) / 1_000_000:.4f} ms')
            return False
        ret = self.rhs[self.s_start_idx] < TILE_BLOCK
        end = time.perf_counter_ns()
        print(f'd star lite has_path() took: {(end - start) / 1_000_000:.4f} ms')
        return ret


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

        start = time.perf_counter_ns()

        self.update_on_view()

        end = time.perf_counter_ns()

        print(f'update_on_view() took: {(end - start) / 1_000_000:.4f} ns')

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
