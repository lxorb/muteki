from collections import deque
from src.lib.information.map_matrix.direction import DirectionInfo
from src.lib.information.map_matrix.field import Field


def get_neighbor_cost(current, direction, shiftx, shifty, map_matrix, end_position):

    newx = current[0] + shiftx
    newy = current[1] + shifty

    if newx < 0 or newx >= len(map_matrix):
        return -1
    if newy < 0 or newy >= len(map_matrix[0]):
        return -1

    new_field = map_matrix[newx][newy][0]

    # in bounds

    if (not (new_field == Field.CONVEYOR or new_field == Field.BUILDABLE)) and not (
        newx,
        newy,
    ) == end_position:
        return -1
        # only makes sense to consider if ores can move from here
        # -> else: harvester would be considered as path element
        # only find paths to things you can go through OR to end !

    current_direction = map_matrix[current[0]][current[1]][1]
    current_field = map_matrix[current[0]][current[1]][0]
    if (
        direction == current_direction or current_direction == DirectionInfo.ALL
    ) and current_field == Field.CONVEYOR:
        return 0

    elif current_field == Field.BUILDABLE:
        return 1

    return -1


def find_shortest_path(map_matrix, start_position, end_position):

    # dijkstra but more efficient since we only have 2 edge weights:
    # if weight 0: pushed to front
    # if weight 1: pushed to back

    dist = {start_position: 0}
    parent = {start_position: None}

    queue = deque([start_position])

    shift = [
        (DirectionInfo.EAST, 1, 0),
        (DirectionInfo.WEST, -1, 0),
        (DirectionInfo.NORTH, 0, -1),
        (DirectionInfo.SOUTH, 0, 1),
    ]

    while queue:
        current = queue.popleft()

        if current == end_position:
            path = []
            while current is not None:
                path.append(current)
                current = parent[current]

            path.reverse()
            return path

        for direction, shiftx, shifty in shift:
            cost = get_neighbor_cost(
                current, direction, shiftx, shifty, map_matrix, end_position
            )
            if cost == -1:
                continue

            neighbor = (current[0] + shiftx, current[1] + shifty)
            new_dist = dist[current] + cost
            if neighbor not in dist or new_dist < dist[neighbor]:
                dist[neighbor] = new_dist
                parent[neighbor] = current

                if cost == 0:
                    queue.appendleft(neighbor)
                else:
                    queue.append(neighbor)

    return None
