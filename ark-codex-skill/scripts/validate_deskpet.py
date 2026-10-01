#!/usr/bin/env python3
"""Validate a generated deskpet and create a checkerboard contact sheet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw


STATES = ("idle", "interact", "move", "sit", "sleep")


def alpha_bbox(image: Image.Image):
    alpha = image.getchannel("A").point(lambda value: 255 if value > 10 else 0)
    box = alpha.getbbox()
    if box is None:
        return None
    left, top, right, bottom = box
    return [left, top, right - 1, bottom - 1]


def union_bbox(boxes):
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def checkerboard(size, block=16):
    image = Image.new("RGBA", size, (238, 238, 238, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], block):
        for x in range(0, size[0], block):
            if (x // block + y // block) % 2:
                draw.rectangle(
                    (x, y, min(x + block - 1, size[0] - 1), min(y + block - 1, size[1] - 1)),
                    fill=(202, 202, 202, 255),
                )
    return image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pet_dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-inactive", action="store_true")
    parser.add_argument("--allow-bbox-mismatch", action="store_true")
    args = parser.parse_args()

    manifest = json.loads((args.pet_dir / "manifest.json").read_text(encoding="utf-8"))
    project = args.pet_dir.parent.parent
    settings_path = project / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {"pet": args.pet_dir.name}
    if not args.allow_inactive:
        assert settings["pet"] == args.pet_dir.name, (settings["pet"], args.pet_dir.name)
    assert set(manifest["states"]) == set(STATES), manifest["states"].keys()

    cell_w, cell_h = 300, 380
    sheet = checkerboard((cell_w * len(STATES), cell_h))
    draw = ImageDraw.Draw(sheet)
    summary = {}

    for column, state in enumerate(STATES):
        info = manifest["states"][state]
        files = sorted((args.pet_dir / "frames" / state).glob("frame_*.png"))
        assert len(files) == info["count"], (state, len(files), info["count"])
        expected_names = [f"frame_{index:04d}.png" for index in range(info["count"])]
        assert [path.name for path in files] == expected_names, state
        offsets = info.get("frame_offsets")
        if offsets:
            assert len(offsets) == len(files), state
        times = info.get("frame_times_ms")
        if times:
            assert len(times) == len(files), state
            assert times[0] == 0 and times == sorted(times), state
            assert times[-1] < info["duration"], state

        boxes = []
        transparent_frames = 0
        for index, path in enumerate(files):
            with Image.open(path) as source:
                image = source.convert("RGBA")
            offset_x, offset_y = offsets[index] if offsets else (0, 0)
            if offsets:
                assert 0 <= offset_x < manifest["size"] and 0 <= offset_y < manifest["size"], (state, path)
                assert offset_x + image.width <= manifest["size"] and offset_y + image.height <= manifest["size"], (state, path)
            else:
                assert image.size == (manifest["size"], manifest["size"]), (state, path, image.size)
            extrema = image.getchannel("A").getextrema()
            if extrema[0] <= 10:
                transparent_frames += 1
            assert all(image.getpixel(point)[3] <= 10 for point in ((0, 0), (image.width-1, 0), (0, image.height-1), (image.width-1, image.height-1))), (state, path)
            box = alpha_bbox(image)
            if box is not None:
                boxes.append([box[0]+offset_x, box[1]+offset_y, box[2]+offset_x, box[3]+offset_y])

        assert boxes, (state, "animation is entirely transparent")
        calculated_bbox = union_bbox(boxes)
        if not args.allow_bbox_mismatch:
            assert calculated_bbox == info["bbox"], (state, calculated_bbox, info["bbox"])
        assert transparent_frames == len(files), (state, transparent_frames, len(files))

        sample_path = files[len(files) // 2]
        with Image.open(sample_path) as source:
            sample = source.convert("RGBA")
        if offsets:
            canvas = Image.new("RGBA", (manifest["size"], manifest["size"]))
            canvas.alpha_composite(sample, tuple(offsets[len(files)//2]))
            sample = canvas
        left, top, right, bottom = info["bbox"]
        margin = 8
        crop = sample.crop(
            (
                max(0, left - margin),
                max(0, top - margin),
                min(sample.width, right + margin + 1),
                min(sample.height, bottom + margin + 1),
            )
        )
        crop.thumbnail((cell_w - 24, cell_h - 50), Image.Resampling.LANCZOS)
        x = column * cell_w + (cell_w - crop.width) // 2
        y = 30 + (cell_h - 40 - crop.height) // 2
        sheet.alpha_composite(crop, (x, y))
        draw.text((column * cell_w + 10, 8), f"{state}  {len(files)} frames", fill=(20, 20, 20, 255))
        summary[state] = {
            "frames": len(files),
            "bbox": calculated_bbox,
            "manifest_bbox": info["bbox"],
            "sample": sample_path.name,
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(args.out, quality=94)
    print(json.dumps({"pet": args.pet_dir.name, "states": summary, "contact_sheet": str(args.out)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
