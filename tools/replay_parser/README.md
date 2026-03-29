# Replay Parser

Small Node.js tool to parse `.replay26` files and output a JSON summary.

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

Write summary to a file:

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
