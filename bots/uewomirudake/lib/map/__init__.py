from array import array
from collections import deque
from collections.abc import Iterable
from enum import Enum
from heapq import heappop, heappush
import json
import math
import marshal
from pathlib import Path
import sys
import time

from cambc import (
    Controller,
    Direction,
    EntityType,
    Environment,
    GameConstants,
    Position,
    Team,
)

from lib.agent.constants import CONVEYOR_ENTITY_TYPES
from lib.agent.time import ALLOCATED_MAP_AND_BOT_TIME_MUS, RoundStopwatch

from lib.map.constants import (
    BUILDER_ACTION_OFFSETS,
    CARDINAL_DIRECTIONS,
    CARDINAL_ORDINAL_DIRECTIONS,
    CORE_DIST_INF,
    DIRECTIONS,
    DISABLE_CORRECT_OWN_CORE_DISTANCE,
    ENABLE_MAP_DETECTION,
    INF_DIST,
    OWN_CORE_DISTANCE_INIT_SETTLE_BUDGET,
    OPPOSITE_ORE_SUPPLY_CHAIN_SEPARATION_INCLUDES_DIAGONALS,
    RESOURCE_TARGET_TYPES,
    SUPPLY_LINK_TYPES,
    WEAPON_TARGET_TYPES,
)
from lib.map.tile import Tile
from lib.map.types import SupplyChainLabel

from lib.debug import Stopwatch


PARSED_TILE_TYPE_INACTIVE = 0
PARSED_TILE_TYPE_EMPTY = 1
PARSED_TILE_TYPE_WALL = 2
PARSED_TILE_TYPE_TITANIUM = 3
PARSED_TILE_TYPE_AXIONITE = 4
PARSED_TILE_TYPE_CORE = 5

MAP_UPDATE_MIN_REMAINING_MUS = 100
PRELOADED_MAP_INDEX_STRIDE = 50
STALE_BUILDER_BOT_PASSABILITY_THRESHOLD = 10

MAP_ENVIRONMENT_OTHER = 0
MAP_ENVIRONMENT_WALL = 1
MAP_ENVIRONMENT_TITANIUM = 2
MAP_ENVIRONMENT_AXIONITE = 3

_SCOUT_SEEN_NEIGHBOR_OFFSETS = (
    *((dx, dy) for dx in range(-1, 2) for dy in range(-1, 2) if dx or dy),
)


def _build_scout_new_vision_offsets_by_direction() -> dict[
    Direction, tuple[tuple[int, int], ...]
]:
    radius_sq = GameConstants.BUILDER_BOT_VISION_RADIUS_SQ
    radius = int(math.sqrt(radius_sq)) + 1
    offsets_by_direction: dict[Direction, tuple[tuple[int, int], ...]] = {}

    for direction in DIRECTIONS:
        step_dx, step_dy = direction.delta()
        offsets: list[tuple[int, int]] = []
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx * dx + dy * dy > radius_sq:
                    continue
                if (
                    (dx + step_dx) * (dx + step_dx)
                    + (dy + step_dy) * (dy + step_dy)
                    <= radius_sq
                ):
                    continue
                offsets.append((dx, dy))
        offsets_by_direction[direction] = tuple(offsets)

    return offsets_by_direction


_SCOUT_NEW_VISION_OFFSETS_BY_DIRECTION = _build_scout_new_vision_offsets_by_direction()


class _TouchedIndexMembership:
    __slots__ = ("marked_by_index", "touched_indices")

    def __init__(self, size: int):
        self.marked_by_index = bytearray(size)
        self.touched_indices: list[int] = []

    def add(self, idx: int) -> None:
        if self.marked_by_index[idx]:
            return
        self.marked_by_index[idx] = 1
        self.touched_indices.append(idx)

    def clear(self) -> None:
        for idx in self.touched_indices:
            self.marked_by_index[idx] = 0
        self.touched_indices.clear()

    def __contains__(self, idx: int) -> bool:
        return bool(self.marked_by_index[idx])


class _TouchedIndexSourceMap:
    __slots__ = ("source_indices_by_target_index", "touched_target_indices")

    def __init__(self, size: int):
        self.source_indices_by_target_index: list[list[int] | None] = [None] * size
        self.touched_target_indices: list[int] = []

    def add(self, target_idx: int, source_idx: int) -> None:
        source_indices = self.source_indices_by_target_index[target_idx]
        if source_indices is None:
            self.source_indices_by_target_index[target_idx] = [source_idx]
            self.touched_target_indices.append(target_idx)
            return
        source_indices.append(source_idx)

    def clear(self) -> None:
        for idx in self.touched_target_indices:
            self.source_indices_by_target_index[idx] = None
        self.touched_target_indices.clear()

    def get(self, target_idx: int, default=None):
        source_indices = self.source_indices_by_target_index[target_idx]
        if source_indices is None:
            return default
        return source_indices


def _iter_existing_parent_roots(path: Path) -> Iterable[Path]:
    try:
        resolved_path = path.resolve()
    except OSError:
        return ()

    if resolved_path.is_file():
        start_path = resolved_path.parent
    else:
        start_path = resolved_path

    return (start_path, *start_path.parents)


def _resolve_bot_root() -> Path:
    candidate_roots: list[Path] = []

    module_file = globals().get("__file__")
    if module_file:
        candidate_roots.extend(_iter_existing_parent_roots(Path(module_file)))

    argv0 = sys.argv[0] if sys.argv else ""
    if argv0:
        candidate_roots.extend(_iter_existing_parent_roots(Path(argv0)))

    candidate_roots.extend(_iter_existing_parent_roots(Path.cwd()))

    seen_roots: set[Path] = set()
    for candidate_root in candidate_roots:
        if candidate_root in seen_roots:
            continue
        seen_roots.add(candidate_root)
        if (
            (candidate_root / "fast_map_inference.json").exists()
            and (candidate_root / "parsed_maps").is_dir()
        ):
            return candidate_root

    return Path.cwd()


_BOT_ROOT = _resolve_bot_root()
_PARSED_MAPS_ROOT = _BOT_ROOT / "parsed_maps"
_FAST_MAP_INFERENCE_PATH = _BOT_ROOT / "fast_map_inference.json"
_PRELOADED_PARSED_MAPS_PATH = _BOT_ROOT / "preloaded_parsed_maps.marshal"

try:
    FAST_MAP_INFERENCE_BY_KEY: dict[str, list[str]] = json.loads(
        _FAST_MAP_INFERENCE_PATH.read_text(encoding="utf-8")
    )
except FileNotFoundError:
    FAST_MAP_INFERENCE_BY_KEY = {}


def _decode_packed_u16_view(data: bytes) -> memoryview:
    return memoryview(data).cast("H")


def _decode_checkpoint_positions(data: bytes) -> tuple[Position, ...]:
    return tuple(
        Position(
            idx // PRELOADED_MAP_INDEX_STRIDE,
            idx % PRELOADED_MAP_INDEX_STRIDE,
        )
        for idx in _decode_packed_u16_view(data)
    )


def _build_runtime_parsed_map_data_from_preloaded(raw_entry: dict) -> dict:
    core_a_center = Position(*raw_entry["core_a_center_xy"])
    core_b_center = Position(*raw_entry["core_b_center_xy"])
    return {
        "core_a_center": core_a_center,
        "core_b_center": core_b_center,
        "tile_type_by_index": raw_entry["tile_type_by_index_bytes"],
        "core_a_dist_by_index": _decode_packed_u16_view(
            raw_entry["core_a_dist_by_index_bytes"]
        ),
        "core_b_dist_by_index": _decode_packed_u16_view(
            raw_entry["core_b_dist_by_index_bytes"]
        ),
        "titanium_by_core_a_dist": _decode_packed_u16_view(
            raw_entry["titanium_by_core_a_dist_bytes"]
        ),
        "titanium_by_core_b_dist": _decode_packed_u16_view(
            raw_entry["titanium_by_core_b_dist_bytes"]
        ),
        "axionite_by_core_a_dist": _decode_packed_u16_view(
            raw_entry["axionite_by_core_a_dist_bytes"]
        ),
        "axionite_by_core_b_dist": _decode_packed_u16_view(
            raw_entry["axionite_by_core_b_dist_bytes"]
        ),
        "core_a_to_core_b_checkpoints": _decode_checkpoint_positions(
            raw_entry["core_a_to_core_b_checkpoint_index_bytes"]
        ),
        "core_b_to_core_a_checkpoints": _decode_checkpoint_positions(
            raw_entry["core_b_to_core_a_checkpoint_index_bytes"]
        ),
    }


def _build_runtime_parsed_map_data_from_legacy(raw_entry: dict) -> dict:
    return {
        "core_a_center": Position(
            raw_entry["core_a_center"]["x"],
            raw_entry["core_a_center"]["y"],
        ),
        "core_b_center": Position(
            raw_entry["core_b_center"]["x"],
            raw_entry["core_b_center"]["y"],
        ),
        "tile_type_by_index": raw_entry["tile_type_by_index"],
        "core_a_dist_by_index": raw_entry["core_a_dist_by_index"],
        "core_b_dist_by_index": raw_entry["core_b_dist_by_index"],
        "titanium_by_core_a_dist": raw_entry["titanium_by_core_a_dist"],
        "titanium_by_core_b_dist": raw_entry["titanium_by_core_b_dist"],
        "axionite_by_core_a_dist": raw_entry["axionite_by_core_a_dist"],
        "axionite_by_core_b_dist": raw_entry["axionite_by_core_b_dist"],
        "core_a_to_core_b_checkpoints": tuple(
            Position(pos["x"], pos["y"])
            for pos in raw_entry["core_a_to_core_b_checkpoints"]
        ),
        "core_b_to_core_a_checkpoints": tuple(
            Position(pos["x"], pos["y"])
            for pos in raw_entry["core_b_to_core_a_checkpoints"]
        ),
    }


try:
    PRELOADED_PARSED_MAP_DATA_BY_PATH: dict[str, dict] = {
        map_path: _build_runtime_parsed_map_data_from_preloaded(raw_entry)
        for map_path, raw_entry in marshal.loads(
            _PRELOADED_PARSED_MAPS_PATH.read_bytes()
        ).items()
    }
except FileNotFoundError:
    PRELOADED_PARSED_MAP_DATA_BY_PATH = {}


def u_format_fast_inference_key(
    width: int,
    height: int,
    core_center: Position,
) -> str:
    return f"({width}, {height}, ({core_center.x}, {core_center.y}))"


class SymmetryMode(Enum):
    ROTATION = "rotation"
    MIRROR_X = "mirror_x"
    MIRROR_Y = "mirror_y"


class Map:
    INITIAL_HEIGHT = 50
    INITIAL_WIDTH = 50
    INITIAL_MAP_SIZE = INITIAL_WIDTH * INITIAL_HEIGHT
    INDEX_STRIDE = INITIAL_HEIGHT
    MAX_NEIGHBOR_COUNT = 8
    MAX_CARDINAL_NEIGHBOR_COUNT = 4
    MAX_BUILDER_ACTION_TARGET_COUNT = len(BUILDER_ACTION_OFFSETS)
    MAX_CORE_FOOTPRINT_TARGET_COUNT = 9
    DIRECTION_SLOT_COUNT = len(DIRECTIONS)
    MARKER_ENTITY_TYPE = getattr(EntityType, "MARKER", None)

    def __init__(self, round_stopwatch: RoundStopwatch):
        self.ct: Controller | None = None
        self.round_stopwatch: RoundStopwatch = round_stopwatch
        self.width = self.INITIAL_WIDTH
        self.height = self.INITIAL_HEIGHT
        self.tile_count = self.INITIAL_MAP_SIZE
        self.own_team: Team | None = None
        self.enemy_team: Team | None = None
        self.current_round = -1
        self.current_pos = Position(0, 0)
        self.turns_on_current_tile = 0
        self.titanium = 0
        self.axionite = 0
        self.compute_dist_to_self = False
        self._first_round_initialized = False
        self._direction_slot_by_direction = {
            direction: slot for slot, direction in enumerate(DIRECTIONS)
        }
        self.index_x_by_index = array("B", [0]) * self.INITIAL_MAP_SIZE
        self.index_y_by_index = array("B", [0]) * self.INITIAL_MAP_SIZE
        self.last_seen_turn_by_index = array("i", [-1]) * self.INITIAL_MAP_SIZE
        self.last_visited_turn_by_index = array("i", [-1]) * self.INITIAL_MAP_SIZE
        self.scout_seen_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.environment_code_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.vision_reachable_turn_by_index = array("I", [0]) * self.INITIAL_MAP_SIZE
        self.dist_to_self_by_index = array("H", [0]) * self.INITIAL_MAP_SIZE
        self.vision_first_step_by_index = array("h", [-1]) * self.INITIAL_MAP_SIZE
        self.dist_to_self_epoch_by_index = array("I", [0]) * self.INITIAL_MAP_SIZE
        self.dist_to_self_epoch = 0
        self.last_dist_to_self_source_idx: int | None = None
        self.vision_max_dist_to_self_this_turn = 0
        self.found_vision_reachable_titanium_this_turn = False
        self.found_vision_reachable_axionite_this_turn = False
        self.is_caged = False
        self.stale_builder_bot_passability_threshold = (
            STALE_BUILDER_BOT_PASSABILITY_THRESHOLD
        )
        self.own_core_dist_by_index = (
            array("H", [CORE_DIST_INF]) * self.INITIAL_MAP_SIZE
        )
        self.core_inf_distances_by_index = (
            array("H", [CORE_DIST_INF]) * self.INITIAL_MAP_SIZE
        )
        self.core_distance_passable_by_index = bytearray([1]) * self.INITIAL_MAP_SIZE
        self.intrinsic_passable_by_index = bytearray([1]) * self.INITIAL_MAP_SIZE
        self.bot_present_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.builder_bot_stationary_turns_by_index = (
            array("H", [0]) * self.INITIAL_MAP_SIZE
        )
        self.enemy_turret_target_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.enemy_gunner_ray_first_target_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.enemy_spin_gunner_ray_first_target_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.core_distance_dirty_indices: list[int] = []
        self.core_distance_dirty_mark_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.enemy_gunner_ray_first_target_touched_indices: list[int] = []
        self.enemy_spin_gunner_ray_first_target_touched_indices: list[int] = []
        self.core_distance_enqueued_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.core_distance_seed_enqueued_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.own_core_source_indices: tuple[int, ...] = ()
        self.enemy_core_source_indices: tuple[int, ...] = ()
        self.own_core_source_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.enemy_core_source_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.own_core_dist_initialized = False
        self.own_core_dist_init_started = False
        self.own_core_dist_exact_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.own_core_dist_init_buckets: tuple[list[int], list[int], list[int]] = (
            [],
            [],
            [],
        )
        self.own_core_dist_init_bucket_heads = [0, 0, 0]
        self.own_core_dist_init_current_dist = 0
        self.own_core_dist_init_pending_count = 0
        self.own_core_dist_incremental_queue: list[int] = []
        self.own_core_dist_incremental_queue_head = 0
        self.own_core_dist_incremental_dirty_queue: list[int] = []
        self.own_core_dist_incremental_dirty_queue_head = 0
        self.own_core_dist_incremental_seed_queue: list[int] = []
        self.own_core_dist_incremental_seed_queue_head = 0
        self.own_core_dist_manhattan_init_started = False
        self.own_core_dist_manhattan_init_next_x = 0
        self.own_core_dist_manhattan_init_next_y = 0
        self.distance_queue_buffer_by_index: list[int] = []
        self.path_queue_buffer_by_index: list[int] = []
        self.path_heap_buffer: list[tuple[int, int, int, int, int, int, int]] = []
        self.visible_builder_bot_ids_by_index = array("i", [-1]) * self.INITIAL_MAP_SIZE
        self.visible_builder_bot_ids_touched_indices: list[int] = []
        self.visible_builder_bot_ids_in_vision: set[int] = set()
        self.visible_building_ids_by_index = array("i", [-1]) * self.INITIAL_MAP_SIZE
        self.visible_building_ids_touched_indices: list[int] = []
        self.conveyor_targets_harvester_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.locked_in_titanium_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.all_own_supply_link_target_indices_in_vision = _TouchedIndexMembership(
            self.INITIAL_MAP_SIZE
        )
        self.own_supply_link_target_indices_in_vision = _TouchedIndexMembership(
            self.INITIAL_MAP_SIZE
        )
        self.enemy_supply_link_target_indices_in_vision = _TouchedIndexMembership(
            self.INITIAL_MAP_SIZE
        )
        self.own_supply_link_source_indices_by_target_index_in_vision = (
            _TouchedIndexSourceMap(self.INITIAL_MAP_SIZE)
        )
        self.enemy_supply_link_source_indices_by_target_index_in_vision = (
            _TouchedIndexSourceMap(self.INITIAL_MAP_SIZE)
        )
        self.own_supply_chain_labels_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.enemy_supply_chain_labels_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.own_supply_chain_parent_by_index = array(
            "H", range(self.INITIAL_MAP_SIZE)
        )
        self.enemy_supply_chain_parent_by_index = array(
            "H", range(self.INITIAL_MAP_SIZE)
        )
        self.own_supply_chain_size_by_index = array("H", [1]) * self.INITIAL_MAP_SIZE
        self.enemy_supply_chain_size_by_index = array("H", [1]) * self.INITIAL_MAP_SIZE
        self.own_supply_chain_active_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.enemy_supply_chain_active_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.own_supply_chain_tile_count_by_index = (
            array("H", [0]) * self.INITIAL_MAP_SIZE
        )
        self.enemy_supply_chain_tile_count_by_index = (
            array("H", [0]) * self.INITIAL_MAP_SIZE
        )
        self.own_supply_chain_harvester_count_by_index = (
            array("H", [0]) * self.INITIAL_MAP_SIZE
        )
        self.enemy_supply_chain_harvester_count_by_index = (
            array("H", [0]) * self.INITIAL_MAP_SIZE
        )
        self.own_supply_chain_resource_item_count_by_index = (
            array("H", [0]) * self.INITIAL_MAP_SIZE
        )
        self.enemy_supply_chain_resource_item_count_by_index = (
            array("H", [0]) * self.INITIAL_MAP_SIZE
        )
        self.own_supply_chain_max_euclidean_dist_to_self_by_index = (
            array("f", [0.0]) * self.INITIAL_MAP_SIZE
        )
        self.enemy_supply_chain_max_euclidean_dist_to_self_by_index = (
            array("f", [0.0]) * self.INITIAL_MAP_SIZE
        )
        self.own_supply_chain_has_titanium_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.enemy_supply_chain_has_titanium_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.own_supply_chain_has_raw_axionite_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.enemy_supply_chain_has_raw_axionite_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.own_supply_chain_has_refined_axionite_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.own_supply_chain_feeds_own_turret_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.enemy_supply_chain_has_refined_axionite_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.enemy_supply_chain_feeds_own_turret_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.own_supply_chain_touched_indices: list[int] = []
        self.enemy_supply_chain_touched_indices: list[int] = []
        self.path_seen_epoch_by_index = array("I", [0]) * self.INITIAL_MAP_SIZE
        self.path_predecessor_by_index = array("h", [-1]) * self.INITIAL_MAP_SIZE
        self.path_first_step_by_index = array("h", [-1]) * self.INITIAL_MAP_SIZE
        self.path_first_step_requires_new_road_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.path_cost_by_index = array("H", [0]) * self.INITIAL_MAP_SIZE
        self.path_epoch = 0
        self.tiles_by_index: list[Tile] = [
            Tile(Position(x, y), self)
            for x in range(self.INITIAL_WIDTH)
            for y in range(self.INITIAL_HEIGHT)
        ]
        self._active_mask_by_dimensions: dict[tuple[int, int], bytes] = {}
        self.active_mask_by_index = b"\x01" * self.INITIAL_MAP_SIZE
        self.neighbor_count_by_index = array("B", [0]) * self.INITIAL_MAP_SIZE
        self.neighbor_indices_by_index = array("H", [0]) * (
            self.INITIAL_MAP_SIZE * self.MAX_NEIGHBOR_COUNT
        )
        self.neighbor_step_costs_by_index = array("B", [0]) * (
            self.INITIAL_MAP_SIZE * self.MAX_NEIGHBOR_COUNT
        )
        self.cardinal_neighbor_count_by_index = array("B", [0]) * self.INITIAL_MAP_SIZE
        self.cardinal_neighbor_indices_by_index = array("H", [0]) * (
            self.INITIAL_MAP_SIZE * self.MAX_CARDINAL_NEIGHBOR_COUNT
        )
        self.neighbor_index_by_direction_by_index = array("h", [-1]) * (
            self.INITIAL_MAP_SIZE * self.DIRECTION_SLOT_COUNT
        )
        self.builder_action_target_count_by_index = (
            array("B", [0]) * self.INITIAL_MAP_SIZE
        )
        self.builder_action_target_indices_by_index = array("H", [0]) * (
            self.INITIAL_MAP_SIZE * self.MAX_BUILDER_ACTION_TARGET_COUNT
        )
        self.core_footprint_target_count_by_index = (
            array("B", [0]) * self.INITIAL_MAP_SIZE
        )
        self.core_footprint_target_indices_by_index = array("H", [0]) * (
            self.INITIAL_MAP_SIZE * self.MAX_CORE_FOOTPRINT_TARGET_COUNT
        )
        self.attackable_target_offset_cache: dict[
            tuple[EntityType, Direction],
            tuple[tuple[int, int], ...],
        ] = {}
        self._build_index_caches()

        self.symmetry_mode: SymmetryMode | None = None
        self.symmetry_mode_candidates = [
            SymmetryMode.ROTATION,
            SymmetryMode.MIRROR_X,
            SymmetryMode.MIRROR_Y,
        ]
        self.own_core_center_pos: Position | None = None
        self.enemy_core_center_pos: Position | None = None
        self.own_core_building_id: int | None = None
        self.enemy_core_building_id: int | None = None
        self.own_core_building_hp: int | None = None
        self.enemy_core_building_hp: int | None = None
        self.enemy_core_center_pos_candidates: list[tuple[SymmetryMode, Position]] = []
        self.known_accessible_titanium_indices: list[int] = []
        self.known_accessible_axionite_indices: list[int] = []
        self.is_map_known: bool = False
        self.known_map_path: str | None = None
        self.map_inference_time_ns: int = 0
        self.parsed_map_tile_type_by_index: list[int] | None = None
        self.parsed_map_own_core_dist_by_index: list[int] | None = None
        self.parsed_titanium_indices: list[int] = []
        self.parsed_axionite_indices: list[int] = []
        self.enemy_core_checkpoint_positions: list[Position] = []
        self.parsed_map_next_update_index: int = 0
        self.map_json_fully_loaded: bool = False
        self.map_json_loaded_print_pending: bool = False
        self.map_update_time_ns: int = 0

        # Frontier expansion cache used by `s_frontier_expand_new`.
        self.frontier_expand_cached_unseen_indices: set[int] = set()
        self.frontier_expand_newly_seen_indices: list[int] = []
        self.frontier_expand_pending_indices: list[int] = []
        self.frontier_expand_pending_head = 0
        self.vision_bfs_passable_touched_indices: list[int] = []
        self.vision_bfs_passable_by_index = bytearray(self.INITIAL_MAP_SIZE)
        self.stale_builder_passability_touched_indices: list[int] = []
        self.stale_builder_passability_tracked_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.own_titanium_harvester_adjacent_candidate_indices: list[int] = []
        self.own_titanium_harvester_adjacent_candidate_mark_by_index = bytearray(
            self.INITIAL_MAP_SIZE
        )
        self.own_titanium_harvester_adjacent_candidate_touched_indices: list[int] = []
        self.known_own_supply_link_indices: set[int] = set()
        self.known_enemy_supply_link_indices: set[int] = set()
        self.closest_enemy_builder_bot_in_vision_pos: Position | None = None

        self.stopwatch = Stopwatch("Map")

    def _reset_turn_state(self) -> None:
        if self.ct is None:
            raise RuntimeError(
                "Map controller must be set before resetting turn state."
            )

        self._reset_marked_bytearray_indices(
            self.enemy_gunner_ray_first_target_touched_indices,
            self.enemy_gunner_ray_first_target_by_index,
        )
        self._reset_marked_bytearray_indices(
            self.enemy_spin_gunner_ray_first_target_touched_indices,
            self.enemy_spin_gunner_ray_first_target_by_index,
        )
        self._reset_marked_bytearray_indices(
            self.vision_bfs_passable_touched_indices,
            self.vision_bfs_passable_by_index,
        )
        self._reset_marked_bytearray_indices(
            self.own_titanium_harvester_adjacent_candidate_touched_indices,
            self.own_titanium_harvester_adjacent_candidate_mark_by_index,
        )
        self._reset_marked_array_indices(
            self.visible_builder_bot_ids_touched_indices,
            self.visible_builder_bot_ids_by_index,
            -1,
        )
        self.visible_builder_bot_ids_in_vision.clear()
        self._reset_marked_array_indices(
            self.visible_building_ids_touched_indices,
            self.visible_building_ids_by_index,
            -1,
        )
        self._reset_supply_chain_union_find_arrays(
            self.own_supply_chain_touched_indices,
            self.own_supply_chain_parent_by_index,
            self.own_supply_chain_size_by_index,
            self.own_supply_chain_active_by_index,
            self.own_supply_chain_tile_count_by_index,
            self.own_supply_chain_harvester_count_by_index,
            self.own_supply_chain_resource_item_count_by_index,
            self.own_supply_chain_max_euclidean_dist_to_self_by_index,
            self.own_supply_chain_has_titanium_by_index,
            self.own_supply_chain_has_raw_axionite_by_index,
            self.own_supply_chain_has_refined_axionite_by_index,
            self.own_supply_chain_feeds_own_turret_by_index,
        )
        self._reset_supply_chain_union_find_arrays(
            self.enemy_supply_chain_touched_indices,
            self.enemy_supply_chain_parent_by_index,
            self.enemy_supply_chain_size_by_index,
            self.enemy_supply_chain_active_by_index,
            self.enemy_supply_chain_tile_count_by_index,
            self.enemy_supply_chain_harvester_count_by_index,
            self.enemy_supply_chain_resource_item_count_by_index,
            self.enemy_supply_chain_max_euclidean_dist_to_self_by_index,
            self.enemy_supply_chain_has_titanium_by_index,
            self.enemy_supply_chain_has_raw_axionite_by_index,
            self.enemy_supply_chain_has_refined_axionite_by_index,
            self.enemy_supply_chain_feeds_own_turret_by_index,
        )

        next_round = self.ct.get_current_round()
        next_pos = self.ct.get_position()
        if next_round != self.current_round:
            if self.current_round != -1 and next_pos == self.current_pos:
                self.turns_on_current_tile += 1
            else:
                self.turns_on_current_tile = 0
        self.current_round = next_round
        self.current_pos = next_pos
        current_idx = self.u_to_index(next_pos)
        self.last_visited_turn_by_index[current_idx] = next_round
        self.scout_seen_by_index[current_idx] = 1
        self.titanium, self.axionite = self.ct.get_global_resources()

        if self.stale_builder_passability_touched_indices:
            for idx in self.stale_builder_passability_touched_indices:
                self.stale_builder_passability_tracked_by_index[idx] = 0
                tile = self.tiles_by_index[idx]
                tile.u_refresh_intrinsic_passability()
                tile.is_passable = tile._is_intrinsically_passable() and (
                    tile.bot.id is None or tile.position == self.current_pos
                )
            self.stale_builder_passability_touched_indices.clear()

        self.has_enemy_bot_in_vision = False
        self.closest_enemy_builder_bot_in_vision_pos = None
        self.tiles_in_vision: list[Tile] = []
        self.newly_seen_tiles_in_vision: list[Tile] = []
        self.own_harvesters_in_vision: list[Tile] = []
        self.enemy_harvesters_in_vision: list[Tile] = []
        self.enemy_supply_targets_in_vision: list[Tile] = []
        self.own_supply_links_in_vision: list[Tile] = []
        self.enemy_supply_links_in_vision: list[Tile] = []
        self.own_buildings_in_vision: list[Tile] = []
        self.enemy_buildings_in_vision: list[Tile] = []
        self.own_buildings_healable_in_action_range: list[Tile] = []
        self.own_buildings_needing_heal: list[Tile] = []
        self.own_missing_supply_links: list[Tile] = []
        self.enemy_missing_supply_links: list[Tile] = []
        self.own_titanium_harvester_adjacent_candidate_indices: list[int] = []
        self.all_own_supply_link_target_indices_in_vision.clear()
        self.own_supply_link_target_indices_in_vision.clear()
        self.enemy_supply_link_target_indices_in_vision.clear()
        self.own_supply_link_source_indices_by_target_index_in_vision.clear()
        self.enemy_supply_link_source_indices_by_target_index_in_vision.clear()
        self.frontier_expand_newly_seen_indices = []

    def _reset_marked_bytearray_indices(
        self,
        touched_indices: list[int],
        values: bytearray,
    ) -> None:
        for idx in touched_indices:
            values[idx] = 0
        touched_indices.clear()

    def _u_mark_bytearray_index(
        self,
        touched_indices: list[int],
        values: bytearray,
        idx: int,
    ) -> None:
        if values[idx]:
            return
        values[idx] = 1
        touched_indices.append(idx)

    def _reset_marked_array_indices(
        self,
        touched_indices: list[int],
        values,
        reset_value: int,
    ) -> None:
        for idx in touched_indices:
            values[idx] = reset_value
        touched_indices.clear()

    def u_mark_core_distance_dirty_index(self, idx: int) -> None:
        if self.core_distance_dirty_mark_by_index[idx]:
            return
        self.core_distance_dirty_mark_by_index[idx] = 1
        self.core_distance_dirty_indices.append(idx)

    def u_clear_core_distance_dirty_indices(self) -> None:
        for idx in self.core_distance_dirty_indices:
            self.core_distance_dirty_mark_by_index[idx] = 0
        self.core_distance_dirty_indices.clear()

    def _reset_supply_chain_union_find_arrays(
        self,
        touched_indices: list[int],
        parent_by_index,
        size_by_index,
        active_by_index: bytearray,
        tile_count_by_index,
        harvester_count_by_index,
        resource_item_count_by_index,
        max_euclidean_dist_to_self_by_index,
        has_titanium_by_index: bytearray,
        has_raw_axionite_by_index: bytearray,
        has_refined_axionite_by_index: bytearray,
        feeds_own_turret_by_index: bytearray | None = None,
    ) -> None:
        for idx in touched_indices:
            parent_by_index[idx] = idx
            size_by_index[idx] = 1
            active_by_index[idx] = 0
            tile_count_by_index[idx] = 0
            harvester_count_by_index[idx] = 0
            resource_item_count_by_index[idx] = 0
            max_euclidean_dist_to_self_by_index[idx] = 0.0
            has_titanium_by_index[idx] = 0
            has_raw_axionite_by_index[idx] = 0
            has_refined_axionite_by_index[idx] = 0
            if feeds_own_turret_by_index is not None:
                feeds_own_turret_by_index[idx] = 0
        touched_indices.clear()

    def _get_supply_chain_union_find_arrays(self, team: Team):
        if team == self.own_team:
            return (
                self.own_supply_chain_parent_by_index,
                self.own_supply_chain_size_by_index,
                self.own_supply_chain_active_by_index,
                self.own_supply_chain_tile_count_by_index,
                self.own_supply_chain_harvester_count_by_index,
                self.own_supply_chain_resource_item_count_by_index,
                self.own_supply_chain_max_euclidean_dist_to_self_by_index,
                self.own_supply_chain_has_titanium_by_index,
                self.own_supply_chain_has_raw_axionite_by_index,
                self.own_supply_chain_has_refined_axionite_by_index,
                self.own_supply_chain_feeds_own_turret_by_index,
                self.own_supply_chain_touched_indices,
            )
        return (
            self.enemy_supply_chain_parent_by_index,
            self.enemy_supply_chain_size_by_index,
            self.enemy_supply_chain_active_by_index,
            self.enemy_supply_chain_tile_count_by_index,
            self.enemy_supply_chain_harvester_count_by_index,
            self.enemy_supply_chain_resource_item_count_by_index,
            self.enemy_supply_chain_max_euclidean_dist_to_self_by_index,
            self.enemy_supply_chain_has_titanium_by_index,
            self.enemy_supply_chain_has_raw_axionite_by_index,
            self.enemy_supply_chain_has_refined_axionite_by_index,
            self.enemy_supply_chain_feeds_own_turret_by_index,
            self.enemy_supply_chain_touched_indices,
        )

    def _u_get_euclidean_dist_to_self_by_index(self, idx: int) -> float:
        dx = self.index_x_by_index[idx] - self.current_pos.x
        dy = self.index_y_by_index[idx] - self.current_pos.y
        return math.hypot(dx, dy)

    def _activate_supply_chain_index(self, idx: int, team: Team) -> None:
        (
            parent_by_index,
            size_by_index,
            active_by_index,
            tile_count_by_index,
            harvester_count_by_index,
            resource_item_count_by_index,
            max_euclidean_dist_to_self_by_index,
            has_titanium_by_index,
            has_raw_axionite_by_index,
            has_refined_axionite_by_index,
            feeds_own_turret_by_index,
            touched_indices,
        ) = self._get_supply_chain_union_find_arrays(team)
        if active_by_index[idx]:
            return
        parent_by_index[idx] = idx
        size_by_index[idx] = 1
        active_by_index[idx] = 1
        tile_count_by_index[idx] = 1
        harvester_count_by_index[idx] = 0
        resource_item_count_by_index[idx] = 0
        max_euclidean_dist_to_self_by_index[idx] = (
            self._u_get_euclidean_dist_to_self_by_index(idx)
        )
        has_titanium_by_index[idx] = 0
        has_raw_axionite_by_index[idx] = 0
        has_refined_axionite_by_index[idx] = 0
        if feeds_own_turret_by_index is not None:
            feeds_own_turret_by_index[idx] = 0
        touched_indices.append(idx)

    def u_find_supply_chain_root_by_index(
        self,
        idx: int,
        team: Team,
    ) -> int | None:
        (
            parent_by_index,
            _size_by_index,
            active_by_index,
            _tile_count_by_index,
            _harvester_count_by_index,
            _resource_item_count_by_index,
            _max_euclidean_dist_to_self_by_index,
            _has_titanium_by_index,
            _has_raw_axionite_by_index,
            _has_refined_axionite_by_index,
            _feeds_own_turret_by_index,
            _touched_indices,
        ) = self._get_supply_chain_union_find_arrays(team)
        if not active_by_index[idx]:
            return None

        root = idx
        while parent_by_index[root] != root:
            root = parent_by_index[root]

        while parent_by_index[idx] != idx:
            next_idx = parent_by_index[idx]
            parent_by_index[idx] = root
            idx = next_idx

        return root

    def u_union_supply_chain_indices(
        self,
        first_idx: int,
        second_idx: int,
        team: Team,
    ) -> int | None:
        first_root = self.u_find_supply_chain_root_by_index(first_idx, team)
        second_root = self.u_find_supply_chain_root_by_index(second_idx, team)
        if first_root is None or second_root is None:
            return None
        if first_root == second_root:
            return first_root

        (
            parent_by_index,
            size_by_index,
            _active_by_index,
            tile_count_by_index,
            harvester_count_by_index,
            resource_item_count_by_index,
            max_euclidean_dist_to_self_by_index,
            has_titanium_by_index,
            has_raw_axionite_by_index,
            has_refined_axionite_by_index,
            feeds_own_turret_by_index,
            _touched_indices,
        ) = self._get_supply_chain_union_find_arrays(team)
        if size_by_index[first_root] < size_by_index[second_root]:
            first_root, second_root = second_root, first_root

        parent_by_index[second_root] = first_root
        size_by_index[first_root] += size_by_index[second_root]
        tile_count_by_index[first_root] += tile_count_by_index[second_root]
        harvester_count_by_index[first_root] += harvester_count_by_index[second_root]
        resource_item_count_by_index[first_root] += resource_item_count_by_index[
            second_root
        ]
        max_euclidean_dist_to_self_by_index[first_root] = max(
            max_euclidean_dist_to_self_by_index[first_root],
            max_euclidean_dist_to_self_by_index[second_root],
        )
        has_titanium_by_index[first_root] |= has_titanium_by_index[second_root]
        has_raw_axionite_by_index[first_root] |= has_raw_axionite_by_index[
            second_root
        ]
        has_refined_axionite_by_index[first_root] |= (
            has_refined_axionite_by_index[second_root]
        )
        if feeds_own_turret_by_index is not None:
            feeds_own_turret_by_index[first_root] |= feeds_own_turret_by_index[
                second_root
            ]
        return first_root

    def u_get_supply_chain_id_by_index(
        self,
        idx: int,
        team: Team,
    ) -> int | None:
        return self.u_find_supply_chain_root_by_index(idx, team)

    def u_get_supply_chain_tile_count_by_index(
        self,
        idx: int,
        team: Team,
    ) -> int:
        root = self.u_find_supply_chain_root_by_index(idx, team)
        if root is None:
            return 0
        if team == self.own_team:
            return self.own_supply_chain_tile_count_by_index[root]
        return self.enemy_supply_chain_tile_count_by_index[root]

    def u_get_supply_chain_harvester_count_by_index(
        self,
        idx: int,
        team: Team,
    ) -> int:
        root = self.u_find_supply_chain_root_by_index(idx, team)
        if root is None:
            return 0
        if team == self.own_team:
            return self.own_supply_chain_harvester_count_by_index[root]
        return self.enemy_supply_chain_harvester_count_by_index[root]

    def u_get_supply_chain_resource_item_count_by_index(
        self,
        idx: int,
        team: Team,
    ) -> int:
        root = self.u_find_supply_chain_root_by_index(idx, team)
        if root is None:
            return 0
        if team == self.own_team:
            return self.own_supply_chain_resource_item_count_by_index[root]
        return self.enemy_supply_chain_resource_item_count_by_index[root]

    def u_get_supply_chain_max_euclidean_dist_to_self_by_index(
        self,
        idx: int,
        team: Team,
    ) -> float:
        root = self.u_find_supply_chain_root_by_index(idx, team)
        if root is None:
            return math.inf
        if team == self.own_team:
            return self.own_supply_chain_max_euclidean_dist_to_self_by_index[root]
        return self.enemy_supply_chain_max_euclidean_dist_to_self_by_index[root]

    def u_supply_chain_is_continuable(
        self,
        idx: int,
        team: Team,
    ) -> bool:
        return (
            self.u_get_supply_chain_resource_item_count_by_index(idx, team) > 0
            or self.u_get_supply_chain_harvester_count_by_index(idx, team) > 0
        )

    def u_supply_chain_is_joinable(
        self,
        idx: int,
        team: Team,
    ) -> bool:
        root = self.u_find_supply_chain_root_by_index(idx, team)
        return (
            root is not None
            and self.u_get_supply_chain_harvester_count_by_index(idx, team) < 4
            and self.u_get_supply_chain_max_euclidean_dist_to_self_by_index(
                idx,
                team,
            )
            <= 3.0
        )

    def u_supply_chain_has_titanium(
        self,
        idx: int,
        team: Team,
    ) -> bool:
        root = self.u_find_supply_chain_root_by_index(idx, team)
        if root is None:
            return False
        if team == self.own_team:
            return bool(self.own_supply_chain_has_titanium_by_index[root])
        return bool(self.enemy_supply_chain_has_titanium_by_index[root])

    def u_supply_chain_has_raw_axionite(
        self,
        idx: int,
        team: Team,
    ) -> bool:
        root = self.u_find_supply_chain_root_by_index(idx, team)
        if root is None:
            return False
        if team == self.own_team:
            return bool(self.own_supply_chain_has_raw_axionite_by_index[root])
        return bool(self.enemy_supply_chain_has_raw_axionite_by_index[root])

    def u_supply_chain_has_refined_axionite(
        self,
        idx: int,
        team: Team,
    ) -> bool:
        root = self.u_find_supply_chain_root_by_index(idx, team)
        if root is None:
            return False
        if team == self.own_team:
            return bool(self.own_supply_chain_has_refined_axionite_by_index[root])
        return bool(self.enemy_supply_chain_has_refined_axionite_by_index[root])

    def u_enemy_supply_chain_feeds_own_turret(
        self,
        idx: int,
    ) -> bool:
        root = self.u_find_supply_chain_root_by_index(idx, self.enemy_team)
        if root is None:
            return False
        return bool(self.enemy_supply_chain_feeds_own_turret_by_index[root])

    def u_enemy_tile_is_targeted_by_titanium_supply_chain(
        self,
        idx: int,
    ) -> bool:
        for source_idx in self.enemy_supply_link_source_indices_by_target_index_in_vision.get(
            idx,
            (),
        ):
            if self.u_supply_chain_has_titanium(source_idx, self.enemy_team):
                return True
        return False

    def u_own_supply_chain_feeds_own_turret(
        self,
        idx: int,
    ) -> bool:
        root = self.u_find_supply_chain_root_by_index(idx, self.own_team)
        if root is None:
            return False
        return bool(self.own_supply_chain_feeds_own_turret_by_index[root])

    def _u_apply_connected_harvester_resource_flags(
        self,
        harvester_tile: Tile,
        root: int,
        has_titanium_by_index: bytearray,
        has_raw_axionite_by_index: bytearray,
    ) -> None:
        if harvester_tile.environment == Environment.ORE_TITANIUM:
            has_titanium_by_index[root] = 1
        elif harvester_tile.environment == Environment.ORE_AXIONITE:
            has_raw_axionite_by_index[root] = 1

    def u_update_supply_chain_union_find_for_team(self, team: Team) -> None:
        if team == self.own_team:
            supply_links_in_vision = self.own_supply_links_in_vision
            supply_chain_harvester_count_by_index = (
                self.own_supply_chain_harvester_count_by_index
            )
            supply_chain_resource_item_count_by_index = (
                self.own_supply_chain_resource_item_count_by_index
            )
            supply_chain_has_titanium_by_index = (
                self.own_supply_chain_has_titanium_by_index
            )
            supply_chain_has_raw_axionite_by_index = (
                self.own_supply_chain_has_raw_axionite_by_index
            )
            supply_chain_has_refined_axionite_by_index = (
                self.own_supply_chain_has_refined_axionite_by_index
            )
            supply_chain_feeds_own_turret_by_index = (
                self.own_supply_chain_feeds_own_turret_by_index
            )
        else:
            supply_links_in_vision = self.enemy_supply_links_in_vision
            supply_chain_harvester_count_by_index = (
                self.enemy_supply_chain_harvester_count_by_index
            )
            supply_chain_resource_item_count_by_index = (
                self.enemy_supply_chain_resource_item_count_by_index
            )
            supply_chain_has_titanium_by_index = (
                self.enemy_supply_chain_has_titanium_by_index
            )
            supply_chain_has_raw_axionite_by_index = (
                self.enemy_supply_chain_has_raw_axionite_by_index
            )
            supply_chain_has_refined_axionite_by_index = (
                self.enemy_supply_chain_has_refined_axionite_by_index
            )
            supply_chain_feeds_own_turret_by_index = (
                self.enemy_supply_chain_feeds_own_turret_by_index
            )

        for tile in supply_links_in_vision:
            self._activate_supply_chain_index(tile.index, team)
            if self.round_stopwatch.check_overtime_interval():
                break

        for tile in supply_links_in_vision:
            for target_tile in tile.building.targets:
                if (
                    target_tile.last_seen_turn == self.current_round
                    and target_tile.building.team == team
                    and target_tile.building.entity_type in SUPPLY_LINK_TYPES
                ):
                    self.u_union_supply_chain_indices(
                        tile.index,
                        target_tile.index,
                        team,
                    )
            if self.round_stopwatch.check_overtime_interval():
                break

        counted_harvester_component_keys: set[int] = set()
        for tile in supply_links_in_vision:
            root = self.u_find_supply_chain_root_by_index(tile.index, team)
            if root is None:
                continue

            if tile.building.last_resource_onit_turn == self.current_round:
                supply_chain_resource_item_count_by_index[root] += 1
            if tile.building.last_titanium_onit_turn == self.current_round:
                supply_chain_has_titanium_by_index[root] = 1
            if tile.building.last_raw_axionite_onit_turn == self.current_round:
                supply_chain_has_raw_axionite_by_index[root] = 1
            if tile.building.last_refined_axionite_onit_turn == self.current_round:
                supply_chain_has_refined_axionite_by_index[root] = 1

            for target_tile in tile.building.targets:
                if (
                    target_tile.last_seen_turn != self.current_round
                    or target_tile.building.team != team
                    or target_tile.building.entity_type != EntityType.HARVESTER
                ):
                    continue
                pair_key = root * self.tile_count + target_tile.index
                if pair_key in counted_harvester_component_keys:
                    continue
                counted_harvester_component_keys.add(pair_key)
                supply_chain_harvester_count_by_index[root] += 1
                self._u_apply_connected_harvester_resource_flags(
                    target_tile,
                    root,
                    supply_chain_has_titanium_by_index,
                    supply_chain_has_raw_axionite_by_index,
                )

            # Harvesters feed any orthogonally adjacent supplier, even when the
            # supplier does not target the harvester itself, such as a splitter
            # facing away from it.
            for adjacent_idx in self.u_iter_cardinal_neighbor_indices(tile.index):
                adjacent_tile = self.tiles_by_index[adjacent_idx]
                if (
                    adjacent_tile.last_seen_turn != self.current_round
                    or adjacent_tile.building.team != team
                    or adjacent_tile.building.entity_type != EntityType.HARVESTER
                ):
                    continue
                pair_key = root * self.tile_count + adjacent_idx
                if pair_key in counted_harvester_component_keys:
                    continue
                counted_harvester_component_keys.add(pair_key)
                supply_chain_harvester_count_by_index[root] += 1
                self._u_apply_connected_harvester_resource_flags(
                    adjacent_tile,
                    root,
                    supply_chain_has_titanium_by_index,
                    supply_chain_has_raw_axionite_by_index,
                )

            if supply_chain_feeds_own_turret_by_index is not None:
                if any(
                    target_tile.last_seen_turn == self.current_round
                    and target_tile.building.team == self.own_team
                    and target_tile.building.entity_type
                    in {
                        EntityType.GUNNER,
                        EntityType.SENTINEL,
                        EntityType.BREACH,
                    }
                    for target_tile in tile.building.targets
                ):
                    supply_chain_feeds_own_turret_by_index[root] = 1

            if self.round_stopwatch.check_overtime_interval():
                break

    def u_update_supply_chain_union_find(self) -> None:
        self._u_update_supply_chain_union_find_for_team_fast(
            self.own_team,
            self.own_supply_links_in_vision,
        )
        self._u_update_supply_chain_union_find_for_team_fast(
            self.enemy_team,
            self.enemy_supply_links_in_vision,
        )

    def _build_index_caches(self) -> None:
        max_width = self.INITIAL_WIDTH
        max_height = self.INITIAL_HEIGHT

        for x in range(max_width):
            base_idx = x * self.INDEX_STRIDE
            for y in range(max_height):
                idx = base_idx + y
                self.index_x_by_index[idx] = x
                self.index_y_by_index[idx] = y

                neighbor_count = 0
                cardinal_neighbor_count = 0
                direction_base = idx * self.DIRECTION_SLOT_COUNT
                for direction in DIRECTIONS:
                    dx, dy = direction.delta()
                    nx = x + dx
                    ny = y + dy
                    if 0 <= nx < max_width and 0 <= ny < max_height:
                        neighbor_offset = idx * self.MAX_NEIGHBOR_COUNT + neighbor_count
                        neighbor_idx = self.u_to_index_xy(nx, ny)
                        self.neighbor_indices_by_index[neighbor_offset] = neighbor_idx
                        self.neighbor_step_costs_by_index[neighbor_offset] = (
                            1 if dx == 0 or dy == 0 else 2
                        )
                        self.neighbor_index_by_direction_by_index[
                            direction_base
                            + self._direction_slot_by_direction[direction]
                        ] = neighbor_idx
                        neighbor_count += 1
                        if dx == 0 or dy == 0:
                            self.cardinal_neighbor_indices_by_index[
                                idx * self.MAX_CARDINAL_NEIGHBOR_COUNT
                                + cardinal_neighbor_count
                            ] = neighbor_idx
                            cardinal_neighbor_count += 1
                self.neighbor_count_by_index[idx] = neighbor_count
                self.cardinal_neighbor_count_by_index[idx] = cardinal_neighbor_count

                builder_target_count = 0
                for dx, dy in BUILDER_ACTION_OFFSETS:
                    nx = x + dx
                    ny = y + dy
                    if 0 <= nx < max_width and 0 <= ny < max_height:
                        self.builder_action_target_indices_by_index[
                            idx * self.MAX_BUILDER_ACTION_TARGET_COUNT
                            + builder_target_count
                        ] = self.u_to_index_xy(nx, ny)
                        builder_target_count += 1
                self.builder_action_target_count_by_index[idx] = builder_target_count

                core_target_count = 0
                for dx in range(-1, 2):
                    for dy in range(-1, 2):
                        nx = x + dx
                        ny = y + dy
                        if 0 <= nx < max_width and 0 <= ny < max_height:
                            self.core_footprint_target_indices_by_index[
                                idx * self.MAX_CORE_FOOTPRINT_TARGET_COUNT
                                + core_target_count
                            ] = self.u_to_index_xy(nx, ny)
                            core_target_count += 1
                self.core_footprint_target_count_by_index[idx] = core_target_count

        for width in range(1, max_width + 1):
            for height in range(1, max_height + 1):
                mask = bytearray(self.INITIAL_MAP_SIZE)
                for x in range(width):
                    start = x * self.INDEX_STRIDE
                    mask[start : start + height] = b"\x01" * height
                self._active_mask_by_dimensions[(width, height)] = bytes(mask)

        self._build_attackable_target_offset_cache()

    def u_prune_enemy_core_center_pos_candidates(self) -> None:
        if self.enemy_core_center_pos is not None:
            return
        if not self.enemy_core_center_pos_candidates:
            return

        current_round = self.current_round
        parsed_map_tile_type_by_index = self.parsed_map_tile_type_by_index
        pruned_enemy_core_center_pos_candidates = []
        inferred_enemy_core_center_pos = None

        for mode, center_pos in self.enemy_core_center_pos_candidates:
            footprint_overlaps_current_vision = False
            footprint_contains_enemy_core = False
            candidate_is_impossible = False

            for candidate_tile in self.u_get_core_footprint_positions(center_pos):
                if (
                    parsed_map_tile_type_by_index is not None
                    and parsed_map_tile_type_by_index[candidate_tile.index]
                    == PARSED_TILE_TYPE_WALL
                ) or candidate_tile.environment == Environment.WALL:
                    candidate_is_impossible = True
                    break

                if candidate_tile.last_seen_turn != current_round:
                    continue
                footprint_overlaps_current_vision = True
                if (
                    candidate_tile.building.entity_type == EntityType.CORE
                    and candidate_tile.building.team == self.enemy_team
                ):
                    footprint_contains_enemy_core = True
                    inferred_enemy_core_center_pos = center_pos
                    break

            if candidate_is_impossible:
                continue
            if not footprint_overlaps_current_vision or footprint_contains_enemy_core:
                pruned_enemy_core_center_pos_candidates.append((mode, center_pos))

        if inferred_enemy_core_center_pos is not None:
            self.enemy_core_center_pos_candidates = [
                (mode, pos)
                for mode, pos in pruned_enemy_core_center_pos_candidates
                if pos == inferred_enemy_core_center_pos
            ]
            self.enemy_core_center_pos = inferred_enemy_core_center_pos
            self.enemy_core_source_indices = self.u_set_core_source_indices(
                self.enemy_team,
                self.enemy_core_center_pos,
            )
            return

        if len(pruned_enemy_core_center_pos_candidates) == len(
            self.enemy_core_center_pos_candidates
        ):
            return

        self.enemy_core_center_pos_candidates = (
            pruned_enemy_core_center_pos_candidates
        )
        remaining_positions = {
            pos for _, pos in self.enemy_core_center_pos_candidates
        }
        if len(remaining_positions) == 1:
            self.enemy_core_center_pos = next(iter(remaining_positions))
            self.enemy_core_source_indices = self.u_set_core_source_indices(
                self.enemy_team,
                self.enemy_core_center_pos,
            )

    def _build_attackable_target_offset_cache(self) -> None:
        max_width = self.INITIAL_WIDTH
        max_height = self.INITIAL_HEIGHT
        source_pos = Position(max_width // 2, max_height // 2)
        cache = self.attackable_target_offset_cache

        for direction in DIRECTIONS:
            cache[(EntityType.GUNNER, direction)] = tuple(
                (target_x - source_pos.x, target_y - source_pos.y)
                for target_x in range(max_width)
                for target_y in range(max_height)
                if self.u_gunner_covers_target(
                    source_pos,
                    direction,
                    Position(target_x, target_y),
                    GameConstants.GUNNER_VISION_RADIUS_SQ,
                )
            )

            cache[(EntityType.SENTINEL, direction)] = tuple(
                (target_x - source_pos.x, target_y - source_pos.y)
                for target_x in range(max_width)
                for target_y in range(max_height)
                if self.u_sentinel_covers_target(
                    source_pos,
                    direction,
                    Position(target_x, target_y),
                    GameConstants.SENTINEL_VISION_RADIUS_SQ,
                )
            )

            cache[(EntityType.BREACH, direction)] = tuple(
                (target_x - source_pos.x, target_y - source_pos.y)
                for target_x in range(max_width)
                for target_y in range(max_height)
                if self.u_breach_covers_target(
                    source_pos,
                    direction,
                    Position(target_x, target_y),
                )
            )

        cache[(EntityType.LAUNCHER, Direction.NORTH)] = tuple(
            (target_x - source_pos.x, target_y - source_pos.y)
            for target_x in range(max_width)
            for target_y in range(max_height)
            if 0
            < source_pos.distance_squared(Position(target_x, target_y))
            <= GameConstants.LAUNCHER_VISION_RADIUS_SQ
        )

    def _first_round_init(self, ct: Controller) -> None:
        self.ct = ct
        self.width = ct.get_map_width()
        self.height = ct.get_map_height()
        self.tile_count = self.width * self.height
        self.own_team = ct.get_team()
        self.enemy_team = next(team for team in Team if team != self.own_team)
        self.active_mask_by_index = self._active_mask_by_dimensions[
            (self.width, self.height)
        ]
        self._first_round_initialized = True
        self._reset_turn_state()

    def u_to_index_xy(self, x: int, y: int) -> int:
        return x * self.INDEX_STRIDE + y

    def u_to_index(self, pos: Position) -> int:
        return self.u_to_index_xy(pos.x, pos.y)

    def u_index_to_xy(self, idx: int) -> tuple[int, int]:
        return (self.index_x_by_index[idx], self.index_y_by_index[idx])

    def u_is_index_active(self, idx: int) -> bool:
        return bool(self.active_mask_by_index[idx])

    def u_iter_active_tile_indices(self):
        for x in range(self.width):
            base_idx = x * self.INDEX_STRIDE
            for y in range(self.height):
                yield base_idx + y

    def u_iter_neighbor_indices(self, idx: int):
        base = idx * self.MAX_NEIGHBOR_COUNT
        count = self.neighbor_count_by_index[idx]
        for offset in range(count):
            neighbor_idx = self.neighbor_indices_by_index[base + offset]
            if self.active_mask_by_index[neighbor_idx]:
                yield neighbor_idx

    def u_iter_cardinal_neighbor_indices(self, idx: int):
        base = idx * self.MAX_CARDINAL_NEIGHBOR_COUNT
        count = self.cardinal_neighbor_count_by_index[idx]
        for offset in range(count):
            neighbor_idx = self.cardinal_neighbor_indices_by_index[base + offset]
            if self.active_mask_by_index[neighbor_idx]:
                yield neighbor_idx

    def u_mark_scout_seen_around_index(self, idx: int) -> None:
        center_x = self.index_x_by_index[idx]
        center_y = self.index_y_by_index[idx]
        width = self.width
        height = self.height
        scout_seen_by_index = self.scout_seen_by_index

        for dx, dy in _SCOUT_SEEN_NEIGHBOR_OFFSETS:
            target_x = center_x + dx
            target_y = center_y + dy
            if 0 <= target_x < width and 0 <= target_y < height:
                scout_seen_by_index[self.u_to_index_xy(target_x, target_y)] = 1

    def u_get_scout_information_gain_for_step(
        self,
        step_idx: int,
        direction: Direction,
    ) -> int:
        step_x = self.index_x_by_index[step_idx]
        step_y = self.index_y_by_index[step_idx]
        width = self.width
        height = self.height
        last_seen_turn_by_index = self.last_seen_turn_by_index
        scout_seen_by_index = self.scout_seen_by_index
        gain = 0

        for dx, dy in _SCOUT_NEW_VISION_OFFSETS_BY_DIRECTION[direction]:
            target_x = step_x + dx
            target_y = step_y + dy
            if not (0 <= target_x < width and 0 <= target_y < height):
                continue
            target_idx = self.u_to_index_xy(target_x, target_y)
            if last_seen_turn_by_index[target_idx] != -1 or scout_seen_by_index[target_idx]:
                continue
            gain += 1

        return gain

    def u_iter_builder_action_target_indices(self, idx: int):
        base = idx * self.MAX_BUILDER_ACTION_TARGET_COUNT
        count = self.builder_action_target_count_by_index[idx]
        for offset in range(count):
            target_idx = self.builder_action_target_indices_by_index[base + offset]
            if self.active_mask_by_index[target_idx]:
                yield target_idx

    def u_iter_core_footprint_target_indices(self, idx: int):
        base = idx * self.MAX_CORE_FOOTPRINT_TARGET_COUNT
        count = self.core_footprint_target_count_by_index[idx]
        for offset in range(count):
            target_idx = self.core_footprint_target_indices_by_index[base + offset]
            if self.active_mask_by_index[target_idx]:
                yield target_idx

    def u_get_neighbor_index_by_direction(
        self,
        idx: int,
        direction: Direction,
    ) -> int | None:
        neighbor_idx = self.neighbor_index_by_direction_by_index[
            idx * self.DIRECTION_SLOT_COUNT
            + self._direction_slot_by_direction[direction]
        ]
        if neighbor_idx < 0 or not self.active_mask_by_index[neighbor_idx]:
            return None
        return neighbor_idx

    def u_update_vision(self):
        if not self._first_round_initialized or self.ct is None:
            raise RuntimeError(
                "Map must be first-round initialized before updating vision."
            )

        self.stopwatch.start()

        self._reset_turn_state()
        self.tiles_in_vision = [
            self.u_get_pos_tile(pos) for pos in self.ct.get_nearby_tiles()
        ]

        for unit_id in self.ct.get_nearby_units():
            if self.ct.get_entity_type(unit_id) != EntityType.BUILDER_BOT:
                continue
            self.visible_builder_bot_ids_in_vision.add(unit_id)
            pos = self.ct.get_position(unit_id)
            if self.u_is_in_bounds(pos):
                idx = self.u_to_index(pos)
                if self.visible_builder_bot_ids_by_index[idx] < 0:
                    self.visible_builder_bot_ids_touched_indices.append(idx)
                self.visible_builder_bot_ids_by_index[idx] = unit_id

        for building_id in self.ct.get_nearby_buildings():
            if (
                self.MARKER_ENTITY_TYPE is not None
                and self.ct.get_entity_type(building_id) == self.MARKER_ENTITY_TYPE
            ):
                continue
            pos = self.ct.get_position(building_id)
            if self.u_is_in_bounds(pos):
                idx = self.u_to_index(pos)
                if self.visible_building_ids_by_index[idx] < 0:
                    self.visible_building_ids_touched_indices.append(idx)
                self.visible_building_ids_by_index[idx] = building_id
        self.stopwatch.lap("Reset + nearby queries")

        processed_tiles_in_vision = []
        known_accessible_titanium_indices = set(self.known_accessible_titanium_indices)
        known_accessible_axionite_indices = set(self.known_accessible_axionite_indices)
        closest_enemy_builder_key = None
        own_team = self.own_team
        current_pos = self.current_pos
        conveyor_targets_harvester_by_index = self.conveyor_targets_harvester_by_index
        own_buildings_in_vision = self.own_buildings_in_vision
        enemy_buildings_in_vision = self.enemy_buildings_in_vision
        own_buildings_healable_in_action_range = (
            self.own_buildings_healable_in_action_range
        )
        own_buildings_needing_heal = self.own_buildings_needing_heal
        own_supply_links_in_vision = self.own_supply_links_in_vision
        enemy_supply_links_in_vision = self.enemy_supply_links_in_vision
        own_harvesters_in_vision = self.own_harvesters_in_vision
        enemy_harvesters_in_vision = self.enemy_harvesters_in_vision
        for tile in self.tiles_in_vision:
            tile.update_attributes()
            processed_tiles_in_vision.append(tile)
            building = tile.building
            conveyor_targets_harvester_by_index[tile.index] = 0

            if building.entity_type in {
                EntityType.CONVEYOR,
                EntityType.ARMOURED_CONVEYOR,
            }:
                for target_tile in building.targets:
                    if target_tile.building.entity_type == EntityType.HARVESTER:
                        conveyor_targets_harvester_by_index[tile.index] = 1
                        break

            if tile.bot.id is not None and tile.bot.team != own_team:
                self.has_enemy_bot_in_vision = True
                if tile.bot.entity_type == EntityType.BUILDER_BOT:
                    key = (
                        current_pos.distance_squared(tile.position),
                        tile.position.x,
                        tile.position.y,
                    )
                    if (
                        closest_enemy_builder_key is None
                        or key < closest_enemy_builder_key
                    ):
                        closest_enemy_builder_key = key
                        self.closest_enemy_builder_bot_in_vision_pos = tile.position

            if building.id is not None:
                if building.team == own_team:
                    own_buildings_in_vision.append(tile)
                    self.u_mark_scout_seen_around_index(tile.index)
                else:
                    enemy_buildings_in_vision.append(tile)

                if building.team == own_team:
                    building_damaged = building.hp < self.ct.get_max_hp(building.id)
                    if (
                        building.entity_type
                        in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}
                        and building.hp > 16
                    ):
                        building_damaged = False
                    own_bot_damaged = (
                        tile.bot.id is not None
                        and tile.bot.team == own_team
                        and tile.bot.hp < self.ct.get_max_hp(tile.bot.id)
                    )
                    if building_damaged or own_bot_damaged:
                        if self.ct.can_heal(tile.position):
                            own_buildings_healable_in_action_range.append(tile)
                        else:
                            own_buildings_needing_heal.append(tile)

                if building.entity_type in SUPPLY_LINK_TYPES:
                    if building.team == own_team:
                        own_supply_links_in_vision.append(tile)
                    else:
                        enemy_supply_links_in_vision.append(tile)

                if building.entity_type == EntityType.HARVESTER:
                    if building.team == own_team:
                        own_harvesters_in_vision.append(tile)
                    else:
                        enemy_harvesters_in_vision.append(tile)

            if tile.environment == Environment.ORE_TITANIUM:
                if building.id is None or (
                    building.team == own_team
                    and building.entity_type in {
                        EntityType.ROAD,
                        EntityType.CONVEYOR,
                        EntityType.ARMOURED_CONVEYOR,
                        EntityType.BARRIER,
                    }
                ):
                    known_accessible_titanium_indices.add(tile.index)
                else:
                    known_accessible_titanium_indices.discard(tile.index)
            else:
                known_accessible_titanium_indices.discard(tile.index)

            if tile.environment == Environment.ORE_AXIONITE:
                if building.id is None or (
                    building.team == own_team
                    and building.entity_type in {
                        EntityType.ROAD,
                        EntityType.CONVEYOR,
                        EntityType.ARMOURED_CONVEYOR,
                        EntityType.BARRIER,
                    }
                ):
                    known_accessible_axionite_indices.add(tile.index)
                else:
                    known_accessible_axionite_indices.discard(tile.index)
            else:
                known_accessible_axionite_indices.discard(tile.index)

            if self.round_stopwatch.check_overtime_interval():
                break

        self.tiles_in_vision = processed_tiles_in_vision
        self.known_accessible_titanium_indices = self.u_order_known_resource_indices(
            known_accessible_titanium_indices,
            self.parsed_titanium_indices,
        )
        self.known_accessible_axionite_indices = self.u_order_known_resource_indices(
            known_accessible_axionite_indices,
            self.parsed_axionite_indices,
        )

        self.stopwatch.lap("Tile attributes")

        self.u_update_visible_map_caches()

        if self.own_core_center_pos is None:
            self.u_calc_core_center_positions()

        self.u_infer_map()
        self.u_sync_core_footprint_tiles()

        self.stopwatch.lap("Core positions")

        self.u_update_supply_information()
        self.u_update_enemy_gunner_first_target_caches()

        self.stopwatch.lap("Supply info")

        self.u_update_supply_patrol_indices()

        self.stopwatch.lap("Patrol indices")

        self.u_update_distances()

        self.stopwatch.lap("Distances")

        self.stopwatch.log()

    def u_get_attackable_target_indices(
        self,
        source_idx: int,
        turret_type: EntityType,
        direction: Direction,
    ) -> tuple[int, ...]:
        if not self.u_is_index_active(source_idx):
            return ()

        source_x, source_y = self.u_index_to_xy(source_idx)
        if turret_type == EntityType.LAUNCHER:
            direction = Direction.NORTH

        return tuple(
            self.u_to_index_xy(target_x, target_y)
            for dx, dy in self.attackable_target_offset_cache[(turret_type, direction)]
            if 0 <= (target_x := source_x + dx) < self.width
            and 0 <= (target_y := source_y + dy) < self.height
        )

    def u_order_known_resource_indices(
        self,
        resource_indices: set[int],
        parsed_order: list[int],
    ) -> list[int]:
        if not parsed_order:
            return sorted(resource_indices)

        ordered_indices = [idx for idx in parsed_order if idx in resource_indices]
        ordered_index_set = set(ordered_indices)
        if len(ordered_index_set) == len(resource_indices):
            return ordered_indices

        remaining_indices = sorted(resource_indices - ordered_index_set)
        ordered_indices.extend(remaining_indices)
        return ordered_indices

    def u_update_visible_map_caches(self) -> None:
        self.u_update_symmetry_from_visible_tiles()
        self.stopwatch.lap("Visible caches: symmetry")

        self.stopwatch.lap("Visible caches: classify")
        for tile in self.own_buildings_in_vision:
            if tile.building.entity_type == EntityType.CORE:
                self.u_update_visible_core_center(tile)
        for tile in self.enemy_buildings_in_vision:
            if tile.building.entity_type == EntityType.CORE:
                self.u_update_visible_core_center(tile)
        self.u_update_own_titanium_harvester_adjacent_candidate_cache()
        self.stopwatch.lap("Visible caches: accessible ore")
        self.u_update_frontier_expand_cache()
        self.stopwatch.lap("Visible caches: frontier")

    def u_update_own_titanium_harvester_adjacent_candidate_cache(self) -> None:
        current_round = self.current_round
        own_team = self.own_team
        candidate_indices = self.own_titanium_harvester_adjacent_candidate_indices
        candidate_mark_by_index = (
            self.own_titanium_harvester_adjacent_candidate_mark_by_index
        )
        candidate_touched_indices = (
            self.own_titanium_harvester_adjacent_candidate_touched_indices
        )
        conveyor_targets_harvester_by_index = self.conveyor_targets_harvester_by_index
        tiles_by_index = self.tiles_by_index

        for harvester_tile in self.own_harvesters_in_vision:
            if harvester_tile.environment != Environment.ORE_TITANIUM:
                continue

            for adjacent_idx in self.u_iter_cardinal_neighbor_indices(harvester_tile.index):
                if candidate_mark_by_index[adjacent_idx]:
                    continue

                adjacent_tile = tiles_by_index[adjacent_idx]
                if adjacent_tile.last_seen_turn != current_round:
                    continue

                adjacent_building = adjacent_tile.building
                is_candidate_tile = (
                    adjacent_building.id is None
                    or (
                        adjacent_building.team == own_team
                        and adjacent_building.entity_type == EntityType.ROAD
                    )
                    or (
                        adjacent_building.team == own_team
                        and adjacent_building.entity_type in CONVEYOR_ENTITY_TYPES
                        and conveyor_targets_harvester_by_index[adjacent_idx]
                    )
                    or (
                        adjacent_building.team == own_team
                        and adjacent_building.entity_type == EntityType.BARRIER
                    )
                )
                if not is_candidate_tile:
                    continue

                candidate_mark_by_index[adjacent_idx] = 1
                candidate_touched_indices.append(adjacent_idx)
                candidate_indices.append(adjacent_idx)

    def u_update_frontier_expand_cache(self) -> None:
        pending_indices = self.frontier_expand_pending_indices
        if self.frontier_expand_newly_seen_indices:
            pending_indices.extend(self.frontier_expand_newly_seen_indices)
            self.frontier_expand_newly_seen_indices.clear()

        pending_head = self.frontier_expand_pending_head
        if pending_head >= len(pending_indices):
            pending_indices.clear()
            self.frontier_expand_pending_head = 0
            return

        frontier_indices = self.frontier_expand_cached_unseen_indices
        tiles_by_index = self.tiles_by_index

        while pending_head < len(pending_indices):
            idx = pending_indices[pending_head]
            pending_head += 1
            frontier_indices.discard(idx)
            for neighbor_idx in self.u_iter_neighbor_indices(idx):
                if tiles_by_index[neighbor_idx].last_seen_turn == -1:
                    frontier_indices.add(neighbor_idx)

            if self.round_stopwatch.check_overtime_interval():
                self.frontier_expand_pending_head = pending_head
                return

        pending_indices.clear()
        self.frontier_expand_pending_head = 0

    def u_update_symmetry_from_visible_tiles(self) -> None:
        if self.symmetry_mode is not None:
            return

        self.u_prune_enemy_core_center_pos_candidates()

        newly_seen_tiles = self.newly_seen_tiles_in_vision
        if not newly_seen_tiles:
            return

        symmetry_mode_candidates = self.symmetry_mode_candidates
        rotation_possible = SymmetryMode.ROTATION in symmetry_mode_candidates
        mirror_x_possible = SymmetryMode.MIRROR_X in symmetry_mode_candidates
        mirror_y_possible = SymmetryMode.MIRROR_Y in symmetry_mode_candidates
        original_rotation_possible = rotation_possible
        original_mirror_x_possible = mirror_x_possible
        original_mirror_y_possible = mirror_y_possible

        possible_count = (
            int(rotation_possible) + int(mirror_x_possible) + int(mirror_y_possible)
        )
        width_minus_1 = self.width - 1
        height_minus_1 = self.height - 1
        index_stride = self.INDEX_STRIDE
        tiles_by_index = self.tiles_by_index
        index_x_by_index = self.index_x_by_index
        index_y_by_index = self.index_y_by_index
        own_core_center_pos = self.own_core_center_pos
        enemy_core_center_pos = self.enemy_core_center_pos
        current_round = self.current_round
        core_entity_type = EntityType.CORE
        check_overtime_interval = self.round_stopwatch.check_overtime_interval

        def is_core_center_tile(tile: Tile, x: int, y: int) -> bool:
            if tile.building.entity_type != core_entity_type:
                return False
            if own_core_center_pos is not None and x == own_core_center_pos.x and y == own_core_center_pos.y:
                return True
            if (
                enemy_core_center_pos is not None
                and x == enemy_core_center_pos.x
                and y == enemy_core_center_pos.y
            ):
                return True
            if (
                tile.last_seen_turn == current_round
                and tile.building.id is not None
            ):
                tile_core_center_pos = self.ct.get_position(tile.building.id)
                return tile_core_center_pos.x == x and tile_core_center_pos.y == y
            return False

        for tile in newly_seen_tiles:
            tile_index = tile.index
            x = index_x_by_index[tile_index]
            y = index_y_by_index[tile_index]
            tile_environment = tile.environment
            tile_is_core_center = is_core_center_tile(tile, x, y)
            has_known_symmetric_tile = False

            if rotation_possible:
                rotation_x = width_minus_1 - x
                rotation_y = height_minus_1 - y
                rotation_idx = (width_minus_1 - x) * index_stride + (height_minus_1 - y)
                rotation_tile = tiles_by_index[rotation_idx]
                rotation_environment = rotation_tile.environment
                if rotation_environment is not None:
                    has_known_symmetric_tile = True
                    rotation_is_core_center = is_core_center_tile(
                        rotation_tile,
                        rotation_x,
                        rotation_y,
                    )
                    if tile_environment != rotation_environment or (
                        tile_is_core_center != rotation_is_core_center
                    ):
                        rotation_possible = False
                        possible_count -= 1

            if mirror_x_possible:
                mirror_x_x = x
                mirror_x_y = height_minus_1 - y
                mirror_x_idx = x * index_stride + (height_minus_1 - y)
                mirror_x_tile = tiles_by_index[mirror_x_idx]
                mirror_x_environment = mirror_x_tile.environment
                if mirror_x_environment is not None:
                    has_known_symmetric_tile = True
                    mirror_x_is_core_center = is_core_center_tile(
                        mirror_x_tile,
                        mirror_x_x,
                        mirror_x_y,
                    )
                    if tile_environment != mirror_x_environment or (
                        tile_is_core_center != mirror_x_is_core_center
                    ):
                        mirror_x_possible = False
                        possible_count -= 1

            if mirror_y_possible:
                mirror_y_x = width_minus_1 - x
                mirror_y_y = y
                mirror_y_idx = (width_minus_1 - x) * index_stride + y
                mirror_y_tile = tiles_by_index[mirror_y_idx]
                mirror_y_environment = mirror_y_tile.environment
                if mirror_y_environment is not None:
                    has_known_symmetric_tile = True
                    mirror_y_is_core_center = is_core_center_tile(
                        mirror_y_tile,
                        mirror_y_x,
                        mirror_y_y,
                    )
                    if tile_environment != mirror_y_environment or (
                        tile_is_core_center != mirror_y_is_core_center
                    ):
                        mirror_y_possible = False
                        possible_count -= 1

            if not has_known_symmetric_tile:
                continue

            if possible_count <= 1:
                break

            if check_overtime_interval():
                break

        if (
            rotation_possible == original_rotation_possible
            and mirror_x_possible == original_mirror_x_possible
            and mirror_y_possible == original_mirror_y_possible
        ):
            return

        new_symmetry_mode_candidates = []
        if rotation_possible:
            new_symmetry_mode_candidates.append(SymmetryMode.ROTATION)
        if mirror_x_possible:
            new_symmetry_mode_candidates.append(SymmetryMode.MIRROR_X)
        if mirror_y_possible:
            new_symmetry_mode_candidates.append(SymmetryMode.MIRROR_Y)

        self.symmetry_mode_candidates = new_symmetry_mode_candidates
        if possible_count == 1:
            self.symmetry_mode = new_symmetry_mode_candidates[0]

        self.enemy_core_center_pos_candidates = [
            (mode, symmetric_location)
            for mode, symmetric_location in self.enemy_core_center_pos_candidates
            if mode in self.symmetry_mode_candidates
        ]
        self.u_prune_enemy_core_center_pos_candidates()

    def u_get_pos_tile(self, pos: Position) -> Tile:
        return self.tiles_by_index[self.u_to_index(pos)]

    def u_is_in_bounds(self, pos: Position) -> bool:
        return 0 <= pos.x < self.width and 0 <= pos.y < self.height

    def u_positions_to_tiles(
        self,
        positions: Iterable[Position],
    ) -> list[Tile]:
        seen: set[int] = set()
        valid_tiles: list[Tile] = []
        for pos in positions:
            if not self.u_is_in_bounds(pos):
                continue
            idx = self.u_to_index(pos)
            if idx in seen:
                continue
            seen.add(idx)
            valid_tiles.append(self.u_get_pos_tile(pos))
        return valid_tiles

    def u_iter_adjacent_cardinal_positions(self, pos: Position):
        for direction in CARDINAL_DIRECTIONS:
            next_pos = pos.add(direction)
            if not self.u_is_in_bounds(next_pos):
                continue
            yield next_pos

    def u_iter_adjacent_all_positions(self, pos: Position):
        for direction in CARDINAL_ORDINAL_DIRECTIONS:
            next_pos = pos.add(direction)
            if not self.u_is_in_bounds(next_pos):
                continue
            yield next_pos

    def u_is_adjacent_to_ore(
        self,
        pos: Position,
        ore_type: Environment,
        consider_diagonal: bool = OPPOSITE_ORE_SUPPLY_CHAIN_SEPARATION_INCLUDES_DIAGONALS,
    ) -> bool:
        iter_fn = self.u_iter_adjacent_all_positions if consider_diagonal else self.u_iter_adjacent_cardinal_positions
        for adjacent_pos in iter_fn(pos):
            if self.u_get_pos_tile(adjacent_pos).environment == ore_type:
                return True
        return False

    def u_get_direction_between(
        self,
        source_pos: Position,
        target_pos: Position,
    ) -> Direction | None:
        delta_x = target_pos.x - source_pos.x
        delta_y = target_pos.y - source_pos.y
        step_x = 0 if delta_x == 0 else (1 if delta_x > 0 else -1)
        step_y = 0 if delta_y == 0 else (1 if delta_y > 0 else -1)

        for direction in Direction:
            if direction == Direction.CENTRE:
                continue
            if direction.delta() == (step_x, step_y):
                return direction
        return None

    def u_get_core_footprint_positions(self, center: Position) -> list[Tile]:
        return self.u_positions_to_tiles(
            [
                Position(center.x + dx, center.y + dy)
                for dx in range(-1, 2)
                for dy in range(-1, 2)
            ]
        )

    def u_cache_core_source_indices(
        self,
        center: Position | None,
        source_mask_by_index: bytearray,
    ) -> tuple[int, ...]:
        source_mask_by_index[:] = b"\x00" * len(source_mask_by_index)
        if center is None:
            return ()

        source_indices = tuple(
            tile.index for tile in self.u_get_core_footprint_positions(center)
        )
        for idx in source_indices:
            source_mask_by_index[idx] = 1
        return source_indices

    def u_set_core_source_indices(
        self,
        team: Team,
        center: Position | None,
    ) -> tuple[int, ...]:
        if team == self.own_team:
            old_source_indices = self.own_core_source_indices
            source_mask_by_index = self.own_core_source_by_index
        else:
            old_source_indices = self.enemy_core_source_indices
            source_mask_by_index = self.enemy_core_source_by_index

        source_indices = self.u_cache_core_source_indices(center, source_mask_by_index)
        if team == self.own_team:
            self.own_core_source_indices = source_indices
        else:
            self.enemy_core_source_indices = source_indices

        for idx in set(old_source_indices) - set(source_indices):
            self.tiles_by_index[idx].u_clear_core_building_state(team)

        self.u_sync_core_footprint_tiles_for_team(team)
        return source_indices

    def u_sync_core_footprint_tiles_for_team(self, team: Team) -> None:
        if team == self.own_team:
            center_pos = self.own_core_center_pos
            source_indices = self.own_core_source_indices
            building_id = self.own_core_building_id
            building_hp = self.own_core_building_hp
        else:
            center_pos = self.enemy_core_center_pos
            source_indices = self.enemy_core_source_indices
            building_id = self.enemy_core_building_id
            building_hp = self.enemy_core_building_hp

        if center_pos is not None:
            center_tile = self.u_get_pos_tile(center_pos)
            if (
                center_tile.building.entity_type == EntityType.CORE
                and center_tile.building.team == team
            ):
                building_id = center_tile.building.id
                building_hp = center_tile.building.hp

        if team == self.own_team:
            self.own_core_building_id = building_id
            self.own_core_building_hp = building_hp
        else:
            self.enemy_core_building_id = building_id
            self.enemy_core_building_hp = building_hp

        for idx in source_indices:
            self.tiles_by_index[idx].u_apply_core_building_state(
                team,
                building_id,
                building_hp,
            )

    def u_sync_core_footprint_tiles(self) -> None:
        self.u_sync_core_footprint_tiles_for_team(self.own_team)
        self.u_sync_core_footprint_tiles_for_team(self.enemy_team)

    def u_calc_core_center_positions(self) -> bool:
        if self.own_core_center_pos is None:
            current_tile = self.u_get_pos_tile(self.current_pos)
            core_tile = current_tile
            if (
                core_tile.building.entity_type != EntityType.CORE
                or core_tile.building.team != self.own_team
            ):
                core_tile = None
                for candidate_tile in self.own_buildings_in_vision:
                    if (
                        candidate_tile.building.entity_type == EntityType.CORE
                        and candidate_tile.building.team == self.own_team
                    ):
                        core_tile = candidate_tile
                        break
                    if self.round_stopwatch.check_overtime_interval():
                        break
                if core_tile is None:
                    return False

            self.own_core_center_pos = self.ct.get_position(core_tile.building.id)
            self.own_core_source_indices = self.u_set_core_source_indices(
                self.own_team,
                self.own_core_center_pos,
            )
            self.u_reset_own_core_distance_initialization()

        if self.own_core_center_pos is None:
            return False

        if not self.enemy_core_center_pos_candidates:
            center = self.own_core_center_pos
            all_enemy_core_center_pos_candidates = [
                (
                    SymmetryMode.ROTATION,
                    Position(self.width - 1 - center.x, self.height - 1 - center.y),
                ),
                (
                    SymmetryMode.MIRROR_X,
                    Position(center.x, self.height - 1 - center.y),
                ),
                (
                    SymmetryMode.MIRROR_Y,
                    Position(self.width - 1 - center.x, center.y),
                ),
            ]
            self.enemy_core_center_pos_candidates = [
                (mode, pos)
                for mode, pos in all_enemy_core_center_pos_candidates
                if mode in self.symmetry_mode_candidates
            ]
        self.u_prune_enemy_core_center_pos_candidates()
        return True

    def u_get_parsed_map_data_path(self, map_path: str) -> Path:
        relative_map_path = Path(map_path)
        if relative_map_path.parts and relative_map_path.parts[0] == "maps":
            relative_map_path = Path(*relative_map_path.parts[1:])
        return (_PARSED_MAPS_ROOT / relative_map_path).with_suffix(".marshal")

    def u_infer_symmetry_mode_from_core_positions(
        self,
        own_core_pos: Position,
        enemy_core_pos: Position,
    ) -> SymmetryMode | None:
        if enemy_core_pos == Position(
            self.width - 1 - own_core_pos.x,
            self.height - 1 - own_core_pos.y,
        ):
            return SymmetryMode.ROTATION
        if enemy_core_pos == Position(
            own_core_pos.x,
            self.height - 1 - own_core_pos.y,
        ):
            return SymmetryMode.MIRROR_X
        if enemy_core_pos == Position(
            self.width - 1 - own_core_pos.x,
            own_core_pos.y,
        ):
            return SymmetryMode.MIRROR_Y
        return None

    def u_apply_parsed_resource_order_to_known_resources(self) -> None:
        titanium_indices = set(self.parsed_titanium_indices)
        axionite_indices = set(self.parsed_axionite_indices)

        for tile in self.tiles_in_vision:
            building = tile.building
            if tile.environment == Environment.ORE_TITANIUM:
                if building.id is None or (
                    building.team == self.own_team
                    and building.entity_type in {
                        EntityType.ROAD,
                        EntityType.CONVEYOR,
                        EntityType.ARMOURED_CONVEYOR,
                        EntityType.BARRIER,
                    }
                ):
                    titanium_indices.add(tile.index)
                else:
                    titanium_indices.discard(tile.index)
            else:
                titanium_indices.discard(tile.index)

            if tile.environment == Environment.ORE_AXIONITE:
                if building.id is None or (
                    building.team == self.own_team
                    and building.entity_type in {
                        EntityType.ROAD,
                        EntityType.CONVEYOR,
                        EntityType.ARMOURED_CONVEYOR,
                        EntityType.BARRIER,
                    }
                ):
                    axionite_indices.add(tile.index)
                else:
                    axionite_indices.discard(tile.index)
            else:
                axionite_indices.discard(tile.index)

        self.known_accessible_titanium_indices = self.u_order_known_resource_indices(
            titanium_indices,
            self.parsed_titanium_indices,
        )
        self.known_accessible_axionite_indices = self.u_order_known_resource_indices(
            axionite_indices,
            self.parsed_axionite_indices,
        )

    def u_update_visible_core_center(self, tile: Tile) -> None:
        if tile.building.entity_type != EntityType.CORE or tile.building.team is None:
            return

        center_pos = self.ct.get_position(tile.building.id)
        if tile.building.team == self.own_team:
            if self.own_core_center_pos != center_pos:
                self.own_core_center_pos = center_pos
                self.u_set_core_source_indices(self.own_team, center_pos)
                self.u_reset_own_core_distance_initialization()
            return

        if tile.building.team == self.enemy_team:
            if self.enemy_core_center_pos != center_pos:
                self.enemy_core_center_pos = center_pos
                self.u_set_core_source_indices(self.enemy_team, center_pos)

    def u_infer_map(self) -> None:
        if (
            not ENABLE_MAP_DETECTION
            or self.is_map_known
            or self.own_core_center_pos is None
        ):
            return

        inference_start_time_ns = time.perf_counter_ns()
        key = u_format_fast_inference_key(
            self.width,
            self.height,
            self.own_core_center_pos,
        )
        candidate_maps = FAST_MAP_INFERENCE_BY_KEY.get(key, [])
        if not candidate_maps:
            return
        if len(candidate_maps) > 1:
            print(f"Map inference ambiguous for {key}: {candidate_maps}")
            return

        inferred_map_path = candidate_maps[0]
        parsed_map_data = PRELOADED_PARSED_MAP_DATA_BY_PATH.get(inferred_map_path)
        if parsed_map_data is None:
            parsed_map_path = self.u_get_parsed_map_data_path(inferred_map_path)
            if not parsed_map_path.exists():
                print(
                    f"Parsed map data missing for inferred map {inferred_map_path}: "
                    f"{parsed_map_path}"
                )
                return
            parsed_map_data = _build_runtime_parsed_map_data_from_legacy(
                marshal.loads(parsed_map_path.read_bytes())
            )

        if self.own_team == Team.A:
            own_resource_titanium_key = "titanium_by_core_a_dist"
            own_resource_axionite_key = "axionite_by_core_a_dist"
            enemy_core_center_key = "core_b_center"
            checkpoint_key = "core_a_to_core_b_checkpoints"
        else:
            own_resource_titanium_key = "titanium_by_core_b_dist"
            own_resource_axionite_key = "axionite_by_core_b_dist"
            enemy_core_center_key = "core_a_center"
            checkpoint_key = "core_b_to_core_a_checkpoints"

        enemy_core_pos = parsed_map_data[enemy_core_center_key]
        symmetry_mode = self.u_infer_symmetry_mode_from_core_positions(
            self.own_core_center_pos,
            enemy_core_pos,
        )

        self.is_map_known = True
        self.known_map_path = inferred_map_path
        self.parsed_map_tile_type_by_index = parsed_map_data["tile_type_by_index"]
        self.parsed_map_own_core_dist_by_index = parsed_map_data[
            "core_a_dist_by_index" if self.own_team == Team.A else "core_b_dist_by_index"
        ]
        self.parsed_titanium_indices = parsed_map_data[own_resource_titanium_key]
        self.parsed_axionite_indices = parsed_map_data[own_resource_axionite_key]
        self.enemy_core_checkpoint_positions = parsed_map_data[checkpoint_key]
        self.parsed_map_next_update_index = 0
        self.map_json_fully_loaded = False
        self.map_json_loaded_print_pending = False
        self.map_update_time_ns = 0
        self.u_reset_own_core_distance_initialization()
        self.u_clear_core_distance_dirty_indices()
        self.enemy_core_center_pos = enemy_core_pos
        self.enemy_core_source_indices = self.u_set_core_source_indices(
            self.enemy_team,
            self.enemy_core_center_pos,
        )
        if symmetry_mode is not None:
            self.symmetry_mode = symmetry_mode
            self.symmetry_mode_candidates = [symmetry_mode]
            self.enemy_core_center_pos_candidates = [
                (symmetry_mode, self.enemy_core_center_pos)
            ]

        self.u_apply_parsed_resource_order_to_known_resources()
        self.map_inference_time_ns = time.perf_counter_ns() - inference_start_time_ns

    def u_get_environment_for_parsed_tile_type(
        self,
        tile_type: int,
    ) -> Environment | None:
        if tile_type == PARSED_TILE_TYPE_WALL:
            return Environment.WALL
        if tile_type == PARSED_TILE_TYPE_TITANIUM:
            return Environment.ORE_TITANIUM
        if tile_type == PARSED_TILE_TYPE_AXIONITE:
            return Environment.ORE_AXIONITE
        if tile_type in {
            PARSED_TILE_TYPE_EMPTY,
            PARSED_TILE_TYPE_CORE,
        }:
            return Environment.EMPTY
        return None

    def u_get_environment_code(self, environment: Environment | None) -> int:
        if environment == Environment.WALL:
            return MAP_ENVIRONMENT_WALL
        if environment == Environment.ORE_TITANIUM:
            return MAP_ENVIRONMENT_TITANIUM
        if environment == Environment.ORE_AXIONITE:
            return MAP_ENVIRONMENT_AXIONITE
        return MAP_ENVIRONMENT_OTHER

    def u_get_parsed_own_core_dist_by_index(self, idx: int) -> int:
        if self.parsed_map_own_core_dist_by_index is None:
            return INF_DIST
        if self.enemy_core_source_by_index[idx]:
            return INF_DIST

        value = self.parsed_map_own_core_dist_by_index[idx]
        return INF_DIST if value >= CORE_DIST_INF else value

    def u_apply_parsed_own_core_dist_to_tiles(self, tiles: Iterable[Tile]) -> None:
        if self.parsed_map_own_core_dist_by_index is None:
            return

        for tile in tiles:
            tile.own_core_dist = self.u_get_parsed_own_core_dist_by_index(tile.index)
            self.own_core_dist_exact_by_index[tile.index] = 1

    def u_update_map(self) -> bool:
        if (
            not self.is_map_known
            or self.map_json_fully_loaded
            or self.parsed_map_tile_type_by_index is None
            or self.parsed_map_own_core_dist_by_index is None
            or self.ct is None
        ):
            return False

        start_time_ns = time.perf_counter_ns()
        while self.parsed_map_next_update_index < self.INITIAL_MAP_SIZE:
            idx = self.parsed_map_next_update_index
            tile_type = self.parsed_map_tile_type_by_index[idx]
            parsed_dist = self.u_get_parsed_own_core_dist_by_index(idx)

            if self.active_mask_by_index[idx]:
                tile = self.tiles_by_index[idx]
                parsed_environment = self.u_get_environment_for_parsed_tile_type(
                    tile_type
                )
                if parsed_environment is not None:
                    tile.environment = parsed_environment
                    self.environment_code_by_index[idx] = self.u_get_environment_code(
                        parsed_environment
                    )
                tile.u_refresh_core_distance_passability()
                tile.u_refresh_intrinsic_passability()
                tile.own_core_dist = parsed_dist
            else:
                self.own_core_dist_by_index[idx] = CORE_DIST_INF

            self.own_core_dist_exact_by_index[idx] = 1
            self.parsed_map_next_update_index = idx + 1

            if (
                ALLOCATED_MAP_AND_BOT_TIME_MUS - self.ct.get_cpu_time_elapsed()
                <= MAP_UPDATE_MIN_REMAINING_MUS
            ):
                self.map_update_time_ns += time.perf_counter_ns() - start_time_ns
                return False

        self.map_json_fully_loaded = True
        self.map_json_loaded_print_pending = True
        self.map_update_time_ns += time.perf_counter_ns() - start_time_ns
        self.own_core_dist_initialized = True
        self.own_core_dist_init_started = False
        self.u_reset_own_core_distance_init_buckets()
        self.u_reset_own_core_distance_incremental_update()
        self.u_reset_own_core_distance_manhattan_initialization()
        self.u_clear_core_distance_dirty_indices()
        return True

    def u_is_enemy_bot_on_ally_tile(self, target_tile: Tile) -> bool:
        if target_tile.building.id is None:
            return False
        return target_tile.building.team == self.own_team

    def u_enemy_turret_targets_self(self, enemy_turret_id: int) -> bool:
        enemy_turret_pos = self.ct.get_position(enemy_turret_id)
        enemy_turret_tile = self.u_get_pos_tile(enemy_turret_pos)
        turret_type = enemy_turret_tile.building.entity_type
        target_pos = self.current_pos

        if turret_type == EntityType.GUNNER:
            return self.u_gunner_covers_target(
                enemy_turret_pos,
                enemy_turret_tile.building.direction,
                target_pos,
                enemy_turret_tile.building.vision_radius_sq,
            )
        if turret_type == EntityType.SENTINEL:
            return self.u_sentinel_covers_target(
                enemy_turret_pos,
                enemy_turret_tile.building.direction,
                target_pos,
                enemy_turret_tile.building.vision_radius_sq,
            )
        if turret_type == EntityType.BREACH:
            return self.u_breach_covers_target(
                enemy_turret_pos,
                enemy_turret_tile.building.direction,
                target_pos,
            )
        return False

    def u_is_on_gunner_facing_ray(
        self,
        source_pos: Position,
        direction: Direction,
        target_pos: Position,
    ) -> bool:
        if direction == Direction.CENTRE:
            return False

        delta_x = target_pos.x - source_pos.x
        delta_y = target_pos.y - source_pos.y
        dir_x, dir_y = direction.delta()

        if delta_x == 0 and delta_y == 0:
            return False
        if dir_x == 0:
            return delta_x == 0 and delta_y * dir_y > 0
        if dir_y == 0:
            return delta_y == 0 and delta_x * dir_x > 0

        return (
            delta_x * dir_y == delta_y * dir_x
            and delta_x * dir_x > 0
            and delta_y * dir_y > 0
        )

    def u_get_gunner_first_targetable_tile(
        self,
        source_pos: Position,
        direction: Direction,
        radius_sq: int = GameConstants.GUNNER_VISION_RADIUS_SQ,
        current_round: int | None = None,
    ) -> Tile | None:
        if current_round is None:
            current_round = self.current_round

        for tile in self.u_get_gunner_ray_tiles(
            source_pos,
            direction,
            radius_sq,
        ):
            if tile.environment == Environment.WALL:
                return None
            if tile.is_core_of(self.enemy_team) or tile.is_core_of(self.own_team):
                return tile
            if tile.last_seen_turn != current_round:
                continue
            if tile.bot.id is not None or tile.building.id is not None:
                return tile
            if self.round_stopwatch.check_overtime_interval():
                break

        return None

    def u_gunner_covers_target(
        self,
        turret_pos: Position,
        direction: Direction,
        target_pos: Position,
        radius_sq: int,
    ) -> bool:
        if not self.u_is_in_bounds(target_pos):
            return False

        target_distance_sq = turret_pos.distance_squared(target_pos)
        if target_distance_sq == 0 or target_distance_sq > radius_sq:
            return False

        target_index = self.u_to_index(target_pos)
        return any(
            tile.index == target_index
            for tile in self.u_get_gunner_shootable_tiles(
                turret_pos,
                direction,
                radius_sq,
            )
        )

    def u_get_gunner_ray_tiles(
        self,
        source_pos: Position,
        direction: Direction,
        radius_sq: int = GameConstants.GUNNER_VISION_RADIUS_SQ,
    ) -> list[Tile]:
        if direction == Direction.CENTRE:
            return []

        delta_x, delta_y = direction.delta()
        max_steps = max(self.width, self.height)
        tiles: list[Tile] = []

        for step in range(1, max_steps + 1):
            target_pos = Position(
                source_pos.x + delta_x * step,
                source_pos.y + delta_y * step,
            )
            if not self.u_is_in_bounds(target_pos):
                break
            if source_pos.distance_squared(target_pos) > radius_sq:
                break
            tiles.append(self.u_get_pos_tile(target_pos))

            if self.round_stopwatch.check_overtime_interval():
                break

        return tiles

    def u_update_enemy_gunner_first_target_caches(self) -> None:
        current_round = self.current_round

        for gunner_tile in self.enemy_buildings_in_vision:
            if gunner_tile.last_seen_turn != current_round:
                continue

            building = gunner_tile.building
            if building.entity_type != EntityType.GUNNER:
                continue
            if not self.u_enemy_tile_is_targeted_by_titanium_supply_chain(
                gunner_tile.index
            ):
                continue

            radius_sq = building.vision_radius_sq
            if radius_sq is None:
                radius_sq = GameConstants.GUNNER_VISION_RADIUS_SQ

            direction = building.direction
            if direction is not None and direction != Direction.CENTRE:
                target_tile = self.u_get_gunner_first_targetable_tile(
                    gunner_tile.position,
                    direction,
                    radius_sq,
                    current_round,
                )
                if target_tile is not None:
                    self._u_mark_bytearray_index(
                        self.enemy_gunner_ray_first_target_touched_indices,
                        self.enemy_gunner_ray_first_target_by_index,
                        target_tile.index,
                    )

            for direction in Direction:
                if direction == Direction.CENTRE:
                    continue
                target_tile = self.u_get_gunner_first_targetable_tile(
                    gunner_tile.position,
                    direction,
                    radius_sq,
                    current_round,
                )
                if target_tile is None:
                    continue
                self._u_mark_bytearray_index(
                    self.enemy_spin_gunner_ray_first_target_touched_indices,
                    self.enemy_spin_gunner_ray_first_target_by_index,
                    target_tile.index,
                )

            if self.round_stopwatch.check_overtime_interval():
                break

    def u_enemy_titanium_harvester_has_adjacent_own_turret(self, harvester_tile) -> bool:
        if (
            harvester_tile.building.team != self.enemy_team
            or harvester_tile.environment != Environment.ORE_TITANIUM
        ):
            return False

        for adjacent_idx in self.u_iter_neighbor_indices(harvester_tile.index):
            adjacent_tile = self.tiles_by_index[adjacent_idx]
            if (
                adjacent_tile.building.team == self.own_team
                and adjacent_tile.building.entity_type
                in {
                    EntityType.GUNNER,
                    EntityType.SENTINEL,
                    EntityType.BREACH,
                }
            ):
                return True

        return False

    def u_get_gunner_shootable_tiles(
        self,
        source_pos: Position,
        direction: Direction,
        radius_sq: int = GameConstants.GUNNER_VISION_RADIUS_SQ,
        enemy_supply_chain_feeding_own_turret_blocks: bool = True,
    ) -> list[Tile]:
        shootable_tiles: list[Tile] = []
        current_round = self.current_round
        for target_tile in self.u_get_gunner_ray_tiles(
            source_pos,
            direction,
            radius_sq,
        ):
            if target_tile.environment == Environment.WALL:
                break

            if (
                target_tile.building.entity_type == EntityType.HARVESTER
                and (
                    source_pos.distance_squared(target_tile.position) <= 2
                    or self.u_enemy_titanium_harvester_has_adjacent_own_turret(
                        target_tile
                    )
                )
            ):
                break

            if (
                target_tile.building.id is not None
                and target_tile.building.team == self.own_team
                and target_tile.building.entity_type != EntityType.ROAD
            ):
                break

            if (
                enemy_supply_chain_feeding_own_turret_blocks
                and target_tile.last_seen_turn == current_round
                and target_tile.building.team == self.enemy_team
                and target_tile.building.entity_type in SUPPLY_LINK_TYPES
                and self.u_enemy_supply_chain_feeds_own_turret(target_tile.index)
            ):
                break

            shootable_tiles.append(target_tile)
            if self.round_stopwatch.check_overtime_interval():
                break
        return shootable_tiles

    def u_sentinel_covers_target(
        self,
        turret_pos: Position,
        direction: Direction,
        target_pos: Position,
        radius_sq: int,
    ) -> bool:
        if direction == Direction.CENTRE:
            return False

        delta_x, delta_y = direction.delta()
        max_steps = max(self.width, self.height)

        for step in range(max_steps + 1):
            line_pos = Position(
                turret_pos.x + delta_x * step,
                turret_pos.y + delta_y * step,
            )
            if turret_pos.distance_squared(line_pos) > radius_sq:
                break
            if (
                max(
                    abs(target_pos.x - line_pos.x),
                    abs(target_pos.y - line_pos.y),
                )
                <= 1
            ):
                return True

            if self.round_stopwatch.check_overtime_interval():
                break

        return False

    def u_breach_covers_target(
        self,
        turret_pos: Position,
        direction: Direction,
        target_pos: Position,
    ) -> bool:
        if direction == Direction.CENTRE:
            return False

        delta_x = target_pos.x - turret_pos.x
        delta_y = target_pos.y - turret_pos.y
        dir_x, dir_y = direction.delta()

        if delta_x == 0 and delta_y == 0:
            return False
        if (
            turret_pos.distance_squared(target_pos)
            > GameConstants.BREACH_ATTACK_RADIUS_SQ
        ):
            return False

        return (delta_x * dir_x) + (delta_y * dir_y) > 0

    def u_get_launcher_pickup_positions(self, source_pos: Position) -> list[Tile]:
        source_idx = self.u_to_index(source_pos)
        return [
            self.tiles_by_index[idx] for idx in self.u_iter_neighbor_indices(source_idx)
        ]

    def u_is_chokepoint(self, pos: Position) -> bool:
        """
        Return whether this tile matches the simple orthogonal chokepoint pattern.
        """
        if not self.u_is_in_bounds(pos):
            return False

        center_idx = self.u_to_index(pos)
        if not self.intrinsic_passable_by_index[center_idx]:
            return False

        intrinsic_passable_by_index = self.intrinsic_passable_by_index

        def is_intrinsically_passable_or_in_bounds(x: int, y: int) -> bool:
            if x < 0 or x >= self.width or y < 0 or y >= self.height:
                return False
            return intrinsic_passable_by_index[self.u_to_index_xy(x, y)]

        left_right_blocked = not is_intrinsically_passable_or_in_bounds(
            pos.x - 1, pos.y
        ) and not is_intrinsically_passable_or_in_bounds(pos.x + 1, pos.y)
        up_down_open = is_intrinsically_passable_or_in_bounds(
            pos.x, pos.y - 1
        ) and is_intrinsically_passable_or_in_bounds(pos.x, pos.y + 1)
        up_down_blocked = not is_intrinsically_passable_or_in_bounds(
            pos.x, pos.y - 1
        ) and not is_intrinsically_passable_or_in_bounds(pos.x, pos.y + 1)
        left_right_open = is_intrinsically_passable_or_in_bounds(
            pos.x - 1, pos.y
        ) and is_intrinsically_passable_or_in_bounds(pos.x + 1, pos.y)

        return (left_right_blocked and up_down_open) or (
            up_down_blocked and left_right_open
        )

    def u_get_supply_chain_source_label(
        self,
        tile: Tile,
        team: Team,
    ) -> SupplyChainLabel:
        if tile.building.id is None or tile.building.team != team:
            return SupplyChainLabel.NONE

        if tile.building.entity_type == EntityType.HARVESTER:
            if tile.environment == Environment.ORE_TITANIUM:
                return SupplyChainLabel.TITANIUM
            if tile.environment == Environment.ORE_AXIONITE:
                return SupplyChainLabel.AXIONITE
            return SupplyChainLabel.NONE

        return SupplyChainLabel.NONE

    def u_get_supply_chain_output_label(
        self,
        tile: Tile,
        team: Team,
    ) -> SupplyChainLabel:
        if tile.building.id is None or tile.building.team != team:
            return SupplyChainLabel.NONE

        if tile.building.entity_type not in RESOURCE_TARGET_TYPES:
            return SupplyChainLabel.NONE

        return tile.get_supply_chain_label(team)

    def u_can_preserve_visible_supply_chain_label(
        self,
        tile: Tile,
        team: Team,
    ) -> bool:
        supply_link_target_indices_in_vision = (
            self.own_supply_link_target_indices_in_vision
            if team == self.own_team
            else self.enemy_supply_link_target_indices_in_vision
        )
        if tile.environment == Environment.WALL:
            return False
        if tile.is_core_of(team):
            return True
        if tile.building.id is None:
            return tile.index in supply_link_target_indices_in_vision
        if tile.building.team == team and (
            tile.building.entity_type in RESOURCE_TARGET_TYPES
        ):
            return True
        if tile.building.entity_type in {EntityType.ROAD, EntityType.BARRIER}:
            return tile.index in supply_link_target_indices_in_vision
        return False

    def u_can_propagate_visible_supply_chain_label(
        self,
        tile: Tile,
        team: Team,
    ) -> bool:
        return (
            tile.last_seen_turn == self.current_round
            and tile.building.id is not None
            and tile.building.team == team
            and tile.building.entity_type in RESOURCE_TARGET_TYPES
        )

    def u_propagate_supply_chain_labels_for_team(
        self,
        queue: deque[Tile],
        team: Team,
        *,
        fill_only_unlabeled: bool,
    ) -> None:
        while queue:
            source_tile = queue.popleft()
            output_label = self.u_get_supply_chain_output_label(source_tile, team)
            if output_label == SupplyChainLabel.NONE:
                continue

            for target_tile in source_tile.u_get_resource_targets():
                if (
                    target_tile.last_seen_turn == self.current_round
                    and not self.u_can_preserve_visible_supply_chain_label(
                        target_tile,
                        team,
                    )
                ):
                    continue

                if fill_only_unlabeled:
                    if (
                        target_tile.get_supply_chain_label(team)
                        != SupplyChainLabel.NONE
                    ):
                        continue
                    target_tile.set_supply_chain_label(team, output_label)
                    label_changed = True
                else:
                    label_changed = target_tile.add_supply_chain_label(
                        team,
                        output_label,
                    )

                if not label_changed:
                    continue
                if self.u_can_propagate_visible_supply_chain_label(target_tile, team):
                    queue.append(target_tile)

            if self.round_stopwatch.check_overtime_interval():
                break

    def u_update_supply_chain_labels_for_team(self, team: Team) -> None:
        fresh_queue: deque[Tile] = deque()
        remembered_queue: deque[Tile] = deque()
        remembered_labels: list[tuple[Tile, SupplyChainLabel]] = []

        for tile in self.tiles_in_vision:
            remembered_labels.append((tile, tile.get_supply_chain_label(team)))
            tile.set_supply_chain_label(team, SupplyChainLabel.NONE)
            if self.round_stopwatch.check_overtime_interval():
                break

        for tile, _ in remembered_labels:
            source_label = self.u_get_supply_chain_source_label(tile, team)
            if source_label == SupplyChainLabel.NONE:
                continue
            tile.set_supply_chain_label(team, source_label)
            fresh_queue.append(tile)
            if self.round_stopwatch.check_overtime_interval():
                break

        self.u_propagate_supply_chain_labels_for_team(
            fresh_queue,
            team,
            fill_only_unlabeled=False,
        )

        for tile, remembered_label in remembered_labels:
            if remembered_label == SupplyChainLabel.NONE:
                continue
            if tile.get_supply_chain_label(team) != SupplyChainLabel.NONE:
                continue
            if not self.u_can_preserve_visible_supply_chain_label(tile, team):
                continue

            tile.set_supply_chain_label(team, remembered_label)
            if self.u_can_propagate_visible_supply_chain_label(tile, team):
                remembered_queue.append(tile)
            if self.round_stopwatch.check_overtime_interval():
                break

        self.u_propagate_supply_chain_labels_for_team(
            remembered_queue,
            team,
            fill_only_unlabeled=True,
        )

    def u_update_supply_chain_labels(self) -> None:
        self._u_update_supply_chain_labels_for_team_fast(self.own_team)
        self._u_update_supply_chain_labels_for_team_fast(self.enemy_team)

    def u_update_supply_information(self) -> None:
        check_overtime_interval = self.round_stopwatch.check_overtime_interval
        own_team = self.own_team
        enemy_team = self.enemy_team
        supply_chain_sink_types = (EntityType.HARVESTER, EntityType.FOUNDRY)

        enemy_supply_targets_in_vision = self.enemy_supply_targets_in_vision
        own_missing_supply_links = self.own_missing_supply_links
        enemy_missing_supply_links = self.enemy_missing_supply_links
        all_own_target_indices = self.all_own_supply_link_target_indices_in_vision
        own_target_indices = self.own_supply_link_target_indices_in_vision
        enemy_target_indices = self.enemy_supply_link_target_indices_in_vision
        own_supply_link_sources_by_target_index = (
            self.own_supply_link_source_indices_by_target_index_in_vision
        )
        enemy_supply_link_sources_by_target_index = (
            self.enemy_supply_link_source_indices_by_target_index_in_vision
        )

        enemy_supply_targets_in_vision.clear()
        own_missing_supply_links.clear()
        enemy_missing_supply_links.clear()
        all_own_target_indices.clear()
        own_target_indices.clear()
        enemy_target_indices.clear()
        own_supply_link_sources_by_target_index.clear()
        enemy_supply_link_sources_by_target_index.clear()

        for supply_link_tile in self.own_supply_links_in_vision:
            building = supply_link_tile.building
            supply_link_idx = supply_link_tile.index
            include_for_own = not (
                building.entity_type != EntityType.SPLITTER
                and building.team == own_team
                and supply_link_tile.bot.id is not None
                and supply_link_tile.bot.team == own_team
                and supply_link_tile.bot.entity_type == EntityType.BUILDER_BOT
                and supply_link_tile.position != self.current_pos
            )
            for target_tile in building.targets:
                if target_tile.environment == Environment.WALL:
                    continue
                target_idx = target_tile.index
                all_own_target_indices.add(target_idx)
                own_supply_link_sources_by_target_index.add(target_idx, supply_link_idx)
                if include_for_own:
                    own_target_indices.add(target_idx)
            if check_overtime_interval():
                break

        for supply_link_tile in self.enemy_supply_links_in_vision:
            supply_link_idx = supply_link_tile.index
            for target_tile in supply_link_tile.building.targets:
                if target_tile.environment == Environment.WALL:
                    continue
                target_idx = target_tile.index
                enemy_target_indices.add(target_idx)
                enemy_supply_link_sources_by_target_index.add(
                    target_idx,
                    supply_link_idx,
                )
            if check_overtime_interval():
                break

        self._u_update_supply_chain_labels_for_team_fast(own_team)
        self._u_update_supply_chain_labels_for_team_fast(enemy_team)
        self._u_update_supply_chain_union_find_for_team_fast(
            own_team,
            self.own_supply_links_in_vision,
        )
        self._u_update_supply_chain_union_find_for_team_fast(
            enemy_team,
            self.enemy_supply_links_in_vision,
        )

        enemy_supply_targets_append = enemy_supply_targets_in_vision.append
        own_missing_append = own_missing_supply_links.append
        enemy_missing_append = enemy_missing_supply_links.append
        own_core_source_by_index = self.own_core_source_by_index
        enemy_core_source_by_index = self.enemy_core_source_by_index

        for tile in self.tiles_in_vision:
            if tile.in_enemy_resource_range > 0:
                enemy_supply_targets_append(tile)

            tile_idx = tile.index
            building = tile.building
            building_entity_type = building.entity_type
            building_team = building.team

            if tile_idx in own_target_indices and not (
                (
                    building.id is not None
                    and building_team == own_team
                    and building_entity_type in SUPPLY_LINK_TYPES
                )
                or (
                    building_entity_type == EntityType.CORE
                    and building_team == own_team
                )
                or own_core_source_by_index[tile_idx]
                or (
                    building.id is not None
                    and building_team == own_team
                    and building_entity_type in supply_chain_sink_types
                )
            ):
                own_missing_append(tile)

            if tile_idx in enemy_target_indices and not (
                (
                    building.id is not None
                    and building_team == enemy_team
                    and building_entity_type in SUPPLY_LINK_TYPES
                )
                or (
                    building_entity_type == EntityType.CORE
                    and building_team == enemy_team
                )
                or enemy_core_source_by_index[tile_idx]
                or (
                    building.id is not None
                    and building_team == enemy_team
                    and building_entity_type in supply_chain_sink_types
                )
            ):
                enemy_missing_append(tile)

            if check_overtime_interval():
                break

    def _u_update_supply_chain_labels_for_team_fast(self, team: Team) -> None:
        check_overtime_interval = self.round_stopwatch.check_overtime_interval
        current_round = self.current_round
        tiles_in_vision = self.tiles_in_vision
        preservable_visible_entity_types = (EntityType.ROAD, EntityType.BARRIER)

        if team == self.own_team:
            labels_by_index = self.own_supply_chain_labels_by_index
            core_source_by_index = self.own_core_source_by_index
            supply_link_target_indices_in_vision = (
                self.own_supply_link_target_indices_in_vision
            )
        else:
            labels_by_index = self.enemy_supply_chain_labels_by_index
            core_source_by_index = self.enemy_core_source_by_index
            supply_link_target_indices_in_vision = (
                self.enemy_supply_link_target_indices_in_vision
            )

        remembered_tiles: list[Tile] = []
        remembered_labels: list[int] = []
        fresh_queue: deque[Tile] = deque()
        remembered_queue: deque[Tile] = deque()

        for tile in tiles_in_vision:
            tile_idx = tile.index
            remembered_tiles.append(tile)
            remembered_labels.append(labels_by_index[tile_idx])
            labels_by_index[tile_idx] = 0
            if check_overtime_interval():
                break

        for tile in remembered_tiles:
            building = tile.building
            source_label = 0
            if (
                building.id is not None
                and building.team == team
                and building.entity_type == EntityType.HARVESTER
            ):
                if tile.environment == Environment.ORE_TITANIUM:
                    source_label = int(SupplyChainLabel.TITANIUM)
                elif tile.environment == Environment.ORE_AXIONITE:
                    source_label = int(SupplyChainLabel.AXIONITE)
            if source_label == 0:
                continue
            labels_by_index[tile.index] = source_label
            fresh_queue.append(tile)
            if check_overtime_interval():
                break

        while fresh_queue:
            source_tile = fresh_queue.popleft()
            source_building = source_tile.building
            if (
                source_building.id is None
                or source_building.team != team
                or source_building.entity_type not in RESOURCE_TARGET_TYPES
            ):
                continue

            output_label = labels_by_index[source_tile.index]
            if output_label == 0:
                continue

            for target_tile in source_building.targets:
                target_idx = target_tile.index
                target_building = target_tile.building
                if target_tile.last_seen_turn == current_round:
                    can_preserve = False
                    if target_tile.environment != Environment.WALL:
                        target_building_entity_type = target_building.entity_type
                        if (
                            target_building_entity_type == EntityType.CORE
                            and target_building.team == team
                        ) or core_source_by_index[target_idx]:
                            can_preserve = True
                        elif target_building.id is None:
                            can_preserve = (
                                target_idx in supply_link_target_indices_in_vision
                            )
                        elif (
                            target_building.team == team
                            and target_building_entity_type in RESOURCE_TARGET_TYPES
                        ):
                            can_preserve = True
                        elif target_building_entity_type in preservable_visible_entity_types:
                            can_preserve = (
                                target_idx in supply_link_target_indices_in_vision
                            )
                    if not can_preserve:
                        continue

                current_label = labels_by_index[target_idx]
                updated_label = current_label | output_label
                if updated_label == current_label:
                    continue
                labels_by_index[target_idx] = updated_label

                if (
                    target_tile.last_seen_turn == current_round
                    and target_building.id is not None
                    and target_building.team == team
                    and target_building.entity_type in RESOURCE_TARGET_TYPES
                ):
                    fresh_queue.append(target_tile)

            if check_overtime_interval():
                break

        remembered_count = len(remembered_tiles)
        for i in range(remembered_count):
            tile = remembered_tiles[i]
            remembered_label = remembered_labels[i]
            if remembered_label == 0:
                continue

            tile_idx = tile.index
            if labels_by_index[tile_idx] != 0:
                continue

            building = tile.building
            building_entity_type = building.entity_type
            can_preserve = False
            if tile.environment != Environment.WALL:
                if (
                    building_entity_type == EntityType.CORE
                    and building.team == team
                ) or core_source_by_index[tile_idx]:
                    can_preserve = True
                elif building.id is None:
                    can_preserve = tile_idx in supply_link_target_indices_in_vision
                elif (
                    building.team == team
                    and building_entity_type in RESOURCE_TARGET_TYPES
                ):
                    can_preserve = True
                elif building_entity_type in preservable_visible_entity_types:
                    can_preserve = tile_idx in supply_link_target_indices_in_vision

            if not can_preserve:
                continue

            labels_by_index[tile_idx] = remembered_label
            if (
                tile.last_seen_turn == current_round
                and building.id is not None
                and building.team == team
                and building_entity_type in RESOURCE_TARGET_TYPES
            ):
                remembered_queue.append(tile)
            if check_overtime_interval():
                break

        while remembered_queue:
            source_tile = remembered_queue.popleft()
            source_building = source_tile.building
            if (
                source_building.id is None
                or source_building.team != team
                or source_building.entity_type not in RESOURCE_TARGET_TYPES
            ):
                continue

            output_label = labels_by_index[source_tile.index]
            if output_label == 0:
                continue

            for target_tile in source_building.targets:
                target_idx = target_tile.index
                target_building = target_tile.building
                if target_tile.last_seen_turn == current_round:
                    can_preserve = False
                    if target_tile.environment != Environment.WALL:
                        target_building_entity_type = target_building.entity_type
                        if (
                            target_building_entity_type == EntityType.CORE
                            and target_building.team == team
                        ) or core_source_by_index[target_idx]:
                            can_preserve = True
                        elif target_building.id is None:
                            can_preserve = (
                                target_idx in supply_link_target_indices_in_vision
                            )
                        elif (
                            target_building.team == team
                            and target_building_entity_type in RESOURCE_TARGET_TYPES
                        ):
                            can_preserve = True
                        elif target_building_entity_type in preservable_visible_entity_types:
                            can_preserve = (
                                target_idx in supply_link_target_indices_in_vision
                            )
                    if not can_preserve:
                        continue

                if labels_by_index[target_idx] != SupplyChainLabel.NONE:
                    continue
                labels_by_index[target_idx] = output_label

                if (
                    target_tile.last_seen_turn == current_round
                    and target_building.id is not None
                    and target_building.team == team
                    and target_building.entity_type in RESOURCE_TARGET_TYPES
                ):
                    remembered_queue.append(target_tile)

            if check_overtime_interval():
                break

    def _u_update_supply_chain_union_find_for_team_fast(
        self,
        team: Team,
        supply_links_in_vision: list[Tile],
    ) -> None:
        check_overtime_interval = self.round_stopwatch.check_overtime_interval
        current_round = self.current_round
        own_team = self.own_team
        tile_count = self.tile_count
        own_turret_types = (
            EntityType.GUNNER,
            EntityType.SENTINEL,
            EntityType.BREACH,
        )

        if team == own_team:
            parent_by_index = self.own_supply_chain_parent_by_index
            size_by_index = self.own_supply_chain_size_by_index
            active_by_index = self.own_supply_chain_active_by_index
            tile_count_by_index = self.own_supply_chain_tile_count_by_index
            harvester_count_by_index = self.own_supply_chain_harvester_count_by_index
            resource_item_count_by_index = (
                self.own_supply_chain_resource_item_count_by_index
            )
            max_euclidean_dist_to_self_by_index = (
                self.own_supply_chain_max_euclidean_dist_to_self_by_index
            )
            has_titanium_by_index = self.own_supply_chain_has_titanium_by_index
            has_raw_axionite_by_index = self.own_supply_chain_has_raw_axionite_by_index
            has_refined_axionite_by_index = (
                self.own_supply_chain_has_refined_axionite_by_index
            )
            feeds_own_turret_by_index = self.own_supply_chain_feeds_own_turret_by_index
            touched_indices = self.own_supply_chain_touched_indices
            turret_team = own_team
        else:
            parent_by_index = self.enemy_supply_chain_parent_by_index
            size_by_index = self.enemy_supply_chain_size_by_index
            active_by_index = self.enemy_supply_chain_active_by_index
            tile_count_by_index = self.enemy_supply_chain_tile_count_by_index
            harvester_count_by_index = self.enemy_supply_chain_harvester_count_by_index
            resource_item_count_by_index = (
                self.enemy_supply_chain_resource_item_count_by_index
            )
            max_euclidean_dist_to_self_by_index = (
                self.enemy_supply_chain_max_euclidean_dist_to_self_by_index
            )
            has_titanium_by_index = self.enemy_supply_chain_has_titanium_by_index
            has_raw_axionite_by_index = (
                self.enemy_supply_chain_has_raw_axionite_by_index
            )
            has_refined_axionite_by_index = (
                self.enemy_supply_chain_has_refined_axionite_by_index
            )
            feeds_own_turret_by_index = self.enemy_supply_chain_feeds_own_turret_by_index
            touched_indices = self.enemy_supply_chain_touched_indices
            turret_team = own_team

        def find_root(idx: int) -> int | None:
            if not active_by_index[idx]:
                return None

            root = idx
            while parent_by_index[root] != root:
                root = parent_by_index[root]

            while parent_by_index[idx] != idx:
                next_idx = parent_by_index[idx]
                parent_by_index[idx] = root
                idx = next_idx

            return root

        def union_indices(first_idx: int, second_idx: int) -> int | None:
            first_root = find_root(first_idx)
            second_root = find_root(second_idx)
            if first_root is None or second_root is None:
                return None
            if first_root == second_root:
                return first_root

            if size_by_index[first_root] < size_by_index[second_root]:
                first_root, second_root = second_root, first_root

            parent_by_index[second_root] = first_root
            size_by_index[first_root] += size_by_index[second_root]
            tile_count_by_index[first_root] += tile_count_by_index[second_root]
            harvester_count_by_index[first_root] += harvester_count_by_index[
                second_root
            ]
            resource_item_count_by_index[first_root] += resource_item_count_by_index[
                second_root
            ]
            max_euclidean_dist_to_self_by_index[first_root] = max(
                max_euclidean_dist_to_self_by_index[first_root],
                max_euclidean_dist_to_self_by_index[second_root],
            )
            has_titanium_by_index[first_root] |= has_titanium_by_index[second_root]
            has_raw_axionite_by_index[first_root] |= has_raw_axionite_by_index[
                second_root
            ]
            has_refined_axionite_by_index[first_root] |= (
                has_refined_axionite_by_index[second_root]
            )
            if feeds_own_turret_by_index is not None:
                feeds_own_turret_by_index[first_root] |= feeds_own_turret_by_index[
                    second_root
                ]
            return first_root

        for tile in supply_links_in_vision:
            tile_idx = tile.index
            if active_by_index[tile_idx]:
                continue
            parent_by_index[tile_idx] = tile_idx
            size_by_index[tile_idx] = 1
            active_by_index[tile_idx] = 1
            tile_count_by_index[tile_idx] = 1
            harvester_count_by_index[tile_idx] = 0
            resource_item_count_by_index[tile_idx] = 0
            max_euclidean_dist_to_self_by_index[tile_idx] = (
                self._u_get_euclidean_dist_to_self_by_index(tile_idx)
            )
            has_titanium_by_index[tile_idx] = 0
            has_raw_axionite_by_index[tile_idx] = 0
            has_refined_axionite_by_index[tile_idx] = 0
            if feeds_own_turret_by_index is not None:
                feeds_own_turret_by_index[tile_idx] = 0
            touched_indices.append(tile_idx)
            if check_overtime_interval():
                break

        for tile in supply_links_in_vision:
            tile_idx = tile.index
            for target_tile in tile.building.targets:
                target_building = target_tile.building
                if (
                    target_tile.last_seen_turn == current_round
                    and target_building.team == team
                    and target_building.entity_type in SUPPLY_LINK_TYPES
                ):
                    union_indices(tile_idx, target_tile.index)
            if check_overtime_interval():
                break

        counted_harvester_component_keys: set[int] = set()
        for tile in supply_links_in_vision:
            tile_idx = tile.index
            root = find_root(tile_idx)
            if root is None:
                continue

            building = tile.building
            if building.last_resource_onit_turn == current_round:
                resource_item_count_by_index[root] += 1
            if building.last_titanium_onit_turn == current_round:
                has_titanium_by_index[root] = 1
            if building.last_raw_axionite_onit_turn == current_round:
                has_raw_axionite_by_index[root] = 1
            if building.last_refined_axionite_onit_turn == current_round:
                has_refined_axionite_by_index[root] = 1

            feeds_own_turret = False
            for target_tile in building.targets:
                target_building = target_tile.building
                if (
                    target_tile.last_seen_turn == current_round
                    and target_building.team == team
                    and target_building.entity_type == EntityType.HARVESTER
                ):
                    pair_key = root * tile_count + target_tile.index
                    if pair_key not in counted_harvester_component_keys:
                        counted_harvester_component_keys.add(pair_key)
                        harvester_count_by_index[root] += 1
                        self._u_apply_connected_harvester_resource_flags(
                            target_tile,
                            root,
                            has_titanium_by_index,
                            has_raw_axionite_by_index,
                        )

            # Harvesters feed any orthogonally adjacent supplier, even when the
            # supplier does not target the harvester itself, such as a splitter
            # facing away from it.
            for adjacent_idx in self.u_iter_cardinal_neighbor_indices(tile_idx):
                adjacent_tile = self.tiles_by_index[adjacent_idx]
                adjacent_building = adjacent_tile.building
                if (
                    adjacent_tile.last_seen_turn == current_round
                    and adjacent_building.team == team
                    and adjacent_building.entity_type == EntityType.HARVESTER
                ):
                    pair_key = root * tile_count + adjacent_idx
                    if pair_key not in counted_harvester_component_keys:
                        counted_harvester_component_keys.add(pair_key)
                        harvester_count_by_index[root] += 1
                        self._u_apply_connected_harvester_resource_flags(
                            adjacent_tile,
                            root,
                            has_titanium_by_index,
                            has_raw_axionite_by_index,
                        )

                if (
                    not feeds_own_turret
                    and target_tile.last_seen_turn == current_round
                    and target_building.team == turret_team
                    and target_building.entity_type in own_turret_types
                ):
                    feeds_own_turret = True

            if feeds_own_turret:
                feeds_own_turret_by_index[root] = 1

            if check_overtime_interval():
                break

    def u_is_own_supply_link_occupied_by_other_builder(self, tile: Tile) -> bool:
        return bool(
            tile.building.team == self.own_team
            and tile.building.entity_type
            in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR, EntityType.BRIDGE}
            and tile.bot.id is not None
            and tile.bot.team == self.own_team
            and tile.bot.entity_type == EntityType.BUILDER_BOT
            and tile.position != self.current_pos
        )

    def _u_update_known_supply_link_indices_for_tiles(
        self,
        visible_supply_tiles: list[Tile],
        known_supply_indices: set[int],
    ) -> None:
        visible_supply_indices = {tile.index for tile in visible_supply_tiles}
        known_supply_indices.update(visible_supply_indices)

        for tile in self.tiles_in_vision:
            if tile.index in visible_supply_indices:
                continue
            if tile.index not in known_supply_indices:
                continue
            known_supply_indices.discard(tile.index)
            tile.last_patrolled_index = -1
            if self.round_stopwatch.check_overtime_interval():
                break

    def u_update_supply_patrol_indices(self) -> None:
        """
        Refresh persistent knowledge of allied and enemy supply-link tiles.

        Known suppliers remain cached after they leave vision. When a
        previously known tile becomes visible again and is no longer a
        supplier for that side, it is removed from the cache and its patrol
        marker is reset.
        """
        self._u_update_known_supply_link_indices_for_tiles(
            self.own_supply_links_in_vision,
            self.known_own_supply_link_indices,
        )
        self._u_update_known_supply_link_indices_for_tiles(
            self.enemy_supply_links_in_vision,
            self.known_enemy_supply_link_indices,
        )

    def u_enqueue_core_distance_index(
        self,
        idx: int,
        queue: list[int],
    ) -> None:
        if self.core_distance_enqueued_by_index[idx]:
            return
        self.core_distance_enqueued_by_index[idx] = 1
        queue.append(idx)

    def u_enqueue_core_distance_seed_index(
        self,
        idx: int,
        seed_queue: list[int],
    ) -> None:
        if self.core_distance_seed_enqueued_by_index[idx]:
            return
        self.core_distance_seed_enqueued_by_index[idx] = 1
        seed_queue.append(idx)

    def u_reset_own_core_distance_init_buckets(self) -> None:
        for bucket in self.own_core_dist_init_buckets:
            bucket.clear()
        bucket_heads = self.own_core_dist_init_bucket_heads
        bucket_heads[0] = 0
        bucket_heads[1] = 0
        bucket_heads[2] = 0
        self.own_core_dist_init_current_dist = 0
        self.own_core_dist_init_pending_count = 0

    def u_reset_own_core_distance_incremental_update(self) -> None:
        self.core_distance_enqueued_by_index[:] = b"\x00" * len(
            self.core_distance_enqueued_by_index
        )
        self.core_distance_seed_enqueued_by_index[:] = b"\x00" * len(
            self.core_distance_seed_enqueued_by_index
        )
        self.own_core_dist_incremental_queue.clear()
        self.own_core_dist_incremental_queue_head = 0
        self.own_core_dist_incremental_dirty_queue.clear()
        self.own_core_dist_incremental_dirty_queue_head = 0
        self.own_core_dist_incremental_seed_queue.clear()
        self.own_core_dist_incremental_seed_queue_head = 0

    def u_reset_own_core_distance_manhattan_initialization(self) -> None:
        self.own_core_dist_manhattan_init_started = False
        self.own_core_dist_manhattan_init_next_x = 0
        self.own_core_dist_manhattan_init_next_y = 0

    def u_update_core_distance_field_incremental(
        self,
        source_indices: list[int] | tuple[int, ...],
        source_by_index: bytearray,
        distance_by_index,
        dirty_indices: list[int] | tuple[int, ...],
    ) -> bool:
        if not source_indices:
            self.u_reset_own_core_distance_incremental_update()
            return True

        queue = self.own_core_dist_incremental_queue
        queue_head = self.own_core_dist_incremental_queue_head
        dirty_queue = self.own_core_dist_incremental_dirty_queue
        dirty_queue_head = self.own_core_dist_incremental_dirty_queue_head
        seed_queue = self.own_core_dist_incremental_seed_queue
        seed_queue_head = self.own_core_dist_incremental_seed_queue_head
        neighbor_indices_by_index = self.neighbor_indices_by_index
        neighbor_count_by_index = self.neighbor_count_by_index
        max_neighbor_count = self.MAX_NEIGHBOR_COUNT
        active_mask_by_index = self.active_mask_by_index
        core_distance_passable_by_index = self.core_distance_passable_by_index
        neighbor_step_costs_by_index = self.neighbor_step_costs_by_index

        if not queue and not dirty_queue and not seed_queue:
            for idx in source_indices:
                self.u_enqueue_core_distance_index(idx, queue)

        if dirty_indices:
            dirty_queue.extend(dirty_indices)

        while dirty_queue_head < len(dirty_queue):
            if self.round_stopwatch.check_overtime_interval():
                self.own_core_dist_incremental_queue_head = queue_head
                self.own_core_dist_incremental_dirty_queue_head = dirty_queue_head
                self.own_core_dist_incremental_seed_queue_head = seed_queue_head
                return False

            idx = dirty_queue[dirty_queue_head]
            dirty_queue_head += 1
            self.u_enqueue_core_distance_seed_index(idx, seed_queue)
            neighbor_base = idx * max_neighbor_count
            neighbor_count = neighbor_count_by_index[idx]
            for offset in range(neighbor_count):
                neighbor_idx = neighbor_indices_by_index[neighbor_base + offset]
                if not active_mask_by_index[neighbor_idx]:
                    continue
                self.u_enqueue_core_distance_seed_index(neighbor_idx, seed_queue)

        dirty_queue.clear()
        self.own_core_dist_incremental_dirty_queue_head = 0

        while seed_queue_head < len(seed_queue):
            if self.round_stopwatch.check_overtime_interval():
                self.own_core_dist_incremental_queue_head = queue_head
                self.own_core_dist_incremental_dirty_queue_head = 0
                self.own_core_dist_incremental_seed_queue_head = seed_queue_head
                return False

            self.u_enqueue_core_distance_index(seed_queue[seed_queue_head], queue)
            seed_queue_head += 1

        for idx in seed_queue:
            self.core_distance_seed_enqueued_by_index[idx] = 0
        seed_queue.clear()
        self.own_core_dist_incremental_seed_queue_head = 0

        while queue_head < len(queue):
            if self.round_stopwatch.check_overtime_interval():
                self.own_core_dist_incremental_queue_head = queue_head
                self.own_core_dist_incremental_dirty_queue_head = 0
                self.own_core_dist_incremental_seed_queue_head = 0
                return False

            idx = queue[queue_head]
            queue_head += 1
            self.core_distance_enqueued_by_index[idx] = 0

            if source_by_index[idx]:
                updated_dist = 0
            elif not core_distance_passable_by_index[idx]:
                updated_dist = CORE_DIST_INF
            else:
                best_neighbor_dist = CORE_DIST_INF
                neighbor_base = idx * max_neighbor_count
                neighbor_count = neighbor_count_by_index[idx]
                for offset in range(neighbor_count):
                    neighbor_idx = neighbor_indices_by_index[neighbor_base + offset]
                    if not active_mask_by_index[neighbor_idx]:
                        continue
                    neighbor_dist = distance_by_index[neighbor_idx]
                    if neighbor_dist >= CORE_DIST_INF:
                        continue
                    neighbor_dist += neighbor_step_costs_by_index[
                        neighbor_base + offset
                    ]
                    if neighbor_dist < best_neighbor_dist:
                        best_neighbor_dist = neighbor_dist
                updated_dist = best_neighbor_dist

            if updated_dist == distance_by_index[idx]:
                continue

            distance_by_index[idx] = updated_dist
            neighbor_base = idx * max_neighbor_count
            neighbor_count = neighbor_count_by_index[idx]
            for offset in range(neighbor_count):
                neighbor_idx = neighbor_indices_by_index[neighbor_base + offset]
                if not active_mask_by_index[neighbor_idx]:
                    continue
                self.u_enqueue_core_distance_index(neighbor_idx, queue)

        queue.clear()
        self.own_core_dist_incremental_queue_head = 0
        self.own_core_dist_incremental_dirty_queue_head = 0
        self.own_core_dist_incremental_seed_queue_head = 0
        return True

    def u_reset_own_core_distance_initialization(self) -> None:
        self.own_core_dist_initialized = False
        self.own_core_dist_init_started = False
        self.u_reset_own_core_distance_incremental_update()
        self.u_reset_own_core_distance_manhattan_initialization()
        self.own_core_dist_by_index[:] = self.core_inf_distances_by_index
        self.own_core_dist_exact_by_index[:] = b"\x00" * len(
            self.own_core_dist_exact_by_index
        )
        self.u_reset_own_core_distance_init_buckets()

    def u_start_own_core_distance_initialization(self) -> bool:
        if not self.own_core_source_indices:
            return False

        self.u_reset_own_core_distance_initialization()
        self.own_core_dist_init_started = True
        distance_by_index = self.own_core_dist_by_index
        bucket_zero = self.own_core_dist_init_buckets[0]
        pending_count = 0
        for source_idx in self.own_core_source_indices:
            if distance_by_index[source_idx] == 0:
                continue
            distance_by_index[source_idx] = 0
            bucket_zero.append(source_idx)
            pending_count += 1
        self.own_core_dist_init_pending_count = pending_count
        return pending_count > 0

    def u_continue_own_core_distance_initialization(
        self,
        max_finalized_nodes: int,
    ) -> bool:
        if self.own_core_dist_initialized:
            return True
        if not self.own_core_source_indices:
            return False
        if (
            not self.own_core_dist_init_started
            and not self.u_start_own_core_distance_initialization()
        ):
            return False

        distance_by_index = self.own_core_dist_by_index
        exact_by_index = self.own_core_dist_exact_by_index
        buckets = self.own_core_dist_init_buckets
        bucket_heads = self.own_core_dist_init_bucket_heads
        current_dist = self.own_core_dist_init_current_dist
        pending_count = self.own_core_dist_init_pending_count
        neighbor_indices_by_index = self.neighbor_indices_by_index
        neighbor_step_costs_by_index = self.neighbor_step_costs_by_index
        neighbor_count_by_index = self.neighbor_count_by_index
        max_neighbor_count = self.MAX_NEIGHBOR_COUNT
        active_mask_by_index = self.active_mask_by_index
        core_distance_passable_by_index = self.core_distance_passable_by_index
        finalized_nodes = 0

        while pending_count and finalized_nodes < max_finalized_nodes:
            bucket_idx = current_dist % 3
            bucket = buckets[bucket_idx]
            bucket_head = bucket_heads[bucket_idx]
            while bucket_head >= len(bucket):
                bucket.clear()
                bucket_heads[bucket_idx] = 0
                current_dist += 1
                if not pending_count:
                    break
                bucket_idx = current_dist % 3
                bucket = buckets[bucket_idx]
                bucket_head = bucket_heads[bucket_idx]

            if not pending_count:
                break

            current_idx = bucket[bucket_head]
            bucket_heads[bucket_idx] = bucket_head + 1
            pending_count -= 1
            if (
                exact_by_index[current_idx]
                or current_dist != distance_by_index[current_idx]
            ):
                continue

            exact_by_index[current_idx] = 1
            finalized_nodes += 1

            neighbor_base = current_idx * max_neighbor_count
            neighbor_count = neighbor_count_by_index[current_idx]
            for offset in range(neighbor_count):
                neighbor_idx = neighbor_indices_by_index[neighbor_base + offset]
                if (
                    not active_mask_by_index[neighbor_idx]
                    or exact_by_index[neighbor_idx]
                    or not core_distance_passable_by_index[neighbor_idx]
                ):
                    continue

                next_dist = (
                    current_dist + neighbor_step_costs_by_index[neighbor_base + offset]
                )
                if next_dist >= distance_by_index[neighbor_idx]:
                    continue

                distance_by_index[neighbor_idx] = next_dist
                buckets[next_dist % 3].append(neighbor_idx)
                pending_count += 1

            if self.round_stopwatch.check_overtime_interval():
                break

        self.own_core_dist_init_current_dist = current_dist
        self.own_core_dist_init_pending_count = pending_count

        if not pending_count:
            self.own_core_dist_initialized = True

        return self.own_core_dist_initialized

    def u_get_estimated_own_core_dist_by_index(self, idx: int) -> int:
        center = self.own_core_center_pos
        if center is None:
            return INF_DIST

        dx = abs(self.index_x_by_index[idx] - center.x) - 1
        dy = abs(self.index_y_by_index[idx] - center.y) - 1
        if dx < 0:
            dx = 0
        if dy < 0:
            dy = 0
        return dx + dy

    def u_get_own_core_dist_by_index(self, idx: int) -> int:
        if self.is_map_known and self.parsed_map_own_core_dist_by_index is not None:
            return self.u_get_parsed_own_core_dist_by_index(idx)

        value = self.own_core_dist_by_index[idx]
        if self.own_core_dist_initialized or self.own_core_dist_exact_by_index[idx]:
            return INF_DIST if value >= CORE_DIST_INF else value
        return self.u_get_estimated_own_core_dist_by_index(idx)

    def u_get_harvester_best_supply_tile(self, harvester_idx: int) -> int | None:
        if self.own_core_center_pos is None:
            self.u_calc_core_center_positions()

        tiles_by_index = self.tiles_by_index
        index_x_by_index = self.index_x_by_index
        index_y_by_index = self.index_y_by_index
        own_team = self.own_team
        own_core_center_pos = self.own_core_center_pos

        best_non_resource_idx: int | None = None
        best_non_resource_key: tuple[int, int, int, int] | None = None
        best_resource_idx: int | None = None
        best_resource_key: tuple[int, int, int, int] | None = None

        for adjacent_idx in self.u_iter_cardinal_neighbor_indices(harvester_idx):
            adjacent_tile = tiles_by_index[adjacent_idx]
            if adjacent_tile.environment == Environment.WALL:
                continue

            building = adjacent_tile.building
            building_type = building.entity_type
            if (
                building.id is not None
                and building.team != own_team
            ):
                continue
            if (
                building.team == own_team
                and (
                    building_type == EntityType.HARVESTER
                    or building_type in WEAPON_TARGET_TYPES
                )
            ):
                continue

            if own_core_center_pos is None:
                manhattan_dist = INF_DIST
            else:
                dx = abs(index_x_by_index[adjacent_idx] - own_core_center_pos.x) - 1
                dy = abs(index_y_by_index[adjacent_idx] - own_core_center_pos.y) - 1
                if dx < 0:
                    dx = 0
                if dy < 0:
                    dy = 0
                manhattan_dist = dx + dy

            key = (
                manhattan_dist,
                self.u_get_own_core_dist_by_index(adjacent_idx),
                index_x_by_index[adjacent_idx],
                index_y_by_index[adjacent_idx],
            )

            if adjacent_tile.environment in {
                Environment.ORE_TITANIUM,
                Environment.ORE_AXIONITE,
            }:
                if best_resource_key is None or key < best_resource_key:
                    best_resource_key = key
                    best_resource_idx = adjacent_idx
                continue

            if best_non_resource_key is None or key < best_non_resource_key:
                best_non_resource_key = key
                best_non_resource_idx = adjacent_idx

        if best_non_resource_idx is not None:
            return best_non_resource_idx
        return best_resource_idx

    def u_initialize_own_core_distance_field_manhattan(self) -> bool:
        center = self.own_core_center_pos
        if center is None:
            self.u_reset_own_core_distance_manhattan_initialization()
            return False

        if not self.own_core_dist_manhattan_init_started:
            distance_by_index = self.own_core_dist_by_index
            distance_by_index[:] = self.core_inf_distances_by_index
            self.own_core_dist_exact_by_index[:] = b"\x00" * len(
                self.own_core_dist_exact_by_index
            )
            self.own_core_dist_init_started = False
            self.u_reset_own_core_distance_init_buckets()
            self.u_reset_own_core_distance_incremental_update()
            self.own_core_dist_manhattan_init_started = True
            self.own_core_dist_manhattan_init_next_x = 0
            self.own_core_dist_manhattan_init_next_y = 0

        distance_by_index = self.own_core_dist_by_index
        x = self.own_core_dist_manhattan_init_next_x
        y = self.own_core_dist_manhattan_init_next_y

        while x < self.width:
            base_idx = x * self.INDEX_STRIDE

            while y < self.height:
                if self.round_stopwatch.check_overtime_interval():
                    self.own_core_dist_manhattan_init_next_x = x
                    self.own_core_dist_manhattan_init_next_y = y
                    return False

                distance_by_index[base_idx + y] = (
                    self.u_get_estimated_own_core_dist_by_index(base_idx + y)
                )
                y += 1

            x += 1
            y = 0

        self.u_reset_own_core_distance_manhattan_initialization()
        return True

    def u_is_vision_reachable_by_index(self, idx: int) -> bool:
        return self.vision_reachable_turn_by_index[idx] == self.current_round

    def u_get_next_step_towards_vision_reachable_by_index(
        self,
        target_idx: int,
    ) -> Tile | None:
        if not self.u_is_vision_reachable_by_index(target_idx):
            return None
        next_step_idx = self.vision_first_step_by_index[target_idx]
        if next_step_idx < 0:
            return None
        return self.tiles_by_index[next_step_idx]

    def u_get_next_step_towards_vision_reachable(
        self,
        target_pos: Position,
    ) -> Tile | None:
        if not self.u_is_in_bounds(target_pos):
            return None
        return self.u_get_next_step_towards_vision_reachable_by_index(
            self.u_to_index(target_pos)
        )

    def u_get_estimated_dist_to_self_by_index(self, idx: int) -> int:
        if self.u_is_vision_reachable_by_index(idx):
            return self.dist_to_self_by_index[idx]

        current_idx = self.u_to_index(self.current_pos)
        dx = abs(self.index_x_by_index[idx] - self.index_x_by_index[current_idx])
        dy = abs(self.index_y_by_index[idx] - self.index_y_by_index[current_idx])
        estimated_dist = dx if dx >= dy else dy
        if self.tiles_by_index[idx].last_seen_turn == self.current_round:
            return self.vision_max_dist_to_self_this_turn + estimated_dist + 1
        return estimated_dist

    def u_get_estimated_dist_to_self(self, pos: Position) -> int:
        return self.u_get_estimated_dist_to_self_by_index(self.u_to_index(pos))

    def u_refresh_vision_reachable_dist_to_self(self) -> None:
        source_idx = self.u_to_index(self.current_pos)
        current_round = self.current_round
        self.last_dist_to_self_source_idx = source_idx
        self.vision_max_dist_to_self_this_turn = 0
        self.found_vision_reachable_titanium_this_turn = False
        self.found_vision_reachable_axionite_this_turn = False
        self.is_caged = True
        queue = self.distance_queue_buffer_by_index
        queue.clear()
        queue_append = queue.append
        queue_head = 0
        source_neighbor_base = source_idx * self.MAX_NEIGHBOR_COUNT
        source_neighbor_count = self.neighbor_count_by_index[source_idx]
        source_dist = 1
        vision_reachable_turn_by_index = self.vision_reachable_turn_by_index
        vision_first_step_by_index = self.vision_first_step_by_index
        vision_reachable_turn_by_index[source_idx] = current_round
        self.dist_to_self_by_index[source_idx] = 0
        vision_first_step_by_index[source_idx] = -1
        neighbor_indices_by_index = self.neighbor_indices_by_index
        neighbor_count_by_index = self.neighbor_count_by_index
        max_neighbor_count = self.MAX_NEIGHBOR_COUNT
        active_mask_by_index = self.active_mask_by_index
        last_seen_turn_by_index = self.last_seen_turn_by_index
        environment_code_by_index = self.environment_code_by_index
        vision_bfs_passable_by_index = self.vision_bfs_passable_by_index
        bot_present_by_index = self.bot_present_by_index
        dist_to_self_by_index = self.dist_to_self_by_index
        check_overtime_interval = self.round_stopwatch.check_overtime_interval
        overtime_check_countdown = 32

        source_environment_code = environment_code_by_index[source_idx]
        if source_environment_code == MAP_ENVIRONMENT_TITANIUM:
            self.found_vision_reachable_titanium_this_turn = True
        elif source_environment_code == MAP_ENVIRONMENT_AXIONITE:
            self.found_vision_reachable_axionite_this_turn = True

        for offset in range(source_neighbor_count):
            neighbor_idx = neighbor_indices_by_index[source_neighbor_base + offset]
            if not active_mask_by_index[neighbor_idx]:
                continue
            if last_seen_turn_by_index[neighbor_idx] != current_round:
                self.is_caged = False
                continue
            if (
                not vision_bfs_passable_by_index[neighbor_idx]
                or bot_present_by_index[neighbor_idx]
            ):
                continue

            vision_reachable_turn_by_index[neighbor_idx] = current_round
            dist_to_self_by_index[neighbor_idx] = source_dist
            vision_first_step_by_index[neighbor_idx] = neighbor_idx
            queue_append(neighbor_idx)

        while queue_head < len(queue):
            current_idx = queue[queue_head]
            queue_head += 1
            current_dist = dist_to_self_by_index[current_idx]
            if current_dist > self.vision_max_dist_to_self_this_turn:
                self.vision_max_dist_to_self_this_turn = current_dist
            current_environment_code = environment_code_by_index[current_idx]
            if current_environment_code == MAP_ENVIRONMENT_TITANIUM:
                self.found_vision_reachable_titanium_this_turn = True
            elif current_environment_code == MAP_ENVIRONMENT_AXIONITE:
                self.found_vision_reachable_axionite_this_turn = True
            current_first_step_idx = vision_first_step_by_index[current_idx]
            next_dist = current_dist + 1

            neighbor_base = current_idx * max_neighbor_count
            neighbor_count = neighbor_count_by_index[current_idx]
            for offset in range(neighbor_count):
                neighbor_idx = neighbor_indices_by_index[neighbor_base + offset]
                if not active_mask_by_index[neighbor_idx]:
                    continue
                if last_seen_turn_by_index[neighbor_idx] != current_round:
                    self.is_caged = False
                    continue
                if (
                    not vision_bfs_passable_by_index[neighbor_idx]
                    or vision_reachable_turn_by_index[neighbor_idx] == current_round
                ):
                    continue

                vision_reachable_turn_by_index[neighbor_idx] = current_round
                dist_to_self_by_index[neighbor_idx] = next_dist
                vision_first_step_by_index[neighbor_idx] = current_first_step_idx
                queue_append(neighbor_idx)

            overtime_check_countdown -= 1
            if overtime_check_countdown == 0:
                if check_overtime_interval():
                    break
                overtime_check_countdown = 32

    def u_refresh_dist_to_self(self) -> None:
        self.u_refresh_vision_reachable_dist_to_self()

    def u_calculate_shortest_path(
        self,
        source_pos: Position,
        target_pos: Position,
        avoid_enemy_turrets: bool = True,
        avoid_other_builder_bots: bool = True,
    ) -> list[Tile]:
        if not self.u_is_in_bounds(source_pos) or not self.u_is_in_bounds(target_pos):
            return []

        source_tile = self.u_get_pos_tile(source_pos)
        target_tile = self.u_get_pos_tile(target_pos)
        source_idx = source_tile.index
        target_idx = target_tile.index
        tiles_by_index = self.tiles_by_index
        neighbor_indices_by_index = self.neighbor_indices_by_index
        neighbor_count_by_index = self.neighbor_count_by_index
        max_neighbor_count = self.MAX_NEIGHBOR_COUNT
        active_mask_by_index = self.active_mask_by_index
        intrinsic_passable_by_index = self.intrinsic_passable_by_index
        dist_to_self_by_index = self.dist_to_self_by_index
        dist_to_self_epoch_by_index = self.dist_to_self_epoch_by_index
        enemy_turret_target_by_index = self.enemy_turret_target_by_index
        bot_present_by_index = self.bot_present_by_index
        if source_pos == target_pos:
            return [source_tile]
        if not intrinsic_passable_by_index[target_idx]:
            return []

        if (
            self.compute_dist_to_self
            and self.dist_to_self_epoch != 0
            and source_pos == self.current_pos
            and dist_to_self_epoch_by_index[target_idx] == self.dist_to_self_epoch
        ):
            current_idx = target_idx
            path = [tiles_by_index[current_idx]]

            while current_idx != source_idx:
                if self.round_stopwatch.check_overtime_interval():
                    break

                next_dist_to_self = dist_to_self_by_index[current_idx] - 1
                best_candidate_idx: int | None = None
                best_candidate_score: tuple[int, int, int] | None = None

                neighbor_base = current_idx * max_neighbor_count
                neighbor_count = neighbor_count_by_index[current_idx]
                for offset in range(neighbor_count):
                    adjacent_idx = neighbor_indices_by_index[neighbor_base + offset]
                    if (
                        not active_mask_by_index[adjacent_idx]
                        or dist_to_self_epoch_by_index[adjacent_idx]
                        != self.dist_to_self_epoch
                        or dist_to_self_by_index[adjacent_idx] != next_dist_to_self
                    ):
                        continue
                    if (
                        avoid_enemy_turrets
                        and adjacent_idx != source_idx
                        and enemy_turret_target_by_index[adjacent_idx]
                    ):
                        continue
                    if (
                        avoid_other_builder_bots
                        and adjacent_idx != source_idx
                        and adjacent_idx != target_idx
                        and bot_present_by_index[adjacent_idx]
                    ):
                        continue
                    adjacent_x, adjacent_y = self.u_index_to_xy(adjacent_idx)
                    candidate_score = (
                        self.u_get_own_core_dist_by_index(adjacent_idx),
                        adjacent_x,
                        adjacent_y,
                    )
                    if (
                        best_candidate_score is None
                        or candidate_score < best_candidate_score
                    ):
                        best_candidate_score = candidate_score
                        best_candidate_idx = adjacent_idx

                if best_candidate_idx is None:
                    break

                current_idx = best_candidate_idx
                path.append(tiles_by_index[current_idx])

            if path[-1].index == source_idx:
                path.reverse()
                return path

        self.path_epoch += 1
        path_epoch = self.path_epoch
        seen_epoch_by_index = self.path_seen_epoch_by_index
        predecessor_by_index = self.path_predecessor_by_index
        seen_epoch_by_index[source_idx] = path_epoch
        predecessor_by_index[source_idx] = source_idx
        queue = self.path_queue_buffer_by_index
        queue.clear()
        queue.append(source_idx)
        queue_head = 0

        while queue_head < len(queue):
            if self.round_stopwatch.check_overtime_interval():
                break

            current_idx = queue[queue_head]
            queue_head += 1
            neighbor_base = current_idx * max_neighbor_count
            neighbor_count = neighbor_count_by_index[current_idx]
            for offset in range(neighbor_count):
                adjacent_idx = neighbor_indices_by_index[neighbor_base + offset]
                if (
                    not active_mask_by_index[adjacent_idx]
                    or seen_epoch_by_index[adjacent_idx] == path_epoch
                ):
                    continue

                if (
                    avoid_enemy_turrets
                    and adjacent_idx != target_idx
                    and enemy_turret_target_by_index[adjacent_idx]
                ):
                    continue
                if (
                    avoid_other_builder_bots
                    and adjacent_idx != source_idx
                    and adjacent_idx != target_idx
                    and bot_present_by_index[adjacent_idx]
                ):
                    continue
                if (
                    adjacent_idx != target_idx
                    and not intrinsic_passable_by_index[adjacent_idx]
                ):
                    continue

                predecessor_by_index[adjacent_idx] = current_idx
                seen_epoch_by_index[adjacent_idx] = path_epoch
                if adjacent_idx == target_idx:
                    path = [target_tile]
                    walk_idx = adjacent_idx

                    while walk_idx != source_idx:
                        previous_idx = predecessor_by_index[walk_idx]
                        if previous_idx == -1:
                            break
                        path.append(tiles_by_index[previous_idx])
                        walk_idx = previous_idx

                        if self.round_stopwatch.check_overtime_interval():
                            break

                    path.reverse()
                    return path

                queue.append(adjacent_idx)

        return []

    def u_calculate_shortest_path_astar(
        self,
        source_pos: Position,
        target_pos: Position,
        avoid_enemy_turrets: bool = True,
        avoid_other_builder_bots: bool = True,
    ) -> list[Tile]:
        if not self.u_is_in_bounds(source_pos) or not self.u_is_in_bounds(target_pos):
            return []

        source_tile = self.u_get_pos_tile(source_pos)
        target_tile = self.u_get_pos_tile(target_pos)
        source_idx = source_tile.index
        target_idx = target_tile.index
        if source_idx == target_idx:
            return [source_tile]

        reached_idx = self._u_run_astar_search(
            source_idx,
            target_idx,
            avoid_enemy_turrets=avoid_enemy_turrets,
            avoid_other_builder_bots=avoid_other_builder_bots,
        )
        if reached_idx is None:
            return []

        tiles_by_index = self.tiles_by_index
        predecessor_by_index = self.path_predecessor_by_index
        path = [target_tile]
        walk_idx = reached_idx
        check_overtime_interval = self.round_stopwatch.check_overtime_interval
        overtime_check_countdown = 16

        while walk_idx != source_idx:
            previous_idx = predecessor_by_index[walk_idx]
            if previous_idx == -1:
                return []
            path.append(tiles_by_index[previous_idx])
            walk_idx = previous_idx
            overtime_check_countdown -= 1
            if overtime_check_countdown == 0:
                if check_overtime_interval():
                    return []
                overtime_check_countdown = 16

        path.reverse()
        return path

    def u_get_next_step_towards_astar(
        self,
        source_pos: Position,
        target_pos: Position,
        avoid_enemy_turrets: bool = True,
        avoid_other_builder_bots: bool = True,
    ) -> Tile | None:
        if not self.u_is_in_bounds(source_pos) or not self.u_is_in_bounds(target_pos):
            return None

        source_idx = self.u_to_index(source_pos)
        target_idx = self.u_to_index(target_pos)
        if source_idx == target_idx:
            return self.tiles_by_index[source_idx]

        bridge_next_tile = self._u_get_next_step_towards_vision_bridge_astar(
            source_idx,
            target_idx,
            avoid_enemy_turrets=avoid_enemy_turrets,
        )
        if bridge_next_tile is not None:
            return bridge_next_tile

        reached_idx = self._u_run_astar_search(
            source_idx,
            target_idx,
            avoid_enemy_turrets=avoid_enemy_turrets,
            avoid_other_builder_bots=avoid_other_builder_bots,
        )
        if reached_idx is None:
            return None

        next_step_idx = self.path_first_step_by_index[reached_idx]
        if next_step_idx == -1:
            return None
        return self.tiles_by_index[next_step_idx]

    def _u_get_next_step_towards_vision_bridge_astar(
        self,
        source_idx: int,
        target_idx: int,
        avoid_enemy_turrets: bool = True,
    ) -> Tile | None:
        current_round = self.current_round
        if (
            source_idx != self.last_dist_to_self_source_idx
            or self.vision_reachable_turn_by_index[source_idx] != current_round
            or self.vision_reachable_turn_by_index[target_idx] == current_round
        ):
            return None

        active_mask_by_index = self.active_mask_by_index
        intrinsic_passable_by_index = self.intrinsic_passable_by_index
        if (
            not active_mask_by_index[source_idx]
            or not active_mask_by_index[target_idx]
            or not intrinsic_passable_by_index[target_idx]
        ):
            return None

        tiles_by_index = self.tiles_by_index
        neighbor_indices_by_index = self.neighbor_indices_by_index
        neighbor_count_by_index = self.neighbor_count_by_index
        max_neighbor_count = self.MAX_NEIGHBOR_COUNT
        enemy_turret_target_by_index = self.enemy_turret_target_by_index
        bot_present_by_index = self.bot_present_by_index
        vision_reachable_turn_by_index = self.vision_reachable_turn_by_index
        dist_to_self_by_index = self.dist_to_self_by_index
        vision_first_step_by_index = self.vision_first_step_by_index
        seen_epoch_by_index = self.path_seen_epoch_by_index
        predecessor_by_index = self.path_predecessor_by_index
        path_cost_by_index = self.path_cost_by_index
        index_x_by_index = self.index_x_by_index
        index_y_by_index = self.index_y_by_index
        u_get_own_core_dist_by_index = self.u_get_own_core_dist_by_index
        heappush_local = heappush
        heappop_local = heappop
        check_overtime_interval = self.round_stopwatch.check_overtime_interval

        self.path_epoch += 1
        path_epoch = self.path_epoch
        frontier = self.path_heap_buffer
        frontier.clear()

        source_x = index_x_by_index[source_idx]
        source_y = index_y_by_index[source_idx]
        target_x = index_x_by_index[target_idx]
        target_y = index_y_by_index[target_idx]
        dx = target_x - source_x
        if dx < 0:
            dx = -dx
        dy = target_y - source_y
        if dy < 0:
            dy = -dy
        seen_epoch_by_index[target_idx] = path_epoch
        predecessor_by_index[target_idx] = target_idx
        path_cost_by_index[target_idx] = 0
        heappush_local(
            frontier,
            (
                dx if dx >= dy else dy,
                0,
                0,
                u_get_own_core_dist_by_index(target_idx),
                target_x,
                target_y,
                target_idx,
            ),
        )

        best_bridge_idx = -1
        best_bridge_score: tuple[int, int, int, int, int] | None = None
        overtime_check_countdown = 16

        while frontier:
            overtime_check_countdown -= 1
            if overtime_check_countdown == 0:
                if check_overtime_interval():
                    break
                overtime_check_countdown = 16

            (
                current_lower_bound,
                current_cost,
                _,
                current_own_core_dist,
                current_x,
                current_y,
                current_idx,
            ) = heappop_local(frontier)
            if (
                seen_epoch_by_index[current_idx] != path_epoch
                or path_cost_by_index[current_idx] != current_cost
            ):
                continue
            if (
                best_bridge_score is not None
                and current_lower_bound > best_bridge_score[0]
            ):
                break

            if vision_reachable_turn_by_index[current_idx] == current_round:
                bridge_next_step_idx = (
                    predecessor_by_index[current_idx]
                    if current_idx == source_idx
                    else vision_first_step_by_index[current_idx]
                )
                if (
                    bridge_next_step_idx >= 0
                    and bridge_next_step_idx != source_idx
                    and not bot_present_by_index[bridge_next_step_idx]
                ):
                    candidate_score = (
                        current_cost + dist_to_self_by_index[current_idx],
                        current_cost,
                        current_own_core_dist,
                        current_x,
                        current_y,
                    )
                    if (
                        best_bridge_score is None
                        or candidate_score < best_bridge_score
                    ):
                        best_bridge_score = candidate_score
                        best_bridge_idx = current_idx
                continue

            neighbor_base = current_idx * max_neighbor_count
            neighbor_count = neighbor_count_by_index[current_idx]
            next_cost = current_cost + 1

            for offset in range(neighbor_count):
                adjacent_idx = neighbor_indices_by_index[neighbor_base + offset]
                if not active_mask_by_index[adjacent_idx]:
                    continue
                if (
                    avoid_enemy_turrets
                    and adjacent_idx != target_idx
                    and enemy_turret_target_by_index[adjacent_idx]
                ):
                    continue
                if (
                    adjacent_idx != target_idx
                    and not intrinsic_passable_by_index[adjacent_idx]
                ):
                    continue

                if seen_epoch_by_index[adjacent_idx] == path_epoch:
                    previous_cost = path_cost_by_index[adjacent_idx]
                    if next_cost > previous_cost:
                        continue
                    if next_cost == previous_cost:
                        if adjacent_idx != source_idx:
                            continue
                        existing_first_step_idx = predecessor_by_index[source_idx]
                        if (
                            existing_first_step_idx >= 0
                            and existing_first_step_idx != source_idx
                            and not bot_present_by_index[existing_first_step_idx]
                        ):
                            continue
                        if bot_present_by_index[current_idx]:
                            continue

                adjacent_x = index_x_by_index[adjacent_idx]
                adjacent_y = index_y_by_index[adjacent_idx]
                predecessor_by_index[adjacent_idx] = current_idx
                seen_epoch_by_index[adjacent_idx] = path_epoch
                path_cost_by_index[adjacent_idx] = next_cost

                heuristic_dx = adjacent_x - source_x
                if heuristic_dx < 0:
                    heuristic_dx = -heuristic_dx
                heuristic_dy = adjacent_y - source_y
                if heuristic_dy < 0:
                    heuristic_dy = -heuristic_dy
                heuristic = (
                    heuristic_dx if heuristic_dx >= heuristic_dy else heuristic_dy
                )
                lower_bound = next_cost + heuristic
                if (
                    best_bridge_score is not None
                    and lower_bound > best_bridge_score[0]
                ):
                    continue

                heappush_local(
                    frontier,
                    (
                        lower_bound,
                        next_cost,
                        0,
                        u_get_own_core_dist_by_index(adjacent_idx),
                        adjacent_x,
                        adjacent_y,
                        adjacent_idx,
                    ),
                )

        if best_bridge_idx < 0:
            return None

        next_step_idx = (
            predecessor_by_index[best_bridge_idx]
            if best_bridge_idx == source_idx
            else vision_first_step_by_index[best_bridge_idx]
        )
        if next_step_idx < 0:
            return None
        return tiles_by_index[next_step_idx]

    def u_get_next_step_to_builder_action_range_astar(
        self,
        source_pos: Position,
        target_pos: Position,
        avoid_enemy_turrets: bool = True,
        avoid_other_builder_bots: bool = True,
    ) -> Tile | None:
        if not self.u_is_in_bounds(source_pos) or not self.u_is_in_bounds(target_pos):
            return None

        source_idx = self.u_to_index(source_pos)
        target_idx = self.u_to_index(target_pos)
        direct_next_tile = self._u_get_next_step_to_builder_action_range_vision_reachable(
            source_idx,
            target_idx,
            avoid_enemy_turrets=avoid_enemy_turrets,
            avoid_other_builder_bots=avoid_other_builder_bots,
        )
        if direct_next_tile is not None:
            return direct_next_tile

        return self._u_get_next_step_to_builder_action_range_vision_join_astar(
            source_idx,
            target_idx,
            avoid_enemy_turrets=avoid_enemy_turrets,
            avoid_other_builder_bots=avoid_other_builder_bots,
        )

    def _u_get_next_step_to_builder_action_range_vision_reachable(
        self,
        source_idx: int,
        target_idx: int,
        avoid_enemy_turrets: bool = True,
        avoid_other_builder_bots: bool = True,
    ) -> Tile | None:
        current_round = self.current_round
        if (
            source_idx != self.last_dist_to_self_source_idx
            or self.vision_reachable_turn_by_index[source_idx] != current_round
        ):
            return None

        active_mask_by_index = self.active_mask_by_index
        vision_reachable_turn_by_index = self.vision_reachable_turn_by_index
        dist_to_self_by_index = self.dist_to_self_by_index
        vision_first_step_by_index = self.vision_first_step_by_index
        intrinsic_passable_by_index = self.intrinsic_passable_by_index
        enemy_turret_target_by_index = self.enemy_turret_target_by_index
        bot_present_by_index = self.bot_present_by_index
        index_x_by_index = self.index_x_by_index
        index_y_by_index = self.index_y_by_index
        u_get_own_core_dist_by_index = self.u_get_own_core_dist_by_index

        best_goal_idx = -1
        best_score: tuple[int, int, int, int] | None = None

        for goal_idx in self.u_iter_builder_action_target_indices(target_idx):
            if (
                not active_mask_by_index[goal_idx]
                or vision_reachable_turn_by_index[goal_idx] != current_round
            ):
                continue
            if not intrinsic_passable_by_index[goal_idx]:
                continue
            if avoid_enemy_turrets and enemy_turret_target_by_index[goal_idx]:
                continue
            if (
                avoid_other_builder_bots
                and goal_idx != source_idx
                and bot_present_by_index[goal_idx]
            ):
                continue
            next_step_idx = vision_first_step_by_index[goal_idx]
            if next_step_idx < 0:
                continue
            if (
                avoid_other_builder_bots
                and next_step_idx != source_idx
                and bot_present_by_index[next_step_idx]
            ):
                continue

            candidate_score = (
                dist_to_self_by_index[goal_idx],
                u_get_own_core_dist_by_index(goal_idx),
                index_x_by_index[goal_idx],
                index_y_by_index[goal_idx],
            )
            if best_score is None or candidate_score < best_score:
                best_score = candidate_score
                best_goal_idx = goal_idx

        if best_goal_idx < 0:
            return None

        next_step_idx = vision_first_step_by_index[best_goal_idx]
        return self.tiles_by_index[next_step_idx]

    def _u_get_next_step_to_builder_action_range_vision_join_astar(
        self,
        source_idx: int,
        target_idx: int,
        avoid_enemy_turrets: bool = True,
        avoid_other_builder_bots: bool = True,
    ) -> Tile | None:
        current_round = self.current_round
        if (
            source_idx != self.last_dist_to_self_source_idx
            or self.vision_reachable_turn_by_index[source_idx] != current_round
        ):
            return None

        active_mask_by_index = self.active_mask_by_index
        vision_reachable_turn_by_index = self.vision_reachable_turn_by_index
        dist_to_self_by_index = self.dist_to_self_by_index
        vision_first_step_by_index = self.vision_first_step_by_index
        intrinsic_passable_by_index = self.intrinsic_passable_by_index
        enemy_turret_target_by_index = self.enemy_turret_target_by_index
        bot_present_by_index = self.bot_present_by_index
        index_x_by_index = self.index_x_by_index
        index_y_by_index = self.index_y_by_index
        u_get_own_core_dist_by_index = self.u_get_own_core_dist_by_index
        seen_epoch_by_index = self.path_seen_epoch_by_index
        predecessor_by_index = self.path_predecessor_by_index
        path_cost_by_index = self.path_cost_by_index
        heappush_local = heappush
        heappop_local = heappop
        check_overtime_interval = self.round_stopwatch.check_overtime_interval

        if not active_mask_by_index[source_idx]:
            return None

        self.path_epoch += 1
        path_epoch = self.path_epoch
        frontier = self.path_heap_buffer
        frontier.clear()

        source_x = index_x_by_index[source_idx]
        source_y = index_y_by_index[source_idx]
        seeded_goal = False

        for goal_idx in self.u_iter_builder_action_target_indices(target_idx):
            if not active_mask_by_index[goal_idx]:
                continue
            if not intrinsic_passable_by_index[goal_idx]:
                continue
            if avoid_enemy_turrets and enemy_turret_target_by_index[goal_idx]:
                continue
            if (
                avoid_other_builder_bots
                and goal_idx != source_idx
                and bot_present_by_index[goal_idx]
            ):
                continue

            goal_x = index_x_by_index[goal_idx]
            goal_y = index_y_by_index[goal_idx]
            heuristic_dx = goal_x - source_x
            if heuristic_dx < 0:
                heuristic_dx = -heuristic_dx
            heuristic_dy = goal_y - source_y
            if heuristic_dy < 0:
                heuristic_dy = -heuristic_dy
            seen_epoch_by_index[goal_idx] = path_epoch
            predecessor_by_index[goal_idx] = goal_idx
            path_cost_by_index[goal_idx] = 0
            heappush_local(
                frontier,
                (
                    (
                        heuristic_dx
                        if heuristic_dx >= heuristic_dy
                        else heuristic_dy
                    ),
                    0,
                    0,
                    u_get_own_core_dist_by_index(goal_idx),
                    goal_x,
                    goal_y,
                    goal_idx,
                ),
            )
            seeded_goal = True

        if not seeded_goal:
            return None

        best_join_idx = -1
        best_join_score: tuple[int, int, int, int, int] | None = None
        overtime_check_countdown = 16

        while frontier:
            overtime_check_countdown -= 1
            if overtime_check_countdown == 0:
                if check_overtime_interval():
                    break
                overtime_check_countdown = 16

            (
                current_lower_bound,
                current_cost,
                _,
                current_own_core_dist,
                current_x,
                current_y,
                current_idx,
            ) = heappop_local(frontier)
            if (
                seen_epoch_by_index[current_idx] != path_epoch
                or path_cost_by_index[current_idx] != current_cost
            ):
                continue
            if (
                best_join_score is not None
                and current_lower_bound > best_join_score[0]
            ):
                break

            if vision_reachable_turn_by_index[current_idx] == current_round:
                join_next_step_idx = (
                    predecessor_by_index[current_idx]
                    if current_idx == source_idx
                    else vision_first_step_by_index[current_idx]
                )
                if (
                    join_next_step_idx >= 0
                    and join_next_step_idx != source_idx
                    and not bot_present_by_index[join_next_step_idx]
                ):
                    candidate_score = (
                        current_cost + dist_to_self_by_index[current_idx],
                        current_cost,
                        current_own_core_dist,
                        current_x,
                        current_y,
                    )
                    if (
                        best_join_score is None
                        or candidate_score < best_join_score
                    ):
                        best_join_score = candidate_score
                        best_join_idx = current_idx
                continue

            neighbor_base = current_idx * self.MAX_NEIGHBOR_COUNT
            neighbor_count = self.neighbor_count_by_index[current_idx]
            next_cost = current_cost + 1

            for offset in range(neighbor_count):
                adjacent_idx = self.neighbor_indices_by_index[neighbor_base + offset]
                if not active_mask_by_index[adjacent_idx]:
                    continue
                if (
                    avoid_enemy_turrets
                    and enemy_turret_target_by_index[adjacent_idx]
                ):
                    continue
                if not intrinsic_passable_by_index[adjacent_idx]:
                    continue

                if seen_epoch_by_index[adjacent_idx] == path_epoch:
                    previous_cost = path_cost_by_index[adjacent_idx]
                    if next_cost > previous_cost:
                        continue
                    if next_cost == previous_cost:
                        if adjacent_idx != source_idx:
                            continue
                        existing_first_step_idx = predecessor_by_index[source_idx]
                        if (
                            existing_first_step_idx >= 0
                            and existing_first_step_idx != source_idx
                            and not bot_present_by_index[existing_first_step_idx]
                        ):
                            continue
                        if bot_present_by_index[current_idx]:
                            continue

                adjacent_x = index_x_by_index[adjacent_idx]
                adjacent_y = index_y_by_index[adjacent_idx]
                predecessor_by_index[adjacent_idx] = current_idx
                seen_epoch_by_index[adjacent_idx] = path_epoch
                path_cost_by_index[adjacent_idx] = next_cost

                heuristic_dx = adjacent_x - source_x
                if heuristic_dx < 0:
                    heuristic_dx = -heuristic_dx
                heuristic_dy = adjacent_y - source_y
                if heuristic_dy < 0:
                    heuristic_dy = -heuristic_dy
                lower_bound = next_cost + (
                    heuristic_dx if heuristic_dx >= heuristic_dy else heuristic_dy
                )
                if (
                    best_join_score is not None
                    and lower_bound > best_join_score[0]
                ):
                    continue

                heappush_local(
                    frontier,
                    (
                        lower_bound,
                        next_cost,
                        0,
                        u_get_own_core_dist_by_index(adjacent_idx),
                        adjacent_x,
                        adjacent_y,
                        adjacent_idx,
                    ),
                )

        if best_join_idx < 0:
            return None

        next_step_idx = (
            predecessor_by_index[best_join_idx]
            if best_join_idx == source_idx
            else vision_first_step_by_index[best_join_idx]
        )
        if next_step_idx < 0 or next_step_idx == source_idx:
            return None
        return self.tiles_by_index[next_step_idx]

    def _u_run_astar_search(
        self,
        source_idx: int,
        target_idx: int,
        avoid_enemy_turrets: bool = True,
        avoid_other_builder_bots: bool = True,
        stop_in_builder_action_range: bool = False,
    ) -> int | None:
        tiles_by_index = self.tiles_by_index
        neighbor_indices_by_index = self.neighbor_indices_by_index
        neighbor_count_by_index = self.neighbor_count_by_index
        max_neighbor_count = self.MAX_NEIGHBOR_COUNT
        active_mask_by_index = self.active_mask_by_index
        intrinsic_passable_by_index = self.intrinsic_passable_by_index
        enemy_turret_target_by_index = self.enemy_turret_target_by_index
        bot_present_by_index = self.bot_present_by_index
        seen_epoch_by_index = self.path_seen_epoch_by_index
        predecessor_by_index = self.path_predecessor_by_index
        first_step_by_index = self.path_first_step_by_index
        first_step_requires_new_road_by_index = (
            self.path_first_step_requires_new_road_by_index
        )
        path_cost_by_index = self.path_cost_by_index
        index_x_by_index = self.index_x_by_index
        index_y_by_index = self.index_y_by_index
        target_x = index_x_by_index[target_idx]
        target_y = index_y_by_index[target_idx]
        heappush_local = heappush
        heappop_local = heappop
        check_overtime_interval = self.round_stopwatch.check_overtime_interval

        if not stop_in_builder_action_range and not intrinsic_passable_by_index[target_idx]:
            return None

        self.path_epoch += 1
        path_epoch = self.path_epoch
        frontier = self.path_heap_buffer
        frontier.clear()

        source_x = index_x_by_index[source_idx]
        source_y = index_y_by_index[source_idx]
        seen_epoch_by_index[source_idx] = path_epoch
        predecessor_by_index[source_idx] = source_idx
        first_step_by_index[source_idx] = -1
        first_step_requires_new_road_by_index[source_idx] = 0
        path_cost_by_index[source_idx] = 0

        if self.is_map_known and self.parsed_map_own_core_dist_by_index is not None:
            source_own_core_dist = self.parsed_map_own_core_dist_by_index[source_idx]
            use_parsed_core_dist = True
        else:
            use_parsed_core_dist = False
            source_own_core_dist = INF_DIST
        own_core_dist_initialized = self.own_core_dist_initialized
        own_core_dist_by_index = self.own_core_dist_by_index
        own_core_dist_exact_by_index = self.own_core_dist_exact_by_index
        own_core_center_pos = self.own_core_center_pos
        if own_core_center_pos is not None:
            own_core_center_x = own_core_center_pos.x
            own_core_center_y = own_core_center_pos.y
        else:
            own_core_center_x = -1
            own_core_center_y = -1

        if not use_parsed_core_dist:
            if own_core_dist_initialized or own_core_dist_exact_by_index[source_idx]:
                source_own_core_dist = own_core_dist_by_index[source_idx]
                if source_own_core_dist >= CORE_DIST_INF:
                    source_own_core_dist = INF_DIST
            elif own_core_center_pos is not None:
                dx = source_x - own_core_center_x
                if dx < 0:
                    dx = -dx
                dx -= 1
                if dx < 0:
                    dx = 0
                dy = source_y - own_core_center_y
                if dy < 0:
                    dy = -dy
                dy -= 1
                if dy < 0:
                    dy = 0
                source_own_core_dist = dx + dy

        dx = source_x - target_x
        if dx < 0:
            dx = -dx
        dy = source_y - target_y
        if dy < 0:
            dy = -dy
        if stop_in_builder_action_range:
            source_heuristic = dx if dx >= dy else dy
            if source_heuristic > 0:
                source_heuristic -= 1
        else:
            source_heuristic = dx if dx >= dy else dy
        heappush_local(
            frontier,
            (
                source_heuristic,
                0,
                0,
                source_own_core_dist,
                source_x,
                source_y,
                source_idx,
            ),
        )

        overtime_check_countdown = 16

        while frontier:
            overtime_check_countdown -= 1
            if overtime_check_countdown == 0:
                if check_overtime_interval():
                    return None
                overtime_check_countdown = 16

            _, current_cost, _, _, _, _, current_idx = heappop_local(frontier)
            if (
                seen_epoch_by_index[current_idx] != path_epoch
                or path_cost_by_index[current_idx] != current_cost
            ):
                continue

            current_x = index_x_by_index[current_idx]
            current_y = index_y_by_index[current_idx]
            if stop_in_builder_action_range:
                goal_dx = current_x - target_x
                if goal_dx < 0:
                    goal_dx = -goal_dx
                goal_dy = current_y - target_y
                if goal_dy < 0:
                    goal_dy = -goal_dy
                if goal_dx * goal_dx + goal_dy * goal_dy <= 2:
                    return current_idx
            elif current_idx == target_idx:
                return current_idx

            neighbor_base = current_idx * max_neighbor_count
            neighbor_count = neighbor_count_by_index[current_idx]
            next_cost = current_cost + 1
            current_first_step_idx = first_step_by_index[current_idx]

            for offset in range(neighbor_count):
                adjacent_idx = neighbor_indices_by_index[neighbor_base + offset]
                if not active_mask_by_index[adjacent_idx]:
                    continue
                if (
                    avoid_enemy_turrets
                    and adjacent_idx != target_idx
                    and enemy_turret_target_by_index[adjacent_idx]
                ):
                    continue
                if (
                    avoid_other_builder_bots
                    and adjacent_idx != source_idx
                    and adjacent_idx != target_idx
                    and bot_present_by_index[adjacent_idx]
                ):
                    continue
                if (
                    adjacent_idx != target_idx
                    and not intrinsic_passable_by_index[adjacent_idx]
                ):
                    continue
                if current_first_step_idx == -1:
                    first_step_requires_new_road = int(
                        tiles_by_index[adjacent_idx].building.id is None
                    )
                else:
                    first_step_requires_new_road = (
                        first_step_requires_new_road_by_index[current_idx]
                    )
                if (
                    seen_epoch_by_index[adjacent_idx] == path_epoch
                    and (
                        next_cost > path_cost_by_index[adjacent_idx]
                        or (
                            next_cost == path_cost_by_index[adjacent_idx]
                            and first_step_requires_new_road
                            >= first_step_requires_new_road_by_index[adjacent_idx]
                        )
                    )
                ):
                    continue

                adjacent_x = index_x_by_index[adjacent_idx]
                adjacent_y = index_y_by_index[adjacent_idx]
                predecessor_by_index[adjacent_idx] = current_idx
                first_step_by_index[adjacent_idx] = (
                    adjacent_idx
                    if current_first_step_idx == -1
                    else current_first_step_idx
                )
                first_step_requires_new_road_by_index[adjacent_idx] = (
                    first_step_requires_new_road
                )
                seen_epoch_by_index[adjacent_idx] = path_epoch
                path_cost_by_index[adjacent_idx] = next_cost

                if use_parsed_core_dist:
                    own_core_dist = self.parsed_map_own_core_dist_by_index[adjacent_idx]
                elif (
                    own_core_dist_initialized
                    or own_core_dist_exact_by_index[adjacent_idx]
                ):
                    own_core_dist = own_core_dist_by_index[adjacent_idx]
                    if own_core_dist >= CORE_DIST_INF:
                        own_core_dist = INF_DIST
                elif own_core_center_pos is not None:
                    own_core_dx = adjacent_x - own_core_center_x
                    if own_core_dx < 0:
                        own_core_dx = -own_core_dx
                    own_core_dx -= 1
                    if own_core_dx < 0:
                        own_core_dx = 0
                    own_core_dy = adjacent_y - own_core_center_y
                    if own_core_dy < 0:
                        own_core_dy = -own_core_dy
                    own_core_dy -= 1
                    if own_core_dy < 0:
                        own_core_dy = 0
                    own_core_dist = own_core_dx + own_core_dy
                else:
                    own_core_dist = INF_DIST

                heuristic_dx = adjacent_x - target_x
                if heuristic_dx < 0:
                    heuristic_dx = -heuristic_dx
                heuristic_dy = adjacent_y - target_y
                if heuristic_dy < 0:
                    heuristic_dy = -heuristic_dy
                heuristic = (
                    heuristic_dx if heuristic_dx >= heuristic_dy else heuristic_dy
                )
                if stop_in_builder_action_range and heuristic > 0:
                    heuristic -= 1

                heappush_local(
                    frontier,
                    (
                        next_cost + heuristic,
                        next_cost,
                        first_step_requires_new_road,
                        own_core_dist,
                        adjacent_x,
                        adjacent_y,
                        adjacent_idx,
                    ),
                )

        return None

    def u_calculate_shortest_path_to_frontier(
        self,
        source_pos: Position,
        avoid_enemy_turrets: bool = True,
        avoid_other_builder_bots: bool = True,
        frontier_tiebreak_multipliers: tuple[int, int] = (1, 1),
    ) -> list[Tile]:
        if not self.u_is_in_bounds(source_pos):
            return []

        frontier_indices = self.frontier_expand_cached_unseen_indices
        if not frontier_indices:
            return []

        source_tile = self.u_get_pos_tile(source_pos)
        source_idx = source_tile.index
        current_round = self.current_round
        if (
            source_idx != self.last_dist_to_self_source_idx
            or self.vision_reachable_turn_by_index[source_idx] != current_round
        ):
            return []

        tiles_by_index = self.tiles_by_index
        neighbor_indices_by_index = self.neighbor_indices_by_index
        neighbor_count_by_index = self.neighbor_count_by_index
        max_neighbor_count = self.MAX_NEIGHBOR_COUNT
        active_mask_by_index = self.active_mask_by_index
        enemy_turret_target_by_index = self.enemy_turret_target_by_index
        bot_present_by_index = self.bot_present_by_index
        vision_reachable_turn_by_index = self.vision_reachable_turn_by_index
        dist_to_self_by_index = self.dist_to_self_by_index
        index_x_by_index = self.index_x_by_index
        index_y_by_index = self.index_y_by_index
        frontier_x_multiplier, frontier_y_multiplier = frontier_tiebreak_multipliers
        u_get_own_core_dist_by_index = self.u_get_own_core_dist_by_index

        best_frontier_idx = -1
        best_entry_idx = -1
        best_score: tuple[int, int, int, int, int] | None = None

        for frontier_idx in frontier_indices:
            if not active_mask_by_index[frontier_idx]:
                continue
            frontier_tile = tiles_by_index[frontier_idx]
            if frontier_tile.last_seen_turn != -1:
                continue
            if (
                avoid_enemy_turrets
                and enemy_turret_target_by_index[frontier_idx]
            ):
                continue
            if (
                avoid_other_builder_bots
                and frontier_idx != source_idx
                and bot_present_by_index[frontier_idx]
            ):
                continue

            frontier_entry_idx = -1
            frontier_entry_score: tuple[int, int, int] | None = None
            neighbor_base = frontier_idx * max_neighbor_count
            neighbor_count = neighbor_count_by_index[frontier_idx]

            for offset in range(neighbor_count):
                entry_idx = neighbor_indices_by_index[neighbor_base + offset]
                if (
                    not active_mask_by_index[entry_idx]
                    or vision_reachable_turn_by_index[entry_idx] != current_round
                ):
                    continue

                entry_score = (
                    dist_to_self_by_index[entry_idx],
                    index_x_by_index[entry_idx],
                    index_y_by_index[entry_idx],
                )
                if (
                    frontier_entry_score is None
                    or entry_score < frontier_entry_score
                ):
                    frontier_entry_score = entry_score
                    frontier_entry_idx = entry_idx

            if frontier_entry_idx < 0 or frontier_entry_score is None:
                continue

            candidate_score = (
                u_get_own_core_dist_by_index(frontier_idx),
                frontier_x_multiplier * index_x_by_index[frontier_idx],
                frontier_y_multiplier * index_y_by_index[frontier_idx],
            )
            if best_score is None or candidate_score < best_score:
                best_score = candidate_score
                best_frontier_idx = frontier_idx
                best_entry_idx = frontier_entry_idx

            if self.round_stopwatch.check_overtime_interval():
                return []

        if best_frontier_idx < 0:
            return []

        frontier_tile = tiles_by_index[best_frontier_idx]
        if best_entry_idx == source_idx:
            return [source_tile, frontier_tile]

        path = [frontier_tile]
        current_idx = best_entry_idx
        current_dist = dist_to_self_by_index[current_idx]

        while True:
            path.append(tiles_by_index[current_idx])
            if current_idx == source_idx:
                break
            if current_dist == 0:
                return []

            predecessor_idx = -1
            predecessor_score: tuple[int, int] | None = None
            neighbor_base = current_idx * max_neighbor_count
            neighbor_count = neighbor_count_by_index[current_idx]

            for offset in range(neighbor_count):
                adjacent_idx = neighbor_indices_by_index[neighbor_base + offset]
                if (
                    not active_mask_by_index[adjacent_idx]
                    or vision_reachable_turn_by_index[adjacent_idx] != current_round
                    or dist_to_self_by_index[adjacent_idx] != current_dist - 1
                ):
                    continue

                candidate_predecessor_score = (
                    index_x_by_index[adjacent_idx],
                    index_y_by_index[adjacent_idx],
                )
                if (
                    predecessor_score is None
                    or candidate_predecessor_score < predecessor_score
                ):
                    predecessor_score = candidate_predecessor_score
                    predecessor_idx = adjacent_idx

            if predecessor_idx < 0:
                return []

            current_idx = predecessor_idx
            current_dist -= 1

            if self.round_stopwatch.check_overtime_interval():
                return []

        path.reverse()
        return path

    def u_update_distances(self) -> None:
        sw = Stopwatch("Map distances")
        sw.start()
        self.u_refresh_vision_reachable_dist_to_self()
        sw.lap("Self distance field")

        if self.is_map_known and self.parsed_map_own_core_dist_by_index is not None:
            self.u_apply_parsed_own_core_dist_to_tiles(self.tiles_in_vision)
            self.u_clear_core_distance_dirty_indices()
            self.u_reset_own_core_distance_incremental_update()
            self.u_reset_own_core_distance_manhattan_initialization()
            sw.lap("Own core field")
            sw.log()
            return

        dirty_indices = self.core_distance_dirty_indices
        has_pending_own_core_dist_incremental_update = bool(
            self.own_core_dist_incremental_queue
            or self.own_core_dist_incremental_dirty_queue
            or self.own_core_dist_incremental_seed_queue
        )

        if self.own_core_source_indices and (
            not self.own_core_dist_initialized
            or has_pending_own_core_dist_incremental_update
            or (dirty_indices and not DISABLE_CORRECT_OWN_CORE_DISTANCE)
        ):
            if DISABLE_CORRECT_OWN_CORE_DISTANCE:
                if self.u_initialize_own_core_distance_field_manhattan():
                    self.own_core_dist_initialized = True
            elif not self.own_core_dist_initialized:
                if dirty_indices and self.own_core_dist_init_started:
                    self.u_reset_own_core_distance_initialization()
                self.u_continue_own_core_distance_initialization(
                    OWN_CORE_DISTANCE_INIT_SETTLE_BUDGET
                )
            else:
                self.u_update_core_distance_field_incremental(
                    self.own_core_source_indices,
                    self.own_core_source_by_index,
                    self.own_core_dist_by_index,
                    dirty_indices,
                )

        sw.lap("Own core field")

        self.u_clear_core_distance_dirty_indices()

        sw.log()
