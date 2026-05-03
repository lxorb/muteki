# Replay Parser

Node.js tool to parse `.replay26` files into a JSON representation that is meant
to be reconstructable by an LLM: static map state, normalized entity state,
ordered turn events, and per-instance timelines.

## Setup

```powershell
cd tools/replay_parser
npm install
```

## Usage

From repository root:

```powershell
node tools/replay_parser/parse_replay.js replay.replay26
```

Write parsed output to a file:

```powershell
node tools/replay_parser/parse_replay.js replay.replay26 --out profiles/replay_summary.json
```

Write parsed output as multiple files:

```powershell
node tools/replay_parser/parse_replay.js replay.replay26 --out-dir profiles/replay_summary
```

This writes `index.json`, `map.json`, `initial_entities.json`,
`final_entities.json`, turn chunks under `turns/`, and per-instance action chunks
under `instances/`. Use this mode for large replays; it avoids building one huge
JSON string in Node and is easier to inspect incrementally.

Optional chunk sizes:

```powershell
node tools/replay_parser/parse_replay.js replay.replay26 --out-dir profiles/replay_summary --turn-chunk-size 25 --action-chunk-size 25
```

Optional explicit schema path (usually not needed):

```powershell
node tools/replay_parser/parse_replay.js replay.replay26 --schema "C:\path\to\site-packages\cambc\data\visualiser\assets\main-xxxx.js"
```

## Notes

- The parser auto-discovers the installed `cambc` visualizer schema (`main-*.js`) via Python.
- If auto-discovery fails, use `--schema` or environment variable `CAMBC_VISUALIZER_JS`.
- The output includes:
  - `map.rows`: static environment grid.
  - `initialEntities` / `finalEntities`: normalized entity snapshots for replay start/end.
  - `turnsDetailed`: one entry per replay turn with ordered normalized events.
  - `instances`: one entry per tracked bot/core/turret (`builderBot`, `core`,
    `gunner`, `sentinel`, `breach`, `launcher`), each with one action per turn.
- Every normalized entity snapshot includes `occupiedTiles`, so multi-tile cores are
  explicit in the JSON instead of being implicit in map logic.
- Each `instances[].actions[n]` describes the tracked instance on that turn:
  - `startState` / `endState`
  - `visibleTiles`: coordinates visible from the start-of-turn board state
  - `visibleEntities`: full normalized snapshots of entities occupying visible tiles
  - `stdoutLines`, `execTimeUs`, `tled`
  - `selfEventIndices`: indices into `turnsDetailed[n].events` for events related to
    that instance
- Each `turnsDetailed[n]` entry includes:
  - `playersStart` / `playersEnd`
  - `trackedInstanceIdsAliveStart` / `trackedInstanceIdsAliveEnd`
  - `entityCountsStart` / `entityCountsEnd`
  - `changedEntityIds`
  - `changedEntitiesStart` / `changedEntitiesEnd`
  - `events`: normalized replay updates in original turn order
- `map.rows` is intentionally kept separate from `visibleTiles` so static terrain is
  stored once instead of being duplicated for every turn.
- Large replays can produce very large JSON outputs. Prefer `--out-dir` for these.
  The directory may contain stale files if reused after a shorter replay; trust
  `index.json` as the manifest of the current parse.
