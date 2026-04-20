import getpass
import json
import os
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
MAX_BROWSERS = 10

SCRIPT_DIR = os.path.dirname(__file__)
IMAGES_JSON = os.path.join(SCRIPT_DIR, "images.json")
IMAGES_DIR = os.path.join(SCRIPT_DIR, "images")
TEMP_DIR = os.path.join(SCRIPT_DIR, "temp_img")
TEAM_ID = "52f2b5ac-2f05-4bde-ab81-a5dc5edaa276"

_json_lock = __import__("threading").Lock()

CONDITION_ABBREV = {
    "Axionite Collected": "ax",
    "Titanium Collected": "ti",
    "Core Destroyed": "core",
}


def _timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def condition_tag(result: str, condition: str) -> str:
    abbrev = CONDITION_ABBREV.get(condition, condition.lower().replace(" ", "_"))
    prefix = "w" if result == "win" else "l"
    return f"{prefix}_{abbrev}"


def load_images_json() -> dict:
    if os.path.exists(IMAGES_JSON):
        with open(IMAGES_JSON) as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    return {}


def update_stats(data: dict) -> None:
    total_games = 0
    total_losses = 0
    total_wins = 0
    losses_by_condition = {}
    wins_by_condition = {}
    for key, entry in data.items():
        if key == "_stats":
            continue
        for g in entry.get("games", []):
            total_games += 1
            cond = g.get("condition", "unknown")
            if g.get("result") == "loss":
                total_losses += 1
                losses_by_condition[cond] = losses_by_condition.get(cond, 0) + 1
            elif g.get("result") == "win":
                total_wins += 1
                wins_by_condition[cond] = wins_by_condition.get(cond, 0) + 1
    data["_stats"] = {
        "total_games": total_games,
        "total_wins": total_wins,
        "total_losses": total_losses,
        "wins_by_condition": wins_by_condition,
        "losses_by_condition": losses_by_condition,
    }


def save_images_json(data: dict) -> None:
    update_stats(data)
    with open(IMAGES_JSON, "w") as f:
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


def fetch_match_info(match_id: str) -> tuple[str, str, list[str], str, str, list[tuple[int, int]], list[dict]]:
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

    score_el = soup.find("span", class_=lambda c: c and "text-2xl" in c)
    score = score_el.text.strip()

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


def screenshot_game_with_driver(driver, match_id: str, game_nr: int, last_round: int, output_path: str) -> None:
    url = f"https://game.battlecode.cam/visualiser?matchId={match_id}&game={game_nr}"
    driver.get(url)

    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.TAG_NAME, "canvas"))
    )
    time.sleep(5)

    WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "button[title='Click to type a turn number']"))
    )

    max_retries = 10
    for attempt in range(max_retries):
        try:
            set_round(driver, last_round)
            canvas = driver.find_element(By.TAG_NAME, "canvas")
            canvas.screenshot(output_path)
            return
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  [{match_id}] game {game_nr}\tfailed (attempt {attempt + 1}/{max_retries}), retrying...")
                time.sleep(2)
            else:
                raise RuntimeError(f"game {game_nr} failed after {max_retries} attempts") from e


def worker(match_queue, match_infos: dict) -> None:
    """Worker thread: creates one browser and processes matches from the queue."""
    options = Options()
    if HEADLESS:
        options.add_argument("--headless")

    driver = webdriver.Firefox(options=options)

    try:
        while True:
            try:
                match_id = match_queue.get_nowait()
            except Exception:
                break

            match_info = match_infos[match_id]
            date, enemy_team, score, result, game_details = match_info
            game_detail_by_nr = {g["game"]: g for g in game_details}

            try:
                # Screenshot each game to temp
                temp_files = []
                for gd in game_details:
                    game_nr = gd["game"]
                    last_round = gd["turns"]
                    tag = condition_tag(gd.get("result", "loss"), gd.get("condition", "unknown"))
                    map_name = gd.get("map", "unknown")
                    image_name = f"{date}__{enemy_team}__{match_id}__{game_nr}__{last_round}__{map_name}__{tag}.png"
                    temp_path = os.path.join(TEMP_DIR, image_name)
                    final_path = os.path.join(IMAGES_DIR, image_name)

                    screenshot_game_with_driver(driver, match_id, game_nr, last_round, temp_path)
                    temp_files.append((temp_path, final_path))

                # Write json (thread-safe)
                with _json_lock:
                    images_data = load_images_json()
                    losses_by_condition = {}
                    wins_by_condition = {}
                    for g in game_details:
                        cond = g["condition"]
                        if g["result"] == "loss":
                            losses_by_condition[cond] = losses_by_condition.get(cond, 0) + 1
                        elif g["result"] == "win":
                            wins_by_condition[cond] = wins_by_condition.get(cond, 0) + 1
                    images_data[match_id] = {
                        "user": getpass.getuser(),
                        "date": date,
                        "enemy": enemy_team,
                        "score": score,
                        "result": result,
                        "games": game_details,
                        "wins_by_condition": wins_by_condition,
                        "losses_by_condition": losses_by_condition,
                    }
                    save_images_json(images_data)

                # Move from temp to final destination
                for temp_path, final_path in temp_files:
                    if os.path.exists(temp_path):
                        os.rename(temp_path, final_path)

                print(f"  [{_timestamp()}] {match_id} done ({score}, {result})")

            except Exception as e:
                print(f"  [{_timestamp()}] {match_id} FAILED: {e}")
                # Put back in queue for retry
                match_queue.put(match_id)

            match_queue.task_done()
    finally:
        driver.quit()


def process_matches(match_ids: list[str]) -> None:
    import queue
    import threading

    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(TEMP_DIR, exist_ok=True)

    # Fetch match info for all matches
    match_infos = {}
    for match_id in match_ids:
        try:
            date, enemy_team, team_names, score, result, games, game_details = fetch_match_info(match_id)
            print(f"  {match_id}  {' vs '.join(team_names)}  {score} ({result})")
            match_infos[match_id] = (date, enemy_team, score, result, game_details)
        except Exception as e:
            print(f"  {match_id}  ERROR fetching info: {e}")

    total_games = sum(len(info[4]) for info in match_infos.values())
    print(f"\n[{_timestamp()}] Processing {len(match_infos)} matches ({total_games} games) with {MAX_BROWSERS} browsers...")

    match_queue = queue.Queue()
    for mid in match_infos:
        match_queue.put(mid)

    threads = []
    num_workers = min(MAX_BROWSERS, len(match_infos))
    for _ in range(num_workers):
        t = threading.Thread(target=worker, args=(match_queue, match_infos))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    print(f"[{_timestamp()}] All done\n")


if __name__ == "__main__":
    import glob

    # Clear temp folder at startup
    os.makedirs(TEMP_DIR, exist_ok=True)
    old_temp = glob.glob(os.path.join(TEMP_DIR, "*.png"))
    if old_temp:
        for f in old_temp:
            os.remove(f)
        print(f"[{_timestamp()}] Cleared {len(old_temp)} files from temp_img")

    # Migrate old entries missing new fields (once at startup)
    images_data = load_images_json()
    REQUIRED_KEYS = {"user", "date", "enemy", "score", "result", "games", "losses_by_condition", "wins_by_condition"}
    migrated = 0
    for mid, entry in list(images_data.items()):
        if mid == "_stats":
            continue
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
                wbc = {}
                for g in entry.get("games", []):
                    cond = g.get("condition", "unknown")
                    if g.get("result") == "loss":
                        lbc[cond] = lbc.get(cond, 0) + 1
                    elif g.get("result") == "win":
                        wbc[cond] = wbc.get(cond, 0) + 1
                entry.setdefault("losses_by_condition", lbc)
                entry.setdefault("wins_by_condition", wbc)
                migrated += 1
            except Exception as e:
                print(f"  Failed to backfill {mid}: {e}")
    if migrated:
        save_images_json(images_data)
        print(f"[{_timestamp()}] Backfilled {migrated} entries.")

    iteration = 0
    while True:
        iteration += 1
        print(f"\n{'='*60}")
        print(f"[{_timestamp()}] Iteration {iteration}")
        print(f"{'='*60}")

        match_ids = fetch_match_ids(TEAM_ID)
        images_data = load_images_json()
        new_ids = [mid for mid in match_ids if mid not in images_data]

        if not new_ids:
            print(f"[{_timestamp()}] No new matches. Waiting 60s before next check...")
            time.sleep(60)
            continue

        print(f"Found {len(match_ids)} matches, {len(new_ids)} new to process.\n")

        try:
            process_matches(new_ids)
        except Exception as e:
            print(f"  ERROR: {e}\n")
