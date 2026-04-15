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
- Large replays can produce large JSON outputs. If disk space is tight, stream stdout
  into downstream tooling instead of writing a temporary file first.
