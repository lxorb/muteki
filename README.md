# 無敵

無敵の笑顔で荒らすメディア... 

## Lib manual
To implement a new bot, create a new implementation of the `Bot` class in a new descriptive file in `./src/bots/`.

The `./src/bots/__init__.py` file should not be changed, because it contains the base implementation provided by cambc.
You can copy the code from `./src/bots/__init__.py` into your file for a 
quick start (or just duplicate the entire file and rename it).

To run your new bot, you only need to fix the import in `./src/main.py` to point to your new file.

**Example**: You added a new bot in `./src/bots/my_bot.py` (the class name should remain `Bot`), 
then you would need to change the import in `./src/main.py` to `from src.bots.my_bot import Bot`.

Everyone can create a `./src/bots/test_bot.py` file for experimenting purposes, 
because **it's contained** in the `.gitignore` you don't need to worry about commiting bad code.

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