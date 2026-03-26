from src.lib.strategy import DefaultStrategy
import random
from cambc import Direction

# non-centre directions
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


class Strategy(DefaultStrategy):
    def __init__(self):
        self.num_spawned = 0

    def run(self, ct):
        if self.num_spawned < 3:
            # if we haven't spawned 3 builder bots yet, try to spawn one on a random tile
            spawn_pos = ct.get_position().add(random.choice(DIRECTIONS))
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                self.num_spawned += 1