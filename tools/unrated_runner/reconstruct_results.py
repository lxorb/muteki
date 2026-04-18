import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR / "results"
RESULTS_PARTIAL_DIR = RESULTS_DIR / "partial"
RESULTS_ALL_FILE = RESULTS_DIR / "results.json"


def main() -> None:
    partials = sorted(RESULTS_PARTIAL_DIR.glob("results_*.json"))
    results: dict = {}
    seen: set[tuple[str, str, str]] = set()
    games = 0

    for path in partials:
        with open(path) as f:
            partial = json.load(f)
        for team_id, maps in partial.items():
            for map_name, map_data in maps.items():
                for key, value in map_data.items():
                    if key in ("wins", "losses"):
                        continue
                    match_key = (team_id, map_name, key)
                    if match_key in seen:
                        continue
                    seen.add(match_key)
                    team = results.setdefault(team_id, {})
                    entry = team.setdefault(map_name, {"wins": 0, "losses": 0})
                    entry[key] = value
                    if value["win"]:
                        entry["wins"] += 1
                    else:
                        entry["losses"] += 1
                    games += 1

    with open(RESULTS_ALL_FILE, "w") as f:
        json.dump(results, f, indent=4)
    print(
        f"Merged {len(partials)} partials into {RESULTS_ALL_FILE.name} "
        f"({len(results)} teams, {games} games)."
    )


if __name__ == "__main__":
    main()
