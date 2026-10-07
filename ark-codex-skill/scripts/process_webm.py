#!/usr/bin/env python3
"""Convert PRTS WebM to transparent, cropped PNGs with original timestamps.

FFmpeg/ffprobe must be on PATH, including libvpx/libvpx-vp9 decoders.
Existing pet directories are never overwritten. Conversion is staged locally;
only a complete manifest and all five states are moved into the destination.
"""

import argparse
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

STATE_MAP = (
    ("Relax", "idle"), ("Interact", "interact"), ("Move", "move"),
    ("Sit", "sit"), ("Sleep", "sleep"),
)
OPTIONAL_MAP = (("Special", "special"),)


def find_sources(directory):
    directory = Path(directory)
    sources = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".webm":
            continue
        if path.stat().st_size < 1000:
            if re.search(r"(?<![a-z])Special(?![a-z])", path.stem, re.IGNORECASE):
                raise ValueError(f"Optional Special WebM is broken: {path.name}")
            print("skip broken WebM:", path.name, flush=True)
            continue
        for token, state in STATE_MAP + OPTIONAL_MAP:
            if re.search(rf"(?<![a-z]){token}(?![a-z])", path.stem, re.IGNORECASE):
                if state in sources:
                    raise ValueError(
                        f"Multiple files for {state}; use one operator/skin per source directory."
                    )
                sources[state] = path
                break
    missing = [token for token, state in STATE_MAP if state not in sources]
    if missing:
        raise ValueError("Missing valid WebM animations: " + ", ".join(missing))
    return sources


def probe(path):
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=codec_name,width,height:stream_tags=alpha_mode:"
        "format=duration:frame=best_effort_timestamp_time",
        "-show_frames", "-of", "json", str(path),
    ]
    result = subprocess.run(command, capture_output=True, check=True, timeout=120)
    data = json.loads(result.stdout)
    if not data.get("streams"):
        raise ValueError(f"No video stream: {path.name}")
    stream = data["streams"][0]
    times = [
        float(frame["best_effort_timestamp_time"]) * 1000
        for frame in data.get("frames", [])
        if frame.get("best_effort_timestamp_time") is not None
    ]
    if not times or any(not math.isfinite(t) for t in times):
        raise ValueError(f"No usable frame timestamps: {path.name}")
    origin = times[0]
    times = [round(t - origin, 3) for t in times]
    if times != sorted(times) or (len(times) > 1 and any(b <= a for a, b in zip(times, times[1:]))):
        raise ValueError(f"Non-increasing frame timestamps: {path.name}")
    interval = statistics.median([b - a for a, b in zip(times, times[1:])]) if len(times) > 1 else 1000 / 60
    try:
        duration = float(data.get("format", {}).get("duration", 0)) * 1000 - origin
    except (TypeError, ValueError):
        duration = 0
    if not math.isfinite(duration) or duration <= times[-1]:
        duration = times[-1] + interval
    if not 1 <= stream["width"] == stream["height"] <= 8192:
        raise ValueError(f"Expected a square model canvas: {path.name}")
    return stream, times, round(duration, 3)


def transparent_crop(image, recover_black=False):
    points = (
        (0, 0), (image.width - 1, 0),
        (0, image.height - 1), (image.width - 1, image.height - 1),
    )
    opaque_black = sum(
        image.getpixel(p)[3] >= 250 and max(image.getpixel(p)[:3]) <= 12
        for p in points
    ) >= 3
    origin_x = origin_y = 0
    if opaque_black:
        if not recover_black:
            raise ValueError(
                "The decoded WebM has an opaque black background. Re-export "
                "with transparency, or explicitly use --recover-black (approximate)."
            )
        red, green, blue, _ = image.split()
        brightness = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        seed = brightness.point(lambda value: 255 if value > 12 else 0)
        bounds = seed.getbbox()
        if bounds is None:
            return Image.new("RGBA", (1, 1)), (0, 0), None
        left, top, right, bottom = bounds
        region = (
            max(0, left - 8), max(0, top - 8),
            min(image.width, right + 8), min(image.height, bottom + 8),
        )
        image = image.crop(region)
        barrier = seed.crop(region).filter(ImageFilter.MaxFilter(5))
        zones = barrier.copy()
        for point in (
            (0, 0), (zones.width - 1, 0),
            (0, zones.height - 1), (zones.width - 1, zones.height - 1),
        ):
            if zones.getpixel(point) == 0:
                ImageDraw.floodfill(zones, point, 128, thresh=0)
        alpha = zones.point(lambda value: 0 if value == 128 else 255)
        image.putalpha(alpha.filter(ImageFilter.GaussianBlur(0.65)))
        origin_x, origin_y = region[:2]
    elif image.getchannel("A").getextrema()[0] > 10:
        raise ValueError("The decoded frame has no transparent exterior; re-export the model.")

    visible = image.getchannel("A").point(lambda value: 255 if value > 10 else 0).getbbox()
    if visible is None:
        return Image.new("RGBA", (1, 1)), (0, 0), None
    left, top, right, bottom = visible
    crop = (
        max(0, left - 4), max(0, top - 4),
        min(image.width, right + 4), min(image.height, bottom + 4),
    )
    bbox = [left + origin_x, top + origin_y, right + origin_x - 1, bottom + origin_y - 1]
    return image.crop(crop), (origin_x + crop[0], origin_y + crop[1]), bbox


def read_frame(handle, size):
    pieces = []
    remaining = size
    while remaining:
        data = handle.read(remaining)
        if not data:
            break
        pieces.append(data)
        remaining -= len(data)
    return b"".join(pieces)


def decode_state(source, state_dir, stream, times, recover_black):
    command = ["ffmpeg", "-v", "error", "-threads", "2"]
    decoder = {"vp9": "libvpx-vp9", "vp8": "libvpx"}.get(stream["codec_name"])
    if decoder:
        command += ["-c:v", decoder]
    command += [
        "-i", str(source), "-fps_mode", "passthrough",
        "-f", "rawvideo", "-pix_fmt", "rgba", "pipe:1",
    ]
    width, height = stream["width"], stream["height"]
    offsets, union, count = [], None, 0
    state_dir.mkdir(parents=True)
    # A temporary stderr file avoids deadlocking a full stderr pipe.
    with tempfile.TemporaryFile() as errors, subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=errors,
    ) as process:
        try:
            while True:
                data = read_frame(process.stdout, width * height * 4)
                if not data:
                    break
                if len(data) != width * height * 4:
                    raise ValueError("Incomplete RGBA frame")
                image, offset, box = transparent_crop(
                    Image.frombytes("RGBA", (width, height), data), recover_black,
                )
                image.save(state_dir / f"frame_{count:04d}.png", compress_level=7)
                offsets.append(offset)
                if box:
                    union = box if union is None else [
                        min(union[0], box[0]), min(union[1], box[1]),
                        max(union[2], box[2]), max(union[3], box[3]),
                    ]
                count += 1
                if count % 200 == 0:
                    print(f"{state_dir.name}: {count}/{len(times)} frames", flush=True)
            if process.wait(timeout=30) != 0:
                errors.seek(0)
                raise ValueError(errors.read().decode("utf-8", errors="replace"))
        except BaseException:
            process.kill()
            process.wait()
            raise
    if count != len(times) or union is None:
        raise ValueError(f"Frame/timestamp mismatch or empty animation: {count}/{len(times)}")
    return offsets, union, count


def run(src, name, out, recover_black=False):
    src, out = Path(src).resolve(), Path(out).resolve()
    if out.exists():
        raise FileExistsError(
            f"Destination already exists: {out}. Convert to a new directory; "
            "back up existing assets before replacing them."
        )
    if not all(shutil.which(command) for command in ("ffmpeg", "ffprobe")):
        raise RuntimeError("FFmpeg and ffprobe are required on PATH.")
    sources = find_sources(src)
    probed = {state: probe(path) for state, path in sources.items()}
    sizes = {data[0]["width"] for data in probed.values()}
    if len(sizes) != 1:
        raise ValueError("Animations do not share the same canvas size.")
    out.parent.mkdir(parents=True, exist_ok=True)
    if recover_black:
        print("WARNING: black-background recovery is approximate; inspect the contact sheet.", flush=True)
    with tempfile.TemporaryDirectory(prefix=".ark-build-", dir=out.parent) as temporary:
        staged = Path(temporary) / "pet"
        manifest = {
            "name": name, "schema_version": 2, "native_timing": True,
            "fps": 60, "size": sizes.pop(), "states": {},
        }
        (staged / "webm").mkdir(parents=True)
        for state, source in sources.items():
            stream, times, duration = probed[state]
            print("converting", state, source.name, flush=True)
            offsets, bbox, count = decode_state(
                source, staged / "frames" / state, stream, times, recover_black,
            )
            shutil.copy2(source, staged / "webm" / source.name)
            manifest["states"][state] = {
                "duration": duration, "count": count, "bbox": bbox, "source": source.name,
                "frame_times_ms": times, "frame_offsets": offsets,
                "source_average_fps": round((count - 1) * 1000 / times[-1], 3) if count > 1 else 0,
            }
            print(f"  wrote {count} native frames", flush=True)
        (staged / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        if out.exists():
            raise FileExistsError(f"Destination appeared during conversion: {out}")
        os.rename(staged, out)
    print("pet ready at", out)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", required=True, type=Path, help="one operator/skin WebM directory")
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--recover-black", action="store_true",
                        help="approximate alpha recovery; use only for opaque black exports")
    args = parser.parse_args()
    try:
        run(args.src, args.name, args.out, args.recover_black)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Conversion failed: {exc}\n")


if __name__ == "__main__":
    main()
