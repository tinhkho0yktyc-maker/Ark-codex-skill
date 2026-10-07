# Deskpet manifest compatibility

The player accepts the upstream fixed-fps format and the native-timing v2 format. PNG files are named `frames/<state>/frame_0000.png`, consecutively from zero.

Required states: `idle`, `interact`, `move`, `sit`, `sleep`. PRTS sources map Relax, Interact, Move, Sit and Sleep respectively. Optional `special` comes from an actual Special source. Default is not a sixth mode. Additional safe state names are accepted by the runtime action menu; grouped manifests need an adapter and are explicitly rejected.

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

Automatic roaming is a deliberate playback exception: idle frame holds above 120ms are capped in a separate in-memory timeline, and walking/idle images blend for 140ms. The source timestamps and manifest remain unchanged. Non-roaming and manually selected playback use the native timeline.

Movement uses a separate timer and floating-point window-content coordinates. The renderer compensates the native physical client origin and filters the composed pet/subtitle layer only during actual autonomous translation. When stationary, it rounds only the display offset to physical pixels and performs no fractional interpolation; the continuous world position and saved anchor are not rounded. This prevents captions and idle artwork from staying soft at a half-pixel rest position. A Move preview without actual translation uses the stationary path. This changes presentation, not frame timestamps, crops, alpha data, or the animation cap. Saved bottom-center anchors may contain fractional values in the existing v1 position format.

Crop bounds include padding around pixels whose alpha exceeds 10. The union bbox is calculated before trimming, with inclusive right/bottom coordinates. Reconstruct frames using their offsets; do not independently resize crops or treat their top-left corners as the original canvas origin.

Transparent WebM alpha should be preserved by libvpx/libvpx-vp9 decoding. Opaque-black recovery is explicit and approximate; never describe it as lossless alpha recovery.

## Validation and replacement

`library_support.validate_pet` accepts legacy full canvases and v2 offset crops, validates finite timing, strict timestamp order and crop bounds, and can verify every PNG chunk. The installer additionally decodes each PNG with Pillow. Runtime discovery isolates invalid manifests rather than failing the entire library.

Prefer conversion into a prepared working directory, then `scripts/install_deskpet.py --project <project>`. It serializes installs, coordinates a 30-second freeze lease with a running app and reloads current-pet caches. Same-name replacement needs explicit `--replace`; previous frames remain in `pets/.backups`. Only the manifest and PNG frame tree enter the runtime library. On an uncertain finish reply, do not rollback under a live app without another freeze; keep the candidate and recoverable backup if synchronization cannot be confirmed.

The converter requires a complete five-state source set and a new output directory. It stages all PNGs and the manifest locally and moves the complete directory into place only after success. A failure cleans the staged directory and does not change the existing pet.

Validate frame counts, numbering, alpha, timestamp ordering, offset bounds and union bbox, then inspect a checkerboard contact sheet. Very old upstream bboxes were sampled at two-pixel steps; `validate_deskpet.py --allow-bbox-mismatch` can inspect those legacy assets without rewriting them. Do not use that switch to hide a mismatch in newly generated v2 assets.
