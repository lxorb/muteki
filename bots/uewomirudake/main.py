from cambc import Controller, EntityType

from lib.agent import Agent
from lib.agent.builder import BuilderAgent, INITRES_STRATEGY
from lib.agent.core import CoreAgent
from lib.agent.turret import TurretAgent


class Player:
    def __init__(self):
        self.agent: Agent | None = None

    def run(self, ct: Controller) -> None:
        entity_type: EntityType = ct.get_entity_type()

        if self.agent is None:
            match entity_type:
                case EntityType.CORE:
                    self.agent = CoreAgent()
                case EntityType.BUILDER_BOT:
                    self.agent = BuilderAgent(INITRES_STRATEGY)
                case (
                    EntityType.GUNNER
                    | EntityType.SENTINEL
                    | EntityType.BREACH
                    | EntityType.LAUNCHER
                ):
                    self.agent = TurretAgent()
                case _:
                    self.agent = Agent()

        self.agent.u_run(ct)
