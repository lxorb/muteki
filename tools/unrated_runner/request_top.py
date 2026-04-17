import json
from pathlib import Path

TEAM_NAME = "muteki"
TOP_N = 10

# Restriction flags. Set to True to restrict the selection; False to not restrict.
MAIN_ONLY = True  # only include teams in category "main"
STUDENTS_ONLY = True  # only include teams where isStudent is True
INTERNATIONAL_ONLY = True  # only include teams where region == "international"

SCRIPT_DIR = Path(__file__).parent
LADDER_FILE = SCRIPT_DIR / "data" / "ladder.json"
REQUEST_TEAMS_FILE = SCRIPT_DIR / "config" / "request_teams.txt"


def main():
    with open(LADDER_FILE) as f:
        ladder = json.load(f)

    top: list[str] = []
    for entry in ladder:
        if entry["teamName"] == TEAM_NAME:
            continue
        if MAIN_ONLY and entry.get("category") != "main":
            continue
        if STUDENTS_ONLY and not entry.get("isStudent"):
            continue
        if INTERNATIONAL_ONLY and entry.get("region") != "international":
            continue
        top.append(entry["teamName"])
        if len(top) >= TOP_N:
            break

    REQUEST_TEAMS_FILE.write_text("\n".join(top) + "\n", encoding="utf-8")
    print(f"Wrote {len(top)} teams to {REQUEST_TEAMS_FILE}")


if __name__ == "__main__":
    main()
