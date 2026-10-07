"""Isolated behavior, import, rollback and mailbox tests; no live app operations."""

import importlib.util
import json
from pathlib import Path
import random
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "assets" / "deskpet-app"))
sys.path.insert(0, str(SKILL / "scripts"))
import behavior_support as behavior
import library_channel as channel
import library_support as library
import install_deskpet as installer
import process_webm as converter
import build_release as release


def make_pet(root, special=False, cropped=True):
    root.mkdir()
    data = dict(size=64, fps=60, states={})
    if cropped:
        data.update(schema_version=2, native_timing=True)
    for state in library.REQUIRED_STATES + (("special",) if special else ()):
        directory = root / "frames" / state
        directory.mkdir(parents=True)
        image = Image.new("RGBA", (24, 32) if cropped else (64, 64))
        ImageDraw.Draw(image).rectangle((4, 4, 18, 26), fill=(0, 0, 0, 255))
        image.save(directory / "frame_0000.png")
        info = dict(count=1, duration=100, bbox=[14, 14, 28, 36] if cropped else [4, 4, 18, 26])
        if cropped:
            info.update(frame_times_ms=[0], frame_offsets=[[10, 10]])
        data["states"][state] = info
    (root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    return data


class Guard:
    def __init__(self, acquired=True):
        self.acquired = acquired
    def close(self):
        pass


def support(running=False):
    return types.SimpleNamespace(InstanceGuard=lambda role: Guard(not running),
                                 managed_identity=lambda *args: {"pid": 1} if running else None)


class BehaviorTests(unittest.TestCase):
    def test_nonfinite_settings_and_pause_order(self):
        settings = behavior.normalize_settings(dict(roaming_activity=float("nan"), roaming_pause_min=80, roaming_pause_max=2))
        self.assertEqual(settings["roaming_activity"], 100)
        self.assertEqual(settings["roaming_pause_max"], 80)

    def test_walk_zero_and_hundred_percent_and_missing_move(self):
        rng = random.Random(7)
        states = library.REQUIRED_STATES
        self.assertTrue(all(behavior.choose_action(dict(roaming_walk_chance=0), states, rng) != "move" for _ in range(200)))
        self.assertTrue(all(behavior.choose_action(dict(roaming_walk_chance=100), states, rng) == "move" for _ in range(100)))
        self.assertNotEqual(behavior.choose_action(dict(roaming_walk_chance=100), ["idle", "sit"], rng), "move")

    def test_optional_special_is_not_faked(self):
        rng = random.Random(9)
        choices = {behavior.choose_action(dict(roaming_walk_chance=0), library.REQUIRED_STATES, rng) for _ in range(1000)}
        self.assertNotIn("special", choices)
        choices = {behavior.choose_action(dict(roaming_walk_chance=0), library.REQUIRED_STATES + ("special",), rng) for _ in range(1000)}
        self.assertIn("special", choices)

    def test_activity_frequency_changes_real_time_pause_only(self):
        self.assertAlmostEqual(behavior.pause_seconds(dict(roaming_activity=200), random.Random(1)) * 2,
                               behavior.pause_seconds(dict(roaming_activity=100), random.Random(1)))

    def test_walk_direction_distance_and_speed_bounds(self):
        rng = random.Random(3)
        for _ in range(100):
            (dx, dy), distance, speed = behavior.walk_plan(dict(roaming_distance=20), 32, rng)
            self.assertAlmostEqual(dx * dx + dy * dy, 1)
            self.assertEqual(distance, 20)
            self.assertTrue(25.6 <= speed <= 38.4)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "角色测试"
        self.data = make_pet(self.source, special=True)
        self.project = self.root / "project"
        self.project.mkdir()
        for name in ("main.py", "process_support.py"):
            (self.project / name).write_text("fixture", encoding="utf-8")
        (self.project / "settings.json").write_bytes(b"user-settings-do-not-touch")

    def tearDown(self):
        self.temp.cleanup()

    def test_v2_and_legacy_and_extra_special_validate(self):
        self.assertIn("special", library.validate_pet(self.source, True, installer.decode_frame)["states"])
        legacy = self.root / "legacy"
        make_pet(legacy, cropped=False)
        library.validate_pet(legacy, True, installer.decode_frame)

    def test_corrupt_png_is_rejected_before_installation(self):
        (self.source / "frames" / "special" / "frame_0000.png").write_bytes(b"broken")
        with self.assertRaises(ValueError):
            installer.install(self.source, self.project)
        self.assertFalse((self.project / "pets" / self.source.name).exists())

    def test_timestamp_and_crop_bounds_rejected(self):
        for change in ({"frame_times_ms": [float("nan")]}, {"frame_offsets": [[63, 63]]}):
            data = json.loads(json.dumps(self.data))
            data["states"]["idle"].update(change)
            (self.source / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                library.validate_pet(self.source, True)
        data = json.loads(json.dumps(self.data))
        data["fps"] = 0.5
        (self.source / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fps"):
            library.validate_pet(self.source)

    def test_path_and_reserved_names_rejected(self):
        for name in ("../pet", "C:\\pet", ".hidden", "NUL", "COM1", "bad."):
            with self.assertRaises(ValueError):
                library.pet_name(name)

    def test_import_excludes_sources_and_keeps_settings(self):
        (self.source / "private.txt").write_text("not part of pet", encoding="utf-8")
        with patch.object(installer, "runtime_support", lambda _: support()):
            result = installer.install(self.source, self.project)
        target = Path(result["pet"])
        self.assertEqual({p.name for p in target.iterdir()}, {"frames", "manifest.json"})
        self.assertEqual((self.project / "settings.json").read_bytes(), b"user-settings-do-not-touch")
        self.assertFalse(result["hot_refreshed"])

    def test_replace_requires_explicit_flag_and_retains_backup(self):
        with patch.object(installer, "runtime_support", lambda _: support()):
            first = installer.install(self.source, self.project)
            with self.assertRaises(FileExistsError):
                installer.install(self.source, self.project)
            old = (Path(first["pet"]) / "manifest.json").read_bytes()
            result = installer.install(self.source, self.project, replace=True)
        self.assertEqual((Path(result["backup"]) / "manifest.json").read_bytes(), old)
        self.assertEqual(library.discover_pets(self.project / "pets")[0], [self.source.name])

    def test_running_runtime_must_acknowledge_before_replace(self):
        with patch.object(installer, "runtime_support", lambda _: support()):
            installer.install(self.source, self.project)
        target = self.project / "pets" / self.source.name
        old = (target / "manifest.json").read_bytes()
        with patch.object(installer, "runtime_support", lambda _: support(True)), \
                patch.object(channel, "request", side_effect=TimeoutError("offline")):
            with self.assertRaises(TimeoutError):
                installer.install(self.source, self.project, replace=True)
        self.assertEqual((target / "manifest.json").read_bytes(), old)

    def test_finish_failure_restores_old_and_keeps_failed_candidate(self):
        with patch.object(installer, "runtime_support", lambda _: support()):
            installer.install(self.source, self.project)
        target = self.project / "pets" / self.source.name
        old = (target / "manifest.json").read_bytes()
        self.data["states"]["idle"]["duration"] = 200
        (self.source / "manifest.json").write_text(json.dumps(self.data), encoding="utf-8")
        with patch.object(installer, "runtime_support", lambda _: support(True)), \
                patch.object(channel, "request", side_effect=[{}, RuntimeError("reject new"), {}, {}]):
            with self.assertRaises(RuntimeError):
                installer.install(self.source, self.project, replace=True)
        self.assertEqual((target / "manifest.json").read_bytes(), old)
        self.assertEqual(len(list((self.project / "pets").glob(".failed-*"))), 1)

    def test_ambiguous_finish_never_rolls_back_under_an_unresponsive_live_app(self):
        with patch.object(installer, "runtime_support", lambda _: support()):
            installer.install(self.source, self.project)
        self.data["states"]["idle"]["duration"] = 200
        (self.source / "manifest.json").write_text(json.dumps(self.data), encoding="utf-8")
        with patch.object(installer, "runtime_support", lambda _: support(True)), \
                patch.object(channel, "request", side_effect=[{}, TimeoutError(), TimeoutError()]):
            with self.assertRaisesRegex(RuntimeError, "No unsafe live rollback"):
                installer.install(self.source, self.project, replace=True)
        target = self.project / "pets" / self.source.name
        self.assertEqual(library.validate_pet(target)["states"]["idle"]["duration"], 200)
        self.assertEqual(len(list((self.project / "pets" / ".backups").iterdir())), 1)

    def test_invalid_library_member_does_not_hide_valid_pets(self):
        bad = self.root / "bad"
        bad.mkdir()
        (bad / "manifest.json").write_text("invalid", encoding="utf-8")
        names, errors = library.discover_pets(self.root)
        self.assertIn(self.source.name, names)
        self.assertIn("bad", errors)

    def test_optional_webm_and_duplicate_special(self):
        webm = self.root / "webm"
        webm.mkdir()
        for token, _ in converter.STATE_MAP + converter.OPTIONAL_MAP:
            (webm / f"operator-{token}.webm").write_bytes(b"x" * 1001)
        self.assertIn("special", converter.find_sources(webm))
        (webm / "other-Special.webm").write_bytes(b"x" * 1001)
        with self.assertRaisesRegex(ValueError, "Multiple files"):
            converter.find_sources(webm)

    def test_mailbox_roundtrip_and_cleanup(self):
        stop = threading.Event()
        def server():
            while not stop.wait(0.01):
                channel.receive(self.project, lambda data: {"received": data["kind"]})
        thread = threading.Thread(target=server)
        thread.start()
        try:
            result = channel.request(self.project, "prepare", self.source.name, "a" * 32, timeout=2)
            self.assertEqual(result["received"], "prepare")
        finally:
            stop.set()
            thread.join()
        self.assertFalse(list((self.project / ".library-control").iterdir()))

    def test_broken_optional_special_is_not_silently_ignored(self):
        webm = self.root / "webm"
        webm.mkdir()
        for token, _ in converter.STATE_MAP:
            (webm / f"operator-{token}.webm").write_bytes(b"x" * 1001)
        (webm / "operator-Special.webm").write_bytes(b"x" * 110)
        with self.assertRaisesRegex(ValueError, "Special WebM is broken"):
            converter.find_sources(webm)


class ReleaseTests(unittest.TestCase):
    def test_allowlist_excludes_personal_data_and_new_game_assets(self):
        for name in ("settings.json", ".env", "work/private.py", "ark-codex-skill/assets/deskpet-app/settings.json",
                     "ark-codex-skill/assets/deskpet-app/pets/凯尔希/manifest.json",
                     "ark-codex-skill/assets/deskpet-app/.library-control/request.json"):
            self.assertFalse(release.allowed(Path(name)), name)
        self.assertTrue(release.allowed(Path("ark-codex-skill/assets/deskpet-app/pets/予愿安洁莉娜/manifest.json")))

    def test_build_checks_archive_and_refuses_existing_output(self):
        import hashlib
        import zipfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            for name in ("README.md", "NOTICE.md", "CHANGELOG.md", "VERSION", "ark-codex-skill/SKILL.md",
                         "ark-codex-skill/assets/deskpet-app/main.py", "ark-codex-skill/assets/deskpet-app/behavior_support.py",
                         "ark-codex-skill/assets/deskpet-app/library_support.py", "ark-codex-skill/assets/deskpet-app/library_channel.py"):
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("0.3.0-rc.1" if name == "VERSION" else "fixture", encoding="utf-8")
            (repo / "settings.json").write_text("private", encoding="utf-8")
            output = root / "release"
            result = release.build(output, repo)
            with zipfile.ZipFile(result["zip"]) as zipper:
                self.assertIsNone(zipper.testzip())
                self.assertFalse(any("settings.json" in name for name in zipper.namelist()))
            digest = hashlib.sha256(Path(result["zip"]).read_bytes()).hexdigest()
            self.assertIn(digest, (output / "SHA256SUMS.txt").read_text())
            with self.assertRaises(ValueError):
                release.build(output, repo)

    def test_release_directory_cannot_contaminate_source(self):
        with self.assertRaises(ValueError):
            release.build(release.REPO / "release")


if __name__ == "__main__":
    unittest.main(verbosity=2)
