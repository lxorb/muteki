import json
import math
import time
import datetime
from pathlib import Path

RENDER_IMAGES = True
HALF_LIFE_MINUTES = 60
DECAY_LAMBDA = math.log(2) / (HALF_LIFE_MINUTES / 1440)  # in days^-1
CUTOFF_HOURS: float | None = (
    12  # ignore games older than this; set to 0 or None to disable
)

# Map win-rate color cutoffs: (threshold, background_color)
# Applied top-down; first match wins.
MAP_WIN_COLORS = [
    (67, "#C6EFCE"),  # green
    (50, "#F2FCD9"),  # yellow
    (33, "#ECB691"),  # orange
    (0, "#E88A8A"),  # red
]

RESULTS_FILE = ""  # set to a filename under results/ to use a partial result, e.g. "results_2026-04-16.json"

SCRIPT_DIR = Path(__file__).parent
TEAM_LIST_FILE = SCRIPT_DIR / "data" / "team_list.json"
REQUEST_TEAMS_FILE = SCRIPT_DIR / "config" / "request_teams.txt"
OUTPUT_TEAMS_FILE = SCRIPT_DIR / "config" / "output_teams.txt"
RESULTS_ALL_FILE = SCRIPT_DIR / "results" / (RESULTS_FILE or "results.json")
OUTPUT_DIR = SCRIPT_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


def load_team_names() -> dict[str, str]:
    """Return {team_id: team_name} from team_list.json."""
    if not TEAM_LIST_FILE.exists():
        return {}
    with open(TEAM_LIST_FILE) as f:
        data = json.load(f)
    return {tid: info["name"] for tid, info in data.items()}


def load_results() -> dict:
    """Load the cumulative results file."""
    if not RESULTS_ALL_FILE.exists():
        return {}
    with open(RESULTS_ALL_FILE) as f:
        return json.load(f)


def filter_by_cutoff(results: dict, cutoff_hours: float | None) -> dict:
    """Drop game entries older than cutoff_hours; recompute wins/losses.

    Map entries with no remaining games are dropped, as are teams with no
    remaining maps. If cutoff_hours is falsy or non-positive, returns results
    unchanged.
    """
    if not cutoff_hours or cutoff_hours <= 0:
        return results
    cutoff_ts = time.time() - cutoff_hours * 3600
    filtered: dict = {}
    for team_id, maps in results.items():
        team_filtered: dict = {}
        for map_name, map_data in maps.items():
            wins = 0
            losses = 0
            entries: dict = {}
            for k, v in map_data.items():
                if k in ("wins", "losses"):
                    continue
                if v.get("time", 0) < cutoff_ts:
                    continue
                entries[k] = v
                if v.get("win"):
                    wins += 1
                else:
                    losses += 1
            if entries:
                team_filtered[map_name] = {"wins": wins, "losses": losses, **entries}
        if team_filtered:
            filtered[team_id] = team_filtered
    return filtered


def win_pct(wins: int, games: int) -> str:
    """Return win percentage rounded to int, e.g. '67%'."""
    if games == 0:
        return "N/A"
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
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return "#{:02X}{:02X}{:02X}".format(
        int(255 + factor * (r - 255)),
        int(255 + factor * (g - 255)),
        int(255 + factor * (b - 255)),
    )


def map_win_color(pct: float | None) -> str | None:
    """Return a background color for the given map win percentage, or None."""
    if pct is None:
        return None
    for threshold, color in MAP_WIN_COLORS:
        if pct >= threshold:
            return color
    return MAP_WIN_COLORS[-1][1]


def render_table_to_image(
    headers: list[str],
    rows: list[list[str]],
    path: Path,
    cell_times: list[list[int | None]] | None = None,
    map_win_pcts: list[float | None] | None = None,
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
        elif text in ("\u2705", "\u274c"):
            factor = 1.0
            if cell_times is not None and r > 0:
                ts = cell_times[r - 1][c]
                if ts is not None:
                    days = (now_ts - ts) / 86400
                    factor = math.exp(-DECAY_LAMBDA * max(0, days))
            if text == "\u2705":
                cell.set_facecolor(blend_to_white("#A9E7B5", factor))
                cell.set_text_props(color="#006100", fontweight="bold")
                cell.get_text().set_text("W")
            else:
                cell.set_facecolor(blend_to_white("#FFABB5", factor))
                cell.set_text_props(color="#9C0006", fontweight="bold")
                cell.get_text().set_text("L")
        elif c == 0 and r > 0 and map_win_pcts is not None:
            bg = map_win_color(map_win_pcts[r - 1])
            cell.set_facecolor(bg if bg else "white")
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
    combined = filter_by_cutoff(combined, CUTOFF_HOURS)
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
    requested_order: list[str] = []
    if OUTPUT_TEAMS_FILE.exists():
        requested_order = [
            name.strip()
            for name in OUTPUT_TEAMS_FILE.read_text().splitlines()
            if name.strip()
        ]
    requested_rank = {name: i for i, name in enumerate(requested_order)}
    output_set = set(requested_order)
    all_teams = sorted(
        [
            t
            for t in combined.keys()
            if not output_set or team_names.get(t, t) in output_set
        ],
        key=lambda t: (
            requested_rank.get(team_names.get(t, t), len(requested_order)),
            team_names.get(t, t),
        ),
    )
    all_maps: set[str] = set()
    for maps in combined.values():
        all_maps.update(maps.keys())

    headers = ["Map"] + [
        f"{team_names.get(t, t)} ({win_pct(team_totals[t]['wins'], team_totals[t]['wins'] + team_totals[t]['losses'])} N:{team_totals[t]['wins'] + team_totals[t]['losses']})"
        for t in all_teams
    ]

    rows: list[list[str]] = []
    cell_times: list[list[int | None]] = []
    map_win_pcts: list[float | None] = []
    for map_name in sorted(all_maps):
        mt = map_totals.get(map_name, {"wins": 0, "losses": 0})
        map_games = mt["wins"] + mt["losses"]
        map_pct = (mt["wins"] / map_games * 100) if map_games > 0 else None
        map_win_pcts.append(map_pct)
        map_label = f"{map_name} ({win_pct(mt['wins'], map_games)} N:{map_games})"
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
                row.append(
                    "✅" if newest_win else "❌" if newest_win is not None else ""
                )
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
            headers,
            rows,
            OUTPUT_DIR / f"output_{now}.jpg",
            cell_times=cell_times,
            map_win_pcts=map_win_pcts,
        )


if __name__ == "__main__":
    main()
