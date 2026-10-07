"""Local file-mailbox handshake. No network listener or arbitrary code commands."""

import json
from pathlib import Path
import os
import tempfile
import time
import uuid


def atomic_write(path, data):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".mail-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def request(project, kind, name, transaction, timeout=8):
    directory = Path(project) / ".library-control"
    directory.mkdir(exist_ok=True)
    identifier = uuid.uuid4().hex
    path = directory / f"{identifier}.request.json"
    reply = directory / f"{identifier}.reply.json"
    atomic_write(path, {"kind": kind, "name": name, "transaction": transaction,
                        "expires": time.time() + timeout})
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if reply.is_file():
                result = json.loads(reply.read_text(encoding="utf-8"))
                if not result.get("ok"):
                    raise RuntimeError(result.get("error", "Library request rejected"))
                return result
            time.sleep(0.05)
        raise TimeoutError("Desktop pet did not acknowledge library request; existing pet was not replaced")
    finally:
        for item in (path, reply):
            try:
                item.unlink()
            except FileNotFoundError:
                pass


def receive(project, handler):
    directory = Path(project) / ".library-control"
    if not directory.is_dir():
        return
    for path in list(directory.glob("*.request.json"))[:16]:
        identifier = path.name.split(".", 1)[0]
        if len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
            continue
        try:
            if path.stat().st_size > 4096 or path.is_symlink():
                raise ValueError("Invalid library request")
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not time.time() < float(data["expires"]) <= time.time() + 60:
                raise ValueError("Expired library request")
            result = dict(handler(data), ok=True)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            result = {"ok": False, "error": str(error)}
        try:
            atomic_write(directory / f"{identifier}.reply.json", result)
            path.unlink(missing_ok=True)
        except OSError:
            pass
