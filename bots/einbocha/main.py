import time
from abc import ABC, abstractmethod
from typing import NamedTuple
import array
import heapq
from collections import deque

from cambc import (
    Controller,
    EntityType,
    Team,
    Direction,
    Position,
    Environment,
)


def idx_to_pos(idx: int, width: int) -> Position:
    return Position(idx % width, idx // width)


def pos_to_idx(pos: Position, width: int) -> int:
    return pos.y * width + pos.x


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


# Todo: remove Resources inefficient too many object creations
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
        self.width: int = self.ct.get_map_width()
        self.height: int = self.ct.get_map_height()
        self.size: int = self.width * self.height
        _pos = self.ct.get_position()
        self.position: int = pos_to_idx(_pos, self.width)
        _core = self.ct.get_nearby_buildings(1)
        _core = self.ct.get_position(_core[0])
        self.core_pos: int = pos_to_idx(_core, self.width)
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


TILE_WALK: float = 10
TILE_EMPTY: float = 11
TILE_UNKNOWN: float = 12
TILE_BLOCK: float = 10_000_000

# Direction lookup dictionary for (dx, dy) -> Direction
_DIRECTION_MAP: dict[tuple[int, int], Direction] = {
    (0, -1): Direction.NORTH,
    (0, 1): Direction.SOUTH,
    (1, 0): Direction.EAST,
    (-1, 0): Direction.WEST,
    (1, -1): Direction.NORTHEAST,
    (-1, -1): Direction.NORTHWEST,
    (1, 1): Direction.SOUTHEAST,
    (-1, 1): Direction.SOUTHWEST,
}


class DStarLite:
    """D* Lite algorithm for incremental path planning with dynamic obstacles."""
    agent: 'BuilderAgent'
    width: int
    height: int
    size: int
    neighbors: list[list[int]]
    g: list[float]  # or list[int] if TILE_BLOCK is int
    rhs: list[float]
    U: list[tuple[float, float, int]]
    km: float
    s_start_idx: int
    s_goal_idx: int
    s_last_idx: int
    in_queue: list[tuple[float, float] | None]
    changed_cells: set[int]

    def __init__(self, agent: 'BuilderAgent'):
        time_init_start = time.perf_counter_ns()

        self.agent = agent
        self.width = agent.width
        self.height = agent.height
        self.size = agent.size

        self.neighbors = [[] for _ in range(self.size)]
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

        self.reset()

        time_init_end = time.perf_counter_ns()

        print(f'd star lite __init__() took: {(time_init_end - time_init_start) / 1_000_000:.4f} ms')

    def reset(self) -> None:
        # D* Lite state using lists for performance
        self.g = [TILE_BLOCK] * self.size
        self.rhs = [TILE_BLOCK] * self.size
        self.U = []  # Flattened: (k1, k2, idx)
        self.km = 0.0

        self.s_start_idx = -1
        self.s_goal_idx = -1
        self.s_last_idx = -1

        # in_queue tracks the key (k1, k2) for each idx (lazy deletion)
        self.in_queue = [None] * self.size

        # Track which cells have changed since last replan
        self.changed_cells = set()

    def target_position(self) -> int:
        return self.s_goal_idx

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
        
        return min_val + h + self.km, min_val

    def _calculate_rhs(self, u_idx: int) -> float:
        """Calculate one-step lookahead value for vertex u."""
        if u_idx == self.s_goal_idx:
            return 0.0
        
        min_rhs = TILE_BLOCK
        map_walk = self.agent.map_walk
        g = self.g
        for s_prime_idx in self.neighbors[u_idx]:
            cost = map_walk[s_prime_idx]
            if cost < TILE_BLOCK:
                candidate = cost + g[s_prime_idx]
                if candidate < min_rhs:
                    min_rhs = candidate
        return min_rhs

    def _push_vertex(self, u_idx: int, key: tuple[float, float]) -> None:
        """Push u into the heap with the given key and record it in in_queue."""
        if self.in_queue[u_idx] == key:
            return
        self.in_queue[u_idx] = key
        heapq.heappush(self.U, (key[0], key[1], u_idx))

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
        
        # Cache hot attributes as locals
        g = self.g
        rhs = self.rhs
        in_queue = self.in_queue
        U = self.U
        width = self.width
        s_start_idx = self.s_start_idx
        km = self.km
        neighbors = self.neighbors

        for _ in range(max_iterations):
            if not U:
                break

            # Inlined _calculate_key(self.s_start_idx)
            g_start = g[s_start_idx]
            rhs_start = rhs[s_start_idx]
            min_start = min(g_start, rhs_start)
            # h is 0 for start to start
            start_key = (min_start + km, min_start)

            # Peek at flattened heap entry
            top_k1, top_k2, _ = U[0]
            top_key = (top_k1, top_k2)
            if top_key >= start_key and rhs_start == g_start:
                break

            # Pop flattened entry
            k1_old, k2_old, u_idx = heapq.heappop(U)
            k_old = (k1_old, k2_old)

            # Inlined _calculate_key(u_idx)
            g_u = g[u_idx]
            rhs_u = rhs[u_idx]
            min_u = min(g_u, rhs_u)
            h_u = float(max(abs((u_idx % width) - (s_start_idx % width)), 
                            abs((u_idx // width) - (s_start_idx // width))))
            k_new = (min_u + h_u + km, min_u)

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
                for s_idx in neighbors[u_idx]:
                    self._update_vertex(s_idx)
            else:
                g[u_idx] = TILE_BLOCK
                self._update_vertex(u_idx)
                for s_idx in neighbors[u_idx]:
                    self._update_vertex(s_idx)

    def initialize(self, start_idx: int, goal_idx: int) -> None:
        """Initialize D* Lite for a new goal."""
        time_init_start = time.perf_counter_ns()

        self.s_start_idx = start_idx
        self.s_goal_idx = goal_idx
        self.s_last_idx = self.s_start_idx
        self.km = 0.0

        # Fast full reset using list multiplication
        self.g = [TILE_BLOCK] * self.size
        self.rhs = [TILE_BLOCK] * self.size
        self.in_queue = [None] * self.size
        self.U.clear()
        self.changed_cells.clear()

        self.rhs[self.s_goal_idx] = 0.0
        self._push_vertex(self.s_goal_idx, self._calculate_key(self.s_goal_idx))

        self._compute_shortest_path()

        time_init_end = time.perf_counter_ns()

        print(f'd star lite initialize() took: {(time_init_end - time_init_start) / 1_000_000:.4f} ms')

    def update_start(self, new_start_idx: int) -> None:
        """Update when the agent has moved to a new position."""
        start = time.perf_counter_ns()
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

    def update_cell(self, idx: int) -> None:
        """Mark a cell as changed (obstacle detected/removed)."""
        self.changed_cells.add(idx)

    def replan(self) -> None:
        start = time.perf_counter_ns()
        if self.s_start_idx == -1 or self.s_goal_idx == -1:
            end = time.perf_counter_ns()
            print(f'd star lite replan() took: {(end - start) / 1_000_000:.4f} ms')
            return

        if self.agent.map_walk[self.s_goal_idx] >= TILE_BLOCK:
            self.changed_cells.clear()
            end = time.perf_counter_ns()
            print(f'd star lite replan() took: {(end - start) / 1_000_000:.4f} ms')
            return

        if self.changed_cells:
            # Improved affected-cell expansion
            affected = set(self.changed_cells)
            neighbors = self.neighbors
            for u_idx in self.changed_cells:
                affected.update(neighbors[u_idx])
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

        if self.rhs[self.s_start_idx] >= TILE_BLOCK or self.agent.map_walk[self.s_goal_idx] >= TILE_BLOCK:
            end = time.perf_counter_ns()
            print(f'd star lite get_next_direction() took: {(end - start) / 1_000_000:.4f} ms')
            return Direction.CENTRE

        best_cost = TILE_BLOCK
        best_dir = Direction.CENTRE

        # Still need current Position to get coordinates for Direction calculation
        # but we can do it more efficiently
        curr_x, curr_y = self.s_start_idx % self.width, self.s_start_idx // self.width
        
        map_walk = self.agent.map_walk
        g = self.g
        rhs = self.rhs
        width = self.width
        
        for neighbor_idx in self.neighbors[self.s_start_idx]:
            cost = map_walk[neighbor_idx]
            if cost < TILE_BLOCK:
                neighbor_cost = min(g[neighbor_idx], rhs[neighbor_idx])
                total = cost + neighbor_cost
                if total < best_cost:
                    best_cost = total
                    
                    # Calculate direction from indices
                    nx, ny = neighbor_idx % width, neighbor_idx // width
                    dx, dy = nx - curr_x, ny - curr_y
                    
                    # Use dictionary lookup for direction
                    best_dir = _DIRECTION_MAP.get((dx, dy), Direction.CENTRE)

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


class Action(ABC):
    agent: 'BuilderAgent'

    def set_builder_agent(self, agent: 'BuilderAgent'):
        self.agent = agent

    @abstractmethod
    def do(self) -> bool:
        pass


class Explore(Action):
    def do(self) -> bool:
        agent = self.agent
        target = agent.dstar.target_position() # -1 if uninitialized

        print(f'ti_pending: {[idx_to_pos(ti, agent.width) for ti in agent.ti_pending]}')
        print(f'ti_finished: {[idx_to_pos(ti, agent.width) for ti in agent.ti_finished]}')

        if target == -1 and agent.ti_pending:
            target = next(iter(agent.ti_pending))

        elif agent.position == target:
            agent.ti_pending.remove(target)
            agent.ti_finished.add(target)
            agent.dstar.reset()
            return True

        agent.move(target)
        print(f'explore: {idx_to_pos(agent.position, agent.width)} -> {idx_to_pos(target, agent.width)}')
        return False


class Important(Action):
    def do(self) -> bool:
        return True


DIST_INF = 10_000_000

ORE_NOTHING = 0
ORE_TI = 1
ORE_AX = 2

BB_NORMAL = 0

HIERARCHIES: dict[int, tuple] = {
    BB_NORMAL: (Important(), Explore()),
}

class BuilderAgent(DefaultAgent):
    def __init__(self, ct: Controller):
        super().__init__(ct)
        self.bb_type: int = BB_NORMAL # Todo: here should go spawn-position-based type derivation
        self.todo_hierarchy: tuple = HIERARCHIES[self.bb_type]
        for action in self.todo_hierarchy:
            action.set_builder_agent(self)
        self.todo_list: deque = deque([self.todo_hierarchy[-1]], maxlen=len(self.todo_hierarchy))

        self.map_walk = array.array('d', [TILE_UNKNOWN] * self.size)
        self.map_dist = array.array('i', [DIST_INF] * self.size) # Todo: distance map
        self.map_ore = array.array('i', [ORE_NOTHING] * self.size)

        self.ti_finished: set[int] = set()
        self.ti_pending: set[int] = set()
        self.ax_finished: set[int] = set()
        self.ax_pending: set[int] = set()

        self.dstar: DStarLite = DStarLite(self)

    def make_turn(self):
        _pos = self.ct.get_position()
        self.position = pos_to_idx(_pos, self.width)

        start = time.perf_counter_ns()

        self.update_on_view()

        end = time.perf_counter_ns()

        print(f'update_on_view() took: {(end - start) / 1_000_000:.4f} ms')

        self.todo_handler()

        # Todo: try to use your leftover actions in a meaningful way

        # Todo: place marker with information

        # Todo: do any precomputation until turn 2ms reached

    def todo_handler(self):
        todo = self.todo_list[0] if self.todo_list else None
        if todo is not None:
            idx = self.todo_hierarchy.index(todo)
            self.todo_list.extendleft(
                self.todo_hierarchy[idx-1::-1]
            )  # 2k, all C — optimal
        else:
            self.todo_list.extendleft(
                reversed(self.todo_hierarchy)
            )   # n, all C — optimal

        print(f'todo_list: {self.todo_list}')

        while self.todo_list:
            todo = self.todo_list[0]  # peek at front without removing
            skip = todo.do()
            print(f'{todo} skipped: {skip}')
            if skip:
                self.todo_list.popleft()  # now safe to remove
            else:
                break

    def move(self, target_pos_idx: int):

        if target_pos_idx != self.dstar.target_position():
            self.dstar.initialize(self.position, target_pos_idx)
        else:
            self.dstar.update_start(self.position)
            self.dstar.replan()

        direction = self.dstar.get_next_direction() # Todo: first try greedy best first search for in vision targets

        pos = idx_to_pos(self.position, self.width)
        next_pos = pos.add(direction)
        if self.ct.can_build_road(next_pos):
            self.ct.build_road(next_pos)
        if self.ct.can_move(direction):
            self.ct.move(direction)

    def update_on_view(self):
        ct = self.ct
        map_walk = self.map_walk
        map_ore = self.map_ore
        width = self.width
        dstar_update = self.dstar.update_cell
        ti_finished = self.ti_finished
        ti_pending = self.ti_pending
        ax_finished = self.ax_finished
        ax_pending = self.ax_pending

        for pos in ct.get_nearby_tiles():

            idx = pos.y * width + pos.x
            passable = ct.is_tile_passable(pos)
            bb = ct.get_tile_builder_bot_id(pos)
            empty = ct.is_tile_empty(pos)
            env = ct.get_tile_env(pos)
            building = ct.get_tile_building_id(pos)

            # movement related:
            if passable:
                walk = TILE_WALK
            elif bb is not None:
                walk = TILE_BLOCK
            elif empty:
                walk = TILE_EMPTY
            elif env is Environment.WALL:
                walk = TILE_BLOCK
            elif building is not None:
                walk = TILE_BLOCK
            else:
                walk = TILE_UNKNOWN

            if walk != map_walk[idx]:
                dstar_update(idx)
                map_walk[idx] = walk

            # environment related:
            if (
                    idx not in ti_finished and
                    idx not in ti_pending and
                    idx not in ax_finished and
                    idx not in ax_pending
            ):
                # Todo: add opponent and harvester connection check
                if env is Environment.ORE_TITANIUM:
                    map_ore[idx] = ORE_TI
                    ti_pending.add(idx)
                elif env is Environment.ORE_AXIONITE:
                    map_ore[idx] = ORE_AX
                    ax_pending.add(idx)


class CoreAgent(DefaultAgent):
    def __init__(self, ct: Controller):
        super().__init__(ct)
        self.spawn_bb_count: int = 0

    def make_turn(self) -> None:
        if self.spawn_bb_count < 3:
            self.spawn_bb()

    def spawn_bb(self) -> bool:
        pos = idx_to_pos(self.position, self.width)

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
