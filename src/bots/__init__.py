from cambc import Controller, EntityType

from src.lib.strategy import DefaultStrategy

from src.lib.strategy.builder import Strategy as BuilderStrategy
from src.lib.strategy.core import Strategy as CoreStrategy


class Bot:
    def __init__(self):
        self.strategy = None

    def run(self, ct: Controller) -> None:
        e_type = ct.get_entity_type()

        if self.strategy is None:
            match e_type:
                case EntityType.CORE:
                    self.strategy = CoreStrategy()
                case EntityType.BUILDER_BOT:
                    self.strategy = BuilderStrategy()
                case _:
                    self.strategy = DefaultStrategy()

        self.strategy.run(ct)
