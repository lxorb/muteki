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
python tools/unrated_runner/compare.py
```

## Scripts

### fetch_ladder.py

Fetches the full ladder from `https://game.battlecode.cam/api/ladder` and saves it to `data/ladder.json`.

### process_ladder.py

Reads `data/ladder.json` and writes all active teams (matchesPlayed > 0) to `data/team_list.json` as `{"id": {"name", "category", "isStudent", "region"}}`.

### request_top.py

Reads `data/ladder.json` and writes the top `TOP_N` teams by rating to `config/request_teams.txt`, excluding our own team. Three optional restriction flags (`MAIN_ONLY`, `STUDENTS_ONLY`, `INTERNATIONAL_ONLY`) each further filter the pool when set to `True`; when `False`, that dimension is not restricted.

### main.py

Continuously queues unrated matches against configured opponents and records results. Runs in a loop every REQUEST_DELAY seconds until you press **Ctrl+C**. Our own team is automatically excluded from the opponent list.

If `config/discord_interval.txt` contains a positive integer, `main.py` also runs `output.py` and posts the generated JPG to the Discord webhook URL in `config/discord_webhook.txt` every N minutes. If either file is empty/missing or the interval is not a positive integer, this behaviour is disabled.

### output.py

Reads `results/results.json` (the cumulative results file) and generates a markdown summary at `outputs/output_<timestamp>.md` with a map-vs-team grid showing the last game result (✅/❌) for each combination, with cumulative win percentages next to each map and team. Only teams listed in `config/output_teams.txt` are included as columns. Also renders a JPG image of the grid where win/loss cell colors fade over time via exponential decay (configurable via `DECAY_LAMBDA` in the script).

### compare.py

Compares two result files and generates a map-vs-team grid showing the absolute win rate change (percentage points) for each combination. Outputs both a markdown file and a JPG image to `compares/`.

```
python tools/unrated_runner/compare.py                          # auto-compare last two partials
python tools/unrated_runner/compare.py old.json new.json        # compare two specific files
```

- **No arguments**: automatically picks the two most recent files in `results/partial/` and compares them (older → newer). Exits with an error if fewer than 2 partial files exist.
- **Two arguments**: compares the two specified files (first = old, second = new). Paths can be absolute or relative.

Cells show the change in win percentage points (e.g. `+20%`, `-15%`). `N/A` is shown when data doesn't exist in both files for a map/team combination. The JPG colors cells on a cyan (improvement) to white (no change) to pink (regression) scale. Only teams listed in `config/output_teams.txt` are included as columns.

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
| `RESULTS_FILE` | `""` | Filename under `results/` to use as input. When empty (default), uses `results.json`. Set to a partial result filename (e.g. `"results_2026-04-16.json"`) to generate output from a single session. |
| `RENDER_IMAGES` | `True` | Whether to generate the JPG grid image alongside the markdown report. |
| `HALF_LIFE_MINUTES` | `60` | Controls how fast win/loss cell colors fade toward white. After this many minutes, a cell's color is at 50% intensity. |
| `CUTOFF_HOURS` | `12` | Games finished more than this many hours ago are excluded from the report (win/loss counts are recomputed). Set to `0` or `None` to disable. |
| `MAP_WIN_COLORS` | see code | List of `(threshold, hex_color)` tuples that color map name cells by overall win rate. Evaluated top-down; first threshold the win % meets or exceeds is used. |

### compare.py

| Constant | Default | Description |
| --- | --- | --- |
| `RENDER_IMAGES` | `True` | Whether to generate the JPG grid image alongside the markdown report. |
| `MAX_DELTA` | `50` | Percentage points of change at which cell color reaches full intensity. |
| `CYAN` | `"#00B8D4"` | Base color for improvement (blended toward white for smaller deltas). |
| `PINK` | `"#E91E63"` | Base color for regression (blended toward white for smaller deltas). |

### request_top.py

| Constant | Default | Description |
| --- | --- | --- |
| `TEAM_NAME` | `"muteki"` | Our team name — excluded from the generated list. |
| `TOP_N` | `10` | Number of top-rated teams to write to `request_teams.txt`. |
| `MAIN_ONLY` | `False` | If `True`, only include teams in category `"main"`. |
| `STUDENTS_ONLY` | `False` | If `True`, only include teams where `isStudent` is `True`. |
| `INTERNATIONAL_ONLY` | `False` | If `True`, only include teams where `region` is `"international"`. |

## Configuration

### config/request_teams.txt

One team name per line. Only teams listed here (and present in `data/team_list.json`) will be queued for matches. Edit this file while `main.py` is running to add or remove opponents on the fly. Can be auto-populated by `request_top.py`.

```
MFF1
Blue Dragon
```

### config/output_teams.txt

One team name per line. Controls which teams appear as columns in `output.py` and `compare.py`. Teams not listed here are excluded from the output even if results exist for them. If the file is empty or missing, all teams are shown.

### config/discord_interval.txt

A single line containing a positive integer — the number of minutes between automatic `output.py` runs that post the generated JPG to the Discord webhook. If the file is empty or does not parse as a positive integer, the feature is disabled and `main.py` behaves normally. Re-read each loop iteration, so edits take effect live.

### config/discord_webhook.txt

The Discord webhook URL to post generated JPGs to. Gitignored (treat as a secret). Required when `config/discord_interval.txt` is set; if missing or empty, `main.py` skips the Discord post.

## Workflow

1. Run `fetch_ladder.py` to download the current ladder.
2. Run `process_ladder.py` to build the active team list.
3. Run `request_top.py` to auto-fill `config/request_teams.txt` with the top 16 teams, or edit the file manually.
4. Run `main.py`. Let it run as long as you want to collect data. It round-robins through all requested teams.
5. Press **Ctrl+C** to stop. Any pending (not yet completed) matches are saved to `data/queued.json` and will be picked up on the next run.
6. Run `output.py` to generate a summary report in `outputs/`.
7. Run `compare.py` to compare the last two sessions, or pass two file paths to compare specific results.

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
  compare.py           # result comparison tool
  docs.md              # this file
  config/
    request_teams.txt    # teams to queue against
    output_teams.txt     # teams to show in output/compare
    discord_interval.txt # positive int minutes → auto-run output.py + post JPG to Discord
    discord_webhook.txt  # Discord webhook URL (gitignored)
  data/
    ladder.json        # raw ladder data from platform API
    team_list.json     # all active teams {id: name}
    requested_teams.json # auto-generated from team_list + request_teams
    queued.json        # persisted pending matches between runs
  results/
    results.json       # cumulative results (used by output.py)
    partial/
      results_*.json   # per-session results (gitignored)
  outputs/
    output_*.md        # generated reports
    output_*.jpg       # generated result grid images
  compares/
    compare_*.md       # generated comparison reports
    compare_*.jpg      # generated comparison grid images
```
