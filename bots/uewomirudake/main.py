from cambc import Controller, EntityType

from lib.agent import Agent
from lib.agent.core import CoreAgent
from lib.agent.turret import TurretAgent
from lib.agent.builder import BuilderAgent


class Player:
    def __init__(self):
        self.agent: Agent | None = None


    def run(self, ct: Controller) -> None:
        if self.agent is None:
            match ct.get_entity_type():
                case EntityType.CORE:
                    self.agent = CoreAgent(ct)
                case EntityType.BUILDER_BOT:
                    self.agent = BuilderAgent(ct)
                case EntityType.SENTINEL:
                    self.agent = TurretAgent(ct)
                case EntityType.GUNNER:
                    self.agent = TurretAgent(ct)
                case EntityType.BREACH:
                    self.agent = TurretAgent(ct)
                case _:
                    raise ValueError('Invalid EntityType')

        self.agent.run_()
