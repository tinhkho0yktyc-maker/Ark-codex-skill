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
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QToolTip,
)

import autostart_support
import behavior_support
import codex_monitor
import library_channel
import library_support
import motion_support
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
ROAM_TRANSITION_SECONDS = 0.14
ROAM_IDLE_MAX_HOLD_MS = 120

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
    "auto_rest_enabled": True,
    **{key: limits[2] for key, limits in behavior_support.RANGES.items()},
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
    return library_support.discover_pets(PETS_DIR)[0]


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
    MANIFEST = library_support.validate_pet(os.path.join(PETS_DIR, ACTIVE_PET))

FPS = int(MANIFEST["fps"])


def switch_pet(name):
    global ACTIVE_PET, FRAMES_DIR, MANIFEST_PATH, MANIFEST, FPS
    if name not in list_pets():
        return False
    candidate_path = os.path.join(PETS_DIR, name)
    candidate = library_support.validate_pet(candidate_path)
    ACTIVE_PET = name
    FRAMES_DIR = os.path.join(PETS_DIR, name, "frames")
    MANIFEST_PATH = os.path.join(PETS_DIR, name, "manifest.json")
    MANIFEST = candidate
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
        options = behavior_support.normalize_settings(settings)
        self.behavior_sliders = {}
        behavior_page = QWidget()
        behavior_form = QFormLayout(behavior_page)
        behavior_form.addRow(self.roam_check)
        self.auto_rest_check = QCheckBox("无操作后自动坐下 / 睡眠（保留原休息策略）")
        self.auto_rest_check.setChecked(bool(settings.get("auto_rest_enabled", True)))
        behavior_form.addRow(self.auto_rest_check)
        behavior_form.addRow("散步速度", self.slider_row(self.roam_speed, " px/s"))
        for key, label, suffix in (
            ("roaming_activity", "活动频率", "%"),
            ("roaming_walk_chance", "散步比例", "%"),
            ("roaming_distance", "最远散步距离", " px"),
            ("roaming_pause_min", "最短休息", " 秒"),
            ("roaming_pause_max", "最长休息", " 秒"),
        ):
            slider = QSlider(Qt.Horizontal)
            slider.setRange(*behavior_support.RANGES[key][:2])
            slider.setValue(options[key])
            self.behavior_sliders[key] = slider
            behavior_form.addRow(label, self.slider_row(slider, suffix))
        behavior_form.addRow(QLabel("散步比例为 0% 时只做原地动作。\n活动频率改变休息间隔，不改变动画倍速。\n最短休息高于最长时，最长自动调整。"))
        form.addRow("播放帧率上限", self.fps_combo)
        form.addRow("动作倍速", self.speed_combo)
        form.addRow("字幕长度", self.subtitle_combo)
        form.addRow("字幕大小", size_row)
        form.addRow("字幕条宽度", bar_row)
        form.addRow("", self.mini_check)
        form.addRow("", self.fullscreen_check)
        form.addRow("", self.autostart_check)
        appearance_page = QWidget()
        appearance_page.setLayout(form)
        tabs = QTabWidget()
        tabs.addTab(behavior_page, "动作与移动")
        tabs.addTab(appearance_page, "外观与启动")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def slider_row(slider, suffix):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        value = QLabel(f"{slider.value()}{suffix}")
        value.setMinimumWidth(65)
        slider.valueChanged.connect(lambda current: value.setText(f"{current}{suffix}"))
        layout.addWidget(slider, 1)
        layout.addWidget(value)
        return row

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
            **behavior_support.normalize_settings({key: slider.value() for key, slider in self.behavior_sliders.items()}),
            "speed": self.speed_combo.currentData(),
            "playback_fps": self.fps_combo.currentData(),
            "roaming_enabled": self.roam_check.isChecked(),
            "roaming_speed": self.roam_speed.value(),
            "auto_rest_enabled": self.auto_rest_check.isChecked(),
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
        self.setWindowTitle("明日方舟桌宠")
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
        self.roam_remaining = None
        self.roam_actual_speed = None
        self.auto_action_end = None
        self.one_shot_return = None
        self.library_lease = None
        self.library_paused = False
        self.frozen_layer = None
        self.next_roam_at = time.monotonic() + random.uniform(3, 6)
        self._world_target = None
        self._world_widget = None
        self._in_position_move = False
        self._screen_refresh_pending = False
        self._layer_cache = None
        self._layer_cache_key = None
        self.last_motion_tick = time.monotonic()
        self.roam_facing_left = False
        self.roam_idle_timing = None
        self.transition_image = None
        self.transition_frame = None
        self.transition_started_at = 0.0
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

        self.motion_timer = QTimer(self)
        self.motion_timer.setTimerType(Qt.PreciseTimer)
        self.motion_timer.timeout.connect(self.next_motion)

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

        self.library_timer = QTimer(self)
        self.library_timer.setInterval(250)
        self.library_timer.timeout.connect(self.poll_library)
        self.library_timer.start()

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
        if self._in_position_move:
            if not self._screen_refresh_pending:
                self._screen_refresh_pending = True
                QTimer.singleShot(0, self.screen_changed)
            return
        self._screen_refresh_pending = False
        self.apply_geometry()
        if self.motion_timer.isActive():
            self.motion_timer.setInterval(self.motion_tick_ms())
        self.update()

    def tick_ms(self):
        return max(8, round(1000 / self.playback_fps))

    def motion_tick_ms(self):
        screen = self.layout_screen()
        refresh = getattr(screen, "refreshRate", lambda: 60)() if screen else 60
        if not math.isfinite(refresh) or refresh <= 0:
            refresh = 60
        return max(5, round(1000 / min(180, max(60, refresh))))

    def native_origin(self, screen=None):
        handle = self.windowHandle()
        screen = screen or (handle.screen() if handle else None) or self.layout_screen()
        area = screen.geometry() if screen and hasattr(screen, "geometry") else (screen.availableGeometry() if screen else QRect())
        origin = (area.x(), area.y())
        ratio = max(1e-6, self.devicePixelRatioF())
        native = motion_support.native_client_origin(int(self.winId()), origin, ratio) if handle else None
        return native if native is not None else motion_support.quantized_origin((self.x(), self.y()), origin, ratio)

    def content_origin(self, screen=None):
        position = (self.x(), self.y())
        if self._world_target is None or (position != self._world_widget and not self._in_position_move):
            self._world_target = self.native_origin(screen)
            self._world_widget = position
        return self._world_target

    def content_offset(self):
        desired = self.content_origin()
        actual = self.native_origin()
        return desired[0] - actual[0], desired[1] - actual[1]

    def move_precisely(self, left, top, screen=None, immediate=False):
        screen = screen or self.layout_screen()
        if screen:
            area = screen.availableGeometry()
            left = max(area.x(), min(left, area.x() + max(0, area.width() - self.width())))
            top = max(area.y(), min(top, area.y() + max(0, area.height() - self.height())))
        self._world_target = (float(left), float(top))
        self._in_position_move = True
        try:
            self.move(round(left), round(top))
        finally:
            self._in_position_move = False
        self._world_widget = (self.x(), self.y())
        # Flush motion compensation in this callback; do not leave the old
        # backing image visible at a newly moved native window position.
        if immediate and self.isVisible():
            self.repaint()
        else:
            self.update()
        return self._world_target

    def next_motion(self):
        now = time.monotonic()
        delta = min(0.1, max(0, now - self.last_motion_tick))
        self.last_motion_tick = now
        self.step_roaming(now, delta)

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
        left, top = self.content_origin(screen)
        constrained = (max(area.x(), min(left, max_x)), max(area.y(), min(top, max_y)))
        if constrained != (left, top):
            self.move_precisely(*constrained, screen=screen)

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
            self.move_precisely(float(anchor_x) - self.width() / 2,
                                float(anchor_y) - self.height(), screen=screen)
            self.apply_geometry(screen=screen)
            return

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move_precisely(
            area.x() + (area.width() - self.width()) // 2,
            area.y() + area.height() - self.height(),
            screen=screen,
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
        old_left, old_top = self.content_origin(screen)
        old_center = old_left + self.width() / 2
        old_bottom = old_top + self.height()
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
        self.move_precisely(old_center - width / 2, old_bottom - height, screen=screen)
        self.constrain_to_screen(screen)
        pet_left = (width - pet_width) // 2
        region = QRegion(QRect(pet_left - 3, status_extra + PAD - 3, pet_width + 6, pet_height + 6))
        if self.show_status:
            bar_width = self.status_bar_width(screen)
            region |= QRegion(QRect((width - bar_width) // 2, 4, bar_width, STATUS_H - 8).adjusted(-2, -2, 2, 2))
        self.setMask(region)

    def note_activity(self):
        self.last_activity = time.monotonic()
        self.auto_sit_after = random.uniform(40, 60)
        self.manual_state = False
        self.auto_action_end = None
        self.one_shot_return = None
        self.next_roam_at = self.last_activity + behavior_support.pause_seconds(self.settings)

    def set_state(self, name, hold=False, manual=False):
        if name not in MANIFEST["states"]:
            return
        self.auto_action_end = None
        if manual:
            self.one_shot_return = None
            self.auto_action_end = None
        now = time.monotonic()
        self.transition_image = None
        if (self.roaming_enabled and not manual and not self.manual_state
                and name != self.state and {name, self.state} == {"idle", "move"}):
            previous = self.current_image()
            if not previous.isNull():
                info = self.state_info(self.state)
                offsets = info.get("frame_offsets")
                offset = offsets[self.frame_index] if offsets else info.get("offset", (0, 0))
                self.transition_image = previous
                self.transition_frame = (info["bbox"], offset, self.roam_facing_left)
                self.transition_started_at = now
        self.state = name
        self.hold_state = hold
        self.manual_state = manual
        self.frame_index = 0
        self.anim_started_at = now
        self.cache.clear()
        self.cache_bytes = 0
        if name != "move":
            self.roam_direction = (0, 0)
            self.motion_timer.stop()
        elif self.roam_direction != (0, 0):
            self.roam_facing_left = self.roam_direction[0] < 0
        if manual or name not in ("idle", "move"):
            self.roam_facing_left = False
        self.apply_geometry()
        self.update()

    def duration_ms(self):
        return self.playback_timing()[1]

    def playback_timing(self):
        info = self.state_info(self.state)
        times = info.get("frame_times_ms")
        duration = max(1, info.get("duration", info["count"] * 1000 / FPS))
        # A recording can intentionally hold a Relax pose for over a second.
        # Keep native timing everywhere except automatic roaming's idle pauses.
        if self.state == "idle" and self.roaming_enabled and not self.manual_state and times:
            cached = self.roam_idle_timing
            if cached is None or cached[0] is not info:
                paced = [times[0]]
                for first, second in zip(times, times[1:]):
                    paced.append(paced[-1] + min(second - first, ROAM_IDLE_MAX_HOLD_MS))
                paced_duration = paced[-1] + min(max(1, duration - times[-1]), ROAM_IDLE_MAX_HOLD_MS)
                self.roam_idle_timing = (info, paced, paced_duration)
            return self.roam_idle_timing[1:]
        return times, duration

    def stop_roaming(self):
        if self.roam_direction != (0, 0):
            self.set_state("idle")
        self.roam_direction = (0, 0)
        self.roam_remaining = None
        self.roam_actual_speed = None
        self.motion_timer.stop()
        self.next_roam_at = time.monotonic() + behavior_support.pause_seconds(self.settings)

    def step_roaming(self, now, delta):
        if not self.roaming_enabled or self.library_paused or self.drag or self.menu_open or self.press_global is not None or self.manual_state or not self.isVisible():
            self.motion_timer.stop()
            return
        if self.state not in ("idle", "move"):
            self.motion_timer.stop()
            return
        if self.roam_direction == (0, 0):
            if now < self.next_roam_at:
                return
            action = behavior_support.choose_action(self.settings, MANIFEST["states"])
            if action != "move":
                self.next_roam_at = now + behavior_support.pause_seconds(self.settings)
                if action != "idle":
                    self.set_state(action, hold=True)
                    self.auto_action_end = now + self.duration_ms() * random.randint(1, 3) / (1000 * self.speed)
                return
            self.roam_direction, self.roam_remaining, self.roam_actual_speed = behavior_support.walk_plan(self.settings, self.roaming_speed)
            self.roam_until = now + self.roam_remaining / self.roam_actual_speed
            self.set_state("move")
        if now >= self.roam_until:
            self.stop_roaming()
            return
        if not self.motion_timer.isActive():
            self.last_motion_tick = now
            self.motion_timer.start(self.motion_tick_ms())
        if delta <= 0:
            return
        old_position = self.content_origin()
        dx, dy = self.roam_direction
        distance = (self.roam_actual_speed or self.roaming_speed) * delta
        if self.roam_remaining is not None:
            distance = min(distance, self.roam_remaining)
        requested = (old_position[0] + dx * distance, old_position[1] + dy * distance)
        moved = self.move_precisely(*requested, immediate=True)
        if math.hypot(moved[0] - requested[0], moved[1] - requested[1]) > 1e-6:
            self.stop_roaming()
            return
        if self.roam_remaining is not None:
            self.roam_remaining -= math.hypot(moved[0] - old_position[0], moved[1] - old_position[1])
            if self.roam_remaining <= 1e-6:
                self.stop_roaming()
                return
        if (dx or dy) and moved == old_position:
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
        if self.library_paused:
            return
        now = time.monotonic()
        delta = min(0.1, max(0, now - self.last_tick))
        self.last_tick = now
        if self.settings.get("auto_rest_enabled", True) and not self.drag and not self.menu_open and self.press_global is None and not self.manual_state:
            age = now - self.last_activity
            if age >= 90 and self.state != "sleep":
                self.set_state("sleep", hold=True)
            elif age >= self.auto_sit_after and self.state not in ("sit", "sleep"):
                self.set_state("sit", hold=True)
        # This timer chooses animation frames and schedules roaming states only.
        # The independent motion timer integrates displacement exactly once.
        self.step_roaming(now, 0)
        info = self.state_info(self.state)
        elapsed = max(0, (now - self.anim_started_at) * 1000 * self.speed)
        times, duration = self.playback_timing()
        if self.one_shot_return is not None and elapsed >= duration:
            previous = self.one_shot_return
            self.one_shot_return = None
            self.set_state(*previous)
            self.next_roam_at = now + behavior_support.pause_seconds(self.settings)
            return
        if self.auto_action_end is not None and now >= self.auto_action_end:
            self.auto_action_end = None
            self.set_state("idle")
            self.next_roam_at = now + behavior_support.pause_seconds(self.settings)
            return
        if self.state in ("interact", "sit") and not self.hold_state and elapsed >= duration:
            self.set_state("idle")
            return
        position = elapsed % duration
        if times:
            index = max(0, min(info["count"] - 1, bisect.bisect_right(times, position) - 1))
        else:
            index = min(info["count"] - 1, int(position * FPS / 1000))
        transitioning = self.transition_image is not None
        if transitioning and now - self.transition_started_at >= ROAM_TRANSITION_SECONDS:
            self.transition_image = None
        if index != self.frame_index or transitioning:
            self.frame_index = index
            if self.isVisible():
                self.update()

    def draw_pet_frame(self, painter, image, bbox, offset, mirrored, opacity=1.0):
        bx, _, bx2, by2 = bbox
        scale = self.render_scale
        target = QRectF(
            self.width() / 2 + (offset[0] - (bx + bx2 + 1) / 2) * scale,
            self.height() - PAD + (offset[1] - by2 - 1) * scale,
            image.width() * scale, image.height() * scale,
        )
        painter.save()
        painter.setOpacity(opacity)
        if mirrored:
            painter.translate(self.width(), 0)
            painter.scale(-1, 1)
        painter.drawImage(target, image)
        painter.restore()

    def create_surface(self):
        ratio = max(1e-6, self.devicePixelRatioF())
        surface = QImage(math.ceil(self.width() * ratio), math.ceil(self.height() * ratio), QImage.Format_ARGB32_Premultiplied)
        surface.setDevicePixelRatio(ratio)
        surface.fill(Qt.transparent)
        return surface

    def compose_layer(self):
        key = (self.pet_name, self.state, self.frame_index, self.width(), self.height(),
               self.render_scale, self.roam_facing_left, self.show_status,
               self.status_text, self.status_active, self.subtitle_size, self.bar_length,
               self.devicePixelRatioF())
        if self.transition_image is None and self._layer_cache_key == key:
            return self._layer_cache
        layer = self.create_surface()
        info = self.state_info(self.state)
        image = self.current_image()
        painter = QPainter(layer)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.Antialiasing)
        if not image.isNull():
            offsets = info.get("frame_offsets")
            offset = offsets[self.frame_index] if offsets else info.get("offset", (0, 0))
            mirrored = self.state in ("idle", "move") and self.roam_facing_left
            progress = 1.0
            if self.transition_image is not None:
                progress = min(1.0, max(0.0, (time.monotonic() - self.transition_started_at) / ROAM_TRANSITION_SECONDS))
            painter.save()
            if progress < 1:
                blended = self.create_surface()
                mixer = QPainter(blended)
                mixer.setRenderHint(QPainter.SmoothPixmapTransform)
                self.draw_pet_frame(mixer, self.transition_image, *self.transition_frame, opacity=1 - progress)
                mixer.end()
                incoming = self.create_surface()
                next_painter = QPainter(incoming)
                next_painter.setRenderHint(QPainter.SmoothPixmapTransform)
                self.draw_pet_frame(next_painter, image, info["bbox"], offset, mirrored, progress)
                next_painter.end()
                # Weight each raster first, then add with full painter opacity.
                # Qt's Plus + constant opacity otherwise brightens/fades the body.
                mixer = QPainter(blended)
                mixer.setCompositionMode(QPainter.CompositionMode_Plus)
                mixer.drawImage(0, 0, incoming)
                mixer.end()
                painter.drawImage(0, 0, blended)
            else:
                self.draw_pet_frame(painter, image, info["bbox"], offset, mirrored)
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
        painter.end()
        self._layer_cache = layer
        self._layer_cache_key = key if self.transition_image is None else None
        return layer

    def rendered_layer(self):
        composed = self.frozen_layer if self.library_paused else self.compose_layer()
        translating = (not self.library_paused and self.roaming_enabled
                       and self.state == "move" and self.roam_direction != (0, 0)
                       and self.motion_timer.isActive() and not self.manual_state
                       and not self.menu_open and self.press_global is None)
        return motion_support.shift_layer(
            composed, self.content_offset(), self.devicePixelRatioF(),
            interpolate=translating,
        )

    def paintEvent(self, event):
        layer = self.rendered_layer()
        painter = QPainter(self)
        painter.drawImage(0, 0, layer)
        painter.end()

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
        bar = QRectF((self.width() - bar_width) / 2, 4, bar_width, STATUS_H - 8).translated(*self.content_offset())
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
        self.add_animation_actions(menu)
        menu.addAction("刷新桌宠库", lambda: self.refresh_library(notify=True))
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

    def play_action(self, name):
        if name not in MANIFEST["states"] or self.library_paused:
            return
        previous = (self.state, self.hold_state, self.manual_state) if self.manual_state else ("idle", False, False)
        self.stop_roaming()
        self.note_activity()
        self.set_state(name, hold=True, manual=True)
        self.one_shot_return = previous

    def add_animation_actions(self, menu):
        actions = menu.addMenu("全部动作（播放一次）")
        for name in MANIFEST["states"]:
            label = library_support.STATE_LABELS.get(name, name)
            actions.addAction(label, lambda checked=False, state=name: self.play_action(state))
        return actions

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
        self.roam_idle_timing = None
        self.roam_facing_left = False
        self.transition_image = None
        self.state = "idle"
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(self.tick_ms())
        self.note_activity()
        self.set_state("idle", hold=False)
        self.restore_position(pet_state)
        self.save_pet_state()
        self.refresh_status()
        self.update()

    def reload_active_pet(self):
        if not switch_pet(self.pet_name):
            raise ValueError("Current pet is absent or invalid; keeping the existing image")
        previous = (self.state, self.hold_state, self.manual_state)
        self.stop_roaming()
        self.cache.clear()
        self.cache_bytes = 0
        self._layer_cache_key = None
        self.roam_idle_timing = None
        self.transition_image = None
        self.one_shot_return = None
        self.auto_action_end = None
        name, hold, manual = previous
        self.set_state(name if name in MANIFEST["states"] else "idle", hold, manual)
        self.last_tick = time.monotonic()
        self.update()

    def refresh_library(self, notify=False):
        names, errors = library_support.discover_pets(PETS_DIR)
        if self.pet_name in names:
            self.reload_active_pet()
        if notify:
            detail = f"有效桌宠：{len(names)} 只。新角色已可在桌宠库中选择。"
            if errors:
                detail += "\n已忽略无效桌宠：\n" + "\n".join(f"{name}: {error}" for name, error in errors.items())
            QMessageBox.information(self, "桌宠库刷新", detail)
        return names

    def library_request(self, data):
        name = library_support.pet_name(data.get("name"))
        transaction = data.get("transaction", "")
        if len(transaction) != 32 or any(c not in "0123456789abcdef" for c in transaction):
            raise ValueError("Invalid library transaction")
        kind = data.get("kind")
        if kind == "prepare":
            if self.library_lease and self.library_lease[:2] == (transaction, name):
                return {"pid": os.getpid(), "lease_seconds": max(0, self.library_lease[2] - time.monotonic())}
            if self.library_lease or self.menu_open or self.drag or self.press_global is not None:
                raise RuntimeError("Desktop pet is busy; close its menu or finish dragging and retry")
            self.library_lease = (transaction, name, time.monotonic() + 30)
            if name == self.pet_name:
                self.stop_roaming()
                self.frozen_layer = self.compose_layer().copy()
                self.library_paused = True
            return {"pid": os.getpid(), "lease_seconds": 30}
        if not self.library_lease or self.library_lease[:2] != (transaction, name):
            raise RuntimeError("No matching library lease")
        if kind not in ("finish", "cancel"):
            raise ValueError("Unknown library command")
        if kind == "finish" and name == self.pet_name:
            self.reload_active_pet()
        self.library_lease = None
        self.library_paused = False
        self.frozen_layer = None
        self.last_tick = self.last_motion_tick = time.monotonic()
        self.update()
        return {"pid": os.getpid(), "pets": list_pets()}

    def poll_library(self):
        if self.library_lease and time.monotonic() >= self.library_lease[2]:
            try:
                if self.library_paused:
                    self.reload_active_pet()
                self.library_paused = False
                self.frozen_layer = None
            except (OSError, ValueError, TypeError) as error:
                log("pet_runtime", f"library lease expired; frozen image retained: {error}")
            self.library_lease = None
        library_channel.receive(os.path.dirname(SETTINGS_PATH), self.library_request)

    def save_pet_state(self):
        disk = load_settings()
        left, top = self.content_origin()
        self.settings["autostart_with_codex"] = disk.get("autostart_with_codex", False)
        pet_states = self.settings.setdefault("pet_states", {})
        pet_states[self.pet_name] = {
            "scale": self.scale,
            "speed": self.speed,
            "pos_x": self.x(),
            "pos_y": self.y(),
            "anchor_x": round(left + self.width() / 2, 3),
            "anchor_y": round(top + self.height(), 3),
            "position_format": POSITION_FORMAT,
        }
        self.settings["scale"] = self.scale
        self.settings["pos_x"] = self.x()
        self.settings["pos_y"] = self.y()
        self.settings["anchor_x"] = round(left + self.width() / 2, 3)
        self.settings["anchor_y"] = round(top + self.height(), 3)
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
