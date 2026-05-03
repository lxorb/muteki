# Pong Bot

This bot is intentionally small and config-driven for the `pong` map.

Coordinates in `plan.json` and `strategies/*.json` are written for the right
side of the map. If the bot starts on the left side, positions and horizontal
directions are mirrored automatically.

## Core Spawns

Edit `SPAWN_SCHEDULE` in `core_agent.py`. The `turn` values use
`Controller.get_current_round()`; locally, the first round is `0`. The first
entry uses strategy `strategies/1.json`, the second uses `strategies/2.json`,
and so on.

## Strategy Actions

Each strategy file can contain `turns` keyed by turns relative to the builder's
first active round, and `absolute_turns` keyed by game round.

```json
{
  "turns": {
    "0": [
      { "action": "build", "at": [41, 9], "building": "road" },
      { "action": "move_to", "to": [41, 9] }
    ],
    "1": [
      { "action": "build", "at": [41, 10] }
    ]
  }
}
```

Supported actions:

- `destroy`: `{ "action": "destroy", "at": [x, y] }`
- `build`: `{ "action": "build", "at": [x, y], "building": ... }`
- `move_to`: `{ "action": "move_to", "to": [x, y] }`

If a build action omits `building`, the bot looks up the tile in `plan.json`.

Building specs can be strings for non-directional buildings:

```json
"road"
```

or objects:

```json
{ "type": "conveyor", "direction": "south" }
{ "type": "bridge", "target": [41, 12] }
```
