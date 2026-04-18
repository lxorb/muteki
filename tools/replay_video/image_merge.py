import glob
import os
import re
import subprocess

VIDEO_FPS = 5

SCRIPT_DIR = os.path.dirname(__file__)
IMAGE_DIR = os.path.join(SCRIPT_DIR, "images")
VIDEO_DIR = os.path.join(SCRIPT_DIR, "videos")


def find_game_groups(image_dir: str) -> dict[str, list[str]]:
    """Group images by their prefix (everything before the round number)."""
    groups: dict[str, list[str]] = {}
    for path in sorted(glob.glob(os.path.join(image_dir, "*.png"))):
        filename = os.path.basename(path)
        match = re.match(r"^(.+)__(\d{4})\.png$", filename)
        if not match:
            continue
        prefix = match.group(1)
        groups.setdefault(prefix, []).append(path)
    return groups


if __name__ == "__main__":
    os.makedirs(VIDEO_DIR, exist_ok=True)

    groups = find_game_groups(IMAGE_DIR)
    print(f"Found {len(groups)} game(s) to merge\n")

    for prefix, images in groups.items():
        round_count = len(images)
        image_pattern = os.path.join(IMAGE_DIR, f"{prefix}__%04d.png")
        video_name = f"{prefix}__{round_count}rounds.mp4"
        video_path = os.path.join(VIDEO_DIR, video_name)

        print(f"Merging:\t{prefix}\t{round_count} rounds")
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
        print(f"Done:\t\t-> {video_path}\n")
