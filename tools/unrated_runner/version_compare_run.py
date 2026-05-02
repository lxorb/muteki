import argparse
import datetime
import json
import os
import random
import re
import socket
import subprocess
import time
from pathlib import Path

TEAM_NAME = "muteki"
DEFAULT_VERSIONS = ("v213", "v211", "v204", "v191")
DEFAULT_MAP_POOL = ("cold", "cubes", "default_medium2", "pointing", "rush_bait")
DEFAULT_BATCHES = 3
BATCH_DELAY = 300
CHECK_DELAY = 60

SCRIPT_DIR = Path(__file__).parent
MAPS_DIR = SCRIPT_DIR.parent.parent / "maps"
CONFIG_DIR = SCRIPT_DIR / "config"
DATA_DIR = SCRIPT_DIR / "data"
RESULTS_DIR = SCRIPT_DIR / "results" / "version_compare"

TEAM_LIST_FILE = DATA_DIR / "team_list.json"
REQUEST_TEAMS_FILE = CONFIG_DIR / "request_teams.txt"
MAPS_FILE = CONFIG_DIR / "version_compare_maps.txt"

for directory in (CONFIG_DIR, DATA_DIR, RESULTS_DIR):
    directory.mkdir(parents=True, exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare muteki submissions with unrated batches. Each batch queues one "
            "unrated match per version on the same randomly selected map, then waits "
            "five minutes before the next batch."
        )
    )
    parser.add_argument(
        "--results",
        type=Path,
        help="Result JSON to write or resume. Defaults to a timestamped file.",
    )
    parser.add_argument(
        "--versions",
        default=",".join(DEFAULT_VERSIONS),
        help="Comma-separated submission versions. Default: %(default)s",
    )
    parser.add_argument(
        "--batches",
        type=int,
        default=DEFAULT_BATCHES,
        help=(
            "Comparison batches to queue on this runner. Each owned batch queues "
            "one match for every version. Ignored with --continuous."
        ),
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Keep queueing owned comparison batches until interrupted.",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=BATCH_DELAY,
        help="Seconds between global batch slots. Keep at 300 for the unrated cap.",
    )
    parser.add_argument(
        "--initial-delay",
        type=int,
        default=0,
        help="Seconds to wait before the first queue/check loop.",
    )
    parser.add_argument(
        "--check-delay",
        type=int,
        default=CHECK_DELAY,
        help="Seconds between result checks after all local batches are queued.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Optional random seed for reproducible map choices.",
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=1,
        help=(
            "Split global five-minute batch slots across this many runners. Use "
            "the same value on every machine."
        ),
    )
    parser.add_argument(
        "--shard-index",
        type=int,
        default=0,
        help="Zero-based shard index for this runner.",
    )
    parser.add_argument(
        "--no-restore-active",
        action="store_true",
        help="Do not reactivate the first compared version before exit.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not args.continuous and args.batches <= 0:
        raise SystemExit("--batches must be positive unless --continuous is used")
    if args.delay < BATCH_DELAY:
        raise SystemExit(
            f"--delay must be at least {BATCH_DELAY} seconds to stay under the "
            "four-unrated-games-per-five-minutes schedule."
        )
    if args.initial_delay < 0:
        raise SystemExit("--initial-delay must not be negative")
    if args.check_delay <= 0:
        raise SystemExit("--check-delay must be positive")
    if args.shard_count <= 0:
        raise SystemExit("--shard-count must be positive")
    if args.shard_index < 0 or args.shard_index >= args.shard_count:
        raise SystemExit("--shard-index must be in [0, shard-count)")


def version_number(version: str) -> str:
    version = version.strip()
    if version.lower().startswith("v"):
        version = version[1:]
    if not version.isdigit():
        raise ValueError(f"Invalid submission version {version!r}")
    return version


def normalized_version(version: str) -> str:
    return f"v{version_number(version)}"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = int(time.time())
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def ensure_maps_config() -> None:
    if MAPS_FILE.exists() and read_lines(MAPS_FILE):
        return
    MAPS_FILE.write_text(
        "\n".join(DEFAULT_MAP_POOL) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote default random map pool to {MAPS_FILE}")


def load_maps() -> list[str]:
    configured = read_lines(MAPS_FILE)
    maps = configured or list(DEFAULT_MAP_POOL)
    valid_maps = {p.stem for p in MAPS_DIR.glob("*.map26")}
    missing = [map_name for map_name in maps if map_name not in valid_maps]
    if missing:
        raise SystemExit(
            "Unknown map(s) in version comparison pool: "
            + ", ".join(missing)
            + f"\nEdit {MAPS_FILE} or add matching .map26 files."
        )
    if not maps:
        raise SystemExit(f"No maps configured. Fill {MAPS_FILE}.")
    return maps


def load_opponents() -> dict[str, str]:
    all_teams: dict[str, dict] = load_json(TEAM_LIST_FILE)
    name_to_id = {info["name"]: tid for tid, info in all_teams.items()}

    opponents: dict[str, str] = {}
    for entry in read_lines(REQUEST_TEAMS_FILE):
        team_id = entry if entry in all_teams else name_to_id.get(entry)
        if team_id is None:
            print(f"  WARN: unknown team {entry!r}; skipping.")
            continue
        team_name = all_teams[team_id]["name"]
        if team_name == TEAM_NAME:
            continue
        opponents[team_id] = team_name
    if not opponents:
        raise SystemExit(
            f"No opponents loaded. Run process_ladder.py and fill {REQUEST_TEAMS_FILE}."
        )
    return opponents


def make_runner_id() -> str:
    host = re.sub(r"[^A-Za-z0-9_.-]+", "-", socket.gethostname()).strip("-")
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{host}_{os.getpid()}_{now}"


def default_results_path(runner_id: str) -> Path:
    now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return RESULTS_DIR / f"version_compare_{now}_{runner_id}.json"


def activate_submission(version: str) -> None:
    print(f"Activating {version}...")
    result = subprocess.run(
        ["cambc", "submission", "activate", version_number(version)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def queue_match(opponent_id: str, map_name: str) -> tuple[str | None, str | None]:
    result = subprocess.run(
        ["cambc", "match", "unrated", opponent_id, "--map", map_name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    match = re.search(r"Match ID: ([0-9a-f-]+)", result.stdout)
    if match:
        return match.group(1), None
    error = result.stdout.strip() or result.stderr.strip() or "unknown cambc error"
    print(f"  Could not queue: {error}")
    return None, error


def resolve_map_name(name: str, valid_maps: set[str]) -> str | None:
    if name in valid_maps:
        return name
    stem = name.rstrip("\ufffd\u2026")
    if not stem:
        return None
    candidates = [map_name for map_name in valid_maps if map_name.startswith(stem)]
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
    if "Status:  complete" not in output:
        return None

    valid_maps = {p.stem for p in MAPS_DIR.glob("*.map26")}
    games: list[dict] = []
    for line in output.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) != 5 or not cells[0].isdigit():
            continue
        raw_map = cells[1]
        map_name = resolve_map_name(raw_map, valid_maps) or raw_map
        games.append(
            {
                "map": map_name,
                "win": TEAM_NAME in cells[2],
                "condition": cells[3],
                "turns": int(cells[4]),
                "time": int(time.time()),
            }
        )
    return games


def initial_results(
    runner_id: str,
    versions: list[str],
    maps: list[str],
    opponents: dict[str, str],
    args: argparse.Namespace,
) -> dict:
    return {
        "schema_version": 2,
        "mode": "version_compare_batches",
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
        "runner_id": runner_id,
        "team_name": TEAM_NAME,
        "versions": versions,
        "maps": maps,
        "opponents": opponents,
        "batch_delay_seconds": args.delay,
        "check_delay_seconds": args.check_delay,
        "shard_count": args.shard_count,
        "shard_index": args.shard_index,
        "next_global_batch_index": 0,
        "local_batches_queued": 0,
        "batches": {},
        "matches": {},
    }


def restore_run_settings(
    args: argparse.Namespace,
    results: dict,
    versions: list[str],
    maps: list[str],
    opponents: dict[str, str],
) -> tuple[list[str], list[str], dict[str, str]]:
    versions = results.get("versions", versions)
    maps = results.get("maps", maps)
    opponents = results.get("opponents", opponents)
    args.shard_count = results.get("shard_count", args.shard_count)
    args.shard_index = results.get("shard_index", args.shard_index)
    args.delay = results.get("batch_delay_seconds", args.delay)
    args.check_delay = results.get("check_delay_seconds", args.check_delay)
    return versions, maps, opponents


def batch_key(runner_id: str, global_batch_index: int) -> str:
    return f"{runner_id}:batch:{global_batch_index}"


def match_key(
    runner_id: str,
    global_batch_index: int,
    version: str,
    opponent_id: str,
    map_name: str,
) -> str:
    return f"{runner_id}:batch:{global_batch_index}:{version}:{opponent_id}:{map_name}"


def owns_batch(global_batch_index: int, shard_count: int, shard_index: int) -> bool:
    return global_batch_index % shard_count == shard_index


def choose_opponent(
    opponents: dict[str, str],
    global_batch_index: int,
) -> tuple[str, str]:
    items = list(opponents.items())
    return items[global_batch_index % len(items)]


def local_batches_queued(results: dict, runner_id: str) -> int:
    saved = results.get("local_batches_queued")
    if isinstance(saved, int):
        return saved
    return sum(
        1
        for batch in results.get("batches", {}).values()
        if batch.get("runner_id") == runner_id
    )


def update_batch_statuses(results: dict) -> None:
    matches = results.setdefault("matches", {})
    for batch in results.setdefault("batches", {}).values():
        match_keys = list(batch.get("matches", {}).values())
        if not match_keys:
            continue
        statuses = [matches.get(key, {}).get("status") for key in match_keys]
        if all(status == "complete" for status in statuses):
            batch["status"] = "complete"
            batch["completed_at"] = max(
                matches[key].get("completed_at", 0)
                for key in match_keys
                if key in matches
            )
        elif any(status == "queue_failed" for status in statuses):
            batch["status"] = "partial_failed"
        else:
            batch["status"] = "queued"


def check_pending(results_path: Path, results: dict) -> None:
    matches = results.setdefault("matches", {})
    pending = [
        (key, entry)
        for key, entry in matches.items()
        if entry.get("status") == "queued" and entry.get("match_id")
    ]
    for key, entry in pending:
        print(
            f"Checking {entry['match_id']} "
            f"{entry['version']} vs {entry['opponent_name']}..."
        )
        games = check_match(entry["match_id"])
        if games is None:
            continue
        entry["status"] = "complete"
        entry["completed_at"] = int(time.time())
        entry["games"] = games
        print(f"  Complete: {len(games)} game(s)")
        update_batch_statuses(results)
        save_json(results_path, results)


def queue_batch(
    results_path: Path,
    results: dict,
    runner_id: str,
    versions: list[str],
    maps: list[str],
    opponents: dict[str, str],
    rng: random.Random,
    global_batch_index: int,
) -> None:
    map_name = rng.choice(maps)
    opponent_id, opponent_name = choose_opponent(opponents, global_batch_index)
    key = batch_key(runner_id, global_batch_index)
    batches = results.setdefault("batches", {})
    matches = results.setdefault("matches", {})

    if key in batches:
        print(f"Batch {global_batch_index} is already present; skipping queue.")
        return

    batch = {
        "batch_key": key,
        "runner_id": runner_id,
        "global_batch_index": global_batch_index,
        "map": map_name,
        "opponent_id": opponent_id,
        "opponent_name": opponent_name,
        "versions": versions,
        "status": "queued",
        "queued_at": int(time.time()),
        "completed_at": None,
        "matches": {},
    }
    batches[key] = batch
    print(
        f"Queueing batch {global_batch_index}: map={map_name}, "
        f"opponent={opponent_name}, versions={', '.join(versions)}"
    )
    save_json(results_path, results)

    for version in versions:
        activate_submission(version)
        key_for_match = match_key(
            runner_id,
            global_batch_index,
            version,
            opponent_id,
            map_name,
        )
        print(f"  Queuing {version} vs {opponent_name} on {map_name}...")
        match_id, error = queue_match(opponent_id, map_name)
        entry = {
            "task_key": key_for_match,
            "batch_key": key,
            "runner_id": runner_id,
            "global_batch_index": global_batch_index,
            "version": version,
            "version_number": version_number(version),
            "opponent_id": opponent_id,
            "opponent_name": opponent_name,
            "map": map_name,
            "maps": [map_name],
            "match_id": match_id,
            "status": "queued" if match_id else "queue_failed",
            "error": error,
            "queued_at": int(time.time()),
            "completed_at": None,
            "games": [],
        }
        matches[key_for_match] = entry
        batch["matches"][version] = key_for_match
        if match_id:
            print(f"    Queued: {match_id}")
        save_json(results_path, results)

    update_batch_statuses(results)
    save_json(results_path, results)


def local_incomplete_count(results: dict, runner_id: str) -> int:
    return sum(
        1
        for key, entry in results.get("matches", {}).items()
        if key.startswith(f"{runner_id}:") and entry.get("status") == "queued"
    )


def run() -> None:
    args = parse_args()
    validate_args(args)
    versions = [normalized_version(v) for v in args.versions.split(",") if v.strip()]
    ensure_maps_config()
    maps = load_maps()
    opponents = load_opponents()

    runner_id = make_runner_id()
    results_path = args.results or default_results_path(runner_id)
    results = load_json(results_path)
    if results:
        runner_id = results.get("runner_id") or runner_id
        versions, maps, opponents = restore_run_settings(
            args,
            results,
            versions,
            maps,
            opponents,
        )
        results.setdefault("batches", {})
        results.setdefault("matches", {})
        results.setdefault("next_global_batch_index", 0)
        results["local_batches_queued"] = local_batches_queued(results, runner_id)
    else:
        results = initial_results(runner_id, versions, maps, opponents, args)

    rng = random.Random(args.seed)
    save_json(results_path, results)

    print(f"Writing results to {results_path}")
    print(
        f"Batch plan: {len(versions)} games every {args.delay}s, "
        f"versions={', '.join(versions)}, map_pool={maps}"
    )
    print(
        f"Shard: {args.shard_index}/{args.shard_count}; "
        f"local target={'continuous' if args.continuous else args.batches}"
    )

    if args.initial_delay:
        print(f"Initial delay: sleeping {args.initial_delay}s.")
        time.sleep(args.initial_delay)

    try:
        while True:
            check_pending(results_path, results)

            queued_count = local_batches_queued(results, runner_id)
            if not args.continuous and queued_count >= args.batches:
                incomplete = local_incomplete_count(results, runner_id)
                if incomplete == 0:
                    print("All local version comparison batches are complete.")
                    break
                print(f"Waiting on {incomplete} queued local match(es).")
                time.sleep(args.check_delay)
                continue

            global_batch_index = int(results.get("next_global_batch_index", 0))
            results["next_global_batch_index"] = global_batch_index + 1

            if not owns_batch(global_batch_index, args.shard_count, args.shard_index):
                print(
                    f"Skipping global batch slot {global_batch_index} for shard "
                    f"{args.shard_index}/{args.shard_count}; sleeping {args.delay}s."
                )
                save_json(results_path, results)
                time.sleep(args.delay)
                continue

            queue_batch(
                results_path,
                results,
                runner_id,
                versions,
                maps,
                opponents,
                rng,
                global_batch_index,
            )
            next_queued_count = queued_count + 1
            results["local_batches_queued"] = next_queued_count
            save_json(results_path, results)
            if not args.continuous and next_queued_count >= args.batches:
                print(
                    f"Queued local target; checking pending matches every "
                    f"{args.check_delay}s."
                )
                time.sleep(args.check_delay)
            else:
                print(f"Sleeping {args.delay}s before the next global batch slot.")
                time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\nStopped. Re-run with --results to resume this file.")
        save_json(results_path, results)
    finally:
        if not args.no_restore_active and versions:
            try:
                activate_submission(versions[0])
            except Exception as exc:
                print(f"Could not restore active submission to {versions[0]}: {exc}")


if __name__ == "__main__":
    run()
