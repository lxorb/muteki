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

## Strategy Optimizer

`optimize.py` searches over builder spawn schedules, builder ownership regions,
target ordering phases, movement target scoring, cleanup mode, and builder
count. It does not edit `plan.json`; every candidate is passed through
`generate_strategies.py`, so impossible strategy JSONs are rejected before a
game is simulated.

Run a long optimization pass:

```powershell
python tools\pong_optimizer.py --seconds 36000 --workers 4 --commit-improvements
```

Useful shorter runs:

```powershell
python tools\pong_optimizer.py --max-trials 20 --workers 2
python tools\pong_optimizer.py --max-trials 0 --no-validate-improvements
```

The optimizer evaluates only TEAM_B axionite. It creates temporary worker bots
named `pong_opt_worker_*` and writes ignored run logs under
`tools/pong_optimizer_runs/`. On each improvement it writes the winning
`strategy_config.json`, regenerates `spawns.json` and `strategies/*.json`, and
commits when `--commit-improvements` is set.
