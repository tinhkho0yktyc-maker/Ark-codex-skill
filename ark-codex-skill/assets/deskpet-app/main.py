import bisect
import ctypes
import math
import json
import os
import random
import sys
import time
from ctypes import wintypes
from collections import OrderedDict

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QImage,
    QPainter,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QSlider,
    QVBoxLayout,
    QWidget,
    QToolTip,
)

import autostart_support
import codex_monitor
from process_support import InstanceGuard, atomic_json, log, remove_identity, write_identity

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PETS_DIR = os.path.join(BASE_DIR, "pets")
ERROR_LOG = os.path.join(BASE_DIR, "pet_error.log")
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.json")
PID_FILE = os.path.join(BASE_DIR, "pet.pid")
SHUTDOWN_FLAG = os.path.join(BASE_DIR, "pet_shutdown.flag")
DISABLED_FLAG = os.path.join(BASE_DIR, "pet_disabled.flag")
SHOW_FLAG = os.path.join(BASE_DIR, "pet_show.flag")
HIDE_FLAG = os.path.join(BASE_DIR, "pet_hide.flag")
WATCHER_PATH = os.path.join(BASE_DIR, "codex_pet_launcher.pyw")
PYW_PATH = os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe")

PAD = 12
STATUS_H = 46
STATUS_BAR_MIN_W = 220
STATUS_BAR_FULL_W = 720
POSITION_FORMAT = "pet_bottom_center_v1"
MIN_SCALE = 0.3
MAX_SCALE = 2.0

SPEED_OPTIONS = [
    ("0.5x", 0.5),
    ("0.75x", 0.75),
    ("1.0x", 1.0),
    ("1.25x", 1.25),
    ("1.5x", 1.5),
]

SUBTITLE_LEVELS = {
    "short": {
        "label": "简短",
        "task_limit": 14,
        "show_model": False,
        "show_progress": False,
    },
    "medium": {
        "label": "标准",
        "task_limit": 36,
        "show_model": True,
        "show_progress": False,
    },
    "long": {
        "label": "详细",
        "task_limit": 80,
        "show_model": True,
        "show_progress": True,
    },
}

DEFAULT_SETTINGS = {
    "speed": 1.0,
    "subtitle_length": "medium",
    "subtitle_size": 19,
    "bar_length": 100,
    "mini_mode": False,
    "auto_hide_fullscreen": False,
    "locked": True,
    "scale": 1.0,
    "pos_x": None,
    "pos_y": None,
    "pet": None,
    "pet_states": {},
    "autostart_with_codex": False,
    "playback_fps": 60,
    "roaming_enabled": False,
    "roaming_speed": 30,
}


def load_settings():
    data = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data.update(json.load(f))
    except Exception:
        pass
    return data


def save_settings(data):
    atomic_json(SETTINGS_PATH, data)

def list_pets():
    pets = []
    if not os.path.isdir(PETS_DIR):
        return pets
    for name in sorted(os.listdir(PETS_DIR)):
        if os.path.isfile(os.path.join(PETS_DIR, name, "manifest.json")):
            pets.append(name)
    return pets


def resolve_active_pet(settings):
    pets = list_pets()
    name = settings.get("pet")
    if name in pets:
        return name
    return pets[0] if pets else None


_initial_settings = load_settings()
ACTIVE_PET = resolve_active_pet(_initial_settings)
FRAMES_DIR = os.path.join(PETS_DIR, ACTIVE_PET, "frames") if ACTIVE_PET else ""
MANIFEST_PATH = os.path.join(PETS_DIR, ACTIVE_PET, "manifest.json") if ACTIVE_PET else ""
MANIFEST = {"fps": 60, "size": 1000, "states": {}}
if ACTIVE_PET:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        MANIFEST = json.load(f)

FPS = int(MANIFEST["fps"])


def switch_pet(name):
    global ACTIVE_PET, FRAMES_DIR, MANIFEST_PATH, MANIFEST, FPS
    if name not in list_pets():
        return False
    ACTIVE_PET = name
    FRAMES_DIR = os.path.join(PETS_DIR, name, "frames")
    MANIFEST_PATH = os.path.join(PETS_DIR, name, "manifest.json")
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        MANIFEST = json.load(f)
    FPS = int(MANIFEST["fps"])
    return True


def legacy_startup_entry_path():
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(
        appdata,
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "Startup",
        "CodexDeskpetAutoStart.vbs",
    )


def set_autostart(enabled):
    legacy = legacy_startup_entry_path()
    try:
        if os.path.exists(legacy):
            os.remove(legacy)
    except OSError:
        pass
    return autostart_support.set_autostart(enabled)


def remove_disabled_flag():
    try:
        os.remove(DISABLED_FLAG)
    except OSError:
        pass


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Codex 桌宠设置")
        self.setModal(True)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.speed_combo = QComboBox()
        for label, value in SPEED_OPTIONS:
            self.speed_combo.addItem(label, value)
        self.speed_combo.setCurrentIndex(
            self._index_for_value(settings.get("speed", 1.0))
        )

        self.subtitle_combo = QComboBox()
        for key, info in SUBTITLE_LEVELS.items():
            self.subtitle_combo.addItem(info["label"], key)
        self.subtitle_combo.setCurrentIndex(
            self._index_for_key(settings.get("subtitle_length", "medium"))
        )

        self.autostart_check = QCheckBox(
            "随 Codex 启动（登录后监听，检测到 Codex 再启动桌宠）"
        )
        self.autostart_check.setChecked(
            bool(settings.get("autostart_with_codex", False))
        )

        self.mini_check = QCheckBox("迷你模式（隐藏字幕条）")
        self.mini_check.setChecked(bool(settings.get("mini_mode", False)))
        self.fullscreen_check = QCheckBox("全屏应用时自动隐藏")
        self.fullscreen_check.setChecked(
            bool(settings.get("auto_hide_fullscreen", False))
        )

        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(14, 26)
        self.size_slider.setValue(int(settings.get("subtitle_size", 19)))
        self.size_value = QLabel(f"{self.size_slider.value()}px")
        self.size_slider.valueChanged.connect(
            lambda value: self.size_value.setText(f"{value}px")
        )
        size_row = QWidget()
        size_layout = QHBoxLayout(size_row)
        size_layout.setContentsMargins(0, 0, 0, 0)
        size_layout.addWidget(self.size_slider, 1)
        size_layout.addWidget(self.size_value)

        self.bar_slider = QSlider(Qt.Horizontal)
        self.bar_slider.setRange(40, 100)
        self.bar_slider.setValue(int(settings.get("bar_length", 100)))
        self.bar_value = QLabel(f"{self.bar_slider.value()}%")
        self.bar_slider.valueChanged.connect(
            lambda value: self.bar_value.setText(f"{value}%")
        )
        bar_row = QWidget()
        bar_layout = QHBoxLayout(bar_row)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.addWidget(self.bar_slider, 1)
        bar_layout.addWidget(self.bar_value)

        self.fps_combo = QComboBox()
        for fps in (20, 30, 60):
            self.fps_combo.addItem(f"{fps} 帧/秒", fps)
        fps_value = settings.get("playback_fps", 60)
        self.fps_combo.setCurrentIndex((20, 30, 60).index(fps_value) if fps_value in (20, 30, 60) else 2)
        self.roam_check = QCheckBox("自动漫游")
        self.roam_check.setChecked(bool(settings.get("roaming_enabled", False)))
        self.roam_speed = QSlider(Qt.Horizontal)
        self.roam_speed.setRange(10, 100)
        self.roam_speed.setValue(int(settings.get("roaming_speed", 30)))
        self.roam_speed.setToolTip("漫游速度：每秒 10–100 个逻辑像素")
        form.addRow("播放帧率上限", self.fps_combo)
        form.addRow("", self.roam_check)
        form.addRow("漫游速度", self.roam_speed)
        form.addRow("动作倍速", self.speed_combo)
        form.addRow("字幕长度", self.subtitle_combo)
        form.addRow("字幕大小", size_row)
        form.addRow("字幕条宽度", bar_row)
        form.addRow("", self.mini_check)
        form.addRow("", self.fullscreen_check)
        form.addRow("", self.autostart_check)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _index_for_value(value):
        for i, (_, speed) in enumerate(SPEED_OPTIONS):
            if abs(speed - float(value)) < 1e-6:
                return i
        return 2

    @staticmethod
    def _index_for_key(key):
        keys = list(SUBTITLE_LEVELS.keys())
        return keys.index(key) if key in keys else 1

    def values(self):
        return {
            "speed": self.speed_combo.currentData(),
            "playback_fps": self.fps_combo.currentData(),
            "roaming_enabled": self.roam_check.isChecked(),
            "roaming_speed": self.roam_speed.value(),
            "subtitle_length": self.subtitle_combo.currentData(),
            "subtitle_size": self.size_slider.value(),
            "bar_length": self.bar_slider.value(),
            "mini_mode": self.mini_check.isChecked(),
            "auto_hide_fullscreen": self.fullscreen_check.isChecked(),
            "autostart_with_codex": self.autostart_check.isChecked(),
        }


class StatusWorker(QThread):
    ready = Signal(object)

    def run(self):
        while not self.isInterruptionRequested():
            try:
                self.ready.emit(codex_monitor.get_codex_status())
            except Exception as exc:
                log("monitor", str(exc))
            self.msleep(1000)


class PetWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setMouseTracking(True)

        self.settings = load_settings()
        self.pet_name = ACTIVE_PET
        pet_states = self.settings.get("pet_states") or {}
        pet_state = pet_states.get(self.pet_name, {})
        self.pet_state = pet_state
        self.speed = float(
            pet_state.get("speed", self.settings.get("speed", 1.0))
        )
        self.show_status = not bool(self.settings.get("mini_mode", False))
        self.auto_hide_fullscreen = bool(
            self.settings.get("auto_hide_fullscreen", False)
        )
        self.subtitle_length = self.settings.get("subtitle_length", "medium")
        self.subtitle_size = max(
            14, min(26, int(self.settings.get("subtitle_size", 19)))
        )
        self.bar_length = max(
            40, min(100, int(self.settings.get("bar_length", 100)))
        )
        self.locked = bool(self.settings.get("locked", True))

        self.state = "idle"
        self.frame_index = 0
        self.scale = max(
            MIN_SCALE,
            min(
                MAX_SCALE,
                float(
                    pet_state.get(
                        "scale", self.settings.get("scale", 1.0)
                    )
                ),
            ),
        )
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.render_scale = self.scale
        self.playback_fps = int(self.settings.get("playback_fps", 60))
        if self.playback_fps not in (20, 30, 60):
            self.playback_fps = 60
        self.roaming_enabled = bool(self.settings.get("roaming_enabled", False))
        self.roaming_speed = max(10, min(100, int(self.settings.get("roaming_speed", 30))))
        self.roam_direction = (0, 0)
        self.roam_until = 0
        self.next_roam_at = time.monotonic() + random.uniform(3, 6)
        self.roam_fraction = [0.0, 0.0]
        self.last_tick = time.monotonic()
        self.last_activity = self.last_tick
        self.auto_sit_after = random.uniform(40, 60)
        self.manual_state = False
        self.anim_started_at = self.last_tick
        self.cached_status = {}
        self.full_status_text = ""
        self.missing_frames = set()
        self.drag = False
        self.menu_open = False
        self._applying_geometry = False
        self.pre_drag_state = "idle"
        self.pre_drag_hold = False
        self.pre_drag_manual = False
        self.hold_state = False
        self.press_global = None
        self.press_window = None
        self.press_time = 0
        self.status_text = "Codex 待机"
        self.status_active = False
        self.tray_hidden = False

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(self.tick_ms())
        self.timer.timeout.connect(self.next_frame)
        self.timer.start()

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(2000)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start()

        self.fullscreen_timer = QTimer(self)
        self.fullscreen_timer.setInterval(2000)
        self.fullscreen_timer.timeout.connect(self.check_fullscreen)
        self.fullscreen_timer.start()

        self.set_state("idle")
        self.restore_position(pet_state)
        self.save_pet_state()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.save_position)
        self.refresh_status()
        self.show()
        self.status_worker = StatusWorker(self)
        self.status_worker.ready.connect(self.receive_status)
        self.status_worker.start()
        if app is not None:
            app.aboutToQuit.connect(self.stop_worker)
            app.screenAdded.connect(self.connect_screen)
            app.screenRemoved.connect(self.screen_changed)
            for display in app.screens():
                self.connect_screen(display)
        if self.windowHandle():
            self.windowHandle().screenChanged.connect(self.screen_changed)

    def stop_worker(self):
        self.status_worker.requestInterruption()
        self.status_worker.wait(5000)

    def connect_screen(self, display):
        display.availableGeometryChanged.connect(self.screen_changed)
        display.geometryChanged.connect(self.screen_changed)
        display.logicalDotsPerInchChanged.connect(self.screen_changed)
        self.screen_changed()

    def screen_changed(self, *args):
        self.apply_geometry()
        self.update()

    def tick_ms(self):
        return max(8, round(1000 / self.playback_fps))

    def state_info(self, name):
        return MANIFEST["states"][name]

    def layout_screen(self):
        point = QPoint(int(self.x() + self.width() / 2), int(self.y() + self.height() / 2))
        return QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()

    def status_bar_width(self, screen=None):
        screen = screen or self.layout_screen()
        available = screen.availableGeometry().width() if screen else STATUS_BAR_FULL_W
        full_width = min(STATUS_BAR_FULL_W, max(120, available - 24))
        return min(full_width, max(min(STATUS_BAR_MIN_W, full_width), int(full_width * self.bar_length / 100)))

    def pet_only_window_size(self):
        bx, by, bx2, by2 = self.state_info(self.state)["bbox"]
        status_extra = STATUS_H if self.show_status else 0
        return (
            int((bx2 - bx + 1) * self.scale) + PAD * 2,
            int((by2 - by + 1) * self.scale) + PAD * 2 + status_extra,
        )

    def constrain_to_screen(self, screen=None):
        if screen is None:
            center = QPoint(
                int(self.x() + self.width() / 2),
                int(self.y() + self.height() / 2),
            )
            screen = (
                QGuiApplication.screenAt(center)
                or QGuiApplication.primaryScreen()
            )
        if screen is None:
            return
        area = screen.availableGeometry()
        max_x = area.x() + max(0, area.width() - self.width())
        max_y = area.y() + max(0, area.height() - self.height())
        self.move(
            max(area.x(), min(self.x(), max_x)),
            max(area.y(), min(self.y(), max_y)),
        )

    def restore_position(self, pet_state):
        anchor_x = pet_state.get("anchor_x")
        anchor_y = pet_state.get("anchor_y")
        if anchor_x is None or anchor_y is None:
            pos_x = pet_state.get("pos_x")
            pos_y = pet_state.get("pos_y")
            if pos_x is None:
                pos_x = self.settings.get("pos_x")
            if pos_y is None:
                pos_y = self.settings.get("pos_y")
            if pos_x is not None and pos_y is not None:
                legacy_width, legacy_height = self.pet_only_window_size()
                anchor_x = float(pos_x) + legacy_width / 2
                anchor_y = float(pos_y) + legacy_height

        if anchor_x is not None and anchor_y is not None:
            anchor_point = QPoint(int(anchor_x), int(anchor_y))
            screen = (
                QGuiApplication.screenAt(anchor_point)
                or QGuiApplication.primaryScreen()
            )
            self.move(
                int(float(anchor_x) - self.width() / 2),
                int(float(anchor_y) - self.height()),
            )
            self.apply_geometry(screen=screen)
            return

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.x() + (area.width() - self.width()) // 2,
            area.y() + area.height() - self.height(),
        )

    def apply_geometry(self, screen=None):
        if self._applying_geometry:
            return
        self._applying_geometry = True
        try:
            self._apply_geometry(screen)
        finally:
            self._applying_geometry = False

    def _apply_geometry(self, screen=None):
        old_center = self.x() + self.width() / 2
        old_bottom = self.y() + self.height()
        screen = screen or self.layout_screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        bx, by, bx2, by2 = self.state_info(self.state)["bbox"]
        status_extra = STATUS_H if self.show_status else 0
        self.render_scale = min(
            self.scale,
            (area.width() - PAD * 2) / (bx2 - bx + 1),
            (area.height() - PAD * 2 - status_extra) / (by2 - by + 1),
        )
        pet_width = math.ceil((bx2 - bx + 1) * self.render_scale)
        pet_height = math.ceil((by2 - by + 1) * self.render_scale)
        width = max(pet_width + PAD * 2, self.status_bar_width(screen) + 12 if self.show_status else 0)
        height = pet_height + PAD * 2 + status_extra
        self.resize(width, height)
        self.move(round(old_center - width / 2), round(old_bottom - height))
        self.constrain_to_screen(screen)
        pet_left = (width - pet_width) // 2
        region = QRegion(QRect(pet_left - 3, status_extra + PAD - 3, pet_width + 6, pet_height + 6))
        if self.show_status:
            bar_width = self.status_bar_width(screen)
            region |= QRegion(QRect((width - bar_width) // 2, 4, bar_width, STATUS_H - 8))
        self.setMask(region)

    def note_activity(self):
        self.last_activity = time.monotonic()
        self.auto_sit_after = random.uniform(40, 60)
        self.manual_state = False
        self.next_roam_at = self.last_activity + random.uniform(3, 6)

    def set_state(self, name, hold=False, manual=False):
        if name not in MANIFEST["states"]:
            return
        self.state = name
        self.hold_state = hold
        self.manual_state = manual
        self.frame_index = 0
        self.anim_started_at = time.monotonic()
        self.cache.clear()
        self.cache_bytes = 0
        if name != "move":
            self.roam_direction = (0, 0)
        self.apply_geometry()
        self.update()

    def duration_ms(self):
        info = self.state_info(self.state)
        return max(1, info.get("duration", info["count"] * 1000 / FPS))

    def stop_roaming(self):
        if self.roam_direction != (0, 0):
            self.roam_direction = (0, 0)
            self.set_state("idle")
        self.next_roam_at = time.monotonic() + random.uniform(2, 5)

    def step_roaming(self, now, delta):
        if not self.roaming_enabled or self.drag or self.menu_open or self.press_global is not None or self.manual_state or not self.isVisible():
            return
        if self.state not in ("idle", "move"):
            return
        if self.roam_direction == (0, 0):
            if now < self.next_roam_at:
                return
            angle = random.uniform(0, math.tau)
            self.roam_direction = (math.cos(angle), math.sin(angle) * 0.35)
            self.roam_until = now + random.uniform(3, 6)
            self.roam_fraction = [0.0, 0.0]
            self.set_state("move")
        if now >= self.roam_until:
            self.stop_roaming()
            return
        old_position = self.pos()
        dx, dy = self.roam_direction
        self.roam_fraction[0] += dx * self.roaming_speed * delta
        self.roam_fraction[1] += dy * self.roaming_speed * delta
        step_x, step_y = int(self.roam_fraction[0]), int(self.roam_fraction[1])
        self.roam_fraction[0] -= step_x
        self.roam_fraction[1] -= step_y
        self.move(self.x() + step_x, self.y() + step_y)
        self.constrain_to_screen()
        if (step_x or step_y) and self.pos() == old_position:
            self.stop_roaming()

    def toggle_roaming(self):
        self.roaming_enabled = not self.roaming_enabled
        self.settings["roaming_enabled"] = self.roaming_enabled
        self.stop_roaming()
        self.note_activity()
        self.set_state("idle")
        save_settings(self.settings)

    def frame_path(self, index):
        return os.path.join(FRAMES_DIR, self.state, f"frame_{index:04d}.png")

    def current_image(self):
        cached = self.cache.get(self.frame_index)
        if cached is not None:
            self.cache.move_to_end(self.frame_index)
            return cached
        image = QImage(self.frame_path(self.frame_index))
        if image.isNull():
            key = (self.state, self.frame_index)
            if key not in self.missing_frames:
                log("pet_runtime", f"missing or invalid frame: {self.pet_name}/{key}")
                self.missing_frames.add(key)
            return QImage()
        image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self.cache[self.frame_index] = image
        self.cache_bytes += image.sizeInBytes()
        while self.cache_bytes > 32 * 1024 * 1024 or len(self.cache) > 128:
            _, evicted = self.cache.popitem(last=False)
            self.cache_bytes -= evicted.sizeInBytes()
        return image

    def next_frame(self):
        now = time.monotonic()
        delta = min(0.1, max(0, now - self.last_tick))
        self.last_tick = now
        if not self.drag and not self.menu_open and self.press_global is None and not self.manual_state:
            age = now - self.last_activity
            if age >= 90 and self.state != "sleep":
                self.set_state("sleep", hold=True)
            elif age >= self.auto_sit_after and self.state not in ("sit", "sleep"):
                self.set_state("sit", hold=True)
        self.step_roaming(now, delta)
        info = self.state_info(self.state)
        elapsed = max(0, (now - self.anim_started_at) * 1000 * self.speed)
        duration = self.duration_ms()
        if self.state in ("interact", "sit") and not self.hold_state and elapsed >= duration:
            self.set_state("idle")
            return
        times = info.get("frame_times_ms")
        position = elapsed % duration
        if times:
            index = max(0, min(info["count"] - 1, bisect.bisect_right(times, position) - 1))
        else:
            index = min(info["count"] - 1, int(position * FPS / 1000))
        if index != self.frame_index:
            self.frame_index = index
            if self.isVisible():
                self.update()

    def paintEvent(self, event):
        info = self.state_info(self.state)
        bx, by, bx2, _ = info["bbox"]
        image = self.current_image()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        status_extra = STATUS_H if self.show_status else 0
        if not image.isNull():
            scale = self.render_scale
            pet_width = (bx2 - bx + 1) * scale
            pet_left = (self.width() - pet_width) / 2
            offsets = info.get("frame_offsets")
            offset_x, offset_y = offsets[self.frame_index] if offsets else info.get("offset", (0, 0))
            target = QRectF(
                pet_left + (offset_x - bx) * scale,
                status_extra + PAD + (offset_y - by) * scale,
                image.width() * scale,
                image.height() * scale,
            )
            painter.save()
            if self.state == "move" and self.roam_direction[0] < 0:
                painter.translate(self.width(), 0)
                painter.scale(-1, 1)
            painter.drawImage(target, image)
            painter.restore()

        if self.show_status:
            bar_width = min(self.width() - 12, self.status_bar_width())
            bar_x = (self.width() - bar_width) / 2
            bar = QRectF(bar_x, 4, bar_width, STATUS_H - 8)
            if self.status_active:
                painter.setBrush(QColor(30, 120, 70, 190))
            else:
                painter.setBrush(QColor(25, 25, 25, 170))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bar, 8, 8)

            font = QFont()
            font.setPixelSize(self.subtitle_size)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            elided = metrics.elidedText(
                self.status_text, Qt.ElideRight, int(bar.width() - 16)
            )
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(
                bar.adjusted(8, 0, -8, 0),
                Qt.AlignVCenter | Qt.AlignLeft,
                elided,
            )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.stop_roaming()
            self.pre_drag_manual = self.manual_state
            self.note_activity()
            self.drag = False
            self.pre_drag_state = self.state
            self.pre_drag_hold = self.hold_state
            self.press_global = event.globalPosition().toPoint()
            self.press_window = self.pos()
            self.press_time = time.monotonic()

    def mouseMoveEvent(self, event):
        bar_width = self.status_bar_width()
        bar = QRectF((self.width() - bar_width) / 2, 4, bar_width, STATUS_H - 8)
        if self.show_status and bar.contains(event.position()):
            QToolTip.showText(event.globalPosition().toPoint(), self.full_status_text, self)
        else:
            QToolTip.hideText()
        if self.press_global is None:
            return
        if self.locked:
            return
        current = event.globalPosition().toPoint()
        dx = current.x() - self.press_global.x()
        dy = current.y() - self.press_global.y()
        if not self.drag and (dx * dx + dy * dy) > 36:
            self.drag = True
            if self.state != "move":
                self.set_state("move")
                self.press_window = self.pos()
        if self.drag and not (event.buttons() & Qt.LeftButton):
            self.drag = False
            self.press_global = None
            self.press_window = None
            target = (
                self.pre_drag_state
                if self.pre_drag_state in MANIFEST["states"]
                else "idle"
            )
            self.set_state(target, hold=self.pre_drag_hold, manual=self.pre_drag_manual)
        elif self.drag:
            self.move(self.press_window.x() + dx, self.press_window.y() + dy)
            self.constrain_to_screen()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self.drag:
            self.drag = False
            self.press_global = None
            self.press_window = None
            target = (
                self.pre_drag_state
                if self.pre_drag_state in MANIFEST["states"]
                else "idle"
            )
            self.set_state(target, hold=self.pre_drag_hold, manual=self.pre_drag_manual)
            self.save_pet_state()
            return
        if self.press_global is None:
            return
        current = event.globalPosition().toPoint()
        moved = (current.x() - self.press_global.x()) ** 2 + (
            current.y() - self.press_global.y()
        ) ** 2
        held = time.monotonic() - self.press_time
        self.press_global = None
        self.press_window = None
        if held < 0.5 and moved < 36:
            self.set_state("interact")

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_mini()

    def contextMenuEvent(self, event):
        self.stop_roaming()
        self.menu_open = True
        menu = QMenu(self)
        menu.addAction(
            QAction(
                "坐下",
                self,
                triggered=lambda: self.set_state("sit", hold=True, manual=True),
            )
        )
        menu.addAction(
            QAction(
                "放松",
                self,
                triggered=lambda: self.set_state("idle", hold=True, manual=True),
            )
        )
        menu.addAction(
            QAction(
                "睡觉",
                self,
                triggered=lambda: self.set_state("sleep", hold=True, manual=True),
            )
        )
        menu.addSeparator()
        roam_action = QAction("自动漫游", self, checkable=True)
        roam_action.setChecked(self.roaming_enabled)
        roam_action.triggered.connect(self.toggle_roaming)
        menu.addAction(roam_action)
        menu.addSeparator()
        pet_menu = menu.addMenu("桌宠库")
        for name in list_pets():
            action = QAction(name, self, checkable=True)
            action.setChecked(name == self.pet_name)
            action.triggered.connect(
                lambda checked=False, n=name: self.select_pet(n)
            )
            pet_menu.addAction(action)
        menu.addSeparator()
        mini_action = QAction("迷你模式（隐藏字幕）", self, checkable=True)
        mini_action.setChecked(not self.show_status)
        mini_action.triggered.connect(self.toggle_mini)
        menu.addAction(mini_action)
        full_action = QAction("全屏应用时自动隐藏", self, checkable=True)
        full_action.setChecked(self.auto_hide_fullscreen)
        full_action.triggered.connect(self.toggle_fullscreen_auto_hide)
        menu.addAction(full_action)
        menu.addSeparator()
        menu.addAction(
            QAction(
                "解锁拖动" if self.locked else "锁定拖动",
                self,
                triggered=self.toggle_lock,
            )
        )
        menu.addSeparator()
        menu.addAction(QAction("设置...", self, triggered=self.open_settings))
        menu.addSeparator()
        menu.addAction(QAction("放大", self, triggered=self.scale_up))
        menu.addAction(QAction("缩小", self, triggered=self.scale_down))
        menu.addSeparator()
        menu.addAction(
            QAction("隐藏到托盘", self, triggered=self.hide_to_tray)
        )
        menu.addAction(
            QAction("完全退出", self, triggered=self.quit_pet)
        )
        try:
            menu.exec(event.globalPos())
        finally:
            self.menu_open = False
            self.last_activity = time.monotonic()
            self.auto_sit_after = random.uniform(40, 60)

    def scale_up(self):
        self.set_scale(self.scale + 0.1)

    def scale_down(self):
        self.set_scale(self.scale - 0.1)

    def set_scale(self, value):
        self.scale = max(MIN_SCALE, min(MAX_SCALE, round(value, 1)))
        self.apply_geometry()
        self.settings["scale"] = self.scale
        self.save_pet_state()
        self.update()

    def select_pet(self, name):
        if name == self.pet_name or not switch_pet(name):
            return
        self.save_pet_state()
        self.pet_name = name
        self.settings["pet"] = name
        pet_state = (self.settings.get("pet_states") or {}).get(name, {})
        self.scale = max(
            MIN_SCALE,
            min(
                MAX_SCALE,
                float(
                    pet_state.get(
                        "scale", self.settings.get("scale", 1.0)
                    )
                ),
            ),
        )
        self.speed = float(
            pet_state.get("speed", self.settings.get("speed", 1.0))
        )
        self.cache.clear()
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(self.tick_ms())
        self.note_activity()
        self.set_state("idle", hold=False)
        self.restore_position(pet_state)
        self.save_pet_state()
        self.refresh_status()
        self.update()

    def save_pet_state(self):
        disk = load_settings()
        self.settings["autostart_with_codex"] = disk.get("autostart_with_codex", False)
        pet_states = self.settings.setdefault("pet_states", {})
        pet_states[self.pet_name] = {
            "scale": self.scale,
            "speed": self.speed,
            "pos_x": self.x(),
            "pos_y": self.y(),
            "anchor_x": int(self.x() + self.width() / 2),
            "anchor_y": self.y() + self.height(),
            "position_format": POSITION_FORMAT,
        }
        self.settings["scale"] = self.scale
        self.settings["pos_x"] = self.x()
        self.settings["pos_y"] = self.y()
        self.settings["anchor_x"] = int(self.x() + self.width() / 2)
        self.settings["anchor_y"] = self.y() + self.height()
        self.settings["position_format"] = POSITION_FORMAT
        save_settings(self.settings)

    def save_position(self):
        self.save_pet_state()

    def toggle_mini(self):
        self.show_status = not self.show_status
        self.settings["mini_mode"] = not self.show_status
        save_settings(self.settings)
        self.apply_geometry()
        self.constrain_to_screen()
        self.save_pet_state()
        self.update()

    def toggle_fullscreen_auto_hide(self):
        self.auto_hide_fullscreen = not self.auto_hide_fullscreen
        self.settings["auto_hide_fullscreen"] = self.auto_hide_fullscreen
        save_settings(self.settings)
        self.check_fullscreen()

    def check_fullscreen(self):
        if self.tray_hidden:
            return
        if not self.auto_hide_fullscreen:
            if not self.isVisible():
                self.show()
            return
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        hwnd = user32.GetForegroundWindow()
        full = False
        if hwnd and hwnd != int(self.winId()):
            rect = wintypes.RECT()
            monitor = user32.MonitorFromWindow(hwnd, 2)
            info = MonitorInfo()
            info.size = ctypes.sizeof(info)
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)) and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                area = info.monitor
                full = rect.left <= area.left and rect.top <= area.top and rect.right >= area.right and rect.bottom >= area.bottom
        if full:
            self.hide()
        elif not self.isVisible():
            self.show()

    def hide_to_tray(self):
        self.stop_roaming()
        self.tray_hidden = True
        self.hide()

    def show_from_tray(self):
        self.tray_hidden = False
        self.apply_geometry()
        self.show()
        self.raise_()
        self.activateWindow()

    def quit_pet(self):
        try:
            with open(DISABLED_FLAG, "w", encoding="utf-8") as f:
                f.write("1")
        except OSError:
            pass
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def toggle_lock(self):
        self.locked = not self.locked
        self.settings["locked"] = self.locked
        save_settings(self.settings)
        self.drag = False
        self.press_global = None
        self.press_window = None

    def open_settings(self):
        self.settings["speed"] = self.speed
        dialog = SettingsDialog(self.settings, self)
        was_menu_open = self.menu_open
        self.menu_open = True
        self.stop_roaming()
        try:
            accepted = dialog.exec() == QDialog.Accepted
        finally:
            self.menu_open = was_menu_open
            self.last_activity = time.monotonic()
        if not accepted:
            return
        data = dialog.values()
        old_autostart = bool(self.settings.get("autostart_with_codex", False))
        if bool(data["autostart_with_codex"]) != old_autostart:
            if not set_autostart(bool(data["autostart_with_codex"])):
                data["autostart_with_codex"] = old_autostart
                QMessageBox.warning(self, "Codex 桌宠", "自动启动设置未完成，详情见 autostart.log。")
        self.settings.update(data)
        save_settings(self.settings)
        now = time.monotonic()
        played_ms = max(0, (now - self.anim_started_at) * 1000 * self.speed)
        self.speed = float(data["speed"])
        self.anim_started_at = now - played_ms / (1000 * self.speed)
        self.playback_fps = int(data["playback_fps"])
        self.roaming_enabled = bool(data["roaming_enabled"])
        self.roaming_speed = int(data["roaming_speed"])
        self.subtitle_length = data["subtitle_length"]
        self.subtitle_size = int(data["subtitle_size"])
        self.bar_length = int(data["bar_length"])
        self.show_status = not bool(data["mini_mode"])
        self.auto_hide_fullscreen = bool(data["auto_hide_fullscreen"])
        self.timer.setInterval(self.tick_ms())
        self.stop_roaming()
        self.apply_geometry()
        self.save_pet_state()
        self.refresh_status()
        self.update()

    @staticmethod
    def _cut(text, limit):
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)] + "…"

    @staticmethod
    def _format_elapsed(seconds):
        seconds = int(seconds)
        minutes, sec = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}小时{minutes}分"
        if minutes:
            return f"{minutes}分{sec}秒"
        return f"{sec}秒"

    @staticmethod
    def _format_tokens(count):
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        if count >= 1_000:
            return f"{count / 1_000:.1f}k"
        return str(count)

    def refresh_status(self):
        if os.path.exists(HIDE_FLAG):
            try:
                os.remove(HIDE_FLAG)
            except OSError:
                pass
            self.hide_to_tray()
        if os.path.exists(SHOW_FLAG):
            try:
                os.remove(SHOW_FLAG)
            except OSError:
                pass
            self.show_from_tray()
        if os.path.exists(SHUTDOWN_FLAG):
            try:
                os.remove(SHUTDOWN_FLAG)
            except OSError:
                pass
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return
        status = self.cached_status
        self.status_active = bool(status.get("active"))
        level = SUBTITLE_LEVELS.get(
            self.subtitle_length, SUBTITLE_LEVELS["medium"]
        )
        if self.status_active:
            base = "Codex 运行中"
        else:
            base = "Codex 待机"
        parts = [base]
        if self.status_active:
            elapsed = status.get("elapsed")
            if elapsed is not None:
                parts.append(f"已运行 {self._format_elapsed(elapsed)}")
            tokens = status.get("tokens")
            if tokens is not None:
                parts.append(f"本轮 Token {self._format_tokens(tokens)}")
        task = status.get("task")
        if task:
            parts.append(self._cut(task, level["task_limit"]))
        if level["show_model"]:
            model = status.get("model")
            if model:
                parts.append(f"模型 {self._cut(model, 24)}")
        if level["show_progress"]:
            last_finished = status.get("last_finished")
            if last_finished:
                parts.append(f"上次完成 {last_finished}")
            progress = status.get("progress")
            if progress:
                parts.append(self._cut(progress, 80))
        self.status_text = " · ".join(parts)
        detail = [base]
        for label, key in (("任务", "task"), ("模型", "model"), ("进度", "progress")):
            if status.get(key):
                detail.append(f"{label}：{status[key]}")
        if status.get("tokens") is not None:
            detail.append(f"本轮 Token：{status['tokens']:,}")
        if status.get("session_tokens") is not None:
            detail.append(f"会话累计 Token：{status['session_tokens']:,}")
        if status.get("active_count", 0) > 1:
            detail.append(f"正在运行的会话：{status['active_count']}")
        detail.append("悬停查看完整信息；右键设置可调帧率与漫游。")
        self.full_status_text = "\n".join(detail)
        disk = load_settings()
        self.settings["autostart_with_codex"] = disk.get("autostart_with_codex", False)
        self.update()

    def receive_status(self, status):
        was_active = self.status_active
        self.cached_status = status
        if status.get("active") and not was_active and not self.manual_state:
            self.note_activity()
            if self.state in ("sleep", "sit"):
                self.set_state("idle")
        self.refresh_status()


def main():
    guard = InstanceGuard("pet")
    if not guard.acquired:
        guard.close()
        return 0
    write_identity("pet", __file__)
    try:
        remove_disabled_flag()
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(True)
        app.setStyle("Fusion")
        if ACTIVE_PET is None:
            # Do not let the watcher repeatedly relaunch an empty library.
            with open(DISABLED_FLAG, "w", encoding="ascii") as handle:
                handle.write("1")
            QMessageBox.information(
                None, "Ark Codex 桌宠",
                "桌宠库中还没有角色。请按 README.md 的素材导入步骤生成 "
                "pets/<角色名>/manifest.json，然后重新启动桌宠。",
            )
            return 0
        window = PetWindow()
        return app.exec()
    finally:
        remove_identity("pet")
        guard.close()



if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        log("pet_error", traceback.format_exc())
        raise
