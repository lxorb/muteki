from enum import IntFlag
from enum import Enum

class SupplyChainLabel(IntFlag):
    NONE = 0
    TITANIUM = 1
    AXIONITE = 2

class SymmetryMode(Enum):
    ROTATION = "rotation"
    MIRROR_X = "mirror_x"
    MIRROR_Y = "mirror_y"