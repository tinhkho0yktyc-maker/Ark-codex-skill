import base64
import json
import os
import subprocess
import winreg

from process_support import atomic_json, log


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYW_PATH = os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe")
WATCHER_PATH = os.path.join(BASE_DIR, "codex_pet_launcher.pyw")
LOG_PATH = os.path.join(BASE_DIR, "autostart.log")

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "CodexDeskpetWatcher"
STARTUP_APPROVED_KEY_PATH = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer"
    r"\StartupApproved\Run"
)
STARTUP_ENABLED_VALUE = bytes([2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
TASK_NAME = "ArkCodexDeskpetWatcher"


def _log(message):
    log("autostart", message)


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def _run_powershell(script):
    script = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);" + script
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log(f"PowerShell launch failed: {exc}")
        return False
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown error").strip()
        _log(f"PowerShell failed ({result.returncode}): {detail}")
        return False
    return True


def _set_run_entry(enabled):
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            if enabled:
                command = f'"{PYW_PATH}" "{WATCHER_PATH}"'
                winreg.SetValueEx(
                    key, RUN_VALUE_NAME, 0, winreg.REG_SZ, command
                )
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)

        approved_key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            STARTUP_APPROVED_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            if enabled:
                winreg.SetValueEx(
                    approved_key,
                    RUN_VALUE_NAME,
                    0,
                    winreg.REG_BINARY,
                    STARTUP_ENABLED_VALUE,
                )
            else:
                try:
                    winreg.DeleteValue(approved_key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(approved_key)
        return True
    except OSError as exc:
        _log(f"registry update failed: {exc}")
        return False


def _set_scheduled_task(enabled):
    task_name = _ps_quote(TASK_NAME)
    if not enabled:
        return _run_powershell(
            "$ErrorActionPreference='Stop';"
            f"Unregister-ScheduledTask -TaskName {task_name} "
            "-Confirm:$false -ErrorAction SilentlyContinue"
        )

    execute = _ps_quote(PYW_PATH)
    argument = _ps_quote(f'"{WATCHER_PATH}"')
    working_dir = _ps_quote(BASE_DIR)
    description = _ps_quote(
        "Starts the Ark Codex desktop-pet watcher after user logon."
    )
    script = (
        "$ErrorActionPreference='Stop';"
        "$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name;"
        # Register a limited, interactive current-user task through COM.
        # The launcher supervises its worker itself: this Windows build
        # forces the unified engine and did not honor exit-code retries.
        "$service=New-Object -ComObject 'Schedule.Service';$service.Connect();"
        "$definition=$service.NewTask(0);"
        f"$definition.RegistrationInfo.Description={description};"
        "$definition.Principal.UserId=$user;"
        "$definition.Principal.LogonType=3;$definition.Principal.RunLevel=0;"
        "$trigger=$definition.Triggers.Create(9);"
        "$trigger.UserId=$user;$trigger.Delay='PT10S';"
        "$action=$definition.Actions.Create(0);"
        f"$action.Path={execute};$action.Arguments={argument};"
        f"$action.WorkingDirectory={working_dir};"
        "$settings=$definition.Settings;"
        "$settings.Compatibility=4;"
        "$settings.DisallowStartIfOnBatteries=$false;"
        "$settings.StopIfGoingOnBatteries=$false;$settings.StartWhenAvailable=$true;"
        "$settings.ExecutionTimeLimit='PT0S';$settings.MultipleInstances=2;"
        "$settings.RestartCount=3;$settings.RestartInterval='PT1M';"
        f"$service.GetFolder('\\').RegisterTaskDefinition({task_name},"
        "$definition,6,$user,$null,3,$null) | Out-Null"
    )
    return _run_powershell(script)


def scheduled_task_exists():
    script = (
        "$ErrorActionPreference='Stop';"
        f"Get-ScheduledTask -TaskName {_ps_quote(TASK_NAME)} "
        "-ErrorAction Stop | Out-Null"
    )
    return _run_powershell(script)


def registry_entry_exists():
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ
        )
        try:
            winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return True
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False


def autostart_enabled():
    return scheduled_task_exists() or registry_entry_exists()


def set_autostart(enabled, launch_now=True):
    registry_ok = _set_run_entry(enabled)
    task_ok = _set_scheduled_task(enabled)
    if enabled and task_ok and launch_now:
        try:
            subprocess.Popen(
                [PYW_PATH, WATCHER_PATH],
                cwd=BASE_DIR,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except OSError as exc:
            _log(f"immediate watcher launch failed: {exc}")
            return False
    ok = registry_ok and task_ok
    if ok:
        settings_path = os.path.join(BASE_DIR, "settings.json")
        try:
            with open(settings_path, encoding="utf-8") as handle:
                settings = json.load(handle)
            settings["autostart_with_codex"] = bool(enabled)
            atomic_json(settings_path, settings)
        except (OSError, ValueError) as exc:
            _log(f"settings synchronization failed: {exc}")
    _log(f"set_autostart enabled={enabled} success={ok}")
    return ok
