from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor
import http.cookiejar

BASE_URL = "https://game.battlecode.cam"
SESSION_COOKIE_NAME = "__Secure-better-auth.session_token"

LADDER_ENDPOINT = "f043f981ce667d6058afbccc0480d022cd652d168b6939c387213d09cf92b3c9"
TEAM_PROFILE_ENDPOINT = "dc1c67546577734fb17807d4e96c73aa23843de1904c3f712154204acb3b23ab"
TEAM_MATCHES_ENDPOINT = "342e8819792d7a767255f42f4b375f76dad393aa3461091e20e25439b756de0c"
MATCH_GAMES_ENDPOINT = "8450fe0d23f291c5258bcef199bba0e39aa04eec125352ed8d454d31941d17b3"
SIGNED_URL_ENDPOINT = "6cb1de8540743967bac3895502d3b8b7dd37023afe7cc001542395121cecfe5f"


@dataclass
class DownloadSummary:
    match_count: int = 0
    game_count: int = 0
    replay_key_count: int = 0
    download_count: int = 0


class BattlecodeReplayClient:
    def __init__(
        self,
        base_url: str,
        *,
        session_cookie: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookie_jar))
        self.session_cookie = self._normalize_session_cookie(session_cookie)

    @staticmethod
    def _normalize_session_cookie(session_cookie: str | None) -> str | None:
        if not session_cookie:
            return None
        cookie = session_cookie.strip()
        if not cookie:
            return None
        if "=" not in cookie:
            return f"{SESSION_COOKIE_NAME}={cookie}"
        return cookie

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> bytes:
        request_headers = dict(headers or {})
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        if self.session_cookie and url.startswith(self.base_url):
            request_headers.setdefault("Cookie", self.session_cookie)
        request = Request(
            url,
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with self.opener.open(request) as response:
                return response.read()
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{method} {path} failed with HTTP {exc.code}: {details}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"{method} {path} failed: {exc.reason}") from exc

    def login(self, email: str, password: str) -> None:
        payload = json.dumps(
            {
                "email": email,
                "password": password,
                "callbackURL": "/team",
            }
        ).encode("utf-8")
        self._request(
            "POST",
            "/api/auth/sign-in/email",
            headers={
                "Content-Type": "application/json",
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/login",
                "Accept": "application/json",
            },
            body=payload,
        )

    def server_get(self, endpoint: str, data: dict[str, Any] | None = None) -> Any:
        payload = json.dumps(
            self._build_server_fn_payload(data or {}),
            separators=(",", ":"),
        )
        query = urlencode({"payload": payload})
        raw = self._request(
            "GET",
            f"/_serverFn/{endpoint}?{query}",
            headers={
                "x-tsr-serverFn": "true",
                "Accept": "application/json",
            },
        )
        return self._decode_server_fn_response(raw)

    def download_bytes(self, url: str) -> bytes:
        return self._request("GET", url)

    @classmethod
    def _build_server_fn_payload(cls, data: dict[str, Any]) -> dict[str, Any]:
        encoder = _SerovalEncoder()
        return {"t": encoder.encode({"data": data}), "f": 63, "m": []}

    @classmethod
    def _decode_server_fn_response(cls, raw: bytes) -> Any:
        decoded = _decode_seroval(json.loads(raw.decode("utf-8")))
        error = decoded.get("error")
        if error not in (None, {}):
            raise RuntimeError(f"Server function error: {error}")
        return decoded.get("result")


class _SerovalEncoder:
    def __init__(self) -> None:
        self.next_id = 0

    def encode(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {"t": 2, "s": 0}
        if value is True:
            return {"t": 2, "s": 2}
        if value is False:
            return {"t": 2, "s": 3}
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return {"t": 0, "s": value}
        if isinstance(value, str):
            return {"t": 1, "s": value}
        if isinstance(value, list):
            return {
                "t": 9,
                "i": self._claim_id(),
                "a": [self.encode(item) for item in value],
                "o": 0,
            }
        if isinstance(value, dict):
            return {
                "t": 10,
                "i": self._claim_id(),
                "p": {
                    "k": list(value.keys()),
                    "v": [self.encode(item) for item in value.values()],
                },
                "o": 0,
            }
        raise TypeError(f"Unsupported payload type: {type(value)!r}")

    def _claim_id(self) -> int:
        current = self.next_id
        self.next_id += 1
        return current


def _decode_seroval(node: dict[str, Any]) -> Any:
    node_type = node["t"]
    if node_type == 0:
        return node["s"]
    if node_type == 1:
        return node["s"]
    if node_type == 2:
        scalar = node["s"]
        if scalar in (0, 1):
            return None
        if scalar == 2:
            return True
        if scalar == 3:
            return False
        return scalar
    if node_type == 5:
        return node["s"]
    if node_type == 9:
        return [_decode_seroval(item) for item in node["a"]]
    if node_type in (10, 11):
        payload = node["p"]
        return {
            key: _decode_seroval(value)
            for key, value in zip(payload["k"], payload["v"])
        }
    if node_type == 25:
        return {"class": node.get("c"), "details": node.get("s")}
    return node


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download replay files for a Battlecode team from "
            "https://game.battlecode.cam/."
        )
    )
    parser.add_argument(
        "--team-id",
        help="Exact team id to download replays for.",
    )
    parser.add_argument(
        "--team-name",
        help="Exact team name. Resolved through the ladder endpoint.",
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
        "--limit-matches",
        type=int,
        default=None,
        help="Only inspect the first N team matches.",
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

    if bool(args.team_id) == bool(args.team_name):
        parser.error("Provide exactly one of --team-id or --team-name.")
    if not args.session_cookie and not (args.email and args.password):
        parser.error(
            "Provide either --session-cookie or both --email and --password."
        )
    if args.session_cookie and (args.email or args.password):
        parser.error(
            "Use either --session-cookie or email/password auth, not both."
        )
    if args.limit_matches is not None and args.limit_matches <= 0:
        parser.error("--limit-matches must be a positive integer.")
    return args


def confirm_vpn_usage() -> bool:
    response = input("Are you using a vpn? ").strip().lower()
    return response == "yes"


def resolve_team_id(
    client: BattlecodeReplayClient,
    *,
    team_id: str | None,
    team_name: str | None,
) -> str:
    if team_id:
        return team_id

    ladder = client.server_get(LADDER_ENDPOINT, {})
    rankings = ladder.get("rankings", [])
    matches = [
        ranking
        for ranking in rankings
        if ranking.get("teamName", "").casefold() == team_name.casefold()
    ]
    if not matches:
        raise RuntimeError(f'No team named "{team_name}" found in ladder data.')
    if len(matches) > 1:
        ids = ", ".join(match["teamId"] for match in matches)
        raise RuntimeError(
            f'Ambiguous team name "{team_name}". Matching ids: {ids}'
        )
    return matches[0]["teamId"]


def safe_filename(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in ("-", "_", ".") else "_"
        for character in value
    ).strip("._")
    return cleaned or "team"


def replay_destination(
    output_root: Path,
    team_name: str,
    team_id: str,
    match_id: str,
    game: dict[str, Any],
    replay_key: str,
) -> Path:
    key_path = Path(replay_key)
    filename = key_path.name or f"{game['id']}.replay26"
    if "." not in filename:
        filename = f"{filename}.replay26"
    team_dir = output_root / f"{safe_filename(team_name)}_{team_id}"
    match_dir = team_dir / match_id
    return match_dir / filename


def download_team_replays(args: argparse.Namespace) -> int:
    client = BattlecodeReplayClient(
        args.base_url,
        session_cookie=args.session_cookie,
    )
    if args.email and args.password:
        client.login(args.email, args.password)

    team_id = resolve_team_id(
        client,
        team_id=args.team_id,
        team_name=args.team_name,
    )
    profile = client.server_get(TEAM_PROFILE_ENDPOINT, {"teamId": team_id})
    team = profile.get("team", {})
    team_name = team.get("name", team_id)
    matches = client.server_get(TEAM_MATCHES_ENDPOINT, {"teamId": team_id})
    if args.limit_matches is not None:
        matches = matches[: args.limit_matches]

    summary = DownloadSummary(match_count=len(matches))
    seen_keys: set[str] = set()
    print(f"Team: {team_name} ({team_id})")
    print(f"Matches inspected: {len(matches)}")

    for match in matches:
        match_id = match["id"]
        games = client.server_get(MATCH_GAMES_ENDPOINT, {"matchId": match_id})
        summary.game_count += len(games)
        for game in games:
            replay_key = game.get("replayS3Key")
            if not replay_key or replay_key in seen_keys:
                continue

            seen_keys.add(replay_key)
            summary.replay_key_count += 1
            destination = replay_destination(
                args.output_dir,
                team_name,
                team_id,
                match_id,
                game,
                replay_key,
            )
            print(
                f"Replay: match={match_id} game={game['gameNumber']} "
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
            summary.download_count += 1

    if summary.replay_key_count == 0:
        print("No replay keys were present in the inspected team matches.")
    else:
        action = "would download" if args.dry_run else "downloaded"
        print(
            f"Found {summary.replay_key_count} replay keys across "
            f"{summary.game_count} games and {action} {summary.download_count} files."
        )
    return 0


def main() -> int:
    args = parse_args()
    if not confirm_vpn_usage():
        print("Cancelled.")
        return 1
    try:
        return download_team_replays(args)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
