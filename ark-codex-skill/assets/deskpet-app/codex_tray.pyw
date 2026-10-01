import os
import json
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QMessageBox

import autostart_support
from process_support import InstanceGuard, remove_identity, write_identity, log

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRAY_PID_FILE = os.path.join(BASE_DIR, "tray.pid")
TRAY_STOP_FLAG = os.path.join(BASE_DIR, "tray_stop.flag")
WATCHER_EXIT_FLAG = os.path.join(BASE_DIR, "watcher_exit.flag")
SHOW_FLAG = os.path.join(BASE_DIR, "pet_show.flag")
HIDE_FLAG = os.path.join(BASE_DIR, "pet_hide.flag")
SHUTDOWN_FLAG = os.path.join(BASE_DIR, "pet_shutdown.flag")
DISABLED_FLAG = os.path.join(BASE_DIR, "pet_disabled.flag")
PYW_PATH = os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe")
WATCHER_PATH = os.path.join(BASE_DIR, "codex_pet_launcher.pyw")
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "CodexDeskpetWatcher"
STARTUP_APPROVED_KEY_PATH = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer"
    r"\StartupApproved\Run"
)
STARTUP_ENABLED_VALUE = bytes([2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])


def write_flag(path):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("1")
    except OSError:
        pass


def remove_flag(path):
    try:
        os.remove(path)
    except OSError:
        pass


def make_icon():
    pix = QPixmap(64, 64)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(30, 120, 70))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(8, 8, 48, 48)
    painter.setPen(QColor(255, 255, 255))
    font = painter.font()
    font.setPixelSize(30)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignCenter, "C")
    painter.end()
    return QIcon(pix)


def show_pet():
    remove_flag(DISABLED_FLAG)
    write_flag(SHOW_FLAG)


def hide_pet():
    write_flag(HIDE_FLAG)


def close_pet():
    write_flag(DISABLED_FLAG)
    write_flag(SHUTDOWN_FLAG)


def autostart_enabled():
    return autostart_support.autostart_enabled()


def set_autostart(enabled):
    return autostart_support.set_autostart(enabled)


def quit_watcher():
    write_flag(WATCHER_EXIT_FLAG)
    QApplication.instance().quit()


def main():
    guard = InstanceGuard("tray")
    if not guard.acquired:
        guard.close()
        return
    write_identity("tray", __file__)
    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        tray = QSystemTrayIcon(make_icon(), app)
        tray.setToolTip("Ark Codex 桌宠")
        menu = QMenu()
        show_action = QAction("显示桌宠", menu, triggered=show_pet)
        close_action = QAction("隐藏桌宠", menu, triggered=close_pet)
        autostart_action = QAction("开机自启动", menu, checkable=True)
        autostart_action.setChecked(autostart_enabled())

        def refresh_autostart():
            try:
                with open(os.path.join(BASE_DIR, "settings.json"), encoding="utf-8") as handle:
                    enabled = bool(json.load(handle).get("autostart_with_codex", False))
                autostart_action.blockSignals(True)
                autostart_action.setChecked(enabled)
                autostart_action.blockSignals(False)
            except (OSError, ValueError):
                pass

        def change_autostart(enabled):
            if not set_autostart(enabled):
                refresh_autostart()
                QMessageBox.warning(None, "Ark Codex 桌宠", "自动启动设置未完成，详情见 autostart.log。")

        autostart_action.toggled.connect(change_autostart)
        menu.aboutToShow.connect(refresh_autostart)
        exit_action = QAction("退出", menu, triggered=quit_watcher)
        menu.addAction(show_action)
        menu.addAction(close_action)
        menu.addSeparator()
        menu.addAction(autostart_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        tray.setContextMenu(menu)
        tray.show()

        timer = QTimer()
        timer.timeout.connect(
            lambda: (
                remove_flag(TRAY_STOP_FLAG),
                QApplication.instance().quit(),
            )
            if os.path.exists(TRAY_STOP_FLAG)
            else None
        )
        timer.start(1000)
        app.exec()
    except Exception:
        import traceback
        log("tray", traceback.format_exc())
        raise
    finally:
        remove_identity("tray")
        guard.close()


if __name__ == "__main__":
    main()
