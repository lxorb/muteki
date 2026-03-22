# 無敵

無敵の笑顔で荒らすメディア... 

## Bot layout
Bots now use the standard `cambc` layout:

```text
bots/
  base/
    main.py
lib/
  ...
```

Each bot directory contains its own `main.py` with a `Player` class, so you can run bots directly with:

```bash
cambc run base base
```

Shared helper code lives in the top-level `./lib/` package. Bot entrypoints add the project root to `sys.path` at
import time so they can use the shared helpers from a standard `bots/<name>/main.py` layout.

To implement a new bot, create a new directory in `./bots/` and add a `main.py` file that exposes a `Player` class.
For quick experiments, create a `./bots/test_bot/` directory; it is ignored by git.

## Setup

```bash
pip install cambc # install this globally
cambc run <bot1> <bot2> [--watch]
```

Install the black python formatter - automatic formatting on save is already configured, so try modifying something slightly and saving then to see if the automatic formatting kicks in. 

## Resources
- [docs](https://docs.battlecode.cam/getting-started/installation)
- [Reference Table](https://docs.battlecode.cam/spec/reference)
- [matches](https://game.battlecode.cam/matches)
