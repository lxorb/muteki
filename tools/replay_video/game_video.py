import glob
import os
import subprocess
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
MAX_BROWSERS = 12
ROUNDS_PER_CHUNK = 250
VIDEO_FPS = 5

match_id = "a7786e31-34f4-4133-9b14-e670ac8659ad"


def fetch_match_info(match_id: str) -> tuple[str, str, list[tuple[int, int]]]:
    url = f"https://game.battlecode.cam/match/{match_id}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    date_el = soup.find("p", class_="text-sm text-muted-foreground")
    raw_date = date_el.text.strip()
    parsed = datetime.strptime(raw_date, "%b %d, %I:%M:%S %p")
    parsed = parsed.replace(year=datetime.now().year)
    date = parsed.strftime("%Y-%m-%d")

    team_links = soup.find_all("a", href=lambda h: h and h.startswith("/team/"))
    enemy_team = next(
        link.text.strip()
        for link in team_links
        if link.text.strip() != OWN_TEAM
    )

    games = []
    for row in soup.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) >= 5:
            game_nr = int(cells[0].text.strip())
            turns = int(cells[4].text.strip())
            games.append((game_nr, turns))

    return date, enemy_team, games


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
                    print(f"[game {game_nr}]\tRound {round_nr:4d}/{round_end}\t-> {output_path}")
                    break
                except Exception as e:
                    print(f"[game {game_nr}]\tRound {round_nr:4d}\t\tfailed: {e}, retrying...")
                    time.sleep(2)
    finally:
        driver.quit()


if __name__ == "__main__":
    date, enemy_team, games = fetch_match_info(match_id)
    print(f"Date: {date}, Enemy: {enemy_team}, Games: {games}")

    output_dir = os.path.join(os.path.dirname(__file__), "images")
    os.makedirs(output_dir, exist_ok=True)

    chunks = []
    for game_nr, last_round in games:
        prefix = os.path.join(output_dir, f"{date}__{enemy_team}__{match_id}__{game_nr}")
        for chunk_start in range(0, last_round + 1, ROUNDS_PER_CHUNK):
            chunk_end = min(chunk_start + ROUNDS_PER_CHUNK - 1, last_round)
            chunks.append((match_id, game_nr, chunk_start, chunk_end, prefix))

    print(f"Launching {len(chunks)} chunks across {MAX_BROWSERS} browsers...")

    with ThreadPoolExecutor(max_workers=MAX_BROWSERS) as pool:
        futures = {
            pool.submit(screenshot_chunk, *chunk): chunk for chunk in chunks
        }
        for future in as_completed(futures):
            chunk = futures[future]
            try:
                future.result()
                print(f"Done:\tgame {chunk[1]}\trounds {chunk[2]:4d}-{chunk[3]:4d}")
            except Exception as e:
                print(f"Failed:\tgame {chunk[1]}\trounds {chunk[2]:4d}-{chunk[3]:4d}\t{e}")

    # Merge images into videos
    video_dir = os.path.join(os.path.dirname(__file__), "videos")
    os.makedirs(video_dir, exist_ok=True)

    for game_nr, last_round in games:
        image_prefix = os.path.join(output_dir, f"{date}__{enemy_team}__{match_id}__{game_nr}")
        image_pattern = f"{image_prefix}__%04d.png"
        video_name = f"{date}__{enemy_team}__{match_id}__{game_nr}__{last_round}rounds.mp4"
        video_path = os.path.join(video_dir, video_name)

        print(f"Creating video:\tgame {game_nr}\t-> {video_path}")
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
        print(f"Done:\t\tgame {game_nr}\t-> {video_path}")
