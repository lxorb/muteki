import json
import re
import subprocess
import time
from collections import deque
from itertools import cycle
from pathlib import Path

import datetime

TEAM_NAME = "muteki"

SCRIPT_DIR = Path(__file__).parent
TEAMS_FILE = SCRIPT_DIR / "teams.json"
QUEUED_FILE = SCRIPT_DIR / "queued.json"
RESULTS_DIR = SCRIPT_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)
RESULTS_FILE = RESULTS_DIR / "results_{}.json".format(
    datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
)

REQUEST_DELAY = 30


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def queue_match(team_id: str) -> str | None:
    result = subprocess.run(
        ["cambc", "match", "unrated", team_id], capture_output=True, text=True
    )
    m = re.search(r"Match ID: ([0-9a-f-]+)", result.stdout)
    if m:
        return m.group(1)
    print(f"  Could not queue: {result.stdout.strip()}")
    return None


def check_match(match_id: str) -> list[dict] | None:
    result = subprocess.run(
        ["cambc", "match", "info", match_id], capture_output=True, text=True
    )
    output = result.stdout
    # print(repr(output))  # DEBUG: see raw captured output
    if "Status:  complete" not in output:
        return None

    games = []
    for line in output.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) != 5 or not cells[0].isdigit():
            continue
        games.append(
            {
                "map": cells[1],
                "win": TEAM_NAME in cells[2],
                "condition": cells[3],
                "turns": int(cells[4]),
            }
        )
    return games


def record_games(results: dict, team_id: str, match_id: str, games: list[dict]) -> None:
    team = results.setdefault(team_id, {})
    for game in games:
        map_entry = team.setdefault(game["map"], {"wins": 0, "losses": 0})
        if game["win"]:
            map_entry["wins"] += 1
        else:
            map_entry["losses"] += 1
        map_entry[match_id] = {
            "win": game["win"],
            "condition": game["condition"],
            "turns": game["turns"],
        }


def main():
    teams = load_json(TEAMS_FILE)
    results = load_json(RESULTS_FILE)
    team_cycle = cycle(teams.keys())

    # Restore queued matches from previous run
    queued_data = load_json(QUEUED_FILE)
    match_queue: deque[tuple[str, str]] = deque(
        (mid, tid) for mid, tid in queued_data.get("queued", [])
    )
    save_json(QUEUED_FILE, {"queued": []})

    print(
        f"Unrated runner started. {len(match_queue)} queued from previous run. Ctrl+C to stop."
    )

    try:
        while True:
            # Check pending matches
            remaining: deque[tuple[str, str]] = deque()
            for match_id, team_id in match_queue:
                print(f"  Checking {match_id}...")
                games = check_match(match_id)
                if games is not None:
                    print(f"  Match {match_id} complete ({len(games)} games)")
                    record_games(results, team_id, match_id, games)
                    save_json(RESULTS_FILE, results)
                else:
                    remaining.append((match_id, team_id))
            match_queue = remaining

            # Queue new match
            team_id = next(team_cycle)
            print(f"Queuing vs {teams[team_id]} ({team_id})...")
            match_id = queue_match(team_id)
            if match_id:
                print(f"  Queued: {match_id}")
                match_queue.append((match_id, team_id))

            time.sleep(REQUEST_DELAY)
    except KeyboardInterrupt:
        if match_queue:
            save_json(QUEUED_FILE, {"queued": list(match_queue)})
            print(f"\nSaved {len(match_queue)} pending matches to queued.json.")
        print("Stopped.")


if __name__ == "__main__":
    main()
