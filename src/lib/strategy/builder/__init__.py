from src.lib.strategy import DefaultStrategy
import random
from cambc import Direction

# non-centre directions
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]


class Strategy(DefaultStrategy):
    def __init__(self):
        pass

    def run(self, ct):
        # if we are adjacent to an ore tile, build a harvester on it
        for d in Direction:
            check_pos = ct.get_position().add(d)
            if ct.can_build_harvester(check_pos):
                ct.build_harvester(check_pos)
                break

        # move in a random direction
        move_dir = random.choice(DIRECTIONS)
        move_pos = ct.get_position().add(move_dir)
        # we need to place a conveyor or road to stand on, before we can move onto a tile
        if ct.can_build_road(move_pos):
            ct.build_road(move_pos)
        if ct.can_move(move_dir):
            ct.move(move_dir)

        # place a marker on an adjacent tile with the current round number
        marker_pos = ct.get_position().add(random.choice(DIRECTIONS))
        if ct.can_place_marker(marker_pos):
            ct.place_marker(marker_pos, ct.get_current_round())