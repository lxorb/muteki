import json
import urllib.request
from pathlib import Path

LADDER_URL = "https://game.battlecode.cam/api/ladder"

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
OUTPUT_FILE = DATA_DIR / "ladder.json"

def main():
    DATA_DIR.mkdir(exist_ok=True)
    with urllib.request.urlopen(LADDER_URL) as resp:
        data = json.loads(resp.read())
    OUTPUT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {len(data)} teams to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
