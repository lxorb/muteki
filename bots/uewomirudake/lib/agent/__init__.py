from cambc import Controller

class Agent:
    def __init__(self) -> None:
        pass
    
    def name(self) -> None:
        return self.__class__.__name__

    def run(self, ct: Controller) -> None:
        pass