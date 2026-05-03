from __future__ import annotations

import argparse
import concurrent.futures
import copy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BOT_ROOT = REPO_ROOT / "bots" / "pong"
sys.path.insert(0, str(BOT_ROOT))

import generate_strategies as generator


BOTS_ROOT = REPO_ROOT / "bots"
RUN_ROOT = REPO_ROOT / "tools" / "pong_optimizer_runs"
PARSER_PATH = REPO_ROOT / "tools" / "replay_parser" / "parse_replay.js"
MAP_ARG = "maps\\pong.map26"

TEAM_B_AXIONITE_RE = re.compile(
    r"Axionite\s+(\d+)\s+\(\d+\s+mined\)\s+(\d+)\s+\(\d+\s+mined\)"
)
TEAM_B_TITANIUM_RE = re.compile(
    r"Titanium\s+(\d+)\s+\(\d+\s+mined\)\s+(\d+)\s+\(\d+\s+mined\)"
)

SPAWN_TILES = [
    [40, 9],
    [42, 9],
    [40, 7],
    [42, 7],
    [41, 9],
    [40, 8],
    [42, 8],
    [41, 7],
    [41, 8],
]

REGION_TEMPLATES = [
    {"name": "top_right", "min_x": 43, "max_x": 49, "min_y": 3, "max_y": 11},
    {"name": "mid_right", "min_x": 43, "max_x": 49, "min_y": 12, "max_y": 18},
    {"name": "low_right", "min_x": 43, "max_x": 49, "min_y": 16, "max_y": 22},
    {"name": "low_left", "min_x": 29, "max_x": 36, "min_y": 16, "max_y": 22},
    {"name": "mid_left", "min_x": 29, "max_x": 36, "min_y": 10, "max_y": 17},
    {"name": "centre_low", "min_x": 37, "max_x": 42, "min_y": 14, "max_y": 22},
    {"name": "centre_top", "min_x": 37, "max_x": 43, "min_y": 3, "max_y": 9},
]

PHASE_RANGES = {
    "titanium_path_base": (-40, 80),
    "titanium_path_weight": (1, 8),
    "titanium_harvester_base": (-20, 120),
    "titanium_harvester_weight": (1, 10),
    "foundry_base": (50, 1800),
    "foundry_core_weight": (0, 8),
    "generic_walkable_base": (120, 2200),
    "generic_walkable_flow_weight": (0, 8),
    "axionite_harvester_base": (400, 3200),
    "axionite_harvester_core_weight": (0, 8),
    "other_base": (1200, 5000),
    "other_core_weight": (0, 8),
}

SCORING_RANGES = {
    "path_weight": (1, 40),
    "manhattan_weight": (0, 10),
    "flow_weight": (-5, 10),
    "core_distance_weight": (-5, 10),
}


@dataclass(frozen=True)
class Candidate:
    config: dict[str, Any]
    source: str
    generation: int = 0
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fingerprint", fingerprint_config(self.config))


@dataclass
class EvalResult:
    trial: int
    candidate: Candidate
    feasible: bool
    score_b: int = -1
    score_a: int = -1
    titanium_b: int = -1
    reason: str = ""
    summary: dict[str, Any] | None = None
    replay_path: Path | None = None
    worker_name: str = ""
    elapsed_s: float = 0.0
    validation: dict[str, Any] | None = None


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def clean_json_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if not key.startswith("_")}


def fingerprint_config(config: dict[str, Any]) -> str:
    payload = json.dumps(clean_json_config(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def load_seed_config() -> dict[str, Any]:
    if generator.CONFIG_PATH.exists():
        raw = read_json(generator.CONFIG_PATH)
    else:
        raw = copy.deepcopy(generator.DEFAULT_CONFIG)
    return clean_json_config(generator.normalize_config(raw))


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def repair_config(config: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    config = clean_json_config(generator.normalize_config(config))
    spawns = config["spawns"]
    if not spawns:
        spawns = copy.deepcopy(generator.DEFAULT_CONFIG["spawns"])
    spawns = spawns[:5]

    used_turns: set[int] = set()
    used_tiles: set[tuple[int, int]] = set()
    for index, spawn in enumerate(spawns):
        turn = clamp(int(spawn.get("turn", index)), 0, 30)
        while turn in used_turns:
            turn = clamp(turn + 1, 0, 30)
            if turn in used_turns and turn == 30:
                turn = min(set(range(31)) - used_turns)
        used_turns.add(turn)

        tile = spawn.get("tile", SPAWN_TILES[index % len(SPAWN_TILES)])
        tile_tuple = tuple(int(value) for value in tile)
        if tile_tuple not in {tuple(candidate) for candidate in SPAWN_TILES}:
            tile_tuple = tuple(SPAWN_TILES[index % len(SPAWN_TILES)])
        if tile_tuple in used_tiles and len(used_tiles) < len(SPAWN_TILES):
            choices = [candidate for candidate in SPAWN_TILES if tuple(candidate) not in used_tiles]
            tile_tuple = tuple(rng.choice(choices))
        used_tiles.add(tile_tuple)
        spawn["turn"] = turn
        spawn["tile"] = [tile_tuple[0], tile_tuple[1]]

    builder_count = len(spawns)
    policy = config["owner_policy"]
    policy["left_x"] = clamp(int(policy.get("left_x", 36)), 29, 42)
    policy["center_left_x"] = clamp(int(policy.get("center_left_x", 40)), 35, 44)
    policy["center_y_min"] = clamp(int(policy.get("center_y_min", 10)), 3, 21)
    policy["center_y_max"] = clamp(int(policy.get("center_y_max", 13)), policy["center_y_min"], 22)
    policy["right_x"] = clamp(int(policy.get("right_x", 43)), 37, 49)
    fallback_owner = clamp(int(policy.get("fallback_owner", min(3, builder_count))), 1, builder_count)
    policy["fallback_owner"] = fallback_owner

    rules = []
    for rule in policy.get("rules", []):
        owner = int(rule.get("owner", 1))
        if not 1 <= owner <= builder_count:
            continue
        rules.append(
            {
                "owner": owner,
                "min_x": clamp(int(rule.get("min_x", 25)), 25, 49),
                "max_x": clamp(int(rule.get("max_x", 49)), 25, 49),
                "min_y": clamp(int(rule.get("min_y", 0)), 0, 34),
                "max_y": clamp(int(rule.get("max_y", 34)), 0, 34),
            }
        )
    for rule in rules:
        if rule["min_x"] > rule["max_x"]:
            rule["min_x"], rule["max_x"] = rule["max_x"], rule["min_x"]
        if rule["min_y"] > rule["max_y"]:
            rule["min_y"], rule["max_y"] = rule["max_y"], rule["min_y"]
    policy["rules"] = rules[: max(0, builder_count - 2)]

    for key, (low, high) in PHASE_RANGES.items():
        config["phase"][key] = clamp(int(config["phase"].get(key, generator.DEFAULT_CONFIG["phase"][key])), low, high)
    for key, (low, high) in SCORING_RANGES.items():
        config["target_scoring"][key] = clamp(
            int(config["target_scoring"].get(key, generator.DEFAULT_CONFIG["target_scoring"][key])),
            low,
            high,
        )

    if builder_count != 3:
        config["auto_temp_bounds"] = True
    config["temp_margin"] = clamp(int(config.get("temp_margin", 2)), 1, 8)
    if config["cleanup"].get("mode") not in {"nearest", "farthest"}:
        config["cleanup"]["mode"] = "nearest"
    return config


def mutate_int(value: int, low: int, high: int, rng: random.Random, scale: int = 1) -> int:
    steps = [-3, -2, -1, 1, 2, 3]
    return clamp(value + rng.choice(steps) * scale, low, high)


def mutate_phase(config: dict[str, Any], rng: random.Random) -> str:
    key = rng.choice(list(PHASE_RANGES))
    low, high = PHASE_RANGES[key]
    span = max(1, (high - low) // 20)
    config["phase"][key] = mutate_int(int(config["phase"][key]), low, high, rng, span)
    return f"phase:{key}"


def mutate_scoring(config: dict[str, Any], rng: random.Random) -> str:
    key = rng.choice(list(SCORING_RANGES))
    low, high = SCORING_RANGES[key]
    config["target_scoring"][key] = mutate_int(int(config["target_scoring"][key]), low, high, rng)
    return f"scoring:{key}"


def mutate_owner(config: dict[str, Any], rng: random.Random) -> str:
    policy = config["owner_policy"]
    key = rng.choice(["left_x", "center_left_x", "center_y_min", "center_y_max", "right_x", "fallback_owner"])
    if key == "fallback_owner":
        policy[key] = rng.randint(1, len(config["spawns"]))
    else:
        policy[key] = int(policy[key]) + rng.choice([-2, -1, 1, 2])
    return f"owner:{key}"


def mutate_builder_count(config: dict[str, Any], rng: random.Random) -> str:
    spawns = config["spawns"]
    old_count = len(spawns)
    new_count = clamp(old_count + rng.choice([-1, 1]), 2, 5)
    if new_count > old_count:
        used_tiles = {tuple(spawn["tile"]) for spawn in spawns}
        choices = [tile for tile in SPAWN_TILES if tuple(tile) not in used_tiles] or SPAWN_TILES
        spawns.append(
            {
                "turn": max(int(spawn["turn"]) for spawn in spawns) + 1,
                "tile": list(rng.choice(choices)),
            }
        )
        maybe_assign_extra_regions(config, rng)
    elif new_count < old_count:
        del spawns[new_count:]
        config["owner_policy"]["rules"] = [
            rule for rule in config["owner_policy"].get("rules", []) if int(rule["owner"]) <= new_count
        ]
    return f"builder_count:{old_count}->{new_count}"


def mutate_spawns(config: dict[str, Any], rng: random.Random) -> str:
    spawn = rng.choice(config["spawns"])
    if rng.random() < 0.55:
        spawn["turn"] = int(spawn["turn"]) + rng.choice([-3, -2, -1, 1, 2, 3])
        return "spawn_turn"
    spawn["tile"] = list(rng.choice(SPAWN_TILES))
    return "spawn_tile"


def maybe_assign_extra_regions(config: dict[str, Any], rng: random.Random) -> None:
    builder_count = len(config["spawns"])
    if builder_count <= 3:
        return
    existing_owners = {int(rule["owner"]) for rule in config["owner_policy"].get("rules", [])}
    rules = list(config["owner_policy"].get("rules", []))
    for owner in range(4, builder_count + 1):
        if owner in existing_owners:
            continue
        template = copy.deepcopy(rng.choice(REGION_TEMPLATES))
        template.pop("name", None)
        template["owner"] = owner
        rules.append(template)
    config["owner_policy"]["rules"] = rules


def mutate_rules(config: dict[str, Any], rng: random.Random) -> str:
    builder_count = len(config["spawns"])
    if builder_count <= 3:
        return mutate_builder_count(config, rng)
    rules = config["owner_policy"].setdefault("rules", [])
    if not rules or rng.random() < 0.35:
        owner = rng.randint(4, builder_count)
        template = copy.deepcopy(rng.choice(REGION_TEMPLATES))
        template.pop("name", None)
        template["owner"] = owner
        rules.append(template)
        return f"rule:add:{owner}"
    rule = rng.choice(rules)
    key = rng.choice(["min_x", "max_x", "min_y", "max_y", "owner"])
    if key == "owner":
        rule[key] = rng.randint(1, builder_count)
    else:
        rule[key] = int(rule[key]) + rng.choice([-2, -1, 1, 2])
    return f"rule:{key}"


def mutate_misc(config: dict[str, Any], rng: random.Random) -> str:
    choice = rng.choice(["cleanup", "auto_bounds", "temp_margin"])
    if choice == "cleanup":
        config["cleanup"]["mode"] = "farthest" if config["cleanup"].get("mode") == "nearest" else "nearest"
    elif choice == "auto_bounds":
        config["auto_temp_bounds"] = not bool(config.get("auto_temp_bounds", False))
    else:
        config["temp_margin"] = int(config.get("temp_margin", 2)) + rng.choice([-1, 1])
    return choice


def mutate_candidate(parent: Candidate, rng: random.Random, generation: int) -> Candidate:
    config = copy.deepcopy(parent.config)
    operations = [
        mutate_phase,
        mutate_phase,
        mutate_scoring,
        mutate_owner,
        mutate_spawns,
        mutate_rules,
        mutate_builder_count,
        mutate_misc,
    ]
    count = 1 if rng.random() < 0.72 else rng.randint(2, 4)
    sources = []
    for _ in range(count):
        operation = rng.choice(operations)
        sources.append(operation(config, rng))
    config = repair_config(config, rng)
    return Candidate(config=config, source="+".join(sources), generation=generation)


def crossover_candidate(
    left: Candidate,
    right: Candidate,
    rng: random.Random,
    generation: int,
) -> Candidate:
    config = copy.deepcopy(left.config)
    donor = right.config
    for section in ["phase", "target_scoring", "owner_policy", "cleanup"]:
        if rng.random() < 0.5:
            config[section] = copy.deepcopy(donor[section])
    if rng.random() < 0.35:
        config["spawns"] = copy.deepcopy(donor["spawns"])
    config = repair_config(config, rng)
    return Candidate(config=config, source=f"crossover:{left.fingerprint}:{right.fingerprint}", generation=generation)


def prepare_worker(worker_name: str) -> Path:
    worker_root = BOTS_ROOT / worker_name
    worker_root.mkdir(parents=True, exist_ok=True)
    for filename in [
        "main.py",
        "builder_agent.py",
        "core_agent.py",
        "plan.json",
        "pong_map.json",
        "strategy_config.json",
    ]:
        source = BOT_ROOT / filename
        if source.exists():
            shutil.copy2(source, worker_root / filename)
    (worker_root / "strategies").mkdir(exist_ok=True)
    return worker_root


def parse_score(output: str) -> tuple[int, int, int]:
    axionite_match = TEAM_B_AXIONITE_RE.search(output)
    titanium_match = TEAM_B_TITANIUM_RE.search(output)
    if axionite_match is None:
        raise ValueError("could not parse axionite score from cambc output")
    score_a = int(axionite_match.group(1))
    score_b = int(axionite_match.group(2))
    titanium_b = int(titanium_match.group(2)) if titanium_match else -1
    return score_a, score_b, titanium_b


def evaluate_candidate(
    trial: int,
    candidate: Candidate,
    worker_name: str,
    run_dir: Path,
    cambc_timeout_s: int,
) -> EvalResult:
    started = time.monotonic()
    worker_root = prepare_worker(worker_name)
    replay_path = run_dir / "replays" / f"trial_{trial:05d}_{worker_name}.replay26"
    log_path = run_dir / "logs" / f"trial_{trial:05d}_{worker_name}.log"
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        summary = generator.generate(
            raw_config=candidate.config,
            plan_path=worker_root / "plan.json",
            map_path=worker_root / "pong_map.json",
            spawns_path=worker_root / "spawns.json",
            strategy_root=worker_root / "strategies",
            cleanup_stale=True,
        )
        if summary["planned_final_builds"] != summary["final_tile_count"]:
            return EvalResult(
                trial=trial,
                candidate=candidate,
                feasible=False,
                reason="generator did not cover every final tile",
                summary=summary,
                worker_name=worker_name,
                elapsed_s=time.monotonic() - started,
            )
        if any(builder["temp_roads_remaining"] for builder in summary["builders"].values()):
            return EvalResult(
                trial=trial,
                candidate=candidate,
                feasible=False,
                reason="generator left temporary roads",
                summary=summary,
                worker_name=worker_name,
                elapsed_s=time.monotonic() - started,
            )
    except Exception as exc:
        return EvalResult(
            trial=trial,
            candidate=candidate,
            feasible=False,
            reason=f"generation failed: {type(exc).__name__}: {exc}",
            worker_name=worker_name,
            elapsed_s=time.monotonic() - started,
        )

    command = [
        "cambc",
        "run",
        worker_name,
        worker_name,
        MAP_ARG,
        "--replay",
        str(replay_path),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=cambc_timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(exc.stdout or "", encoding="utf-8")
        return EvalResult(
            trial=trial,
            candidate=candidate,
            feasible=False,
            reason="cambc timeout",
            summary=summary,
            replay_path=replay_path,
            worker_name=worker_name,
            elapsed_s=time.monotonic() - started,
        )

    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        return EvalResult(
            trial=trial,
            candidate=candidate,
            feasible=False,
            reason=f"cambc exited {completed.returncode}",
            summary=summary,
            replay_path=replay_path,
            worker_name=worker_name,
            elapsed_s=time.monotonic() - started,
        )

    try:
        score_a, score_b, titanium_b = parse_score(completed.stdout)
    except Exception as exc:
        return EvalResult(
            trial=trial,
            candidate=candidate,
            feasible=False,
            reason=str(exc),
            summary=summary,
            replay_path=replay_path,
            worker_name=worker_name,
            elapsed_s=time.monotonic() - started,
        )

    return EvalResult(
        trial=trial,
        candidate=candidate,
        feasible=True,
        score_a=score_a,
        score_b=score_b,
        titanium_b=titanium_b,
        reason="ok",
        summary=summary,
        replay_path=replay_path,
        worker_name=worker_name,
        elapsed_s=time.monotonic() - started,
    )


def validate_replay(replay_path: Path, run_dir: Path) -> dict[str, Any]:
    parsed_dir = run_dir / "validation" / replay_path.stem
    if parsed_dir.exists():
        shutil.rmtree(parsed_dir)
    command = [
        "node",
        str(PARSER_PATH),
        str(replay_path),
        "--out-dir",
        str(parsed_dir),
        "--turn-chunk-size",
        "200",
        "--action-chunk-size",
        "200",
    ]
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=240,
        check=False,
    )
    if completed.returncode != 0:
        return {"ok": False, "reason": completed.stdout[-1200:]}

    plan = read_json(BOT_ROOT / "plan.json")
    final_entities = read_json(parsed_dir / "final_entities.json")
    plan_tiles = {}
    for raw_key, spec in plan["tiles"].items():
        if spec is None:
            continue
        x, y = (int(part) for part in raw_key.split(",", 1))
        if x < generator.RIGHT_MIN_X:
            continue
        plan_tiles[(x, y)] = (
            {"type": spec} if isinstance(spec, str) else copy.deepcopy(spec)
        )

    final = {}
    for entity in final_entities:
        if entity.get("teamName") != "TEAM_B":
            continue
        if entity.get("kind") in {"core", "builderBot"}:
            continue
        pos = entity["position"]
        final[(pos["x"], pos["y"])] = entity

    missing = []
    extra = []
    mismatch = []
    for pos, spec in plan_tiles.items():
        entity = final.get(pos)
        if entity is None:
            missing.append([pos[0], pos[1], spec["type"]])
            continue
        if entity["kind"] != spec["type"]:
            mismatch.append([pos[0], pos[1], "type", spec["type"], entity["kind"]])
            continue
        if spec["type"] == "conveyor":
            got = (entity.get("direction") or "").removeprefix("DIR_").lower()
            if got != spec.get("direction"):
                mismatch.append([pos[0], pos[1], "direction", spec.get("direction"), got])
        elif spec["type"] == "bridge":
            target = entity.get("bridgeTarget")
            got = [target["x"], target["y"]] if target else None
            if got != spec.get("target"):
                mismatch.append([pos[0], pos[1], "target", spec.get("target"), got])

    for pos, entity in final.items():
        if pos not in plan_tiles:
            extra.append([pos[0], pos[1], entity["kind"]])

    index = read_json(parsed_dir / "index.json")
    return {
        "ok": not missing and not extra and not mismatch,
        "planned": len(plan_tiles),
        "final": len(final),
        "missing": len(missing),
        "extra": len(extra),
        "mismatch": len(mismatch),
        "examples": {
            "missing": missing[:10],
            "extra": extra[:10],
            "mismatch": mismatch[:10],
        },
        "eventCounts": index.get("eventCounts", {}),
    }


def copy_tree_contents(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for old_path in destination.glob("*"):
        if old_path.is_dir():
            shutil.rmtree(old_path)
        else:
            old_path.unlink()
    for source_path in source.glob("*"):
        target = destination / source_path.name
        if source_path.is_dir():
            shutil.copytree(source_path, target)
        else:
            shutil.copy2(source_path, target)


def publish_best(result: EvalResult, commit: bool) -> None:
    worker_root = BOTS_ROOT / result.worker_name
    write_json(BOT_ROOT / "strategy_config.json", clean_json_config(result.candidate.config))
    shutil.copy2(worker_root / "spawns.json", BOT_ROOT / "spawns.json")
    copy_tree_contents(worker_root / "strategies", BOT_ROOT / "strategies")
    subprocess.run(
        ["python", str(BOT_ROOT / "generate_strategies.py"), "--quiet"],
        cwd=REPO_ROOT,
        check=True,
    )
    if commit:
        subprocess.run(
            [
                "git",
                "add",
                str(BOT_ROOT / "strategy_config.json"),
                str(BOT_ROOT / "spawns.json"),
                str(BOT_ROOT / "strategies"),
            ],
            cwd=REPO_ROOT,
            check=True,
        )
        completed = subprocess.run(
            [
                "git",
                "commit",
                "-m",
                f"Optimize pong strategy ({result.score_b} axionite)",
            ],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.returncode != 0 and "nothing to commit" not in completed.stdout:
            raise RuntimeError(completed.stdout)


def append_history(path: Path, result: EvalResult, best_score: int) -> None:
    payload = {
        "trial": result.trial,
        "fingerprint": result.candidate.fingerprint,
        "source": result.candidate.source,
        "generation": result.candidate.generation,
        "feasible": result.feasible,
        "score_b": result.score_b,
        "score_a": result.score_a,
        "titanium_b": result.titanium_b,
        "best_score_b": best_score,
        "reason": result.reason,
        "elapsed_s": round(result.elapsed_s, 3),
        "worker": result.worker_name,
        "validation": result.validation,
        "config": clean_json_config(result.candidate.config),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def choose_parent(population: list[EvalResult], rng: random.Random) -> EvalResult:
    sample_size = min(len(population), 4)
    sample = rng.sample(population, sample_size)
    return max(sample, key=lambda result: result.score_b)


def make_candidate(
    population: list[EvalResult],
    seen: set[str],
    rng: random.Random,
    generation: int,
) -> Candidate:
    for _ in range(200):
        if len(population) >= 2 and rng.random() < 0.22:
            left = choose_parent(population, rng)
            right = choose_parent(population, rng)
            candidate = crossover_candidate(left.candidate, right.candidate, rng, generation)
        else:
            parent = choose_parent(population, rng)
            candidate = mutate_candidate(parent.candidate, rng, generation)
        if candidate.fingerprint not in seen:
            seen.add(candidate.fingerprint)
            return candidate

    config = repair_config(copy.deepcopy(generator.DEFAULT_CONFIG), rng)
    candidate = Candidate(config=config, source="random_restart", generation=generation)
    seen.add(candidate.fingerprint)
    return candidate


def plan_hash() -> str:
    payload = (BOT_ROOT / "plan.json").read_bytes()
    return hashlib.sha256(payload).hexdigest()


def cleanup_workers(worker_names: list[str]) -> None:
    for worker_name in worker_names:
        worker_root = BOTS_ROOT / worker_name
        if worker_root.exists() and worker_root.name.startswith("pong_opt_worker_"):
            shutil.rmtree(worker_root)


def run(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    run_id = time.strftime("%Y%m%d_%H%M%S")
    run_dir = RUN_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    history_path = run_dir / "trials.jsonl"
    initial_plan_hash = plan_hash()

    worker_names = [f"pong_opt_worker_{index}" for index in range(args.workers)]
    for worker_name in worker_names:
        prepare_worker(worker_name)

    seed_config = repair_config(load_seed_config(), rng)
    baseline = Candidate(config=seed_config, source="baseline", generation=0)
    seen = {baseline.fingerprint}
    print(f"[optimizer] run={run_id} workers={args.workers} seed={args.seed}")
    print("[optimizer] evaluating baseline")
    best = evaluate_candidate(0, baseline, worker_names[0], run_dir, args.cambc_timeout)
    if not best.feasible:
        raise RuntimeError(f"baseline is not feasible: {best.reason}")
    population = [best]
    append_history(history_path, best, best.score_b)
    write_json(run_dir / "best.json", {"score_b": best.score_b, "config": best.candidate.config})
    print(f"[optimizer] baseline score_b={best.score_b} score_a={best.score_a}")

    trial = 1
    generation = 1
    deadline = time.monotonic() + args.seconds if args.seconds else None
    try:
        while trial <= args.max_trials:
            if deadline is not None and time.monotonic() >= deadline:
                break

            batch: list[tuple[int, Candidate, str]] = []
            for worker_name in worker_names:
                if trial > args.max_trials:
                    break
                candidate = make_candidate(population, seen, rng, generation)
                batch.append((trial, candidate, worker_name))
                trial += 1
                generation += 1

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as executor:
                futures = [
                    executor.submit(
                        evaluate_candidate,
                        batch_trial,
                        candidate,
                        worker_name,
                        run_dir,
                        args.cambc_timeout,
                    )
                    for batch_trial, candidate, worker_name in batch
                ]
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    improved = result.feasible and result.score_b > best.score_b
                    if improved and args.validate_improvements and result.replay_path is not None:
                        result.validation = validate_replay(result.replay_path, run_dir)
                        if not result.validation.get("ok", False):
                            result.feasible = False
                            result.reason = f"validation failed: {result.validation}"
                            improved = False

                    if result.feasible:
                        population.append(result)
                        population.sort(key=lambda item: item.score_b, reverse=True)
                        del population[args.population_size :]

                    if improved:
                        best = result
                        publish_best(best, args.commit_improvements)
                        write_json(
                            run_dir / "best.json",
                            {
                                "score_b": best.score_b,
                                "score_a": best.score_a,
                                "titanium_b": best.titanium_b,
                                "trial": best.trial,
                                "fingerprint": best.candidate.fingerprint,
                                "source": best.candidate.source,
                                "validation": best.validation,
                                "config": clean_json_config(best.candidate.config),
                            },
                        )
                        print(
                            f"[optimizer] IMPROVED trial={best.trial} "
                            f"score_b={best.score_b} score_a={best.score_a} "
                            f"source={best.candidate.source}"
                        )
                    else:
                        status = "score" if result.feasible else "reject"
                        value = result.score_b if result.feasible else result.reason
                        print(
                            f"[optimizer] {status} trial={result.trial} "
                            f"value={value} best={best.score_b} "
                            f"source={result.candidate.source}"
                        )

                    append_history(history_path, result, best.score_b)

            if plan_hash() != initial_plan_hash:
                raise RuntimeError("plan.json changed during optimization; aborting")
    finally:
        if not args.keep_workers:
            cleanup_workers(worker_names)

    print(f"[optimizer] done best_score_b={best.score_b} run_dir={run_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay-guided pong strategy optimizer. It keeps plan.json fixed and "
            "optimizes only builder spawns, ownership, and action ordering."
        )
    )
    parser.add_argument("--max-trials", type=int, default=1000)
    parser.add_argument("--seconds", type=int, default=10 * 60 * 60)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--population-size", type=int, default=32)
    parser.add_argument("--cambc-timeout", type=int, default=90)
    parser.add_argument("--commit-improvements", action="store_true")
    parser.add_argument(
        "--validate-improvements",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--keep-workers", action="store_true")
    args = parser.parse_args()
    args.workers = max(1, args.workers)
    args.max_trials = max(0, args.max_trials)
    args.population_size = max(2, args.population_size)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
