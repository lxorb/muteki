import json
import math
import time
import datetime
from pathlib import Path

RENDER_IMAGES = True
DECAY_LAMBDA = 0.1  # exponential decay rate in days^-1 (half-life ≈ ln2/λ ≈ 7 days)

SCRIPT_DIR = Path(__file__).parent
TEAM_LIST_FILE = SCRIPT_DIR / "data" / "team_list.json"
RESULTS_ALL_FILE = SCRIPT_DIR / "results" / "results.json"
OUTPUT_DIR = SCRIPT_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


def load_team_names() -> dict[str, str]:
    """Return {team_id: team_name} from team_list.json."""
    if not TEAM_LIST_FILE.exists():
        return {}
    with open(TEAM_LIST_FILE) as f:
        return json.load(f)


def load_results() -> dict:
    """Load the cumulative results file."""
    if not RESULTS_ALL_FILE.exists():
        return {}
    with open(RESULTS_ALL_FILE) as f:
        return json.load(f)


def win_pct(wins: int, games: int) -> str:
    """Return win percentage rounded to int, e.g. '67%'."""
    if games == 0:
        return "0%"
    return f"{round(wins / games * 100)}%"


def make_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def blend_to_white(hex_color: str, factor: float) -> str:
    """Blend hex_color toward white. factor=1 is full color, factor=0 is white."""
    r, g, b = (int(hex_color[i:i+2], 16) for i in (1, 3, 5))
    return "#{:02X}{:02X}{:02X}".format(
        int(255 + factor * (r - 255)),
        int(255 + factor * (g - 255)),
        int(255 + factor * (b - 255)),
    )


def render_table_to_image(
    headers: list[str], rows: list[list[str]], path: Path,
    cell_times: list[list[int | None]] | None = None,
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

    now_ts = time.time()
    for (r, c), cell in table.get_celld().items():
        text = cell.get_text().get_text()
        if r == 0:
            cell.set_facecolor("#4472C4")
            cell.set_text_props(color="white", fontweight="bold")
        elif text in ("\u2705", "\u274C"):
            factor = 1.0
            if cell_times is not None and r > 0:
                ts = cell_times[r - 1][c]
                if ts is not None:
                    days = (now_ts - ts) / 86400
                    factor = math.exp(-DECAY_LAMBDA * max(0, days))
            if text == "\u2705":
                cell.set_facecolor(blend_to_white("#C6EFCE", factor))
                cell.set_text_props(color="#006100", fontweight="bold")
                cell.get_text().set_text("W")
            else:
                cell.set_facecolor(blend_to_white("#FFC7CE", factor))
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

    # Compute per-map totals (across all teams)
    map_totals: dict[str, dict[str, int]] = {}
    for team_id, maps in combined.items():
        for map_name, map_data in maps.items():
            if map_name not in map_totals:
                map_totals[map_name] = {"wins": 0, "losses": 0}
            map_totals[map_name]["wins"] += map_data["wins"]
            map_totals[map_name]["losses"] += map_data["losses"]

    # Compute per-team totals (across all maps)
    team_totals: dict[str, dict[str, int]] = {}
    for team_id, maps in combined.items():
        if team_id not in team_totals:
            team_totals[team_id] = {"wins": 0, "losses": 0}
        for map_name, map_data in maps.items():
            team_totals[team_id]["wins"] += map_data["wins"]
            team_totals[team_id]["losses"] += map_data["losses"]

    # --- Result grid: maps (rows) vs teams (columns) with win % ---
    all_teams = sorted(combined.keys(), key=lambda t: team_names.get(t, t))
    all_maps: set[str] = set()
    for maps in combined.values():
        all_maps.update(maps.keys())

    headers = ["Map"] + [
        f"{team_names.get(t, t)} ({win_pct(team_totals[t]['wins'], team_totals[t]['wins'] + team_totals[t]['losses'])})"
        for t in all_teams
    ]

    rows: list[list[str]] = []
    cell_times: list[list[int | None]] = []
    for map_name in sorted(all_maps):
        mt = map_totals.get(map_name, {"wins": 0, "losses": 0})
        map_games = mt["wins"] + mt["losses"]
        map_label = f"{map_name} ({win_pct(mt['wins'], map_games)})"
        row = [map_label]
        row_times: list[int | None] = [None]
        for team_id in all_teams:
            map_data = combined.get(team_id, {}).get(map_name)
            if map_data is None:
                row.append("")
                row_times.append(None)
            else:
                newest_win = None
                newest_time = 0
                for k, v in map_data.items():
                    if k not in ("wins", "losses"):
                        entry_time = v.get("time", 0)
                        if entry_time >= newest_time:
                            newest_time = entry_time
                            newest_win = v["win"]
                row.append("✅" if newest_win else "❌" if newest_win is not None else "")
                row_times.append(newest_time if newest_time > 0 else None)
        rows.append(row)
        cell_times.append(row_times)

    lines: list[str] = []
    lines.append(f"# Unrated runner output from {now}")
    lines.append("")
    lines.append("## Results by map and team")
    lines.append("")
    lines.append(make_table(headers, rows))
    lines.append("")

    output_path = OUTPUT_DIR / f"output_{now}.md"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written to {output_path}")

    if RENDER_IMAGES:
        render_table_to_image(
            headers, rows,
            OUTPUT_DIR / f"output_{now}.jpg",
            cell_times=cell_times,
        )


if __name__ == "__main__":
    main()
