#!/usr/bin/env python3
"""Install the runtime in .venv; optionally install export tools separately."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def run(command):
    print("RUN", " ".join(map(str, command)), flush=True)
    subprocess.check_call(list(map(str, command)))


def install_environment(project, folder, requirements, python):
    environment = project / folder
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not executable.is_file():
        run([python, "-m", "venv", environment])
    run([executable, "-m", "pip", "install", "--disable-pip-version-check", "-r", requirements])
    return executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--tools", action="store_true", help="also create .tools-venv")
    parser.add_argument("--skip-browser", action="store_true",
                        help="use system Chrome/Edge instead of downloading Chromium")
    args = parser.parse_args()
    project = args.project.resolve()
    requirements = project / "requirements.txt"
    if not (project / "main.py").is_file() or not requirements.is_file():
        parser.error("Scaffold the project first; main.py and requirements.txt are required.")
    install_environment(project, ".venv", requirements, args.python)
    if args.tools:
        tools_python = install_environment(
            project, ".tools-venv", SCRIPT_DIR / "requirements-tools.txt", args.python,
        )
        if not args.skip_browser:
            run([tools_python, "-m", "playwright", "install", "chromium"])
        print("FFmpeg and ffprobe must be installed separately and available on PATH.")
    print("environment ready at", project / ".venv")


if __name__ == "__main__":
    main()
