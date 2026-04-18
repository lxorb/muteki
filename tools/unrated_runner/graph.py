import colorsys
import datetime
import hashlib
import json
import time
from pathlib import Path

CUTOFF_HOURS: float | None = (
    None  # ignore games older than this; set to 0 or None to disable
)
WINDOW_HOURS = (
    24.0  # rolling win-rate window: each point uses games from the last N hours
)
SKIP_FIRST_N = 64  # hide the first N points so early win rates don't spike the plot

SCRIPT_DIR = Path(__file__).parent
TEAM_LIST_FILE = SCRIPT_DIR / "data" / "team_list.json"
GRAPH_TEAMS_FILE = SCRIPT_DIR / "config" / "graph_teams.txt"
RESULTS_ALL_FILE = SCRIPT_DIR / "results" / "results.json"
GRAPHS_DIR = SCRIPT_DIR / "graphs"
GRAPHS_DIR.mkdir(exist_ok=True)


def load_team_names() -> dict[str, str]:
    """Return {team_id: team_name} from team_list.json."""
    if not TEAM_LIST_FILE.exists():
        return {}
    with open(TEAM_LIST_FILE) as f:
        data = json.load(f)
    return {tid: info["name"] for tid, info in data.items()}


def load_results() -> dict:
    if not RESULTS_ALL_FILE.exists():
        return {}
    with open(RESULTS_ALL_FILE) as f:
        return json.load(f)


def load_graph_teams() -> list[str]:
    if not GRAPH_TEAMS_FILE.exists():
        return []
    return [
        name.strip()
        for name in GRAPH_TEAMS_FILE.read_text().splitlines()
        if name.strip()
    ]


def collect_games(
    team_data: dict, cutoff_hours: float | None
) -> list[tuple[int, bool]]:
    """Return list of (timestamp, win) across all maps for a team, sorted by time.

    Drops entries older than cutoff_hours if set.
    """
    cutoff_ts = (
        time.time() - cutoff_hours * 3600 if cutoff_hours and cutoff_hours > 0 else None
    )
    games: list[tuple[int, bool]] = []
    for map_data in team_data.values():
        for k, v in map_data.items():
            if k in ("wins", "losses"):
                continue
            ts = v.get("time")
            if ts is None:
                continue
            if cutoff_ts is not None and ts < cutoff_ts:
                continue
            games.append((int(ts), bool(v.get("win"))))
    games.sort(key=lambda g: g[0])
    return games


def team_color(team_id: str) -> str:
    """Deterministic hex color for a team_id via hashed hue with fixed S/L."""
    digest = hashlib.sha1(team_id.encode()).digest()
    hue = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    r, g, b = colorsys.hls_to_rgb(hue, 0.45, 0.65)
    return "#{:02X}{:02X}{:02X}".format(int(r * 255), int(g * 255), int(b * 255))


def render_team_graph(
    team_name: str,
    team_id: str,
    games: list[tuple[int, bool]],
    window_hours: float,
    skip_first: int,
    path: Path,
) -> None:
    import matplotlib.pyplot as plt
    import matplotlib
    import matplotlib.dates as mdates

    matplotlib.use("Agg")

    times = [datetime.datetime.fromtimestamp(ts) for ts, _ in games]
    window_seconds = window_hours * 3600
    pcts: list[float] = []
    left = 0
    wins_in_window = 0
    for right, (ts, win) in enumerate(games):
        if win:
            wins_in_window += 1
        while games[left][0] < ts - window_seconds:
            if games[left][1]:
                wins_in_window -= 1
            left += 1
        n = right - left + 1
        pcts.append(wins_in_window / n * 100)

    plot_times = times[skip_first:]
    plot_pcts = pcts[skip_first:]

    color = team_color(team_id)
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(plot_times, plot_pcts, marker="o", markersize=2, linewidth=1.5, color=color)
    ax.axhline(50, color="#B4C6E7", linewidth=1.5, linestyle="--")

    ax.set_ylim(0, 100)
    ax.set_xlabel("Date")
    ax.set_ylabel("Win rate (%)")
    ax.set_title(
        f"{team_name} — win rate over time (window={window_hours:g}h, N={len(games)})"
    )
    ax.grid(True, linestyle=":", linewidth=0.5, color="#CCCCCC")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    fig.autofmt_xdate()

    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Written to {path}")


def main():
    team_names = load_team_names()
    name_to_id = {name: tid for tid, name in team_names.items()}
    combined = load_results()
    graph_teams = load_graph_teams()
    now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    if not graph_teams:
        print(f"No teams listed in {GRAPH_TEAMS_FILE}; nothing to plot.")
        return

    for team_name in graph_teams:
        team_id = name_to_id.get(team_name)
        if team_id is None:
            print(f"  Unknown team {team_name!r} (not in team_list.json); skipping.")
            continue
        team_data = combined.get(team_id)
        if not team_data:
            print(f"  No results for {team_name}; skipping.")
            continue
        games = collect_games(team_data, CUTOFF_HOURS)
        if len(games) <= SKIP_FIRST_N:
            print(
                f"  Only {len(games)} game(s) for {team_name}; need more than SKIP_FIRST_N={SKIP_FIRST_N}; skipping."
            )
            continue
        path = GRAPHS_DIR / f"graph_{now}_{team_name}.jpg"
        render_team_graph(team_name, team_id, games, WINDOW_HOURS, SKIP_FIRST_N, path)


if __name__ == "__main__":
    main()
