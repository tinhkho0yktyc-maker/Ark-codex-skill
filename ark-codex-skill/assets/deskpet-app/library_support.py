"""Legacy/v2 library validation, also used before installing user pets."""

import json
import math
from pathlib import Path
import re
import struct
import zlib

REQUIRED_STATES = ("idle", "interact", "move", "sit", "sleep")
STATE_LABELS = {"idle": "放松", "interact": "互动", "move": "移动",
                "sit": "坐下", "sleep": "睡眠", "special": "特殊 / Special"}


def pet_name(value):
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or value.startswith(".") or any(c in value for c in '<>:"/\\|?*')
            or any(ord(c) < 32 for c in value) or value.endswith((".", " "))):
        raise ValueError("Invalid Windows pet directory name")
    stem = value.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        raise ValueError("Reserved Windows pet name")
    return value


def number(value, label, minimum=0):
    try:
        finite = math.isfinite(value)
    except (TypeError, OverflowError):
        finite = False
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not finite or value < minimum:
        raise ValueError(f"Invalid {label}")
    return value


def png_size(path):
    """Check every PNG chunk CRC, including IDAT; no Qt/Pillow dependency."""
    with Path(path).open("rb") as handle:
        if handle.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"Not a PNG: {path}")
        size = None
        saw_data = False
        while True:
            head = handle.read(8)
            if len(head) != 8:
                raise ValueError(f"Truncated PNG: {path}")
            length, kind = struct.unpack(">I4s", head)
            if length > 128 * 1024 * 1024:
                raise ValueError(f"Oversized PNG chunk: {path}")
            data = handle.read(length)
            check = handle.read(4)
            if len(data) != length or len(check) != 4 or zlib.crc32(kind + data) & 0xffffffff != struct.unpack(">I", check)[0]:
                raise ValueError(f"Corrupt PNG: {path}")
            if size is None:
                if kind != b"IHDR" or length != 13:
                    raise ValueError(f"Missing PNG header: {path}")
                size = struct.unpack(">II", data[:8])
            if kind == b"IDAT":
                saw_data = True
            if kind == b"IEND":
                if length or not saw_data:
                    raise ValueError(f"Incomplete PNG: {path}")
                return size


def validate_pet(root, check_frames=False, decode=None):
    """Validate original full canvases or offset crops, without modifying either."""
    root = Path(root)
    if root.is_symlink() or getattr(root, "is_junction", lambda: False)():
        raise ValueError("Pet directory must not be a link")
    manifest_path = root / "manifest.json"
    if manifest_path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Oversized manifest")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Manifest must be an object")
    if "groups" in data:
        raise ValueError("Animation groups require an adapter; flat legacy/v2 pets only")
    size = number(data.get("size"), "canvas size", 1)
    if type(size) is not int or size > 8192:
        raise ValueError("Invalid canvas size")
    if number(data.get("fps"), "fps", 1) > 1000:
        raise ValueError("Invalid fps")
    states = data.get("states")
    if not isinstance(states, dict) or len(states) > 64 or not set(REQUIRED_STATES) <= states.keys():
        raise ValueError("Missing required states")
    for name, info in states.items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) or not isinstance(info, dict):
            raise ValueError("Invalid animation state")
        count = info.get("count")
        if type(count) is not int or not 1 <= count <= 100000:
            raise ValueError(f"Invalid frame count: {name}")
        duration = number(info.get("duration", count * 1000 / data["fps"]), "duration", 0.001)
        bbox = info.get("bbox")
        if (not isinstance(bbox, list) or len(bbox) != 4 or any(type(v) is not int for v in bbox)
                or not (0 <= bbox[0] <= bbox[2] < size and 0 <= bbox[1] <= bbox[3] < size)):
            raise ValueError(f"Invalid bbox: {name}")
        times, offsets = info.get("frame_times_ms"), info.get("frame_offsets")
        if data.get("schema_version") == 2 and (times is None or offsets is None):
            raise ValueError(f"v2 needs timestamps and offsets: {name}")
        if times is not None:
            if not isinstance(times, list) or len(times) != count:
                raise ValueError(f"Timestamp count mismatch: {name}")
            for value in times:
                number(value, "timestamp")
            if times[0] != 0 or times[-1] >= duration or any(a >= b for a, b in zip(times, times[1:])):
                raise ValueError(f"Invalid timestamp order: {name}")
        if offsets is not None:
            if not isinstance(offsets, list) or len(offsets) != count:
                raise ValueError(f"Offset count mismatch: {name}")
            for offset in offsets:
                if not isinstance(offset, list) or len(offset) != 2 or any(type(v) is not int or not 0 <= v < size for v in offset):
                    raise ValueError(f"Invalid offset: {name}")
        if check_frames:
            directory = root / "frames" / name
            files = sorted(directory.glob("frame_*.png"))
            expected = [f"frame_{index:04d}.png" for index in range(count)]
            if [p.name for p in files] != expected:
                raise ValueError(f"Frame files/count mismatch: {name}")
            for index, path in enumerate(files):
                if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                    raise ValueError("Frame path leaves pet directory")
                width, height = png_size(path)
                x, y = offsets[index] if offsets is not None else (0, 0)
                if not 1 <= width <= size or not 1 <= height <= size or x + width > size or y + height > size:
                    raise ValueError(f"Frame crop leaves original canvas: {path}")
                if offsets is None and (width, height) != (size, size):
                    raise ValueError(f"Legacy frame must be full canvas: {path}")
                if decode is not None:
                    decode(path)
    return data


def discover_pets(directory):
    names, errors = [], {}
    root = Path(directory)
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.name.startswith(".") or not child.is_dir() or not (child / "manifest.json").is_file():
                continue
            try:
                pet_name(child.name)
                validate_pet(child)
                names.append(child.name)
            except (OSError, ValueError, TypeError) as error:
                errors[child.name] = str(error)
    return names, errors
