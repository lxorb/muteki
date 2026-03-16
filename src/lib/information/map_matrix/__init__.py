from cambc import *


class MapMatrix:

    matrix: list = []




    def __init__(self, ct: Controller):

        width = ct.get_map_width()
        height = ct.get_map_height()

        list = [[(Field.BUILDABLE, Directions.NONE)] * width for h in range(height)]

