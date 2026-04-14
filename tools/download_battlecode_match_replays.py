from __future__ import annotations

import argparse
import sys
from pathlib import Path

from download_battlecode_team_replays import (
    BASE_URL,
    MATCH_GAMES_ENDPOINT,
    SIGNED_URL_ENDPOINT,
    BattlecodeReplayClient,
    confirm_vpn_usage,
    safe_filename,
)

MATCH_DETAIL_ENDPOINT = "551c0477e81f343b9d687375b9118e480c530d9f785c4e1bca88dec15fca734a"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download all replay files for a single Battlecode match from "
            "https://game.battlecode.cam/."
        )
    )
    parser.add_argument(
        "match_id",
        help="Match id to inspect.",
    )
    parser.add_argument(
        "--email",
        help="Login email. Required unless --session-cookie is provided.",
    )
    parser.add_argument(
        "--password",
        help="Login password. Required unless --session-cookie is provided.",
    )
    parser.add_argument(
        "--session-cookie",
        help=(
            "Either the full auth cookie header entry or just the "
            "__Secure-better-auth.session_token value."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("downloads") / "battlecode_replays",
        help="Directory where replay files will be written.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List replay files that would be downloaded without writing them.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Do not redownload files that already exist.",
    )
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if not args.session_cookie and not (args.email and args.password):
        parser.error(
            "Provide either --session-cookie or both --email and --password."
        )
    if args.session_cookie and (args.email or args.password):
        parser.error(
            "Use either --session-cookie or email/password auth, not both."
        )
    return args


def match_output_dir(
    output_root: Path,
    match_id: str,
    match_detail: dict,
) -> Path:
    team_a = safe_filename(match_detail.get("teamAName") or "team_a")
    team_b = safe_filename(match_detail.get("teamBName") or "team_b")
    return output_root / "matches" / f"{match_id}_{team_a}_vs_{team_b}"


def replay_destination(
    output_root: Path,
    match_id: str,
    match_detail: dict,
    game: dict,
    replay_key: str,
) -> Path:
    key_path = Path(replay_key)
    filename = key_path.name or f"{game['id']}.replay26"
    if "." not in filename:
        filename = f"{filename}.replay26"
    return match_output_dir(output_root, match_id, match_detail) / filename


def download_match_replays(args: argparse.Namespace) -> int:
    client = BattlecodeReplayClient(
        args.base_url,
        session_cookie=args.session_cookie,
    )
    if args.email and args.password:
        client.login(args.email, args.password)

    match_detail = client.server_get(
        MATCH_DETAIL_ENDPOINT,
        {"matchId": args.match_id},
    )
    games = client.server_get(MATCH_GAMES_ENDPOINT, {"matchId": args.match_id})

    print(
        "Match: "
        f"{args.match_id} "
        f"({match_detail.get('teamAName', 'Team A')} vs "
        f"{match_detail.get('teamBName', 'Team B')})"
    )
    print(f"Games inspected: {len(games)}")

    replay_count = 0
    download_count = 0
    for game in games:
        replay_key = game.get("replayS3Key")
        if not replay_key:
            continue

        replay_count += 1
        destination = replay_destination(
            args.output_dir,
            args.match_id,
            match_detail,
            game,
            replay_key,
        )
        print(
            f"Replay: game={game['gameNumber']} "
            f"map={game['mapName']} -> {destination}"
        )
        if args.dry_run:
            continue
        if args.skip_existing and destination.exists():
            print("  skipped existing file")
            continue

        signed = client.server_get(SIGNED_URL_ENDPOINT, {"s3Key": replay_key})
        replay_url = signed.get("url")
        if not replay_url:
            raise RuntimeError(
                f"Replay signer did not return a url for key {replay_key!r}"
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(client.download_bytes(replay_url))
        download_count += 1

    if replay_count == 0:
        print("No replay keys were present in the inspected match games.")
    else:
        action = "would download" if args.dry_run else "downloaded"
        print(f"Found {replay_count} replay keys and {action} {download_count} files.")
    return 0


def main() -> int:
    args = parse_args()
    if not confirm_vpn_usage():
        print("Cancelled.")
        return 1
    try:
        return download_match_replays(args)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
