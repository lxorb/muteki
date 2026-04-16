# Unrated Runner

Automated unrated match runner and results analyzer for cambc.

## Required packages

matplotlib

## Quick Start

In VSCode, right-click a script and select **Run Python File in Terminal**, or run from a terminal:

```
python tools/unrated_runner/fetch_ladder.py
python tools/unrated_runner/process_ladder.py
python tools/unrated_runner/request_top.py
python tools/unrated_runner/main.py
python tools/unrated_runner/output.py
```

## Scripts

### fetch_ladder.py

Fetches the full ladder from `https://game.battlecode.cam/api/ladder` and saves it to `data/ladder.json`.

### process_ladder.py

Reads `data/ladder.json` and writes all active teams (matchesPlayed > 0) to `data/team_list.json` in `{"id": "name"}` format.

### request_top.py

Reads `data/ladder.json` and writes the top 16 teams by rating to `config/request_teams.txt`, excluding our own team.

### main.py

Continuously queues unrated matches against configured opponents and records results. Runs in a loop every REQUEST_DELAY seconds until you press **Ctrl+C**. Our own team is automatically excluded from the opponent list.

### output.py

Reads `results/results.json` (the cumulative results file) and generates a markdown summary at `outputs/output_<timestamp>.md` with a map-vs-team grid showing the last game result (✅/❌) for each combination, with cumulative win percentages next to each map and team. Also renders a JPG image of the grid where win/loss cell colors fade over time via exponential decay (configurable via `DECAY_LAMBDA` in the script).

## Constants

### main.py

| Constant | Default | Description |
| --- | --- | --- |
| `TEAM_NAME` | `"muteki"` | Our team name — automatically excluded from opponents. |
| `REQUEST_DELAY` | `30` | Seconds between each loop iteration (queue check + new match request). |
| `RANDOM_MAP_SELECTION` | `True` | When `True`, picks a random map each match. When `False`, cycles through all maps in order. |

### output.py

| Constant | Default | Description |
| --- | --- | --- |
| `RENDER_IMAGES` | `True` | Whether to generate the JPG grid image alongside the markdown report. |
| `HALF_LIFE_MINUTES` | `60` | Controls how fast win/loss cell colors fade toward white. After this many minutes, a cell's color is at 50% intensity. |
| `MAP_WIN_COLORS` | see code | List of `(threshold, hex_color)` tuples that color map name cells by overall win rate. Evaluated top-down; first threshold the win % meets or exceeds is used. |

### request_top.py

| Constant | Default | Description |
| --- | --- | --- |
| `TEAM_NAME` | `"muteki"` | Our team name — excluded from the generated list. |
| `TOP_N` | `10` | Number of top-rated teams to write to `request_teams.txt`. |

## Configuration

### config/request_teams.txt

One team name per line. Only teams listed here (and present in `data/team_list.json`) will be queued for matches. Edit this file while `main.py` is running to add or remove opponents on the fly. Can be auto-populated by `request_top.py`.

```
MFF1
Blue Dragon
```

## Workflow

1. Run `fetch_ladder.py` to download the current ladder.
2. Run `process_ladder.py` to build the active team list.
3. Run `request_top.py` to auto-fill `config/request_teams.txt` with the top 16 teams, or edit the file manually.
4. Run `main.py`. Let it run as long as you want to collect data. It round-robins through all requested teams.
5. Press **Ctrl+C** to stop. Any pending (not yet completed) matches are saved to `data/queued.json` and will be picked up on the next run.
6. Run `output.py` to generate a summary report in `outputs/`.

## How It Works

- Each loop iteration, `main.py` rebuilds the requested team list from `data/team_list.json` and `config/request_teams.txt`, checks all pending matches for completion, and queues one new match.
- Completed match results are written to both `results/results_<timestamp>.json` (per-session) and `results/results.json` (cumulative). Per-session files are gitignored.
- The rate limit is 10 unrated matches per 10 minutes. The script handles failures gracefully if the limit is hit.
- `output.py` reads `results/results.json` to generate its report.

## Folder Structure

```
unrated_runner/
  fetch_ladder.py      # download ladder from platform API
  process_ladder.py    # ladder.json → team_list.json (active teams)
  request_top.py       # auto-fill request_teams.txt with top 16
  main.py              # match runner
  output.py            # report generator
  docs.md              # this file
  config/
    request_teams.txt  # teams to queue against
  data/
    ladder.json        # raw ladder data from platform API
    team_list.json     # all active teams {id: name}
    requested_teams.json # auto-generated from team_list + request_teams
    queued.json        # persisted pending matches between runs
  results/
    results.json       # cumulative results (used by output.py)
    results_*.json     # per-session results (gitignored)
  outputs/
    output_*.md        # generated reports
    output_*.jpg       # generated result grid images
```
