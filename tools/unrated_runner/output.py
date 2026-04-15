import json
import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
TEAM_LIST_FILE = SCRIPT_DIR / "config" / "team_list.txt"
RESULTS_ALL_FILE = SCRIPT_DIR / "results" / "results.json"
OUTPUT_DIR = SCRIPT_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


def load_team_names() -> dict[str, str]:
    """Return {team_id: team_name} from team_list.txt."""
    lines = TEAM_LIST_FILE.read_text().splitlines()
    teams: dict[str, str] = {}
    i = 0
    while i + 1 < len(lines):
        team_name = lines[i].strip()
        team_id = lines[i + 1].strip()
        if team_name and team_id:
            teams[team_id] = team_name
        i += 3
    return teams


def load_results() -> dict:
    """Load the cumulative results file."""
    if not RESULTS_ALL_FILE.exists():
        return {}
    with open(RESULTS_ALL_FILE) as f:
        return json.load(f)


def win_rate(wins: int, games: int) -> str:
    if games == 0:
        return "0.00%"
    return f"{wins / games * 100:.2f}%"


def make_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def main():
    team_names = load_team_names()
    combined = load_results()
    now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    lines: list[str] = []

    lines.append(f"# Unrated runner output from {now}")
    lines.append("")

    # --- By win rate, then map ---
    lines.append("## By win rate, then map")
    lines.append("")
    map_totals_wr: dict[str, dict[str, int]] = {}
    for team_id, maps in combined.items():
        for map_name, map_data in maps.items():
            if map_name not in map_totals_wr:
                map_totals_wr[map_name] = {"wins": 0, "losses": 0}
            map_totals_wr[map_name]["wins"] += map_data["wins"]
            map_totals_wr[map_name]["losses"] += map_data["losses"]
    rows = []
    for map_name in map_totals_wr:
        m = map_totals_wr[map_name]
        w, l = m["wins"], m["losses"]
        g = w + l
        wr = w / g if g > 0 else 0
        rows.append((wr, map_name, w, g))
    rows.sort(key=lambda r: (r[0], r[1]))
    lines.append(make_table(
        ["Win rate", "Map", "Wins", "Games played"],
        [[win_rate(w, g), map_name, str(w), str(g)] for _, map_name, w, g in rows],
    ))
    lines.append("")

    # --- Last result: maps (rows) vs teams (columns) ---
    lines.append("## Last result by map and team")
    lines.append("")
    all_teams = sorted(combined.keys(), key=lambda t: team_names.get(t, t))
    all_maps: set[str] = set()
    for maps in combined.values():
        all_maps.update(maps.keys())
    headers = ["Map"] + [team_names.get(t, t) for t in all_teams]
    rows = []
    for map_name in sorted(all_maps):
        row = [map_name]
        for team_id in all_teams:
            map_data = combined.get(team_id, {}).get(map_name)
            if map_data is None:
                row.append("")
            else:
                # Last match entry is the last key that isn't wins/losses
                last_win = None
                for k, v in map_data.items():
                    if k not in ("wins", "losses"):
                        last_win = v["win"]
                row.append("✅" if last_win else "❌" if last_win is not None else "")
        rows.append(row)
    lines.append(make_table(headers, rows))
    lines.append("")

    output_path = OUTPUT_DIR / f"output_{now}.md"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()
