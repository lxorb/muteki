import importlib.util
from pathlib import Path


def load_bot_class():
    bot_path = Path(__file__).with_name("bots") / "grid.py"
    spec = importlib.util.spec_from_file_location("grid", bot_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load bot module from {bot_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Bot


Bot = load_bot_class()


class Player(Bot):
    pass
