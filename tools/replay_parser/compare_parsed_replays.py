#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ACTION_EVENT_TYPES = {
    "place_entity",
    "move_builder_bot",
    "builder_attack",
    "fire_turret",
}
TEAM_CHOICES = ("BOTH", "TEAM_A", "TEAM_B")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare concrete in-game actions between two parsed replay JSON files."
        )
    )
    parser.add_argument("left", type=Path, help="Path to the first parsed replay JSON")
    parser.add_argument("right", type=Path, help="Path to the second parsed replay JSON")
    parser.add_argument(
        "--turns",
        type=int,
        default=None,
        help=(
            "Only compare the first N turns. By default, compare the full replay and "
            "require both replays to have the same turn count."
        ),
    )
    parser.add_argument(
        "--team",
        choices=TEAM_CHOICES,
        default="BOTH",
        help="Restrict comparison to one team, or compare both teams together.",
    )
    return parser.parse_args()


def load_parsed_replay(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def normalize_position(pos: Any) -> dict[str, int] | None:
    if not isinstance(pos, dict):
        return None
    x = pos.get("x")
    y = pos.get("y")
    if x is None or y is None:
        return None
    return {"x": x, "y": y}


def compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def normalize_action_event(event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = event.get("type")
    if event_type not in ACTION_EVENT_TYPES:
        return None

    if event_type == "place_entity":
        entity = event.get("entity") or {}
        team = entity.get("teamName")
        kind = entity.get("kind")
        position = normalize_position(entity.get("position"))
        if kind == "builderBot":
            return compact_dict(
                {
                    "type": "spawn_builder_bot",
                    "team": team,
                    "position": position,
                }
            )

        return compact_dict(
            {
                "type": "place_entity",
                "team": team,
                "kind": kind,
                "position": position,
                "direction": entity.get("direction"),
                "bridgeTarget": normalize_position(entity.get("bridgeTarget")),
                "harvesterResourceType": entity.get("harvesterResourceType"),
            }
        )

    if event_type == "move_builder_bot":
        return compact_dict(
            {
                "type": "move_builder_bot",
                "team": event.get("actorTeam"),
                "from": normalize_position(event.get("from")),
                "to": normalize_position(event.get("to")),
            }
        )

    if event_type == "builder_attack":
        return compact_dict(
            {
                "type": "builder_attack",
                "team": event.get("actorTeam"),
                "from": normalize_position(event.get("from")),
            }
        )

    if event_type == "fire_turret":
        return compact_dict(
            {
                "type": "fire_turret",
                "team": event.get("actorTeam"),
                "actorKind": event.get("actorKind"),
                "from": normalize_position(event.get("from")),
                "to": normalize_position(event.get("to")),
            }
        )

    return None


def get_event_team(action: dict[str, Any]) -> str | None:
    team = action.get("team")
    return team if isinstance(team, str) else None


def collect_turn_actions(
    turn_data: dict[str, Any],
    team_filter: str,
) -> list[dict[str, Any]]:
    normalized_actions: list[dict[str, Any]] = []
    for event in turn_data.get("events", []):
        action = normalize_action_event(event)
        if action is None:
            continue
        if team_filter != "BOTH" and get_event_team(action) != team_filter:
            continue
        normalized_actions.append(action)
    return normalized_actions


def format_action(action: dict[str, Any]) -> str:
    return json.dumps(action, sort_keys=True, ensure_ascii=True)


def compare_action_lists(
    left_actions: list[dict[str, Any]],
    right_actions: list[dict[str, Any]],
) -> tuple[bool, int | None]:
    common_length = min(len(left_actions), len(right_actions))
    for idx in range(common_length):
        if left_actions[idx] != right_actions[idx]:
            return False, idx
    if len(left_actions) != len(right_actions):
        return False, common_length
    return True, None


def main() -> int:
    args = parse_args()
    left_data = load_parsed_replay(args.left)
    right_data = load_parsed_replay(args.right)

    left_turns = left_data.get("turnsDetailed", [])
    right_turns = right_data.get("turnsDetailed", [])
    left_turn_count = len(left_turns)
    right_turn_count = len(right_turns)

    if args.turns is None:
        if left_turn_count != right_turn_count:
            print(
                "Replay turn-count mismatch:",
                f"{args.left} has {left_turn_count} turns,",
                f"{args.right} has {right_turn_count} turns.",
            )
            return 1
        turn_limit = left_turn_count
    else:
        if args.turns <= 0:
            print("--turns must be a positive integer.")
            return 2
        if left_turn_count < args.turns or right_turn_count < args.turns:
            print(
                "Replay too short for requested turn comparison:",
                f"requested {args.turns},",
                f"{args.left} has {left_turn_count},",
                f"{args.right} has {right_turn_count}.",
            )
            return 1
        turn_limit = args.turns

    compared_action_count = 0
    for turn_idx in range(turn_limit):
        left_actions = collect_turn_actions(left_turns[turn_idx], args.team)
        right_actions = collect_turn_actions(right_turns[turn_idx], args.team)
        compared_action_count += max(len(left_actions), len(right_actions))
        equal, mismatch_idx = compare_action_lists(left_actions, right_actions)
        if equal:
            continue

        print(
            f"Mismatch on turn {turn_idx + 1} for team filter {args.team}.",
        )
        if mismatch_idx is not None and mismatch_idx < len(left_actions):
            print("Left :", format_action(left_actions[mismatch_idx]))
        else:
            print("Left : <no action>")
        if mismatch_idx is not None and mismatch_idx < len(right_actions):
            print("Right:", format_action(right_actions[mismatch_idx]))
        else:
            print("Right: <no action>")

        print(
            f"Left action count on turn {turn_idx + 1}: {len(left_actions)}",
        )
        print(
            f"Right action count on turn {turn_idx + 1}: {len(right_actions)}",
        )

        if left_actions != right_actions:
            print("\nFull left turn actions:")
            for idx, action in enumerate(left_actions):
                print(f"  [{idx}] {format_action(action)}")
            print("\nFull right turn actions:")
            for idx, action in enumerate(right_actions):
                print(f"  [{idx}] {format_action(action)}")

        return 1

    print(
        "Replays matched for concrete actions.",
        f"Turns compared: {turn_limit}.",
        f"Team filter: {args.team}.",
        f"Actions examined: {compared_action_count}.",
    )
    print(
        "Compared event types:",
        ", ".join(sorted(ACTION_EVENT_TYPES)),
    )
    print(
        "Ignored replay-only / derived event types such as bot_output, cooldown updates, "
        "hp deltas, and resource distribution.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
