# Unrated Runner

Automated unrated match runner and results analyzer for cambc.

## Required packages

matplotlib

## Quick Start

In VSCode, right-click a script and select **Run Python File in Terminal**, or run from a terminal:

```
python tools/unrated_runner/main.py
python tools/unrated_runner/output.py
```

## Scripts

### main.py

Continuously queues unrated matches against configured opponents and records results. Runs in a loop every REQUEST_DELAY seconds until you press **Ctrl+C**.

### output.py

Reads `results/results.json` (the cumulative results file) and generates a markdown summary at `outputs/output_<timestamp>.md` with a map-vs-team grid showing the last game result (✅/❌) for each combination, with cumulative win percentages next to each map and team.

## Configuration

Both config files live in `config/`.

### config/team_list.txt

Master list of all known teams. Format is repeating blocks of three lines: team name, team ID (UUID), then a blank line.

```
MFF1
05a96b0d-3ce5-4be8-921b-570dd973994a

Blue Dragon
023ce802-d72e-44f5-b99e-71a6f97db4b7

```

### config/request_teams.txt

One team name per line. Only teams listed here (and present in `team_list.txt`) will be queued for matches. Edit this file while `main.py` is running to add or remove opponents on the fly.

```
MFF1
Blue Dragon
```

## Workflow

1. Fill in `config/team_list.txt` with all teams you might want to play against.
2. Add the teams you want to run matches against right now to `config/request_teams.txt`.
3. Run `main.py`. Let it run as long as you want to collect data. It round-robins through all requested teams.
4. Press **Ctrl+C** to stop. Any pending (not yet completed) matches are saved to `data/queued.json` and will be picked up on the next run.
5. Run `output.py` to generate a summary report in `outputs/`.
6. Open the generated markdown file to review win rates and the map-vs-team result grid.

## How It Works

- Each loop iteration, `main.py` rebuilds the active team list from the config files, checks all pending matches for completion, and queues one new match.
- Completed match results are written to both `results/results_<timestamp>.json` (per-session) and `results/results.json` (cumulative). Per-session files are gitignored.
- The rate limit is 10 unrated matches per 10 minutes. The script handles failures gracefully if the limit is hit.
- `output.py` reads `results/results.json` to generate its report.

## Folder Structure

```
unrated_runner/
  main.py              # match runner
  output.py            # report generator
  docs.md              # this file
  config/
    team_list.txt      # all known teams
    request_teams.txt  # teams to queue against
  data/
    teams.json         # auto-generated active team list
    queued.json        # persisted pending matches between runs
  results/
    results.json       # cumulative results (used by output.py)
    results_*.json     # per-session results (gitignored)
  outputs/
    output_*.md        # generated reports
    output_*.jpg       # generated result grid images
```
