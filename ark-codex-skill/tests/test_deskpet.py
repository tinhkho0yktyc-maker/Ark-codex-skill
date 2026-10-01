"""Isolated regression tests: no writes to live settings, processes or Codex data."""

import bisect
import importlib.machinery
import importlib.util
import json
import os
import shutil
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
PROJECT = Path(__file__).resolve().parents[1] / "assets" / "deskpet-app"
import sys
sys.path.insert(0, str(PROJECT))

import codex_monitor as monitor
import process_support as support
import main as pet
from PySide6.QtCore import QThread, QRect, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication

loader = importlib.machinery.SourceFileLoader("watcher_under_test", str(PROJECT / "codex_pet_launcher.pyw"))
spec = importlib.util.spec_from_loader(loader.name, loader)
watcher = importlib.util.module_from_spec(spec)
loader.exec_module(watcher)


def event(kind, **payload):
    return {"timestamp": "2026-10-01T00:00:00Z", "type": "event_msg", "payload": dict(type=kind, **payload)}


class MonitorTests(unittest.TestCase):
    def test_old_and_current_messages(self):
        s = monitor.SessionStatus()
        s.consume(event("user_message", message="旧任务"))
        self.assertEqual(s.task, "旧任务")
        s.consume(event("item_completed", item={"type": "UserMessage", "content": [{"text": "## My request:\n新任务"}]}))
        self.assertEqual(s.task, "新任务")
        s.consume(event("item_completed", item={"type": "AgentMessage", "content": [{"text": "正在验证"}], "phase": "commentary"}))
        self.assertEqual(s.progress, "正在验证")
        s.consume(event("user_message", message="<environment_context>not a user task</environment_context>"))
        self.assertEqual(s.task, "新任务")

    def test_model_and_turn_tokens(self):
        s = monitor.SessionStatus()
        s.consume({"type": "turn_context", "payload": {"thread_settings": {"model": "test-model"}}})
        s.consume(event("token_count", info={"total_token_usage": {"total_tokens": 10000}}))
        s.consume(event("task_started", started_at=1790812800000))
        s.consume(event("token_count", info={"total_token_usage": {"total_tokens": 10425}}))
        self.assertEqual((s.model, s.turn_tokens, s.session_tokens), ("test-model", 425, 10425))
        s.consume(event("task_complete", last_agent_message="完成"))
        self.assertFalse(s.active)
        s.consume(event("task_started"))
        s.consume(event("token_count", info={"total_token_usage": {"total_tokens": 10525}}))
        self.assertEqual(s.turn_tokens, 100)

    def test_silent_tool_call_does_not_end_turn(self):
        s = monitor.SessionStatus()
        s.consume(event("task_started", started_at=time.time() - 3600))
        self.assertTrue(s.active)
        s.consume(event("turn_aborted"))
        self.assertFalse(s.active)

    def test_partial_utf8_lines_and_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout-test.jsonl"
            data = json.dumps(event("user_message", message="中文测试"), ensure_ascii=False).encode("utf-8") + b"\n"
            cut = data.index("中".encode("utf-8")) + 1
            path.write_bytes(data[:cut])
            s = monitor.SessionStatus()
            s.read_new(path)
            self.assertEqual(s.task, "")
            with path.open("ab") as handle:
                handle.write(data[cut:] + b"invalid-json\n")
            s.read_new(path)
            self.assertEqual((s.task, s.malformed_lines), ("中文测试", 1))
            offset = s.offset
            s.read_new(path)
            self.assertEqual(s.offset, offset)
            path.write_text(json.dumps(event("task_complete")) + "\n", encoding="utf-8")
            s.read_new(path)
            self.assertFalse(s.active)
            self.assertEqual(s.task, "")

    def test_reader_multiple_sessions_incremental(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout-first.jsonl"
            path.write_text(json.dumps(event("task_started")) + "\n", encoding="utf-8")
            reader = monitor.StatusReader(directory)
            self.assertEqual(reader.poll()["active_count"], 1)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event("task_complete")) + "\n")
            self.assertFalse(reader.poll()["active"])


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.change = patch.object(support, "BASE_DIR", self.temp.name)
        self.change.start()

    def tearDown(self):
        self.change.stop()
        self.temp.cleanup()

    def test_named_single_instance_mutex(self):
        first = support.InstanceGuard("test")
        second = support.InstanceGuard("test")
        try:
            self.assertTrue(first.acquired)
            self.assertFalse(second.acquired)
        finally:
            first.close()
            second.close()
        third = support.InstanceGuard("test")
        self.assertTrue(third.acquired)
        third.close()

    def test_identity_rejects_reused_pid_and_wrong_role(self):
        support.write_identity("test", __file__)
        self.assertEqual(support.managed_identity("test", __file__)["pid"], os.getpid())
        self.assertIsNone(support.managed_identity("test", str(PROJECT / "main.py")))
        path = Path(self.temp.name) / "test.process.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["created"] += 1
        support.atomic_json(str(path), record)
        self.assertIsNone(support.managed_identity("test", __file__))
        self.assertFalse(support.terminate_managed("test", __file__))

    def test_identity_cleanup(self):
        support.write_identity("test", __file__)
        support.remove_identity("test")
        self.assertFalse((Path(self.temp.name) / "test.pid").exists())
        self.assertFalse((Path(self.temp.name) / "test.process.json").exists())

    def test_atomic_write_retries_transient_windows_lock(self):
        real_replace = os.replace
        attempts = []
        def replace(source, target):
            attempts.append(True)
            if len(attempts) < 3:
                raise PermissionError("temporary lock")
            real_replace(source, target)
        path = str(Path(self.temp.name) / "settings.json")
        with patch.object(support.os, "replace", replace):
            support.atomic_json(path, {"中文": True})
        self.assertEqual(len(attempts), 3)
        self.assertEqual(json.loads(Path(path).read_text(encoding="utf-8")), {"中文": True})

    def test_log_rotation(self):
        path = Path(self.temp.name) / "test.log"
        path.write_bytes(b"x" * 1_048_577)
        support.log("test", "rotated")
        self.assertTrue(Path(str(path) + ".1").is_file())
        self.assertLess(path.stat().st_size, 200)


class FakeProcess:
    pid = 101
    exit_code = None
    def poll(self):
        return self.exit_code


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.live = None
        self.process = FakeProcess()
        self.spawns = []
        self.patches = [
            patch.object(watcher.time, "monotonic", lambda: self.now),
            patch.object(watcher, "managed_identity", lambda *a: self.live),
            patch.object(watcher, "remove_flag", lambda *a: None),
            patch.object(watcher, "log", lambda *a: None),
            patch.object(watcher.subprocess, "Popen", lambda *a, **k: self.spawn()),
        ]
        for change in self.patches:
            change.start()
        self.supervisor = watcher.Supervisor()

    def spawn(self):
        self.spawns.append(self.now)
        return self.process

    def tearDown(self):
        for change in reversed(self.patches):
            change.stop()

    def test_grace_period_does_not_duplicate_slow_process(self):
        self.supervisor.ensure("pet")
        self.now += 20
        self.supervisor.ensure("pet")
        self.assertEqual(len(self.spawns), 1)

    def test_failed_initialization_backoff(self):
        self.supervisor.ensure("pet")
        self.process.exit_code = 1
        self.now += 1
        self.supervisor.ensure("pet")
        self.assertEqual(len(self.spawns), 1)
        self.now += 3
        self.supervisor.ensure("pet")
        self.assertEqual(len(self.spawns), 2)

    def test_repeated_crashes_keep_backoff_until_stable(self):
        self.live = {"created": 1}
        self.supervisor.ensure("pet")
        self.live = None
        self.now += 1
        self.supervisor.ensure("pet")
        self.assertEqual(self.supervisor.retry_at["pet"], self.now + 2)
        self.live = {"created": 2}
        self.now += 3
        self.supervisor.ensure("pet")
        self.live = None
        self.now += 1
        self.supervisor.ensure("pet")
        self.assertEqual(self.supervisor.retry_at["pet"], self.now + 4)


class DummyStatusWorker(QThread):
    ready = Signal(object)
    def run(self):
        pass


class LauncherParentTests(unittest.TestCase):
    def run_parent(self, exits):
        processes = [types.SimpleNamespace(wait=lambda code=code: code) for code in exits]
        delays, launches = [], []
        def launch(*args, **kwargs):
            launches.append(args[0])
            return processes.pop(0)
        guard = types.SimpleNamespace(acquired=True, close=lambda: None)
        with patch.object(watcher, "InstanceGuard", lambda role: guard), \
             patch.object(watcher, "write_identity", lambda *a: None), \
             patch.object(watcher, "remove_identity", lambda *a: None), \
             patch.object(watcher, "log", lambda *a: None), \
             patch.object(watcher.subprocess, "Popen", launch), \
             patch.object(watcher.time, "monotonic", lambda: 100), \
             patch.object(watcher.time, "sleep", delays.append):
            result = watcher.supervise_worker()
        return result, delays, launches

    def test_failed_worker_is_restarted_with_backoff(self):
        result, delays, launches = self.run_parent([1, 1, 0])
        self.assertEqual(result, 0)
        self.assertEqual(delays, [2, 4])
        self.assertEqual(len(launches), 3)
        self.assertTrue(all(command[-1] == "--worker" for command in launches))
        self.assertNotIn("--resume-host", launches[0])
        self.assertTrue(all("--resume-host" in command for command in launches[1:]))

    def test_normal_exit_does_not_restart(self):
        result, delays, launches = self.run_parent([0])
        self.assertEqual((result, delays, len(launches)), (0, [], 1))


class AutostartTests(unittest.TestCase):
    def test_powershell_output_encoding_is_explicit(self):
        import autostart_support
        response = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(autostart_support.subprocess, "run", return_value=response) as run:
            self.assertTrue(autostart_support._run_powershell("$null=1"))
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_task_keeps_current_user_and_interactive_logon(self):
        import autostart_support
        with patch.object(autostart_support, "_run_powershell", return_value=True) as run:
            self.assertTrue(autostart_support._set_scheduled_task(True))
        script = run.call_args.args[0]
        self.assertIn("Principal.LogonType=3", script)
        self.assertIn("Principal.RunLevel=0", script)
        self.assertIn("MultipleInstances=2", script)
        self.assertIn("RegisterTaskDefinition", script)


class FakeScreen:
    def __init__(self, rectangle):
        self.rectangle = rectangle
    def availableGeometry(self):
        return self.rectangle



def create_test_assets(root):
    """Procedural fixtures only; no PRTS downloads or personal character files."""
    image = QImage(256, 480, QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.fillRect(4, 4, 248, 472, QColor(40, 160, 100, 255))
    painter.end()
    first = root / "fixture.png"
    assert image.save(str(first))
    times = [index * 50 + (5 if index % 2 else 0) for index in range(120)]
    for name in ("测试角色A", "测试角色B"):
        manifest = {"schema_version": 2, "native_timing": True, "size": 1000, "fps": 60, "states": {}}
        for state in ("idle", "interact", "move", "sit", "sleep"):
            directory = root / name / "frames" / state
            directory.mkdir(parents=True)
            for index in range(120):
                shutil.copyfile(first, directory / f"frame_{index:04d}.png")
            manifest["states"][state] = {
                "count": 120, "duration": 6000, "bbox": [354, 404, 601, 875],
                "frame_times_ms": times, "frame_offsets": [[350, 400] for _ in times],
            }
        (root / name / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8",
        )


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        # The offscreen plugin has no Windows system-font backend.
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
            cls.app.setFont(QFont("Microsoft YaHei"))
        cls.assets = tempfile.TemporaryDirectory()
        create_test_assets(Path(cls.assets.name))

    @classmethod
    def tearDownClass(cls):
        cls.assets.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        selected = "测试角色A"
        settings = dict(pet.DEFAULT_SETTINGS, pet=selected, scale=0.3, locked=False, bar_length=45, subtitle_size=16)
        settings["pet_states"] = {}
        settings_path = str(Path(self.temp.name) / "settings.json")
        support.atomic_json(settings_path, settings)
        assets = Path(self.assets.name)
        manifest_path = assets / selected / "manifest.json"
        self.messages = []
        self.patches = [
            patch.object(pet, "StatusWorker", DummyStatusWorker),
            patch.object(pet, "SETTINGS_PATH", settings_path),
            patch.object(pet, "ACTIVE_PET", selected),
            patch.object(pet, "FPS", 60),
            patch.object(pet, "PETS_DIR", str(assets)),
            patch.object(pet, "MANIFEST", json.loads(manifest_path.read_text(encoding="utf-8"))),
            patch.object(pet, "FRAMES_DIR", str(assets / selected / "frames")),
            patch.object(pet, "log", lambda *a: self.messages.append(a)),
        ]
        for flag in ("HIDE_FLAG", "SHOW_FLAG", "SHUTDOWN_FLAG", "DISABLED_FLAG"):
            self.patches.append(patch.object(pet, flag, str(Path(self.temp.name) / flag)))
        for change in self.patches:
            change.start()
        self.window = pet.PetWindow()
        for timer in (self.window.timer, self.window.status_timer, self.window.fullscreen_timer):
            timer.stop()

    def tearDown(self):
        self.window.stop_worker()
        self.window.hide()
        try:
            self.app.aboutToQuit.disconnect(self.window.save_position)
            self.app.aboutToQuit.disconnect(self.window.stop_worker)
            self.app.screenAdded.disconnect(self.window.connect_screen)
            self.app.screenRemoved.disconnect(self.window.screen_changed)
            for display in self.app.screens():
                display.availableGeometryChanged.disconnect(self.window.screen_changed)
                display.geometryChanged.disconnect(self.window.screen_changed)
                display.logicalDotsPerInchChanged.disconnect(self.window.screen_changed)
        except RuntimeError:
            pass
        self.window.deleteLater()
        self.app.processEvents()
        for change in reversed(self.patches):
            change.stop()
        self.temp.cleanup()

    def test_native_timestamps_and_loop_duration(self):
        w = self.window
        w.manual_state = True
        w.anim_started_at = 100
        info = w.state_info("idle")
        times = info["frame_times_ms"]
        for elapsed in (0, 1, 517, 2120, info["duration"] + 250):
            with patch.object(pet.time, "monotonic", lambda: 100 + elapsed / 1000):
                w.next_frame()
            expected = max(0, bisect.bisect_right(times, elapsed % info["duration"]) - 1)
            self.assertEqual(w.frame_index, expected)

    def test_legacy_uniform_timing_remains_supported(self):
        w = self.window
        manifest = json.loads(json.dumps(pet.MANIFEST))
        for info in manifest["states"].values():
            info.pop("frame_times_ms")
        w.manual_state = True
        w.anim_started_at = 100
        with patch.object(pet, "MANIFEST", manifest), patch.object(pet, "FPS", 20), \
             patch.object(pet.time, "monotonic", lambda: 100.75):
            w.next_frame()
        self.assertEqual(w.frame_index, 15)

    def test_empty_library_has_no_active_pet(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(pet, "PETS_DIR", directory):
            self.assertEqual(pet.list_pets(), [])
            self.assertIsNone(pet.resolve_active_pet({}))

    def test_speed_changes_time_not_source_frame_rate(self):
        w = self.window
        w.manual_state = True
        w.anim_started_at = 100
        w.speed = 2
        with patch.object(pet.time, "monotonic", lambda: 101):
            w.next_frame()
        self.assertEqual(w.frame_index, bisect.bisect_right(w.state_info("idle")["frame_times_ms"], 2000) - 1)

    def test_automatic_rest_and_manual_priority(self):
        w = self.window
        w.auto_sit_after = 50
        w.last_activity = 940
        with patch.object(pet.time, "monotonic", lambda: 1000):
            w.next_frame()
        self.assertEqual(w.state, "sit")
        with patch.object(pet.time, "monotonic", lambda: 1030):
            w.next_frame()
        self.assertEqual(w.state, "sleep")
        w.set_state("idle", hold=True, manual=True)
        with patch.object(pet.time, "monotonic", lambda: 5000):
            w.next_frame()
        self.assertEqual(w.state, "idle")

    def test_menu_and_press_pause_automatic_rest(self):
        w = self.window
        w.last_activity = 0
        w.menu_open = True
        with patch.object(pet.time, "monotonic", lambda: 1000):
            w.next_frame()
        self.assertEqual(w.state, "idle")

    def test_interaction_completes_and_returns_to_idle(self):
        w = self.window
        with patch.object(pet.time, "monotonic", lambda: 100):
            w.note_activity()
            w.set_state("interact")
        completed_at = 100 + w.duration_ms() / 1000 + 0.1
        with patch.object(pet.time, "monotonic", lambda: completed_at):
            w.next_frame()
        self.assertEqual(w.state, "idle")

    def test_tiny_screen_and_large_action_remain_inside(self):
        w = self.window
        screen = FakeScreen(QRect(0, 0, 320, 200))
        with patch.object(w, "layout_screen", lambda: screen):
            w.scale = 2
            for state in pet.MANIFEST["states"]:
                w.set_state(state)
                self.assertTrue(screen.availableGeometry().contains(w.geometry()), (state, w.geometry()))
                self.assertGreater(w.render_scale, 0)

    def test_negative_monitor_origin_and_preserved_anchor(self):
        w = self.window
        screen = FakeScreen(QRect(-1920, -100, 1920, 1080))
        w.move(-900, 400)
        with patch.object(w, "layout_screen", lambda: screen):
            anchor = (w.x() + w.width()/2, w.y() + w.height())
            w.set_state("sleep")
            self.assertTrue(screen.availableGeometry().contains(w.geometry()))
            self.assertAlmostEqual(w.x() + w.width()/2, anchor[0], delta=1)
            self.assertEqual(w.y() + w.height(), anchor[1])

    def test_subtitle_width_independent_of_pet_scale(self):
        w = self.window
        width = w.status_bar_width()
        w.set_scale(1.5)
        self.assertEqual(w.status_bar_width(), width)
        w.bar_length = 100
        w.apply_geometry()
        self.assertGreater(w.status_bar_width(), width)

    def test_crop_image_cache_is_bounded(self):
        w = self.window
        w.set_state("interact")
        for index in range(100):
            w.frame_index = index
            self.assertFalse(w.current_image().isNull())
        self.assertLessEqual(w.cache_bytes, 32 * 1024 * 1024)
        self.assertLessEqual(len(w.cache), 128)

    def test_missing_image_logs_once(self):
        w = self.window
        w.frame_index = 99999
        self.assertTrue(w.current_image().isNull())
        self.assertTrue(w.current_image().isNull())
        self.assertEqual(len(self.messages), 1)

    def test_roaming_moves_and_manual_sleep_pauses_it(self):
        w = self.window
        w.move(250, 200)
        with patch.object(pet.time, "monotonic", lambda: 100):
            w.set_state("move")
            w.roaming_enabled = True
            w.roam_direction = (1, 0)
            w.roam_until = 110
            old = w.pos()
            w.step_roaming(100, 0.1)
            self.assertEqual(w.x(), old.x() + 3)
            w.set_state("sleep", hold=True, manual=True)
            old = w.pos()
            w.step_roaming(100.1, 0.1)
            self.assertEqual(w.pos(), old)

    def test_new_task_wakes_auto_sleep_but_not_manual_sleep(self):
        w = self.window
        w.set_state("sleep", hold=True)
        w.receive_status({"active": True, "task": "完整任务文本", "tokens": 425, "session_tokens": 10425})
        self.assertEqual(w.state, "idle")
        self.assertIn("完整任务文本", w.full_status_text)
        self.assertIn("10,425", w.full_status_text)
        w.receive_status({"active": False})
        w.set_state("sleep", hold=True, manual=True)
        w.receive_status({"active": True})
        self.assertEqual(w.state, "sleep")

    def test_selecting_pet_resets_idle_clock(self):
        w = self.window
        w.last_activity = 0
        w.select_pet("测试角色B")
        self.assertEqual(w.pet_name, "测试角色B")
        self.assertGreater(w.last_activity, 0)
        self.assertFalse(w.current_image().isNull())

    def test_render_contact_preview(self):
        w = self.window
        w.cached_status = {"active": True, "task": "桌宠优化：原始帧率与字幕悬停", "model": "test-model", "elapsed": 75, "tokens": 425}
        w.refresh_status()
        self.app.processEvents()
        self.assertTrue(w.grab().save(str(Path(self.temp.name) / "preview.png")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
