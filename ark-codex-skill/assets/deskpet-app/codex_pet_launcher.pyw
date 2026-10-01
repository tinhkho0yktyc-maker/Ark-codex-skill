"""Follow Codex/ChatGPT with identity checks, startup grace and retries."""

import ctypes
import os
import subprocess
import sys
import time
import traceback
from ctypes import wintypes

from process_support import (
    BASE_DIR, InstanceGuard, kernel32, log, managed_identity, remove_flag,
    remove_identity, terminate_managed, write_flag, write_identity,
)

PYW_PATH = os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe")
SCRIPTS = {"pet": os.path.join(BASE_DIR, "main.py"), "tray": os.path.join(BASE_DIR, "codex_tray.pyw")}
HOST_NAMES = {"chatgpt.exe", "codex.exe"}
POLL_SECONDS = 2


class ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
for name in ("Process32FirstW", "Process32NextW"):
    method = getattr(kernel32, name)
    method.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
    method.restype = wintypes.BOOL


def host_running():
    snapshot = kernel32.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return None
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        valid = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while valid:
            if entry.szExeFile.lower() in HOST_NAMES:
                return True
            valid = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return False
    finally:
        kernel32.CloseHandle(snapshot)


def stop_role(role):
    if managed_identity(role, SCRIPTS[role]) is None:
        return
    flag = "pet_shutdown.flag" if role == "pet" else "tray_stop.flag"
    write_flag(flag)
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if managed_identity(role, SCRIPTS[role]) is None:
            remove_flag(flag)
            return
        time.sleep(0.2)
    terminate_managed(role, SCRIPTS[role])
    remove_flag(flag)
    log("watcher", f"forced shutdown: {role}")


class Supervisor:
    def __init__(self):
        self.pending = {}
        self.failures = {}
        self.retry_at = {}
        self.ready = {}
        self.slow_reported = set()

    def forget(self, role):
        for mapping in (self.pending, self.failures, self.retry_at, self.ready):
            mapping.pop(role, None)
        self.slow_reported.discard(role)

    def failed(self, role, now, reason):
        attempts = self.failures.get(role, 0) + 1
        self.failures[role] = attempts
        delay = min(60, 2 ** min(attempts, 6))
        self.retry_at[role] = now + delay
        log("watcher", f"{role}: {reason}; retry in {delay}s")

    def ensure(self, role):
        now = time.monotonic()
        identity = managed_identity(role, SCRIPTS[role])
        if identity:
            self.pending.pop(role, None)
            self.slow_reported.discard(role)
            previous = self.ready.get(role)
            if previous is None or previous[0] != identity["created"]:
                self.ready[role] = identity["created"], now
            elif now - previous[1] >= 30:
                self.failures.pop(role, None)
                self.retry_at.pop(role, None)
            return
        if role in self.ready:
            self.ready.pop(role)
            self.failed(role, now, "exited unexpectedly")
            return
        if role in self.pending:
            process, started = self.pending[role]
            exit_code = process.poll()
            if exit_code is None:
                if now - started >= 15 and role not in self.slow_reported:
                    log("watcher", f"{role} startup exceeded 15s; waiting for owned process, not duplicating it")
                    self.slow_reported.add(role)
                return
            self.pending.pop(role)
            self.slow_reported.discard(role)
            self.failed(role, now, f"did not become ready, exit={exit_code}")
        if now < self.retry_at.get(role, 0):
            return
        try:
            remove_flag("pet_shutdown.flag" if role == "pet" else "tray_stop.flag")
            process = subprocess.Popen([PYW_PATH, SCRIPTS[role]], cwd=BASE_DIR, creationflags=subprocess.CREATE_NO_WINDOW)
            self.pending[role] = process, now
            log("watcher", f"launch requested: {role} wrapper_pid={process.pid}")
        except OSError as exc:
            self.retry_at[role] = now + 15
            log("watcher", f"{role} launch failed: {exc}")


def main():
    guard = InstanceGuard("watcher")
    if not guard.acquired:
        guard.close()
        return
    write_identity("watcher", __file__)
    supervisor = Supervisor()
    was_host = "--resume-host" in sys.argv and host_running() is True
    absent_since = None
    try:
        while True:
            if os.path.exists(os.path.join(BASE_DIR, "watcher_exit.flag")):
                remove_flag("watcher_exit.flag")
                stop_role("pet")
                stop_role("tray")
                return 0
            host = host_running()
            if host is None:
                time.sleep(POLL_SECONDS)
                continue
            if host:
                absent_since = None
                if not was_host:
                    remove_flag("pet_disabled.flag")
                    log("watcher", "Codex/ChatGPT detected")
                supervisor.ensure("tray")
                if not os.path.exists(os.path.join(BASE_DIR, "pet_disabled.flag")):
                    supervisor.ensure("pet")
                else:
                    supervisor.forget("pet")
                was_host = True
            elif was_host:
                absent_since = absent_since or time.monotonic()
                if time.monotonic() - absent_since >= 8:
                    stop_role("pet")
                    stop_role("tray")
                    for role in SCRIPTS:
                        supervisor.forget(role)
                    was_host = False
                    log("watcher", "host closed; waiting for next launch")
            time.sleep(POLL_SECONDS)
    except Exception:
        log("watcher", traceback.format_exc())
        raise
    finally:
        remove_identity("watcher")
        guard.close()
        log("watcher", "watcher stopped")


def supervise_worker():
    """Keep the watcher alive without relying on Task Scheduler exit-code retries.

    A normal worker exit (tray Exit) ends the parent too. Only a failed launch
    or nonzero exit is retried. Popen owns the venv wrapper and waits for it,
    so there is no PID lookup or broad Python-process termination here.
    """
    guard = InstanceGuard("supervisor")
    if not guard.acquired:
        guard.close()
        return 0
    write_identity("supervisor", __file__)
    attempts = 0
    retrying = False
    try:
        while True:
            started = time.monotonic()
            try:
                child = subprocess.Popen(
                    [PYW_PATH, os.path.abspath(__file__)]
                    + (["--resume-host"] if retrying else []) + ["--worker"],
                    cwd=BASE_DIR, creationflags=subprocess.CREATE_NO_WINDOW,
                )
                exit_code = child.wait()
                if exit_code == 0:
                    return 0
                reason = f"watcher exited with code {exit_code}"
            except OSError as exc:
                reason = f"watcher launch failed: {exc}"
            if time.monotonic() - started >= 30:
                attempts = 0
            attempts += 1
            delay = min(60, 2 ** min(attempts, 6))
            log("supervisor", f"{reason}; retry in {delay}s")
            retrying = True
            time.sleep(delay)
    except Exception:
        log("supervisor", traceback.format_exc())
        raise
    finally:
        remove_identity("supervisor")
        guard.close()


if __name__ == "__main__":
    raise SystemExit(main() if "--worker" in sys.argv else supervise_worker())
