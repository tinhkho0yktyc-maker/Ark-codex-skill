#!/usr/bin/env python3
"""Validate and install a flat legacy/v2 pet without resetting project settings."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid

APP = Path(__file__).resolve().parents[1] / "assets" / "deskpet-app"
sys.path.insert(0, str(APP))
import library_channel
import library_support


def runtime_support(project):
    path = project / "process_support.py"
    spec = importlib.util.spec_from_file_location("install_process_identity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.BASE_DIR = str(project)
    return module


def decode_frame(path):
    from PIL import Image
    with Image.open(path) as image:
        image.load()
        if image.mode not in ("RGBA", "LA", "P") or image.convert("RGBA").getchannel("A").getextrema()[0] > 10:
            raise ValueError(f"Frame has no transparent exterior: {path}")


def reject_links(source):
    def check(path):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError(f"Links are not accepted in a pet package: {path}")
    check(source)
    for parent, directories, files in os.walk(source, followlinks=False):
        for name in directories + files:
            check(Path(parent) / name)


def install(source, project, name=None, replace=False, notify=True):
    source, project = Path(source).absolute(), Path(project).resolve()
    reject_links(source)
    name = library_support.pet_name(name if name is not None else source.name)
    if not (project / "main.py").is_file() or not (project / "process_support.py").is_file():
        raise ValueError("Target must be an existing Windows deskpet project")
    library = project / "pets"
    library.mkdir(exist_ok=True)
    if library.resolve() != library.absolute() or library.is_symlink() or getattr(library, "is_junction", lambda: False)():
        raise ValueError("Library directory must be inside the project, not a link")
    target = library / name
    if target == source.resolve() or source.resolve().is_relative_to(target):
        raise ValueError("Source must be separate from the installed pet")
    if target.exists() and not replace:
        raise FileExistsError("Pet already exists; choose another name or explicitly pass --replace")
    if target.exists() and (target.is_symlink() or getattr(target, "is_junction", lambda: False)()):
        raise ValueError("Installed target must not be a link")
    library_support.validate_pet(source, check_frames=True, decode=decode_frame)
    transaction = uuid.uuid4().hex
    lock = library / ".install-lock"
    lock.mkdir()  # An abandoned lock is reported, never automatically stolen.
    guard = None
    prepared = False
    published = False
    backup = None
    try:
        with tempfile.TemporaryDirectory(prefix=".import-", dir=library) as temporary:
            stage = Path(temporary) / "pet"
            stage.mkdir()
            shutil.copy2(source / "manifest.json", stage / "manifest.json")
            shutil.copytree(source / "frames", stage / "frames")
            library_support.validate_pet(stage, check_frames=True, decode=decode_frame)
            support = runtime_support(project)
            guard = support.InstanceGuard("pet")
            running = support.managed_identity("pet", project / "main.py")
            if not guard.acquired:
                guard.close()
                guard = None
                if running is None:
                    raise RuntimeError("Pet is starting or its identity cannot be verified; retry later")
                if not notify:
                    raise RuntimeError("Cannot skip the handshake while a desktop pet is running")
                library_channel.request(project, "prepare", name, transaction)
                prepared = True
                lease_deadline = time.monotonic() + 20
            if target.exists():
                if target.is_symlink() or getattr(target, "is_junction", lambda: False)():
                    raise ValueError("Destination became a link while importing")
                if not replace:
                    raise FileExistsError("Destination appeared while importing")
                backups = library / ".backups"
                backups.mkdir(exist_ok=True)
                if backups.resolve().parent != library.resolve() or backups.is_symlink() or getattr(backups, "is_junction", lambda: False)():
                    raise ValueError("Backup directory must not leave the library")
                backup = backups / f"{name}-{transaction}"
                os.rename(target, backup)
            if prepared and time.monotonic() >= lease_deadline:
                raise TimeoutError("Library lease expired before publication")
            os.rename(stage, target)
            published = True
            if prepared:
                library_channel.request(project, "finish", name, transaction)
                prepared = False
            return {"pet": str(target), "backup": str(backup) if backup else None,
                    "hot_refreshed": running is not None}
    except BaseException as original:
        if published and prepared:
            # A timed-out finish may already have resumed the app. Re-freeze
            # before rollback rather than changing files under a live player.
            try:
                library_channel.request(project, "prepare", name, transaction)
            except (OSError, ValueError, RuntimeError, TimeoutError):
                recovery_guard = runtime_support(project).InstanceGuard("pet")
                if not recovery_guard.acquired:
                    recovery_guard.close()
                    raise RuntimeError(
                        f"New pet was installed but refresh could not be confirmed. "
                        f"No unsafe live rollback was attempted; previous pet remains at {backup}. "
                        "Use Refresh Library or restart the app."
                    ) from original
                guard = recovery_guard
        # Keep a failed new version for diagnostics; restore the previous directory.
        if published and target.exists():
            failed = library / f".failed-{transaction}"
            os.rename(target, failed)
        if backup and backup.exists() and not target.exists():
            os.rename(backup, target)
        if prepared:
            try:
                library_channel.request(project, "finish" if backup else "cancel", name, transaction)
            except (OSError, ValueError, RuntimeError, TimeoutError):
                # Runtime's lease watchdog will retry loading the restored directory.
                pass
        raise
    finally:
        if guard is not None:
            guard.close()
        lock.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="validated pet directory, not the WebM folder")
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--name")
    parser.add_argument("--replace", action="store_true", help="retain the previous pet under pets/.backups before replacing")
    args = parser.parse_args()
    try:
        result = install(args.source, args.project, args.name, args.replace)
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        parser.exit(1, f"Install failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
