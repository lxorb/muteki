import argparse
import datetime
import json
import math
import time
import urllib.request
import uuid
from pathlib import Path

RENDER_IMAGES = True

SCRIPT_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR / "results" / "version_compare"
OUTPUT_DIR = SCRIPT_DIR / "outputs" / "version_compare"
CONFIG_DIR = SCRIPT_DIR / "config"
DISCORD_WEBHOOK_FILE = CONFIG_DIR / "discord_webhook.txt"

OUTPUT_DIR.mkdir(exist_ok=True)

WIN_COLORS = [
    (67, "#C6EFCE"),
    (50, "#F2FCD9"),
    (33, "#ECB691"),
    (0, "#E88A8A"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render and optionally post a version comparison report."
    )
    parser.add_argument(
        "results",
        nargs="?",
        type=Path,
        help="Version comparison JSON. Defaults to latest results/version_compare/*.json.",
    )
    parser.add_argument(
        "--discord",
        action="store_true",
        help="Post the rendered JPG to Discord using config/discord_webhook.txt.",
    )
    parser.add_argument(
        "--webhook-line",
        type=int,
        default=0,
        help="Zero-based webhook line in config/discord_webhook.txt.",
    )
    parser.add_argument("--no-image", action="store_true", help="Do not render a JPG.")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def latest_results_file() -> Path | None:
    files = sorted(RESULTS_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime)
    return files[-1] if files else None


def win_pct(wins: int, games: int) -> str:
    if games == 0:
        return "N/A"
    return f"{round(wins / games * 100)}%"


def pct_value(wins: int, losses: int) -> float | None:
    total = wins + losses
    if total == 0:
        return None
    return wins / total * 100


def pct_color(pct: float | None) -> str | None:
    if pct is None:
        return None
    for threshold, color in WIN_COLORS:
        if pct >= threshold:
            return color
    return WIN_COLORS[-1][1]


def make_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def aggregate(data: dict) -> tuple[dict, dict]:
    versions = data.get("versions", [])
    maps = data.get("maps", [])
    stats: dict[str, dict[str, dict[str, int]]] = {
        version: {
            map_name: {"wins": 0, "losses": 0}
            for map_name in maps
        }
        for version in versions
    }
    status_counts = {"complete": 0, "queued": 0, "other": 0}

    for entry in data.get("matches", {}).values():
        status = entry.get("status")
        if status == "complete":
            status_counts["complete"] += 1
        elif status == "queued":
            status_counts["queued"] += 1
        else:
            status_counts["other"] += 1
        if status != "complete":
            continue

        version = entry.get("version")
        if version not in stats:
            continue
        for game in entry.get("games", []):
            map_name = game.get("map")
            if map_name not in stats[version]:
                stats[version][map_name] = {"wins": 0, "losses": 0}
            if game.get("win"):
                stats[version][map_name]["wins"] += 1
            else:
                stats[version][map_name]["losses"] += 1

    return stats, status_counts


def cell_text(wins: int, losses: int) -> str:
    total = wins + losses
    if total == 0:
        return "N/A"
    return f"{win_pct(wins, total)} {wins}-{losses}"


def build_rows(data: dict, stats: dict) -> tuple[list[str], list[list[str]], list[list[str | None]]]:
    versions = data.get("versions", [])
    maps = data.get("maps", [])

    totals = {
        version: {
            "wins": sum(map_stats["wins"] for map_stats in stats[version].values()),
            "losses": sum(map_stats["losses"] for map_stats in stats[version].values()),
        }
        for version in versions
    }
    headers = ["Map"] + [
        f"{version} ({cell_text(totals[version]['wins'], totals[version]['losses'])})"
        for version in versions
    ]

    rows: list[list[str]] = []
    colors: list[list[str | None]] = []

    overall_row = ["Overall"]
    overall_colors: list[str | None] = [None]
    for version in versions:
        wins = totals[version]["wins"]
        losses = totals[version]["losses"]
        overall_row.append(cell_text(wins, losses))
        overall_colors.append(pct_color(pct_value(wins, losses)))
    rows.append(overall_row)
    colors.append(overall_colors)

    for map_name in maps:
        row = [map_name]
        row_colors: list[str | None] = [None]
        for version in versions:
            map_stats = stats.get(version, {}).get(map_name, {"wins": 0, "losses": 0})
            wins = map_stats["wins"]
            losses = map_stats["losses"]
            row.append(cell_text(wins, losses))
            row_colors.append(pct_color(pct_value(wins, losses)))
        rows.append(row)
        colors.append(row_colors)

    return headers, rows, colors


def render_table_to_image(
    headers: list[str],
    rows: list[list[str]],
    path: Path,
    cell_colors: list[list[str | None]],
) -> None:
    import matplotlib
    import matplotlib.pyplot as plt

    matplotlib.use("Agg")

    if not rows:
        rows = [["No results"] + [""] * (len(headers) - 1)]
        cell_colors = [[None] * len(headers)]

    col_widths = []
    for col_idx, header in enumerate(headers):
        max_len = len(header)
        for row in rows:
            max_len = max(max_len, len(row[col_idx]))
        col_widths.append(max_len)
    col_inches = [max(1.0, width * 0.13 + 0.35) for width in col_widths]

    fig_width = sum(col_inches)
    fig_height = max(1.4, (len(rows) + 1) * 0.36)
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.set_axis_off()

    table = ax.table(
        cellText=rows,
        colLabels=headers,
        cellLoc="center",
        loc="center",
        colWidths=[width / fig_width for width in col_inches],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.3)

    for (row_idx, col_idx), cell in table.get_celld().items():
        if row_idx == 0:
            cell.set_facecolor("#4472C4")
            cell.set_text_props(color="white", fontweight="bold")
        else:
            color = cell_colors[row_idx - 1][col_idx]
            if color:
                cell.set_facecolor(color)
                cell.set_text_props(fontweight="bold")
            elif row_idx % 2 == 0:
                cell.set_facecolor("#D9E2F3")
            else:
                cell.set_facecolor("white")
            if row_idx == 1:
                cell.set_text_props(fontweight="bold")
        cell.set_edgecolor("#B4C6E7")

    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0)
    plt.close(fig)
    print(f"Written to {path}")


def read_discord_webhook_url(line_idx: int) -> str | None:
    if not DISCORD_WEBHOOK_FILE.exists():
        return None
    lines = DISCORD_WEBHOOK_FILE.read_text(encoding="utf-8").splitlines()
    if line_idx >= len(lines):
        return None
    text = lines[line_idx].strip()
    return text or None


def send_discord_jpg(jpg_path: Path, webhook_url: str, content: str) -> bool:
    boundary = uuid.uuid4().hex
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(b'Content-Disposition: form-data; name="payload_json"\r\n')
    body.extend(b"Content-Type: application/json\r\n\r\n")
    payload = json.dumps({"content": content})
    body.extend(payload.encode("utf-8"))
    body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="file"; filename="{jpg_path.name}"\r\n'.encode()
    )
    body.extend(b"Content-Type: image/jpeg\r\n\r\n")
    body.extend(jpg_path.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())

    request = urllib.request.Request(
        webhook_url,
        data=bytes(body),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "DiscordBot (https://github.com/lxorb/cbc-muteki, 1.0)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            response.read()
        return True
    except Exception as exc:
        print(f"Discord webhook failed: {exc}")
        return False


def main() -> None:
    args = parse_args()
    results_path = args.results or latest_results_file()
    if results_path is None:
        raise SystemExit(f"No version comparison results found in {RESULTS_DIR}")
    if not results_path.exists():
        raise SystemExit(f"Result file not found: {results_path}")

    data = load_json(results_path)
    stats, status_counts = aggregate(data)
    headers, rows, colors = build_rows(data, stats)

    now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    md_path = OUTPUT_DIR / f"version_compare_{now}.md"
    jpg_path = OUTPUT_DIR / f"version_compare_{now}.jpg"

    complete = status_counts["complete"]
    queued = status_counts["queued"]
    other = status_counts["other"]
    lines = [
        f"# Version comparison from {results_path.name}",
        "",
        f"Complete matches: {complete}; queued: {queued}; other: {other}",
        f"Maps: {', '.join(data.get('maps', []))}",
        "",
        make_table(headers, rows),
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Written to {md_path}")

    if RENDER_IMAGES and not args.no_image:
        render_table_to_image(headers, rows, jpg_path, colors)
    else:
        jpg_path = None

    if args.discord:
        if jpg_path is None:
            raise SystemExit("--discord requires image rendering")
        webhook_url = read_discord_webhook_url(args.webhook_line)
        if webhook_url is None:
            raise SystemExit(
                f"No webhook URL on line {args.webhook_line + 1} of {DISCORD_WEBHOOK_FILE}"
            )
        content = (
            f"Version comparison: {results_path.name} "
            f"({complete} complete matches, generated <t:{math.floor(time.time())}:R>)"
        )
        if send_discord_jpg(jpg_path, webhook_url, content):
            print(f"Sent {jpg_path.name} to Discord.")


if __name__ == "__main__":
    main()
