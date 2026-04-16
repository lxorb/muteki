from cambc import Controller, EntityType

from lib.agent import Agent
from lib.agent.builder import BuilderAgent
from lib.agent.core import CoreAgent
from lib.agent.turret import TurretAgent

from lib.debug import Stopwatch

core_agent = CoreAgent()
builder_agent = BuilderAgent()
turret_agent = TurretAgent()
sw = Stopwatch("main-stopwatch")

initial_run = False


class Player:
    def __init__(self):
        self.agent: Agent | None = None

    def run(self, ct: Controller) -> None:
        entity_type: EntityType = ct.get_entity_type()

        if self.agent is None:
            sw.start()
            match entity_type:
                case EntityType.CORE:
                    self.agent = core_agent
                case EntityType.BUILDER_BOT:
                    self.agent = builder_agent
                case (
                    EntityType.GUNNER
                    | EntityType.SENTINEL
                    | EntityType.BREACH
                    | EntityType.LAUNCHER
                ):
                    self.agent = turret_agent
                case _:
                    self.agent = Agent()
            sw.lap("Initialize agent")
            sw.log()

        sw.start()
        self.agent.u_run(ct)
        sw.lap("whole run time")
        sw.log()
