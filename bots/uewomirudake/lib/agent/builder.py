from lib.agent import Agent
from lib.agent.constants import BBType, CORE_TILE_BB_TYPE

from cambc import Controller


class BuilderAgent(Agent):
    def __init__(self, ct: Controller):
        super().__init__(ct)
        self.type: BBType = CORE_TILE_BB_TYPE(self.map.core_pos().direction_to(self.position))

    def predate(self):
        self.position = self.ct.get_position()

    def run(self):
        pass

    def postdate(self):
        pass