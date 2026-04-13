from __future__ import annotations

import argparse
import heapq
import json
from collections import defaultdict
from pathlib import Path

from map26_parser import parse_map26_file

ENV_EMPTY = 0
ENV_WALL = 1
ENV_ORE_TITANIUM = 2
ENV_ORE_AXIONITE = 3

TILE_TYPE_INACTIVE = 0
TILE_TYPE_EMPTY = 1
TILE_TYPE_WALL = 2
TILE_TYPE_TITANIUM = 3
TILE_TYPE_AXIONITE = 4
TILE_TYPE_CORE = 5

INDEX_STRIDE = 50
MAX_MAP_SIZE = INDEX_STRIDE * INDEX_STRIDE
INF_DIST = 10**9


def to_index(x: int, y: int) -> int:
    return x * INDEX_STRIDE + y


def core_footprint(center: dict[str, int]) -> list[tuple[int, int]]:
    return [
        (center["x"] + dx, center["y"] + dy)
        for dx in range(-1, 2)
        for dy in range(-1, 2)
    ]


def build_tile_type_by_index(
    width: int,
    height: int,
    rows: list[list[int]],
    core_a_center: dict[str, int],
    core_b_center: dict[str, int],
) -> list[str]:
    tile_type_by_index = [TILE_TYPE_INACTIVE] * MAX_MAP_SIZE
    core_a_positions = set(core_footprint(core_a_center))
    core_b_positions = set(core_footprint(core_b_center))

    for x in range(width):
        for y in range(height):
            idx = to_index(x, y)
            pos = (x, y)
            if pos in core_a_positions:
                tile_type_by_index[idx] = TILE_TYPE_CORE
                continue
            if pos in core_b_positions:
                tile_type_by_index[idx] = TILE_TYPE_CORE
                continue

            env = rows[y][x]
            if env == ENV_WALL:
                tile_type_by_index[idx] = TILE_TYPE_WALL
            elif env == ENV_ORE_TITANIUM:
                tile_type_by_index[idx] = TILE_TYPE_TITANIUM
            elif env == ENV_ORE_AXIONITE:
                tile_type_by_index[idx] = TILE_TYPE_AXIONITE
            else:
                tile_type_by_index[idx] = TILE_TYPE_EMPTY

    return tile_type_by_index


def build_core_distance_by_index(
    width: int,
    height: int,
    tile_type_by_index: list[str],
    core_center: dict[str, int],
) -> list[int]:
    distances = [INF_DIST] * MAX_MAP_SIZE
    frontier: list[tuple[int, int]] = []

    for x, y in core_footprint(core_center):
        if not (0 <= x < width and 0 <= y < height):
            continue
        idx = to_index(x, y)
        distances[idx] = 0
        heapq.heappush(frontier, (0, idx))

    while frontier:
        current_dist, current_idx = heapq.heappop(frontier)
        if current_dist != distances[current_idx]:
            continue

        current_x = current_idx // INDEX_STRIDE
        current_y = current_idx % INDEX_STRIDE
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx = current_x + dx
                ny = current_y + dy
                if not (0 <= nx < width and 0 <= ny < height):
                    continue

                neighbor_idx = to_index(nx, ny)
                if tile_type_by_index[neighbor_idx] == TILE_TYPE_WALL:
                    continue

                step_cost = 1 if dx == 0 or dy == 0 else 2
                next_dist = current_dist + step_cost
                if next_dist >= distances[neighbor_idx]:
                    continue
                distances[neighbor_idx] = next_dist
                heapq.heappush(frontier, (next_dist, neighbor_idx))

    return distances


def build_sorted_resource_indices(
    tile_type_by_index: list[str],
    distances: list[int],
    resource_type: int,
) -> list[int]:
    resource_indices = [
        idx
        for idx, tile_type in enumerate(tile_type_by_index)
        if tile_type == resource_type
    ]
    resource_indices.sort(key=lambda idx: (distances[idx], idx))
    return resource_indices


def build_metadata(map_path: Path) -> dict:
    decoded = parse_map26_file(map_path)
    core_by_team = {
        core.team_name: {
            "x": core.position.x,
            "y": core.position.y,
        }
        for core in decoded.cores
    }
    core_a_center = core_by_team.get("TEAM_A")
    core_b_center = core_by_team.get("TEAM_B")
    if core_a_center is None or core_b_center is None:
        raise ValueError(f"Expected both TEAM_A and TEAM_B cores in {map_path}")

    tile_type_by_index = build_tile_type_by_index(
        decoded.width,
        decoded.height,
        decoded.rows,
        core_a_center,
        core_b_center,
    )
    core_a_dist_by_index = build_core_distance_by_index(
        decoded.width,
        decoded.height,
        tile_type_by_index,
        core_a_center,
    )
    core_b_dist_by_index = build_core_distance_by_index(
        decoded.width,
        decoded.height,
        tile_type_by_index,
        core_b_center,
    )

    return {
        "width": decoded.width,
        "height": decoded.height,
        "core_a_center": core_a_center,
        "core_b_center": core_b_center,
        "titanium_by_core_a_dist": build_sorted_resource_indices(
            tile_type_by_index,
            core_a_dist_by_index,
            TILE_TYPE_TITANIUM,
        ),
        "titanium_by_core_b_dist": build_sorted_resource_indices(
            tile_type_by_index,
            core_b_dist_by_index,
            TILE_TYPE_TITANIUM,
        ),
        "axionite_by_core_a_dist": build_sorted_resource_indices(
            tile_type_by_index,
            core_a_dist_by_index,
            TILE_TYPE_AXIONITE,
        ),
        "axionite_by_core_b_dist": build_sorted_resource_indices(
            tile_type_by_index,
            core_b_dist_by_index,
            TILE_TYPE_AXIONITE,
        ),
        "tile_type_by_index": tile_type_by_index,
        "core_a_dist_by_index": core_a_dist_by_index,
        "core_b_dist_by_index": core_b_dist_by_index,
    }


def format_fast_inference_key(
    width: int,
    height: int,
    core_center: dict[str, int],
) -> str:
    return f"({width}, {height}, ({core_center['x']}, {core_center['y']}))"


def write_fast_map_inference(
    maps_root: Path,
    metadata_by_map_path: dict[Path, dict],
) -> Path:
    repo_root = maps_root.parent
    bot_root = repo_root / "bots" / "uewomirudake"
    candidates_by_key: dict[str, list[str]] = defaultdict(list)

    for map_path, metadata in metadata_by_map_path.items():
        relative_map_path = map_path.relative_to(repo_root).as_posix()
        width = metadata["width"]
        height = metadata["height"]
        for core_key in ("core_a_center", "core_b_center"):
            core_center = metadata[core_key]
            key = format_fast_inference_key(width, height, core_center)
            candidates_by_key[key].append(relative_map_path)

    fast_map_inference = {
        key: sorted(values) for key, values in sorted(candidates_by_key.items())
    }
    bot_root.mkdir(parents=True, exist_ok=True)
    output_path = bot_root / "fast_map_inference.json"
    output_path.write_text(
        json.dumps(fast_map_inference, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def should_process_map(map_path: Path, maps_root: Path) -> bool:
    try:
        relative_parts = map_path.relative_to(maps_root).parts
    except ValueError:
        return True
    return "custom" not in relative_parts


def write_metadata_for_maps(maps_root: Path) -> tuple[list[Path], Path]:
    repo_root = maps_root.parent
    parsed_maps_root = repo_root / "bots" / "uewomirudake" / "parsed_maps"
    parsed_maps_root.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    metadata_by_map_path: dict[Path, dict] = {}
    for map_path in sorted(maps_root.rglob("*.map26")):
        if not should_process_map(map_path, maps_root):
            continue
        metadata = build_metadata(map_path)
        relative_map_path = map_path.relative_to(maps_root)
        output_path = (parsed_maps_root / relative_map_path).with_suffix(".json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        written_paths.append(output_path)
        metadata_by_map_path[map_path] = metadata

    fast_map_inference_path = write_fast_map_inference(maps_root, metadata_by_map_path)
    return written_paths, fast_map_inference_path


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate per-map JSON metadata for every .map26 file"
    )
    parser.add_argument(
        "maps_root",
        nargs="?",
        default=Path("maps"),
        type=Path,
        help="Root folder to scan for .map26 files",
    )
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    written_paths, fast_map_inference_path = write_metadata_for_maps(args.maps_root)
    print(f"Wrote {len(written_paths)} JSON files.")
    for path in written_paths:
        print(path)
    print(fast_map_inference_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
