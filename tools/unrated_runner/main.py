import json
import random
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from collections import deque
from pathlib import Path

import datetime

TEAM_NAME = "muteki"

SCRIPT_DIR = Path(__file__).parent
MAPS_DIR = SCRIPT_DIR.parent.parent / "maps"
CONFIG_DIR = SCRIPT_DIR / "config"
DATA_DIR = SCRIPT_DIR / "data"
RESULTS_DIR = SCRIPT_DIR / "results"
RESULTS_PARTIAL_DIR = RESULTS_DIR / "partial"
OUTPUT_DIR = SCRIPT_DIR / "outputs"
for d in (CONFIG_DIR, DATA_DIR, RESULTS_DIR, RESULTS_PARTIAL_DIR, OUTPUT_DIR):
    d.mkdir(exist_ok=True)
TEAM_LIST_FILE = DATA_DIR / "team_list.json"
REQUEST_TEAMS_FILE = CONFIG_DIR / "request_teams.txt"
DISCORD_INTERVAL_FILE = CONFIG_DIR / "discord_interval.txt"
DISCORD_WEBHOOK_FILE = CONFIG_DIR / "discord_webhook.txt"
TEAMS_FILE = DATA_DIR / "requested_teams.json"
QUEUED_FILE = DATA_DIR / "queued.json"
RESULTS_SESSION_FILE = RESULTS_PARTIAL_DIR / "results_{}.json".format(
    datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
)
RESULTS_ALL_FILE = RESULTS_DIR / "results.json"
OUTPUT_SCRIPT = SCRIPT_DIR / "output.py"
GRAPH_SCRIPT = SCRIPT_DIR / "graph.py"
GRAPHS_DIR = SCRIPT_DIR / "graphs"

REQUEST_DELAY = 120
RANDOM_MAP_SELECTION = True


def build_teams_json() -> None:
    """Read team_list.json and request_teams.txt, write matching teams to requested_teams.json."""
    all_teams: dict[str, dict] = load_json(TEAM_LIST_FILE)  # {id: {name, category, isStudent, region}}
    name_to_id = {info["name"]: tid for tid, info in all_teams.items()}

    requested = {
        name.strip()
        for name in REQUEST_TEAMS_FILE.read_text().splitlines()
        if name.strip()
    }

    teams = {
        name_to_id[name]: name
        for name in requested
        if name in name_to_id and name != TEAM_NAME
    }
    save_json(TEAMS_FILE, teams)
    print(
        f"Built requested_teams.json with {len(teams)} teams: {', '.join(teams.values())}"
    )


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=4)


def get_priority_maps(results: dict, team_id: str, count: int = 5) -> list[str]:
    """Return the maps with the fewest games played against a specific team."""
    all_maps = [p.stem for p in MAPS_DIR.glob("*.map26")]
    games_per_map: dict[str, int] = {m: 0 for m in all_maps}
    team_data = results.get(team_id, {})
    for map_name, map_data in team_data.items():
        if map_name in games_per_map:
            games_per_map[map_name] += map_data.get("wins", 0) + map_data.get(
                "losses", 0
            )
    if RANDOM_MAP_SELECTION:
        # Group maps by game count, shuffle within each tier, then take top count
        from itertools import groupby

        sorted_maps = sorted(games_per_map, key=lambda m: games_per_map[m])
        result = []
        for _, group in groupby(sorted_maps, key=lambda m: games_per_map[m]):
            tier = list(group)
            random.shuffle(tier)
            result.extend(tier)
        return result[:count]
    return sorted(games_per_map, key=lambda m: (games_per_map[m], m))[:count]


def queue_match(team_id: str, maps: list[str]) -> str | None:
    cmd = ["cambc", "match", "unrated", team_id]
    for m in maps:
        cmd += ["--map", m]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    m = re.search(r"Match ID: ([0-9a-f-]+)", result.stdout)
    if m:
        return m.group(1)
    print(f"  Could not queue: {result.stdout.strip()}")
    return None


def resolve_map_name(name: str, valid_maps: set[str]) -> str | None:
    """Resolve a possibly-truncated map name to a full name from valid_maps.

    The cambc match-info table truncates long map names with '…' (or '\\ufffd'
    when the subprocess output is mis-decoded). We fall back to unique-prefix
    matching against the known map list.
    """
    if name in valid_maps:
        return name
    stem = name.rstrip("\ufffd…")
    if not stem:
        return None
    candidates = [m for m in valid_maps if m.startswith(stem)]
    if len(candidates) == 1:
        return candidates[0]
    return None


def check_match(match_id: str) -> list[dict] | None:
    result = subprocess.run(
        ["cambc", "match", "info", match_id],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = result.stdout
    # print(repr(output))  # DEBUG: see raw captured output
    if "Status:  complete" not in output:
        return None

    valid_maps = {p.stem for p in MAPS_DIR.glob("*.map26")}
    games = []
    for line in output.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) != 5 or not cells[0].isdigit():
            continue
        raw_map = cells[1]
        resolved = resolve_map_name(raw_map, valid_maps)
        if resolved is None:
            print(f"  WARN: could not resolve map name {raw_map!r}; keeping as-is.")
            resolved = raw_map
        games.append(
            {
                "map": resolved,
                "win": TEAM_NAME in cells[2],
                "condition": cells[3],
                "turns": int(cells[4]),
            }
        )
    return games


def _read_line(path: Path, line_idx: int) -> str | None:
    """Return the stripped Nth line of a file, or None if missing/out-of-range/empty."""
    if not path.exists():
        return None
    lines = path.read_text().splitlines()
    if line_idx >= len(lines):
        return None
    text = lines[line_idx].strip()
    return text or None


def read_discord_interval_minutes(line_idx: int = 0) -> int | None:
    """Return a positive integer from the Nth line of discord_interval.txt, or None."""
    text = _read_line(DISCORD_INTERVAL_FILE, line_idx)
    if text is None or not text.isdigit():
        return None
    n = int(text)
    return n if n > 0 else None


def read_discord_webhook_url(line_idx: int = 0) -> str | None:
    """Return the webhook URL from the Nth line of discord_webhook.txt, or None."""
    return _read_line(DISCORD_WEBHOOK_FILE, line_idx)


def send_discord_jpg(jpg_path: Path, webhook_url: str) -> bool:
    boundary = uuid.uuid4().hex
    body = bytearray()
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="file"; filename="{jpg_path.name}"\r\n'.encode()
    )
    body.extend(b"Content-Type: image/jpeg\r\n\r\n")
    body.extend(jpg_path.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        webhook_url,
        data=bytes(body),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "DiscordBot (https://github.com/lxorb/cbc-muteki, 1.0)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            resp.read()
        return True
    except Exception as e:
        print(f"  Discord webhook failed: {e}")
        return False


def run_output_and_post() -> None:
    webhook_url = read_discord_webhook_url()
    if webhook_url is None:
        print("  No Discord webhook URL set in config/discord_webhook.txt; skipping.")
        return
    result = subprocess.run(
        [sys.executable, str(OUTPUT_SCRIPT)], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  output.py failed: {result.stderr.strip() or result.stdout.strip()}")
        return
    jpgs = sorted(OUTPUT_DIR.glob("output_*.jpg"), key=lambda p: p.stat().st_mtime)
    if not jpgs:
        print("  No output jpg to send.")
        return
    latest = jpgs[-1]
    if send_discord_jpg(latest, webhook_url):
        print(f"  Sent {latest.name} to Discord.")


def run_graph_and_post() -> None:
    webhook_url = read_discord_webhook_url(line_idx=1)
    if webhook_url is None:
        print(
            "  No graph Discord webhook URL (2nd line of config/discord_webhook.txt); skipping."
        )
        return
    before = time.time()
    result = subprocess.run(
        [sys.executable, str(GRAPH_SCRIPT)], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  graph.py failed: {result.stderr.strip() or result.stdout.strip()}")
        return
    if not GRAPHS_DIR.exists():
        print("  No graphs directory.")
        return
    new_jpgs = sorted(
        (p for p in GRAPHS_DIR.glob("graph_*.jpg") if p.stat().st_mtime >= before),
        key=lambda p: p.stat().st_mtime,
    )
    if not new_jpgs:
        print("  No new graph jpgs to send.")
        return
    for jpg in new_jpgs:
        if send_discord_jpg(jpg, webhook_url):
            print(f"  Sent {jpg.name} to Discord (graphs).")


def record_games(results: dict, team_id: str, match_id: str, games: list[dict]) -> None:
    team = results.setdefault(team_id, {})
    for game in games:
        map_entry = team.setdefault(game["map"], {"wins": 0, "losses": 0})
        if game["win"]:
            map_entry["wins"] += 1
        else:
            map_entry["losses"] += 1
        map_entry[match_id] = {
            "win": game["win"],
            "condition": game["condition"],
            "turns": game["turns"],
            "time": int(time.time()),
        }


def main():
    results_session = load_json(RESULTS_SESSION_FILE)
    results_all = load_json(RESULTS_ALL_FILE)
    queued_teams: set[str] = set()

    # Restore queued matches from previous run
    queued_data = load_json(QUEUED_FILE)
    match_queue: deque[tuple[str, str]] = deque(
        (mid, tid) for mid, tid in queued_data.get("queued", [])
    )
    save_json(QUEUED_FILE, {"queued": []})

    print(
        f"Unrated runner started. {len(match_queue)} queued from previous run. Ctrl+C to stop."
    )

    last_discord_post = -1
    last_graph_post = -1

    try:
        while True:
            # Rebuild teams each iteration
            build_teams_json()
            teams = load_json(TEAMS_FILE)
            team_ids = list(teams.keys())

            # Check pending matches
            remaining: deque[tuple[str, str]] = deque()
            for match_id, team_id in match_queue:
                print(f"  Checking {match_id}...")
                games = check_match(match_id)
                if games is not None:
                    print(f"  Match {match_id} complete ({len(games)} games)")
                    record_games(results_session, team_id, match_id, games)
                    record_games(results_all, team_id, match_id, games)
                    save_json(RESULTS_SESSION_FILE, results_session)
                    save_json(RESULTS_ALL_FILE, results_all)
                else:
                    remaining.append((match_id, team_id))
            match_queue = remaining

            # Queue new match
            if not team_ids:
                print("  No teams configured, skipping.")
                time.sleep(REQUEST_DELAY)
                continue
            remaining_teams = [t for t in team_ids if t not in queued_teams]
            if not remaining_teams:
                queued_teams.clear()
                remaining_teams = team_ids
            team_id = remaining_teams[0]
            queued_teams.add(team_id)
            priority_maps = get_priority_maps(results_all, team_id)
            print(f"Queuing vs {teams[team_id]} ({team_id}) on {priority_maps}...")
            match_id = queue_match(team_id, priority_maps)
            if match_id:
                print(f"  Queued: {match_id}")
                match_queue.append((match_id, team_id))

            interval_minutes = read_discord_interval_minutes()
            if (
                interval_minutes is not None
                and time.time() - last_discord_post >= interval_minutes * 60
            ):
                print("Running output.py and posting to Discord...")
                run_output_and_post()
                last_discord_post = time.time()

            graph_interval_minutes = read_discord_interval_minutes(line_idx=1)
            if (
                graph_interval_minutes is not None
                and time.time() - last_graph_post >= graph_interval_minutes * 60
            ):
                print("Running graph.py and posting to Discord...")
                run_graph_and_post()
                last_graph_post = time.time()

            time.sleep(REQUEST_DELAY)
    except KeyboardInterrupt:
        if match_queue:
            save_json(QUEUED_FILE, {"queued": list(match_queue)})
            print(f"\nSaved {len(match_queue)} pending matches to queued.json.")
        print("Stopped.")


if __name__ == "__main__":
    main()
