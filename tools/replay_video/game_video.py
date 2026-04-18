import getpass
import glob
import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

OWN_TEAM = "muteki"
HEADLESS = True
MAX_BROWSERS = 35
ROUNDS_PER_CHUNK = 80
VIDEO_FPS = 5

SCRIPT_DIR = os.path.dirname(__file__)
VIDEOS_JSON = os.path.join(SCRIPT_DIR, "videos.json")

# Progress tracking
_progress_lock = threading.Lock()
_progress = {"done": 0, "total": 0, "start": 0.0, "rate_ema": 0.0, "last_time": 0.0, "last_milestone": 0.0}
MILESTONE_INTERVAL = 300  # seconds between milestone prints
EMA_WARMUP_ROUNDS = 50


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")

TEAM_ID = "52f2b5ac-2f05-4bde-ab81-a5dc5edaa276"


def load_videos_json() -> dict:
    if os.path.exists(VIDEOS_JSON):
        with open(VIDEOS_JSON) as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    return {}


def update_stats(data: dict) -> None:
    total_games = 0
    total_losses = 0
    losses_by_condition = {}
    for key, entry in data.items():
        if key == "_stats":
            continue
        for g in entry.get("games", []):
            total_games += 1
            if g.get("result") == "loss":
                total_losses += 1
                cond = g.get("condition", "unknown")
                losses_by_condition[cond] = losses_by_condition.get(cond, 0) + 1
    data["_stats"] = {
        "total_games": total_games,
        "total_losses": total_losses,
        "losses_by_condition": losses_by_condition,
    }


def save_videos_json(data: dict) -> None:
    update_stats(data)
    with open(VIDEOS_JSON, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def fetch_match_ids(team_id: str) -> list[str]:
    url = f"https://game.battlecode.cam/matches?matchType=all&teamIdsLeft={team_id}&myTeamLeft=false"

    options = Options()
    options.add_argument("--headless")
    driver = webdriver.Firefox(options=options)

    try:
        print(f"[{_timestamp()}] Fetching match history...")
        driver.get(url)
        print(f"[{_timestamp()}] Waiting for match links to load...")
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/match/']"))
        )
        time.sleep(3)

        history_container = driver.find_element(By.CSS_SELECTOR, "div.border.w-full")
        links = history_container.find_elements(By.CSS_SELECTOR, "a[href^='/match/']")
        match_ids = []
        for link in links:
            href = link.get_attribute("href")
            mid = href.split("/match/")[1]
            if mid not in match_ids:
                match_ids.append(mid)

        print(f"[{_timestamp()}] Found {len(match_ids)} match IDs.")
        return match_ids
    finally:
        driver.quit()


def fetch_match_info(match_id: str) -> tuple[str, str, str, str, list[tuple[int, int]]]:
    url = f"https://game.battlecode.cam/match/{match_id}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    date_el = soup.find("p", class_="text-sm text-muted-foreground")
    raw_date = date_el.text.strip()
    parsed = datetime.strptime(raw_date, "%b %d, %I:%M:%S %p")
    parsed = parsed.replace(year=datetime.now().year)
    date = parsed.strftime("%Y-%m-%d")

    team_links = soup.find_all("a", href=lambda h: h and h.startswith("/team/"))
    team_names = list(dict.fromkeys(link.text.strip() for link in team_links if link.text.strip()))
    enemy_team = next((name for name in team_names if name != OWN_TEAM), team_names[0] if team_names else "unknown")

    # Score is displayed as "X-Y" where left team is first in the grid
    score_el = soup.find("span", class_=lambda c: c and "text-2xl" in c)
    score = score_el.text.strip()  # e.g. "1-4"

    # Determine which side we are: check if the first team column contains OWN_TEAM
    team_columns = soup.select("div.grid > div")
    first_team_name = team_columns[0].find("a").text.strip()
    own_score, enemy_score = score.split("-")
    if first_team_name != OWN_TEAM:
        own_score, enemy_score = enemy_score, own_score

    result = "win" if int(own_score) > int(enemy_score) else "loss"

    games = []
    game_details = []
    for row in soup.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) >= 5:
            game_nr = int(cells[0].text.strip())
            map_name = cells[1].text.strip()
            winner = cells[2].text.strip()
            condition = cells[3].text.strip()
            turns = int(cells[4].text.strip())
            games.append((game_nr, turns))
            game_result = "win" if winner == OWN_TEAM else "loss"
            game_details.append({
                "game": game_nr,
                "map": map_name,
                "winner": winner,
                "condition": condition,
                "turns": turns,
                "result": game_result,
            })

    return date, enemy_team, team_names, score, result, games, game_details


def set_round(driver, round_nr: int) -> None:
    round_button = WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "button[title='Click to type a turn number']"))
    )
    round_button.click()

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='number']"))
    )
    driver.execute_script(f"""
        const input = document.querySelector('input[type="number"]');
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeInputValueSetter.call(input, '{round_nr}');
        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
        input.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true, cancelable: true }}));
        input.dispatchEvent(new KeyboardEvent('keypress', {{ key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true, cancelable: true }}));
        input.dispatchEvent(new KeyboardEvent('keyup', {{ key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true, cancelable: true }}));
        input.blur();
    """)

    time.sleep(3)


def screenshot_chunk(
    match_id: str,
    game_nr: int,
    round_start: int,
    round_end: int,
    output_prefix: str,
) -> None:
    url = f"https://game.battlecode.cam/visualiser?matchId={match_id}&game={game_nr}"

    options = Options()
    if HEADLESS:
        options.add_argument("--headless")

    driver = webdriver.Firefox(options=options)

    try:
        driver.get(url)

        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "canvas"))
        )
        time.sleep(5)

        for round_nr in range(round_start, round_end + 1):
            output_path = f"{output_prefix}__{round_nr:04d}.png"
            while True:
                try:
                    set_round(driver, round_nr)
                    canvas = driver.find_element(By.TAG_NAME, "canvas")
                    canvas.screenshot(output_path)
                    now = time.time()
                    with _progress_lock:
                        _progress["done"] += 1
                        done = _progress["done"]
                        total = _progress["total"]
                        dt = now - _progress["last_time"]
                        if done > EMA_WARMUP_ROUNDS and dt > 0:
                            instant_rate = 1.0 / dt
                            if _progress["rate_ema"] == 0:
                                _progress["rate_ema"] = done / (now - _progress["start"])
                            else:
                                ratio = instant_rate / _progress["rate_ema"]
                                if 0.33 < ratio < 3.0:
                                    alpha = 0.005
                                    _progress["rate_ema"] = alpha * instant_rate + (1 - alpha) * _progress["rate_ema"]
                        _progress["last_time"] = now
                        rate = _progress["rate_ema"]
                        show_milestone = (now - _progress["last_milestone"]) >= MILESTONE_INTERVAL
                        if show_milestone:
                            _progress["last_milestone"] = now
                        elapsed = now - _progress["start"]
                        elapsed_m, elapsed_s = divmod(int(elapsed), 60)
                        total_w = len(str(total))
                        if rate > 0:
                            remaining = (total - done) / rate
                            est_total = elapsed + remaining
                            est_m, est_s = divmod(int(est_total), 60)
                            est_str = f"~{est_m:2d}m{est_s:02d}s"
                        else:
                            est_str = "  --m--s"
                        print(
                            f"[game {game_nr}]\t"
                            f"Round {round_nr:4d}/{round_end}\t\t"
                            f"{done:>{total_w}}/{total}\t\t"
                            f"{elapsed_m:2d}m{elapsed_s:02d}s / {est_str}",
                            flush=True,
                        )
                        if show_milestone and rate > 0:
                            pct = done / total * 100 if total > 0 else 0
                            print(
                                f"\n--- [{_timestamp()}] Milestone: {done}/{total} ({pct:.1f}%) "
                                f"| {elapsed_m}m{elapsed_s:02d}s / {est_str} ---\n",
                                flush=True,
                            )
                    break
                except Exception as e:
                    print(f"[game {game_nr}]\tRound {round_nr:4d}\t\tfailed: {e}, retrying...")
                    time.sleep(2)
    finally:
        driver.quit()


def process_match(match_id: str) -> None:
    videos_data = load_videos_json()
    if match_id in videos_data:
        print(f"  Already processed by {videos_data[match_id]['user']}, skipping.")
        return

    date, enemy_team, team_names, score, result, games, game_details = fetch_match_info(match_id)
    print(f"  Teams: {' vs '.join(team_names)}, Date: {date}, Score: {score} ({result}), Games: {games}")

    image_dir = os.path.join(SCRIPT_DIR, "images")
    os.makedirs(image_dir, exist_ok=True)

    # Screenshot all rounds
    chunks = []
    for game_nr, last_round in games:
        prefix = os.path.join(image_dir, f"{date}__{enemy_team}__{match_id}__{game_nr}")
        for chunk_start in range(0, last_round + 1, ROUNDS_PER_CHUNK):
            chunk_end = min(chunk_start + ROUNDS_PER_CHUNK - 1, last_round)
            chunks.append((match_id, game_nr, chunk_start, chunk_end, prefix))

    now = time.time()
    _progress["total"] = sum(last_round + 1 for _, last_round in games)
    _progress["done"] = 0
    _progress["start"] = now
    _progress["last_time"] = now
    _progress["last_milestone"] = now
    _progress["rate_ema"] = 0.0

    print(f"  [{_timestamp()}] Started screenshots")
    print(f"  Launching {len(chunks)} chunks across {MAX_BROWSERS} browsers ({_progress['total']} total rounds)...")

    remaining = list(chunks)
    while remaining:
        failed = []
        with ThreadPoolExecutor(max_workers=MAX_BROWSERS) as pool:
            futures = {
                pool.submit(screenshot_chunk, *chunk): chunk for chunk in remaining
            }
            for future in as_completed(futures):
                chunk = futures[future]
                try:
                    future.result()
                    print(f"Done:\tgame {chunk[1]}\trounds {chunk[2]:4d}-{chunk[3]:4d}")
                except Exception as e:
                    print(f"Failed:\tgame {chunk[1]}\trounds {chunk[2]:4d}-{chunk[3]:4d}\t(will retry)")
                    failed.append(chunk)

        if failed:
            print(f"\nRetrying {len(failed)} failed chunk(s)...")
            time.sleep(5)
        remaining = failed

    screenshots_elapsed = time.time() - _progress["start"]
    sm, ss = divmod(int(screenshots_elapsed), 60)
    print(f"\n  [{_timestamp()}] All screenshots done in {sm}m{ss:02d}s")

    # Merge images into videos
    video_dir = os.path.join(SCRIPT_DIR, "videos")
    os.makedirs(video_dir, exist_ok=True)

    for game_nr, last_round in games:
        image_prefix = os.path.join(image_dir, f"{date}__{enemy_team}__{match_id}__{game_nr}")
        image_pattern = f"{image_prefix}__%04d.png"
        video_name = f"{date}__{enemy_team}__{match_id}__{game_nr}__{last_round}rounds.mp4"
        video_path = os.path.join(video_dir, video_name)

        print(f"  Creating video:\tgame {game_nr}\t-> {video_path}")
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-loglevel", "error",
                "-framerate", str(VIDEO_FPS),
                "-i", image_pattern,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                video_path,
            ],
            check=True,
        )
        print(f"  Done:\t\tgame {game_nr}\t-> {video_path}")

    # Mark match as processed
    videos_data = load_videos_json()  # reload in case another process updated it
    losses_by_condition = {}
    for g in game_details:
        if g["result"] == "loss":
            cond = g["condition"]
            losses_by_condition[cond] = losses_by_condition.get(cond, 0) + 1
    videos_data[match_id] = {
        "user": getpass.getuser(),
        "date": date,
        "enemy": enemy_team,
        "score": score,
        "result": result,
        "games": game_details,
        "losses_by_condition": losses_by_condition,
    }
    save_videos_json(videos_data)
    print(f"  Recorded {match_id} in videos.json")

    total_elapsed = time.time() - _progress["start"]
    tm, ts = divmod(int(total_elapsed), 60)
    print(f"  [{_timestamp()}] Match done in {tm}m{ts:02d}s")

    # Clean up images
    for f in glob.glob(os.path.join(image_dir, f"*__{match_id}__*.png")):
        os.remove(f)
    print("  Cleaned up images.\n")


if __name__ == "__main__":
    image_dir = os.path.join(SCRIPT_DIR, "images")
    old_images = glob.glob(os.path.join(image_dir, "*.png"))
    print(f"[{_timestamp()}] {len(old_images)} images to clean up")
    if old_images:
        for f in old_images:
            os.remove(f)
        print(f"[{_timestamp()}] {len(old_images)} images removed")

    match_ids = fetch_match_ids(TEAM_ID)
    videos_data = load_videos_json()

    # Migrate old entries missing new fields
    REQUIRED_KEYS = {"user", "date", "enemy", "score", "result", "games", "losses_by_condition"}
    migrated = 0
    for mid, entry in list(videos_data.items()):
        if mid == "_stats":
            continue
        # Remove deprecated keys
        entry.pop("teams", None)
        missing = REQUIRED_KEYS - set(entry.keys())
        if missing:
            print(f"[{_timestamp()}] Backfilling {mid}: missing {missing}")
            try:
                _, enemy, _, score, result, _, game_details = fetch_match_info(mid)
                entry.setdefault("enemy", enemy)
                entry.setdefault("score", score)
                entry.setdefault("result", result)
                entry.setdefault("games", game_details)
                entry.setdefault("user", "unknown")
                entry.setdefault("date", "unknown")
                lbc = {}
                for g in entry.get("games", []):
                    if g.get("result") == "loss":
                        cond = g.get("condition", "unknown")
                        lbc[cond] = lbc.get(cond, 0) + 1
                entry.setdefault("losses_by_condition", lbc)
                migrated += 1
            except Exception as e:
                print(f"  Failed to backfill {mid}: {e}")
    if migrated:
        save_videos_json(videos_data)
        print(f"[{_timestamp()}] Backfilled {migrated} entries.")

    new_ids = [mid for mid in match_ids if mid not in videos_data]

    print(f"Found {len(match_ids)} matches, {len(new_ids)} new to process.\n")

    for i, match_id in enumerate(new_ids, 1):
        print(f"=== [{_timestamp()}] Match {i}/{len(new_ids)}: {match_id} ===")
        try:
            process_match(match_id)
        except Exception as e:
            print(f"  ERROR processing {match_id}: {e}\n")

