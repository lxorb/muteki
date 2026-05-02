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
BATCH_DELAY = 600
CHECK_DELAY = 60
RESULT_MODE = "version_compare_five_map_batches"

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
            "unrated match per version on the same five-map set, then waits ten "
            "minutes before the next batch."
        )
    )
    parser.add_argument(
        "--results",
        type=Path,
        help=(
            "Result JSON to write or resume. Defaults to the latest compatible "
            "result file, or a new timestamped file if none exists."
        ),
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Start a new timestamped result file instead of auto-resuming latest.",
    )
    parser.add_argument(
        "--versions",
        default=",".join(DEFAULT_VERSIONS),
        help="Comma-separated submission versions. Default: %(default)s",
    )
    parser.add_argument(
        "--max-batches",
        "--batches",
        type=int,
        default=None,
        dest="max_batches",
        help=(
            "Optional safety limit for local batches. Omit this for start/stop usage."
        ),
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Deprecated; continuous start/stop mode is now the default.",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=BATCH_DELAY,
        help="Seconds between global batch slots. Keep at 600 for the unrated cap.",
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
            "Split global ten-minute batch slots across this many runners. Use "
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
    if args.results and args.fresh:
        raise SystemExit("Use either --results or --fresh, not both")
    if args.max_batches is not None and args.max_batches <= 0:
        raise SystemExit("--max-batches must be positive")
    if args.delay < BATCH_DELAY:
        raise SystemExit(
            f"--delay must be at least {BATCH_DELAY} seconds to stay under the "
            "four-unrated-matches-per-ten-minutes schedule."
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
    if len(maps) < 5:
        raise SystemExit(f"Expected at least 5 maps in {MAPS_FILE}, got {len(maps)}.")
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


def latest_compatible_results_path() -> Path | None:
    latest_path: Path | None = None
    latest_mtime = -1.0
    for path in RESULTS_DIR.glob("version_compare_*.json"):
        try:
            data = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("mode") != RESULT_MODE:
            continue
        mtime = path.stat().st_mtime
        if mtime > latest_mtime:
            latest_path = path
            latest_mtime = mtime
    return latest_path


def choose_results_path(args: argparse.Namespace, runner_id: str) -> Path:
    if args.results:
        return args.results
    if not args.fresh:
        latest_path = latest_compatible_results_path()
        if latest_path is not None:
            print(f"Auto-resuming latest result file: {latest_path}")
            return latest_path
    return default_results_path(runner_id)


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


def queue_match(opponent_id: str, maps: list[str]) -> tuple[str | None, str | None]:
    cmd = ["cambc", "match", "unrated", opponent_id]
    for map_name in maps:
        cmd += ["--map", map_name]
    result = subprocess.run(
        cmd,
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
        "schema_version": 3,
        "mode": RESULT_MODE,
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
    args.delay = max(int(results.get("batch_delay_seconds", args.delay)), BATCH_DELAY)
    args.check_delay = results.get("check_delay_seconds", args.check_delay)
    return versions, maps, opponents


def batch_key(runner_id: str, global_batch_index: int) -> str:
    return f"{runner_id}:batch:{global_batch_index}"


def match_key(
    runner_id: str,
    global_batch_index: int,
    version: str,
    opponent_id: str,
    maps: list[str],
) -> str:
    map_slug = "-".join(maps)
    return f"{runner_id}:batch:{global_batch_index}:{version}:{opponent_id}:{map_slug}"


def owns_batch(global_batch_index: int, shard_count: int, shard_index: int) -> bool:
    return global_batch_index % shard_count == shard_index


def choose_opponent(
    opponents: dict[str, str],
    global_batch_index: int,
) -> tuple[str, str]:
    items = list(opponents.items())
    return items[global_batch_index % len(items)]


def choose_batch_maps(maps: list[str], rng: random.Random) -> list[str]:
    if len(maps) == 5:
        return list(maps)
    return rng.sample(maps, 5)


def local_batches_queued(results: dict, runner_id: str) -> int:
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
        elif any(status in {"pending_queue", "queue_failed"} for status in statuses):
            batch["status"] = "pending_queue"
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


def queue_pending_match(
    results_path: Path,
    results: dict,
    entry: dict,
) -> bool:
    activate_submission(entry["version"])
    print(
        f"  Queuing {entry['version']} vs {entry['opponent_name']} "
        f"on {entry['maps']}..."
    )
    match_id, error = queue_match(entry["opponent_id"], entry["maps"])
    entry["queue_attempts"] = int(entry.get("queue_attempts", 0)) + 1
    entry["last_queue_attempt_at"] = int(time.time())
    if match_id:
        entry["match_id"] = match_id
        entry["status"] = "queued"
        entry["error"] = None
        entry["queued_at"] = int(time.time())
        print(f"    Queued: {match_id}")
        update_batch_statuses(results)
        save_json(results_path, results)
        return True

    entry["match_id"] = None
    entry["status"] = "pending_queue"
    entry["error"] = error
    update_batch_statuses(results)
    save_json(results_path, results)
    return False


def create_batch(
    results_path: Path,
    results: dict,
    runner_id: str,
    versions: list[str],
    maps: list[str],
    opponents: dict[str, str],
    rng: random.Random,
    global_batch_index: int,
) -> dict:
    batch_maps = choose_batch_maps(maps, rng)
    opponent_id, opponent_name = choose_opponent(opponents, global_batch_index)
    key = batch_key(runner_id, global_batch_index)
    batches = results.setdefault("batches", {})
    matches = results.setdefault("matches", {})

    batch = {
        "batch_key": key,
        "runner_id": runner_id,
        "global_batch_index": global_batch_index,
        "maps": batch_maps,
        "opponent_id": opponent_id,
        "opponent_name": opponent_name,
        "versions": versions,
        "status": "pending_queue",
        "created_at": int(time.time()),
        "queued_at": None,
        "completed_at": None,
        "matches": {},
    }
    batches[key] = batch
    print(
        f"Created batch {global_batch_index}: maps={batch_maps}, "
        f"opponent={opponent_name}, versions={', '.join(versions)}"
    )

    for version in versions:
        key_for_match = match_key(
            runner_id,
            global_batch_index,
            version,
            opponent_id,
            batch_maps,
        )
        matches[key_for_match] = {
            "task_key": key_for_match,
            "batch_key": key,
            "runner_id": runner_id,
            "global_batch_index": global_batch_index,
            "version": version,
            "version_number": version_number(version),
            "opponent_id": opponent_id,
            "opponent_name": opponent_name,
            "maps": batch_maps,
            "match_id": None,
            "status": "pending_queue",
            "error": None,
            "queue_attempts": 0,
            "last_queue_attempt_at": None,
            "queued_at": None,
            "completed_at": None,
            "games": [],
        }
        batch["matches"][version] = key_for_match

    save_json(results_path, results)
    return batch


def sorted_local_batches(results: dict, runner_id: str) -> list[dict]:
    return sorted(
        (
            batch
            for batch in results.get("batches", {}).values()
            if batch.get("runner_id") == runner_id
        ),
        key=lambda batch: int(batch.get("global_batch_index", 0)),
    )


def next_pending_queue_match(results: dict, runner_id: str) -> dict | None:
    matches = results.setdefault("matches", {})
    for batch in sorted_local_batches(results, runner_id):
        version_to_key = batch.get("matches", {})
        for version in batch.get("versions", []):
            entry = matches.get(version_to_key.get(version))
            if not entry:
                continue
            if entry.get("match_id"):
                continue
            if entry.get("status") in {"pending_queue", "queue_failed"}:
                return entry
    return None


def queue_pending_matches_until_blocked(
    results_path: Path,
    results: dict,
    runner_id: str,
) -> bool:
    queued_any = False
    while True:
        entry = next_pending_queue_match(results, runner_id)
        if entry is None:
            return queued_any
        if not queue_pending_match(results_path, results, entry):
            return queued_any
        queued_any = True


def local_incomplete_count(results: dict, runner_id: str) -> int:
    return sum(
        1
        for key, entry in results.get("matches", {}).items()
        if key.startswith(f"{runner_id}:")
        and entry.get("status") in {"pending_queue", "queue_failed", "queued"}
    )


def run() -> None:
    args = parse_args()
    validate_args(args)
    versions = [normalized_version(v) for v in args.versions.split(",") if v.strip()]
    ensure_maps_config()
    maps = load_maps()
    opponents = load_opponents()

    runner_id = make_runner_id()
    results_path = choose_results_path(args, runner_id)
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

    validate_args(args)
    results["batch_delay_seconds"] = args.delay
    results["check_delay_seconds"] = args.check_delay
    rng = random.Random(args.seed)
    save_json(results_path, results)

    print(f"Writing results to {results_path}")
    print(
        f"Batch plan: {len(versions)} five-map matches every {args.delay}s, "
        f"versions={', '.join(versions)}, map_pool={maps}"
    )
    print(
        f"Shard: {args.shard_index}/{args.shard_count}; "
        f"local target={args.max_batches if args.max_batches is not None else 'start/stop'}"
    )

    if args.initial_delay:
        print(f"Initial delay: sleeping {args.initial_delay}s.")
        time.sleep(args.initial_delay)

    try:
        while True:
            check_pending(results_path, results)

            queued_count = local_batches_queued(results, runner_id)
            if args.max_batches is not None and queued_count >= args.max_batches:
                incomplete = local_incomplete_count(results, runner_id)
                if incomplete == 0:
                    print("All local version comparison batches are complete.")
                    break
                pending_queue = next_pending_queue_match(results, runner_id)
                if pending_queue is not None:
                    print(
                        "Retrying unqueued match before checking completed games."
                    )
                    queue_pending_matches_until_blocked(
                        results_path,
                        results,
                        runner_id,
                    )
                    time.sleep(args.delay)
                else:
                    print(f"Waiting on {incomplete} queued local match(es).")
                    time.sleep(args.check_delay)
                continue

            pending_queue = next_pending_queue_match(results, runner_id)
            if pending_queue is not None:
                print("Continuing pending queue work before creating a new batch.")
                queue_pending_matches_until_blocked(
                    results_path,
                    results,
                    runner_id,
                )
                print(f"Sleeping {args.delay}s before the next queue attempt.")
                time.sleep(args.delay)
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

            create_batch(
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
            queue_pending_matches_until_blocked(
                results_path,
                results,
                runner_id,
            )
            save_json(results_path, results)
            if args.max_batches is not None and next_queued_count >= args.max_batches:
                print(
                    f"Queued local target; checking pending matches every "
                    f"{args.check_delay}s."
                )
                time.sleep(args.check_delay)
            else:
                print(f"Sleeping {args.delay}s before the next global batch slot.")
                time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\nStopped. Re-run the same command to auto-resume this file.")
        save_json(results_path, results)
    finally:
        if not args.no_restore_active and versions:
            try:
                activate_submission(versions[0])
            except Exception as exc:
                print(f"Could not restore active submission to {versions[0]}: {exc}")


if __name__ == "__main__":
    run()
