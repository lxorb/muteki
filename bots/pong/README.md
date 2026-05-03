# Pong Bot

This bot is intentionally small and config-driven for the `pong` map.

Coordinates in `plan.json` and `strategies/*.json` are written for the right
side of the map. If the bot starts on the left side, positions and horizontal
directions are mirrored automatically.

## Core Spawns

Edit `spawns.json` or use the editor sidebar. The `turn` values use
`Controller.get_current_round()`; locally, the first round is `0`. The first
entry uses strategy `strategies/1.json`, the second uses `strategies/2.json`,
and so on. Coordinates are written for the right-side core footprint and are
mirrored automatically on the left side.

A spawned builder cannot act on the spawn round. Strategy turn `1` is executed
on `spawn turn + 1`, the first round after the builder was spawned.

## Strategy Actions

Each strategy file can contain `turns` keyed by builder-relative turns after
spawn. Turn `1` is the first turn where the builder can act. `absolute_turns`
is keyed by game round.

```json
{
  "turns": {
    "1": [
      { "action": "build", "at": [41, 9], "building": "road" },
      { "action": "move_to", "to": [41, 9] }
    ],
    "2": [
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
If a build cannot yet be afforded, the builder pauses at that action and retries
it on following turns before continuing with later scripted actions.

Building specs can be strings for non-directional buildings:

```json
"road"
```

or objects:

```json
{ "type": "conveyor", "direction": "south" }
{ "type": "bridge", "target": [41, 12] }
```
