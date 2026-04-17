import sys
import json
import datetime
from pathlib import Path

RENDER_IMAGES = True

# Full-intensity color is reached at this many percentage points of change
MAX_DELTA = 50

# Base colors (full intensity)
CYAN = "#00B8D4"  # improvement
PINK = "#E91E63"  # regression

SCRIPT_DIR = Path(__file__).parent
TEAM_LIST_FILE = SCRIPT_DIR / "data" / "team_list.json"
REQUEST_TEAMS_FILE = SCRIPT_DIR / "config" / "request_teams.txt"
OUTPUT_TEAMS_FILE = SCRIPT_DIR / "config" / "output_teams.txt"
PARTIAL_DIR = SCRIPT_DIR / "results" / "partial"
COMPARE_DIR = SCRIPT_DIR / "compares"
COMPARE_DIR.mkdir(exist_ok=True)


def load_team_names() -> dict[str, str]:
    if not TEAM_LIST_FILE.exists():
        return {}
    with open(TEAM_LIST_FILE) as f:
        data = json.load(f)
    return {tid: info["name"] for tid, info in data.items()}


def load_results(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def get_last_two_partials() -> tuple[Path | None, Path | None]:
    """Return the two most recent partial result files (old, new)."""
    files = sorted(PARTIAL_DIR.glob("results_*.json"))
    if len(files) < 2:
        return None, None
    return files[-2], files[-1]


def compute_win_rates(data: dict) -> dict[str, dict[str, tuple[int, int, float | None]]]:
    """Return {team_id: {map_name: (wins, losses, win_pct)}}."""
    rates: dict[str, dict[str, tuple[int, int, float | None]]] = {}
    for team_id, maps in data.items():
        rates[team_id] = {}
        for map_name, map_data in maps.items():
            w = map_data["wins"]
            l = map_data["losses"]
            total = w + l
            pct = (w / total * 100) if total > 0 else None
            rates[team_id][map_name] = (w, l, pct)
    return rates


def blend_to_white(hex_color: str, factor: float) -> str:
    """Blend hex_color toward white. factor=1 is full color, factor=0 is white."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return "#{:02X}{:02X}{:02X}".format(
        int(255 + factor * (r - 255)),
        int(255 + factor * (g - 255)),
        int(255 + factor * (b - 255)),
    )


def delta_color(delta: float | None) -> str | None:
    """Return hex color for a given delta in percentage points."""
    if delta is None:
        return None
    intensity = min(abs(delta) / MAX_DELTA, 1.0)
    base = CYAN if delta >= 0 else PINK
    return blend_to_white(base, intensity)


def fmt_delta(delta: float | None) -> str:
    if delta is None:
        return "N/A"
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.0f}%"


def make_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_table_to_image(
    headers: list[str],
    rows: list[list[str]],
    path: Path,
    cell_colors: list[list[str | None]],
) -> None:
    import matplotlib.pyplot as plt
    import matplotlib

    matplotlib.use("Agg")

    n_rows = len(rows)

    col_widths = []
    for c in range(len(headers)):
        max_len = len(headers[c])
        for row in rows:
            max_len = max(max_len, len(row[c]))
        col_widths.append(max_len)

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
        if r == 0:
            cell.set_facecolor("#4472C4")
            cell.set_text_props(color="white", fontweight="bold")
        elif cell_colors is not None and r > 0:
            color = cell_colors[r - 1][c]
            if color:
                cell.set_facecolor(color)
                cell.set_text_props(fontweight="bold")
            elif r % 2 == 0:
                cell.set_facecolor("#D9E2F3")
            else:
                cell.set_facecolor("white")
        elif r % 2 == 0:
            cell.set_facecolor("#D9E2F3")
        else:
            cell.set_facecolor("white")
        cell.set_edgecolor("#B4C6E7")

    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    print(f"Written to {path}")


def main():
    args = sys.argv[1:]

    if len(args) == 0:
        old_path, new_path = get_last_two_partials()
        if old_path is None or new_path is None:
            files = sorted(PARTIAL_DIR.glob("results_*.json"))
            print(f"Error: Need at least 2 partial result files for automatic comparison, found {len(files)}.")
            if files:
                for f in files:
                    print(f"  {f.name}")
            sys.exit(1)
    elif len(args) == 2:
        old_path = Path(args[0])
        new_path = Path(args[1])
        for p in (old_path, new_path):
            if not p.exists():
                print(f"Error: File not found: {p}")
                sys.exit(1)
    else:
        print("Usage: python compare.py [old_results.json new_results.json]")
        print("  With no arguments, compares the two most recent partial results.")
        sys.exit(1)

    print(f"Comparing:")
    print(f"  Old: {old_path.name}")
    print(f"  New: {new_path.name}")

    team_names = load_team_names()
    old_data = load_results(old_path)
    new_data = load_results(new_path)
    old_rates = compute_win_rates(old_data)
    new_rates = compute_win_rates(new_data)

    # Collect all teams and maps present in both datasets
    all_team_ids = set(old_data.keys()) | set(new_data.keys())

    # Team ordering (same logic as output.py)
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
        [t for t in all_team_ids if not output_set or team_names.get(t, t) in output_set],
        key=lambda t: (
            requested_rank.get(team_names.get(t, t), len(requested_order)),
            team_names.get(t, t),
        ),
    )

    all_maps: set[str] = set()
    for data in (old_data, new_data):
        for maps in data.values():
            all_maps.update(maps.keys())

    # Per-team overall delta for headers
    def team_overall_delta(team_id: str) -> float | None:
        old = old_rates.get(team_id, {})
        new = new_rates.get(team_id, {})
        old_w = sum(r[0] for r in old.values())
        old_t = sum(r[0] + r[1] for r in old.values())
        new_w = sum(r[0] for r in new.values())
        new_t = sum(r[0] + r[1] for r in new.values())
        old_pct = (old_w / old_t * 100) if old_t > 0 else None
        new_pct = (new_w / new_t * 100) if new_t > 0 else None
        if old_pct is not None and new_pct is not None:
            return new_pct - old_pct
        return None

    headers = ["Map"] + [
        f"{team_names.get(t, t)} ({fmt_delta(team_overall_delta(t))})"
        for t in all_teams
    ]

    rows: list[list[str]] = []
    cell_colors: list[list[str | None]] = []

    for map_name in sorted(all_maps):
        # Overall map delta across all teams
        old_w = old_l = new_w = new_l = 0
        for t in all_teams:
            oe = old_rates.get(t, {}).get(map_name)
            ne = new_rates.get(t, {}).get(map_name)
            if oe:
                old_w += oe[0]
                old_l += oe[1]
            if ne:
                new_w += ne[0]
                new_l += ne[1]
        old_total = old_w + old_l
        new_total = new_w + new_l
        old_pct = (old_w / old_total * 100) if old_total > 0 else None
        new_pct = (new_w / new_total * 100) if new_total > 0 else None
        if old_pct is not None and new_pct is not None:
            map_delta = new_pct - old_pct
        else:
            map_delta = None

        map_label = f"{map_name} ({fmt_delta(map_delta)})"
        row = [map_label]
        row_colors: list[str | None] = [delta_color(map_delta)]

        for team_id in all_teams:
            old_entry = old_rates.get(team_id, {}).get(map_name)
            new_entry = new_rates.get(team_id, {}).get(map_name)

            if old_entry is not None and new_entry is not None:
                old_p = old_entry[2]
                new_p = new_entry[2]
                if old_p is not None and new_p is not None:
                    delta = new_p - old_p
                    row.append(fmt_delta(delta))
                    row_colors.append(delta_color(delta))
                else:
                    row.append("N/A")
                    row_colors.append(None)
            else:
                row.append("N/A")
                row_colors.append(None)

        rows.append(row)
        cell_colors.append(row_colors)

    # Write markdown
    now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    lines: list[str] = []
    lines.append(f"# Comparison: {old_path.name} vs {new_path.name}")
    lines.append("")
    lines.append("## Win rate changes by map and team")
    lines.append("")
    lines.append(make_table(headers, rows))
    lines.append("")

    md_path = COMPARE_DIR / f"compare_{now}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written to {md_path}")

    if RENDER_IMAGES:
        render_table_to_image(
            headers,
            rows,
            COMPARE_DIR / f"compare_{now}.jpg",
            cell_colors=cell_colors,
        )


if __name__ == "__main__":
    main()
