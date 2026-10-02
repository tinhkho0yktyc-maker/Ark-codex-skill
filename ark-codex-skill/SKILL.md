---
name: ark-codex-skill
description: Create or extend transparent Windows desktop pets for Arknights operators using PRTS model exports. Use when the user asks to make an operator deskpet, import or download its WebM animations, add a character to a shared deskpet library, or switch the character.
---

# Arknights Deskpet

Build a transparent Windows deskpet from PRTS operator models, or add an operator to an existing shared library. This improved fork is based on [AstrariaX/Ark-codex-skill](https://github.com/AstrariaX/Ark-codex-skill).

## Choose the project

Confirm the operator and optional skin; omitted skin means 默认. If the user supplies WebM files, use those files instead of downloading them again.

Reuse the existing shared project when adding a character. Keep each operator/skin's input in a separate directory. For different skins of one operator, use distinct library names. Do not scaffold over a running or nonempty project: the scaffolder intentionally refuses to overwrite settings, code or assets.

For a fresh project, Python 3.10+ and Windows 10/11 are required. Always use project-local environments:

```powershell
python scripts/scaffold_deskpet.py --target "<project-dir>" --pet "<operator>"
python scripts/setup_env.py "<project-dir>"
python scripts/setup_env.py "<project-dir>" --tools
```

The runtime uses only PySide6-Essentials in `.venv`. Export/conversion tools use Pillow and Playwright in `.tools-venv`; FFmpeg and ffprobe must be on PATH. With a system Chrome/Edge installation, `--tools --skip-browser` avoids downloading another Chromium.

## Export and import

Resolve the exact PRTS operator page and choose the requested skin and 基建 model group. Export Default, Interact, Move, Relax, Sit and Sleep. If automation is appropriate, the bundled exporter can be used:

```powershell
<project-dir>/.tools-venv/Scripts/python.exe scripts/prts_export.py "<operator>" --skin "<skin>" --out "<project-dir>/work/webm/<library-name>"
```

Read [references/prts-ui.md](references/prts-ui.md) when manual export or selector repair is needed. Preserve any supplied source WebM files.

The exporter explicitly selects VP9 to retain real alpha and discards a first warm-up take to avoid encoder startup gaps. A generic Chromium WebM export can select AV1 and carry an alpha_mode tag without alpha packets. If dark details disappear after black-background recovery, re-export transparently rather than accepting the damaged approximation. Keep the supplied originals and validate decoded alpha, not only container tags.

Convert and validate:

```powershell
<project-dir>/.tools-venv/Scripts/python.exe scripts/process_webm.py --src "<project-dir>/work/webm/<library-name>" --name "<library-name>" --out "<project-dir>/pets/<library-name>"
<project-dir>/.tools-venv/Scripts/python.exe scripts/validate_deskpet.py "<project-dir>/pets/<library-name>" --allow-inactive --out "<project-dir>/work/<library-name>-preview.png"
```

Conversion preserves native frame timestamps and alpha, crops only transparent exterior pixels and records original-canvas offsets. Do not resample new assets to the former fixed 20fps. Read [references/manifest.md](references/manifest.md) when adapting the converter or player.

Relax maps to idle, Interact to interact, Move to move, Sit to sit and Sleep to sleep. Files under 1000 bytes are skipped; Default is often a broken 110-byte export and does not become a state. All five playable states are required. Duplicate state files are rejected instead of silently mixing characters.

The converter stages a complete pet before publishing it and refuses an existing destination. To rebuild a pet, use a fresh output directory, inspect the preview and preserve the old assets before a deliberate replacement with the app stopped. If the decoded source has opaque black background, prefer a transparent re-export. Only use `--recover-black` when approximation is intended; inspect dark outlines and shadows before accepting it.

Restart the project, select the pet through the 桌宠库 menu and verify visible transparency, all five actions, scale and screen position. Initial projects retain the upstream 予愿安洁莉娜 sample, so they can launch before the requested pet is imported. If no valid pet exists, the app shows an import hint rather than failing during module import.

## Runtime behavior

- Per-pet position, scale and animation speed are remembered.
- Subtitle width is independent of pet scale; hovering reveals full local task information.
- Automatic rest starts after about 40–60 seconds and sleep after 90 seconds. Manual states take precedence.
- Roaming is optional and starts disabled. Walking/idle transitions blend for 140ms and retain facing; only automatic roaming idle caps long source holds at 120ms. Manual and other playback retain native timing. Roaming pauses for interaction, dragging, menus and rest.
- The playback cap defaults to 60fps, but old 20fps assets cannot gain frames without reconversion.
- The Codex monitor reads rollout logs under CODEX_HOME/sessions or the default ~/.codex/sessions; it does not change Codex data.
- Autostart is optional and starts disabled. Only enable it or create shortcuts when requested. The watcher shows the pet and tray while Codex/ChatGPT is running, with project-scoped single-instance guards and crash backoff.
- Tray Exit ends normal supervision; do not bypass a user's deliberate hide or exit choice.

When changing the template, run `tests/test_deskpet.py` with the runtime environment and `tests/test_pipeline.py` with the tools environment. Tests use isolated generated fixtures, not personal operator assets. Do not launch a second watcher or register test startup entries.

## Source and sharing

Preserve the original project URL and author attribution. The upstream has no explicit LICENSE; do not invent licensing for its code or third-party art. Retain personal-learning/noncommercial notes. For sharing, exclude settings, logs, identity/PID/flag files, virtual environments, session data and newly downloaded character assets unless the user has appropriate rights and explicitly requests their inclusion.
