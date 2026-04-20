"""Temporary script to rename existing videos to the new format.

New format: {date}__{enemy}__{match_id}__{game_nr}__{turns}__{map}__{tag}.mp4
Run once, then delete. The main videos.py script handles this for new videos.
"""

import glob
import os
import re

import requests
from bs4 import BeautifulSoup

OWN_TEAM = "muteki"
SCRIPT_DIR = os.path.dirname(__file__)
VIDEO_DIR = os.path.join(SCRIPT_DIR, "videos")

CONDITION_ABBREV = {
    "Axionite Collected": "ax",
    "Titanium Collected": "ti",
    "Core Destroyed": "core",
}


def condition_tag(result: str, condition: str) -> str:
    abbrev = CONDITION_ABBREV.get(condition, condition.lower().replace(" ", "_"))
    prefix = "w" if result == "win" else "l"
    return f"{prefix}_{abbrev}"


def fetch_game_details(match_id: str) -> dict[int, dict]:
    url = f"https://game.battlecode.cam/match/{match_id}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    details = {}
    for row in soup.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) >= 5:
            game_nr = int(cells[0].text.strip())
            map_name = cells[1].text.strip()
            winner = cells[2].text.strip()
            condition = cells[3].text.strip()
            game_result = "win" if winner == OWN_TEAM else "loss"
            details[game_nr] = {
                "result": game_result,
                "condition": condition,
                "map": map_name,
            }
    return details


# Matches any old format — with or without "rounds", with or without tag
# Groups: 1=date, 2=enemy, 3=match_id, 4=game_nr, 5=turns (with optional "rounds"), 6=rest (tag if present)
ANY_VIDEO = re.compile(
    r"^(.+)__(.+)__([0-9a-f-]{36})__(\d+)__(\d+)(rounds)?(?:__(.+))?\.mp4$"
)

# Already in new format: {date}__{enemy}__{match_id}__{game_nr}__{turns}__{map}__{tag}.mp4
NEW_FORMAT = re.compile(
    r"^.+__.+__[0-9a-f-]{36}__\d+__\d+__.+__(w|l)_.+\.mp4$"
)


if __name__ == "__main__":
    videos = glob.glob(os.path.join(VIDEO_DIR, "*.mp4"))
    print(f"Found {len(videos)} videos in {VIDEO_DIR}")

    to_rename: dict[str, list[tuple[str, int]]] = {}
    skipped = 0

    for path in sorted(videos):
        filename = os.path.basename(path)

        if NEW_FORMAT.match(filename):
            skipped += 1
            continue

        m = ANY_VIDEO.match(filename)
        if not m:
            print(f"  Skipping unrecognized: {filename}")
            continue

        match_id = m.group(3)
        game_nr = int(m.group(4))
        to_rename.setdefault(match_id, []).append((path, game_nr))

    print(f"  {skipped} already in new format, {sum(len(v) for v in to_rename.values())} to rename across {len(to_rename)} matches")

    for match_id, files in to_rename.items():
        print(f"\nFetching match {match_id}...")
        try:
            details = fetch_game_details(match_id)
        except Exception as e:
            print(f"  ERROR fetching: {e}")
            continue

        for path, game_nr in files:
            filename = os.path.basename(path)
            m = ANY_VIDEO.match(filename)
            gd = details.get(game_nr)
            if not gd:
                print(f"  No data for game {game_nr}, skipping {filename}")
                continue

            date = m.group(1)
            enemy = m.group(2)
            turns = m.group(5)  # just the number, without "rounds"
            tag = condition_tag(gd["result"], gd["condition"])
            map_name = gd["map"]

            new_filename = f"{date}__{enemy}__{match_id}__{game_nr}__{turns}__{map_name}__{tag}.mp4"
            new_path = os.path.join(VIDEO_DIR, new_filename)

            print(f"  {filename}")
            print(f"  -> {new_filename}")
            os.rename(path, new_path)

    print(f"\nDone.")
