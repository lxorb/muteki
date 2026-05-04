from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


EDITOR_ROOT = Path(__file__).resolve().parent
BOT_ROOT = EDITOR_ROOT.parent
REPO_ROOT = BOT_ROOT.parent.parent
PLAN_PATH = BOT_ROOT / "plan.json"
MAP_PATH = BOT_ROOT / "pong_map.json"
SPAWNS_PATH = BOT_ROOT / "spawns.json"
STRATEGY_ROOT = BOT_ROOT / "strategies"
DOCS_IMAGE_ROOT = REPO_ROOT / "docs" / "images"

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(data, indent=2) + "\n")


def strategy_path(builder_number: str) -> Path:
    if not builder_number.isdigit() or int(builder_number) <= 0:
        raise ValueError("Builder number must be a positive integer")
    return STRATEGY_ROOT / f"{builder_number}.json"


def normalized_spawns(data) -> list[dict]:
    raw_builders = data.get("spawn_schedule", data.get("builders", data)) if isinstance(data, dict) else data
    builders = []
    for index, raw in enumerate(raw_builders, start=1):
        builder_number = int(raw.get("builder", index))
        tile = raw["tile"]
        if isinstance(tile, str):
            x_raw, y_raw = tile.split(",", 1)
            x, y = int(x_raw), int(y_raw)
        elif isinstance(tile, dict):
            x, y = int(tile["x"]), int(tile["y"])
        else:
            x, y = int(tile[0]), int(tile[1])
        builders.append(
            {
                "builder": builder_number,
                "turn": int(raw.get("turn", 0)),
                "tile": [x, y],
            }
        )
    builders.sort(key=lambda item: item["builder"])
    return builders


def spawn_schedule() -> list[dict]:
    return normalized_spawns(read_json(SPAWNS_PATH))


def spawn_file_payload(data) -> dict:
    return {
        "builders": [
            {
                "builder": item["builder"],
                "turn": item["turn"],
                "tile": item["tile"],
            }
            for item in normalized_spawns(data)
        ]
    }


class PongEditorHandler(BaseHTTPRequestHandler):
    server_version = "PongEditor/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == "/" or path == "/index.html":
                self._send_file(EDITOR_ROOT / "index.html")
                return
            if path == "/api/state":
                self._send_json(self._state())
                return
            if path.startswith("/api/strategy/"):
                builder_number = path.rsplit("/", 1)[-1].removesuffix(".json")
                self._send_json(read_json(strategy_path(builder_number)))
                return
            if path.startswith("/assets/"):
                self._send_file(self._asset_path(path))
                return
            self._send_file(EDITOR_ROOT / path.lstrip("/"))
        except FileNotFoundError as exc:
            self._send_error(404, str(exc))
        except ValueError as exc:
            self._send_error(404, str(exc))
        except Exception as exc:
            self._send_error(500, str(exc))

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            payload = self._read_json_body()
            if path == "/api/plan":
                write_json(PLAN_PATH, payload)
                self._send_json({"ok": True, "path": PLAN_PATH.name})
                return
            if path == "/api/spawns":
                write_json(SPAWNS_PATH, spawn_file_payload(payload))
                self._send_json({"ok": True, "path": SPAWNS_PATH.name})
                return
            if path.startswith("/api/strategy/"):
                builder_number = path.rsplit("/", 1)[-1].removesuffix(".json")
                write_json(strategy_path(builder_number), payload)
                self._send_json({"ok": True, "path": f"strategies/{builder_number}.json"})
                return
            self._send_error(404, "Unknown API endpoint")
        except ValueError as exc:
            self._send_error(400, str(exc))
        except Exception as exc:
            self._send_error(500, str(exc))

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _state(self) -> dict:
        strategies = []
        STRATEGY_ROOT.mkdir(parents=True, exist_ok=True)
        for path in sorted(STRATEGY_ROOT.glob("*.json"), key=lambda p: int(p.stem)):
            strategies.append(
                {
                    "builder": int(path.stem),
                    "path": f"strategies/{path.name}",
                    "strategy": read_json(path),
                }
            )
        return {
            "map": read_json(MAP_PATH),
            "plan": read_json(PLAN_PATH),
            "spawn_schedule": spawn_schedule(),
            "strategies": strategies,
        }

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        return json.loads(raw_body.decode("utf-8"))

    def _send_json(self, payload: object, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path) -> None:
        resolved = path.resolve()
        allowed_roots = (EDITOR_ROOT.resolve(), DOCS_IMAGE_ROOT.resolve())
        if not any(resolved == root or root in resolved.parents for root in allowed_roots):
            raise FileNotFoundError(path)
        data = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME_TYPES.get(resolved.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _asset_path(self, path: str) -> Path:
        relative = Path(path.removeprefix("/assets/"))
        return DOCS_IMAGE_ROOT / relative

    def _send_error(self, status: int, message: str) -> None:
        self._send_json({"ok": False, "error": message}, status=status)


def main() -> int:
    host = "127.0.0.1"
    port = 8765
    server = ThreadingHTTPServer((host, port), PongEditorHandler)
    print(f"Pong editor running at http://{host}:{port}/")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
