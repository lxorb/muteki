import json
import datetime
from pathlib import Path

RENDER_IMAGES = True

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


def render_table_to_image(
    headers: list[str], rows: list[list[str]], path: Path
) -> None:
    import matplotlib.pyplot as plt
    import matplotlib

    matplotlib.use("Agg")

    n_rows = len(rows)

    # Measure max content length per column to size widths
    col_widths = []
    for c in range(len(headers)):
        max_len = len(headers[c])
        for row in rows:
            max_len = max(max_len, len(row[c]))
        col_widths.append(max_len)
    # Convert char lengths to inches: short columns (<=2 chars) get narrow width
    col_inch = []
    for w in col_widths:
        if w <= 2:
            col_inch.append(0.3)
        else:
            col_inch.append(max(0.8, w * 0.12 + 0.3))

    row_height = 0.3
    fig_width = sum(col_inch)
    fig_height = (n_rows + 1) * row_height

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.set_axis_off()

    table = ax.table(
        cellText=rows,
        colLabels=headers,
        cellLoc="center",
        loc="center",
        colWidths=[w / sum(col_inch) for w in col_inch],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.3)

    for (r, c), cell in table.get_celld().items():
        text = cell.get_text().get_text()
        if r == 0:
            cell.set_facecolor("#4472C4")
            cell.set_text_props(color="white", fontweight="bold")
        elif text == "\u2705":
            cell.set_facecolor("#C6EFCE")
            cell.set_text_props(color="#006100", fontweight="bold")
            cell.get_text().set_text("W")
        elif text == "\u274C":
            cell.set_facecolor("#FFC7CE")
            cell.set_text_props(color="#9C0006", fontweight="bold")
            cell.get_text().set_text("L")
        elif r % 2 == 0:
            cell.set_facecolor("#D9E2F3")
        else:
            cell.set_facecolor("white")
        cell.set_edgecolor("#B4C6E7")

    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    print(f"Written to {path}")


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
    wins_headers = ["Win rate", "Map", "Wins", "Games played"]
    wins_rows = [[win_rate(w, g), map_name, str(w), str(g)] for _, map_name, w, g in rows]
    lines.append(make_table(wins_headers, wins_rows))
    lines.append("")

    # --- Last result: maps (rows) vs teams (columns) ---
    lines.append("## Last result by map and team")
    lines.append("")
    all_teams = sorted(combined.keys(), key=lambda t: team_names.get(t, t))
    all_maps: set[str] = set()
    for maps in combined.values():
        all_maps.update(maps.keys())
    last_headers = ["Map"] + [team_names.get(t, t) for t in all_teams]
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
    last_rows = rows
    lines.append(make_table(last_headers, last_rows))
    lines.append("")

    output_path = OUTPUT_DIR / f"output_{now}.md"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written to {output_path}")

    if RENDER_IMAGES:
        render_table_to_image(
            wins_headers, wins_rows,
            OUTPUT_DIR / f"output_{now}_wins.jpg",
        )
        render_table_to_image(
            last_headers, last_rows,
            OUTPUT_DIR / f"output_{now}_last.jpg",
        )


if __name__ == "__main__":
    main()
