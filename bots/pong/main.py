from cambc import Controller, EntityType

from builder_agent import BuilderAgent
from core_agent import CoreAgent


class Player:
    def __init__(self) -> None:
        self.core_agent = CoreAgent()
        self.builder_agents: dict[int, BuilderAgent] = {}

    def run(self, ct: Controller) -> None:
        entity_type = ct.get_entity_type()
        if entity_type == EntityType.CORE:
            self.core_agent.run(ct)
        elif entity_type == EntityType.BUILDER_BOT:
            entity_id = ct.get_id()
            builder_agent = self.builder_agents.get(entity_id)
            if builder_agent is None:
                builder_agent = BuilderAgent()
                self.builder_agents[entity_id] = builder_agent
            builder_agent.run(ct)
