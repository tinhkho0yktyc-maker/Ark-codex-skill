#!/usr/bin/env python3
"""Create a fresh deskpet project without overwriting an existing library."""

import argparse
import json
import shutil
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
APP_TEMPLATE = SKILL_DIR / "assets" / "deskpet-app"


def scaffold(target, pet_name="予愿安洁莉娜"):
    target = Path(target).resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise FileExistsError(
            f"Target is not empty: {target}. To add a pet, use process_webm.py; "
            "do not scaffold over an existing project."
        )
    target.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns(
        ".venv", ".tools-venv", "__pycache__", "*.pyc", "*.log*", "*.pid",
        "*.flag", "*.process.json", "settings.json", ".write-*.tmp",
    )
    shutil.copytree(APP_TEMPLATE, target, dirs_exist_ok=True, ignore=ignore)
    (target / "pets").mkdir(exist_ok=True)
    settings = {
        "speed": 1.0, "subtitle_length": "medium", "subtitle_size": 19,
        "bar_length": 100, "mini_mode": False, "auto_hide_fullscreen": False,
        "locked": True, "scale": 1.0, "pos_x": None, "pos_y": None,
        "pet": pet_name or "予愿安洁莉娜", "pet_states": {},
        "autostart_with_codex": False, "playback_fps": 60,
        "roaming_enabled": False, "roaming_speed": 30,
        "roaming_activity": 100, "roaming_walk_chance": 60,
        "roaming_distance": 160, "roaming_pause_min": 2, "roaming_pause_max": 5,
        "auto_rest_enabled": True,
    }
    (target / "settings.json").write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--pet", default="予愿安洁莉娜", help="preferred initial pet")
    args = parser.parse_args()
    try:
        target = scaffold(args.target, args.pet)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print("scaffolded deskpet project at", target)
    print("If the requested pet has not been imported, the bundled pet is used.")
    print("Autostart and roaming are off until you enable them in the menu.")


if __name__ == "__main__":
    main()
