"""Windows process identity, single-instance guards and bounded diagnostics."""

import ctypes
import hashlib
import json
import os
import tempfile
import time
from ctypes import wintypes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
kernel32.GetProcessTimes.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateProcess.restype = wintypes.BOOL


def normalized(path):
    return os.path.normcase(os.path.realpath(path))


def atomic_json(path, value):
    fd, tmp = tempfile.mkstemp(prefix=".write-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.03)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def log(role, message):
    path = os.path.join(BASE_DIR, f"{role}.log")
    try:
        if os.path.exists(path) and os.path.getsize(path) > 1_048_576:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except OSError:
        pass


def process_identity(pid):
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, *(ctypes.byref(v) for v in (created, exited, kernel, user))):
            return None
        if exited.dwLowDateTime or exited.dwHighDateTime:
            return None
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return {
            "pid": pid,
            "created": (created.dwHighDateTime << 32) | created.dwLowDateTime,
            "executable": normalized(buffer.value),
        }
    finally:
        kernel32.CloseHandle(handle)


class InstanceGuard:
    def __init__(self, role):
        suffix = hashlib.sha256(normalized(BASE_DIR).encode("utf-8")).hexdigest()[:16]
        self.handle = kernel32.CreateMutexW(None, False, f"Local\\ArkDeskpet_{role}_{suffix}")
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.acquired = ctypes.get_last_error() != 183

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None


def write_identity(role, script):
    record = process_identity(os.getpid())
    if record is None:
        raise RuntimeError("Cannot identify current process")
    record.update(role=role, script=normalized(script), project=normalized(BASE_DIR))
    atomic_json(os.path.join(BASE_DIR, f"{role}.process.json"), record)
    with open(os.path.join(BASE_DIR, f"{role}.pid"), "w", encoding="ascii") as handle:
        handle.write(str(os.getpid()))
    log(role if role != "pet" else "pet_runtime", f"started pid={os.getpid()}")


def managed_identity(role, script):
    try:
        with open(os.path.join(BASE_DIR, f"{role}.process.json"), encoding="utf-8") as handle:
            record = json.load(handle)
        if record.get("role") != role or record.get("script") != normalized(script) or record.get("project") != normalized(BASE_DIR):
            return None
        live = process_identity(int(record["pid"]))
        if live and all(live[key] == record[key] for key in ("pid", "created", "executable")):
            return record
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return None


def remove_identity(role):
    path = os.path.join(BASE_DIR, f"{role}.process.json")
    try:
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
        if record.get("pid") != os.getpid():
            return
        for target in (path, os.path.join(BASE_DIR, f"{role}.pid")):
            try:
                os.remove(target)
            except OSError:
                pass
    except (OSError, ValueError):
        pass


def terminate_managed(role, script):
    record = managed_identity(role, script)
    if record is None:
        return False
    handle = kernel32.OpenProcess(0x1001, False, record["pid"])
    if not handle:
        return False
    try:
        values = [wintypes.FILETIME() for _ in range(4)]
        if not kernel32.GetProcessTimes(handle, *(ctypes.byref(v) for v in values)):
            return False
        created = (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
        return created == record["created"] and bool(kernel32.TerminateProcess(handle, 1))
    finally:
        kernel32.CloseHandle(handle)


def write_flag(name):
    with open(os.path.join(BASE_DIR, name), "w", encoding="ascii") as handle:
        handle.write("1")


def remove_flag(name):
    try:
        os.remove(os.path.join(BASE_DIR, name))
    except FileNotFoundError:
        pass
