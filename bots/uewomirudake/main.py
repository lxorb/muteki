from cambc import Controller, EntityType

from lib.agents import Agent

class Player:
    def __init__(self):
        self.agent: Agent | None = None

    def run(self, ct: Controller) -> None:
        # TODO

        entity_type: EntityType = ct.get_entity_type()

        if self.agent is None:
            match entity_type:
                case _:
                    self.agent = Agent
        
        self.agent.run(ct)
