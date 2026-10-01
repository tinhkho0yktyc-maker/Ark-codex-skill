# Deskpet manifest compatibility

The player accepts the upstream fixed-fps format and the native-timing v2 format. PNG files are named `frames/<state>/frame_0000.png`, consecutively from zero.

Required states: `idle`, `interact`, `move`, `sit`, `sleep`. PRTS sources map Relax, Interact, Move, Sit and Sleep respectively. Default is not a sixth mode.

## Shared fields

- `size`: side length of the original square canvas, normally 1000.
- `fps`: fallback rate for old uniform-timing states. New v2 manifests use 60 as a compatibility value; their actual timings take precedence.
- `states`: per-state objects with `count`, `duration` in milliseconds, inclusive original-canvas `bbox = [left, top, right, bottom]`, and source WebM filename.

Legacy PNGs occupy the full canvas and omit per-frame timestamps and offsets. Keep their source frame rate when displaying them. Raising the redraw cap does not synthesize missing frames.

## V2 fields

- `schema_version: 2`, `native_timing: true`.
- `frame_times_ms`: exactly one timestamp for every PNG, first timestamp zero, increasing, last timestamp less than duration.
- `frame_offsets`: one `[x, y]` per PNG, locating the cropped image on the original canvas.
- `source_average_fps`: diagnostic average, not a replacement for the timestamps.
- `name`: library display name.

The player computes elapsed animation time from a monotonic clock and the user's animation speed, loops modulo duration, and selects the most recent frame timestamp not greater than that position. The 20/30/60fps UI setting caps redraws; it does not change source timestamps or action duration.

Crop bounds include padding around pixels whose alpha exceeds 10. The union bbox is calculated before trimming, with inclusive right/bottom coordinates. Reconstruct frames using their offsets; do not independently resize crops or treat their top-left corners as the original canvas origin.

Transparent WebM alpha should be preserved by libvpx/libvpx-vp9 decoding. Opaque-black recovery is explicit and approximate; never describe it as lossless alpha recovery.

## Validation and replacement

The converter requires a complete five-state source set and a new output directory. It stages all PNGs and the manifest locally and moves the complete directory into place only after success. A failure cleans the staged directory and does not change the existing pet.

Validate frame counts, numbering, alpha, timestamp ordering, offset bounds and union bbox, then inspect a checkerboard contact sheet. Very old upstream bboxes were sampled at two-pixel steps; `validate_deskpet.py --allow-bbox-mismatch` can inspect those legacy assets without rewriting them. Do not use that switch to hide a mismatch in newly generated v2 assets.
