import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
LADDER_FILE = SCRIPT_DIR / "data" / "ladder.json"
TEAM_LIST_FILE = SCRIPT_DIR / "data" / "team_list.json"

def main():
    with open(LADDER_FILE) as f:
        ladder = json.load(f)

    active = {
        entry["teamId"]: {
            "name": entry["teamName"],
            "category": entry["category"],
            "isStudent": entry["isStudent"],
            "region": entry["region"],
        }
        for entry in ladder
        if entry["matchesPlayed"] > 0
    }

    TEAM_LIST_FILE.parent.mkdir(exist_ok=True)
    with open(TEAM_LIST_FILE, "w") as f:
        json.dump(active, f, indent=4)
    print(f"Wrote {len(active)} active teams to {TEAM_LIST_FILE}")

if __name__ == "__main__":
    main()
