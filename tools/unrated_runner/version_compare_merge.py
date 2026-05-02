import argparse
import datetime
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR / "results" / "version_compare"
RESULTS_DIR.mkdir(exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge version comparison result JSON files."
    )
    parser.add_argument("output", type=Path, help="Merged result JSON to write.")
    parser.add_argument("inputs", nargs="+", type=Path, help="Input result JSON files.")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def merge_list(existing: list, incoming: list) -> list:
    result = list(existing)
    seen = set(result)
    for item in incoming:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def merge_results(inputs: list[Path]) -> dict:
    merged: dict = {
        "schema_version": 2,
        "mode": "version_compare_batches",
        "created_at": None,
        "updated_at": None,
        "merged_at": int(datetime.datetime.now().timestamp()),
        "runner_id": "merged",
        "team_name": "muteki",
        "versions": [],
        "maps": [],
        "opponents": {},
        "batch_delay_seconds": None,
        "sources": [],
        "batches": {},
        "matches": {},
    }

    match_ids_seen: dict[str, str] = {}
    for input_path in inputs:
        data = load_json(input_path)
        merged["sources"].append(str(input_path))
        if data.get("team_name"):
            merged["team_name"] = data["team_name"]
        merged["versions"] = merge_list(merged["versions"], data.get("versions", []))
        merged["maps"] = merge_list(merged["maps"], data.get("maps", []))
        merged["opponents"].update(data.get("opponents", {}))
        if merged["batch_delay_seconds"] is None:
            merged["batch_delay_seconds"] = data.get("batch_delay_seconds")
        elif data.get("batch_delay_seconds") != merged["batch_delay_seconds"]:
            merged["batch_delay_seconds"] = "mixed"

        created_at = data.get("created_at")
        updated_at = data.get("updated_at")
        if created_at is not None:
            merged["created_at"] = (
                created_at
                if merged["created_at"] is None
                else min(merged["created_at"], created_at)
            )
        if updated_at is not None:
            merged["updated_at"] = (
                updated_at
                if merged["updated_at"] is None
                else max(merged["updated_at"], updated_at)
            )

        for key, entry in data.get("matches", {}).items():
            match_id = entry.get("match_id")
            if match_id:
                existing_key = match_ids_seen.get(match_id)
                if existing_key is not None:
                    existing = merged["matches"][existing_key]
                    if (
                        existing.get("status") != "complete"
                        and entry.get("status") == "complete"
                    ):
                        merged["matches"][existing_key] = entry
                    continue
                match_ids_seen[match_id] = key

            output_key = key
            if output_key in merged["matches"]:
                suffix = 2
                while f"{key}#{suffix}" in merged["matches"]:
                    suffix += 1
                output_key = f"{key}#{suffix}"
            merged["matches"][output_key] = entry

        for key, entry in data.get("batches", {}).items():
            output_key = key
            if output_key in merged["batches"]:
                suffix = 2
                while f"{key}#{suffix}" in merged["batches"]:
                    suffix += 1
                output_key = f"{key}#{suffix}"
            merged["batches"][output_key] = entry

    if merged["created_at"] is None:
        merged["created_at"] = merged["merged_at"]
    if merged["updated_at"] is None:
        merged["updated_at"] = merged["merged_at"]
    return merged


def main() -> None:
    args = parse_args()
    missing = [path for path in args.inputs if not path.exists()]
    if missing:
        raise SystemExit("Missing input file(s): " + ", ".join(str(p) for p in missing))

    merged = merge_results(args.inputs)
    save_json(args.output, merged)
    complete = sum(
        1 for entry in merged["matches"].values() if entry.get("status") == "complete"
    )
    print(
        f"Wrote {args.output} with {complete}/{len(merged['matches'])} complete matches."
    )


if __name__ == "__main__":
    main()
