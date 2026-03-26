import random
from cambc import Controller, EntityType
from src.lib.information import Information

from src.lib.strategy import DefaultStrategy

from src.lib.strategy.builder import Strategy as BuilderStrategy
from src.lib.strategy.core import Strategy as CoreStrategy


class Bot:
    def __init__(self):
        self.strategy: DefaultStrategy | None = None

        self.information: Information | None = None

    def run(self, ct: Controller) -> None:

        if self.information is None:
            self.information = Information(ct)
            # initializing beforehand without ct doesn't work / make sense:
            # we need width and height for matrix!

        self.information.update_all()

        print(self.information.map_matrix)
        print(self.information.id_map)


        if self.strategy is None:
            match ct.get_entity_type():
                case EntityType.CORE:
                    self.strategy = CoreStrategy()
                case EntityType.BUILDER_BOT:
                    self.strategy = BuilderStrategy()
                case _:
                    self.strategy = DefaultStrategy()

        self.strategy.run(ct)
