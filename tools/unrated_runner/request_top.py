import json
from pathlib import Path

TEAM_NAME = "muteki"
TOP_N = 10

SCRIPT_DIR = Path(__file__).parent
LADDER_FILE = SCRIPT_DIR / "data" / "ladder.json"
REQUEST_TEAMS_FILE = SCRIPT_DIR / "config" / "request_teams.txt"


def main():
    with open(LADDER_FILE) as f:
        ladder = json.load(f)

    top = [
        entry["teamName"]
        for entry in ladder[: TOP_N + 1]
        if entry["teamName"] != TEAM_NAME
    ][:TOP_N]

    REQUEST_TEAMS_FILE.write_text("\n".join(top) + "\n", encoding="utf-8")
    print(f"Wrote {len(top)} teams to {REQUEST_TEAMS_FILE}")


if __name__ == "__main__":
    main()
