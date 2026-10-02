"""Network-free scaffold/conversion tests using procedural, non-game assets."""

import contextlib
import io
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import process_webm as converter
import scaffold_deskpet as scaffold
import setup_env
import prts_export


class PipelineTests(unittest.TestCase):
    def test_scaffold_does_not_replace_existing_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "existing"
            target.mkdir()
            settings = target / "settings.json"
            settings.write_bytes(b"user settings")
            with self.assertRaises(FileExistsError):
                scaffold.scaffold(target)
            self.assertEqual(settings.read_bytes(), b"user settings")
            self.assertEqual(list(target.iterdir()), [settings])

    def test_scaffold_ignores_runtime_state_and_defaults_are_opt_in(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "template"
            template.mkdir()
            for filename in ("main.py", "requirements.txt", "settings.json", "watcher.log", "pet.process.json"):
                (template / filename).write_text("fixture", encoding="utf-8")
            with patch.object(scaffold, "APP_TEMPLATE", template):
                target = scaffold.scaffold(root / "new", "test-pet")
            settings = json.loads((target / "settings.json").read_text(encoding="utf-8"))
            self.assertFalse(settings["autostart_with_codex"])
            self.assertFalse(settings["roaming_enabled"])
            self.assertEqual(settings["playback_fps"], 60)
            self.assertTrue((target / "main.py").is_file())
            self.assertFalse((target / "watcher.log").exists())
            self.assertFalse((target / "pet.process.json").exists())

    def test_runtime_install_does_not_install_tools_globally(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(setup_env, "run") as run:
            project = Path(temporary)
            requirements = project / "requirements.txt"
            executable = setup_env.install_environment(project, ".venv", requirements, "python")
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0], ["python", "-m", "venv", project / ".venv"])
            self.assertEqual(commands[1][0], executable)
            self.assertEqual(commands[1][-1], requirements)
            self.assertEqual(executable.parent.parent, project / ".venv")

    def test_mapping_skips_broken_default_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for token, state in converter.STATE_MAP:
                (directory / f"operator-skin-{token}-x1.webm").write_bytes(b"x" * 1001)
            (directory / "Default.webm").write_bytes(b"x" * 110)
            with contextlib.redirect_stdout(io.StringIO()):
                sources = converter.find_sources(directory)
            self.assertEqual(set(sources), {state for token, state in converter.STATE_MAP})
            (directory / "another-Relax.webm").write_bytes(b"x" * 1001)
            with self.assertRaisesRegex(ValueError, "Multiple files"):
                converter.find_sources(directory)

    def test_missing_state_is_not_silently_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "Missing valid WebM"):
                converter.find_sources(temporary)

    def test_existing_pet_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "pet"
            out.mkdir()
            sentinel = out / "manifest.json"
            sentinel.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                converter.run(Path(temporary), "fixture", out)
            self.assertEqual(sentinel.read_bytes(), b"existing")

    def test_crop_preserves_alpha_and_source_coordinates(self):
        source = Image.new("RGBA", (64, 64))
        ImageDraw.Draw(source).rectangle((20, 15, 40, 45), fill=(30, 160, 80, 200))
        image, offset, box = converter.transparent_crop(source)
        canvas = Image.new("RGBA", source.size)
        canvas.paste(image, offset)
        self.assertEqual(canvas.tobytes(), source.tobytes())
        self.assertEqual(box, [20, 15, 40, 45])
        self.assertEqual(offset, (16, 11))
        self.assertLess(image.width * image.height, source.width * source.height)

    def test_black_recovery_requires_explicit_opt_in(self):
        source = Image.new("RGBA", (64, 64), (0, 0, 0, 255))
        ImageDraw.Draw(source).rectangle((20, 20, 40, 40), fill=(50, 200, 80, 255))
        with self.assertRaisesRegex(ValueError, "opaque black"):
            converter.transparent_crop(source)
        image, offset, box = converter.transparent_crop(source, recover_black=True)
        self.assertIsNotNone(box)
        self.assertLess(image.getchannel("A").getextrema()[0], 255)

    def test_variable_timestamps_are_preserved(self):
        probe = {
            "streams": [{"width": 64, "height": 64, "codec_name": "vp9"}],
            "format": {"duration": "0.19"},
            "frames": [{"best_effort_timestamp_time": t} for t in ("0", "0.017", "0.073", "0.150")],
        }
        response = type("Response", (), {"stdout": json.dumps(probe).encode()})()
        with patch.object(converter.subprocess, "run", return_value=response):
            stream, times, duration = converter.probe(Path("fixture.webm"))
        self.assertEqual(times, [0, 17, 73, 150])
        self.assertEqual(duration, 190)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/ffprobe required")
class NativeConversionTests(unittest.TestCase):
    @unittest.skipUnless(prts_export.find_chrome(), "System Chrome/Edge required")
    def test_browser_export_preserves_true_alpha_and_black_artwork(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as temporary, sync_playwright() as playwright:
            root = Path(temporary)
            browser = playwright.chromium.launch(executable_path=prts_export.find_chrome(), headless=True)
            try:
                context = browser.new_context()
                context.add_init_script(prts_export.ALPHA_RECORDER)
                page = context.new_page()
                page.goto("data:text/html," + urllib.parse.quote('<canvas id="fixture" width="64" height="64"></canvas>'))
                result = page.evaluate("""async () => {
                    const canvas = document.getElementById('fixture');
                    const ctx = canvas.getContext('2d');
                    ctx.fillStyle = 'green';
                    ctx.fillRect(16, 16, 32, 32);
                    const recorder = new MediaRecorder(canvas.captureStream(30), {mimeType: 'video/webm'});
                    const chunks = [];
                    recorder.ondataavailable = event => chunks.push(event.data);
                    const started = new Promise(resolve => recorder.onstart = resolve);
                    const stopped = new Promise(resolve => recorder.onstop = resolve);
                    recorder.start();
                    await started;
                    for (let index = 0; index < 24; index++) {
                        ctx.clearRect(0, 0, 64, 64);
                        ctx.fillStyle = `rgb(${40 + index * 3},160,80)`;
                        ctx.fillRect(16, 16, 32, 32);
                        ctx.fillStyle = 'black';
                        ctx.fillRect(24, 24, 12, 12);
                        await new Promise(resolve => setTimeout(resolve, 40));
                    }
                    recorder.stop();
                    await stopped;
                    return {mime: recorder.mimeType, bytes: Array.from(new Uint8Array(await new Blob(chunks).arrayBuffer()))};
                }""")
                self.assertIn("vp9", result["mime"].lower())
                source = root / "browser-alpha.webm"
                source.write_bytes(bytes(result["bytes"]))
            finally:
                browser.close()
            try:
                stream, times, duration = converter.probe(source)
            except subprocess.CalledProcessError as error:
                self.fail(f"Browser produced {source.stat().st_size} bytes: {error.stderr.decode(errors='replace')}")
            self.assertEqual(stream["codec_name"], "vp9")
            self.assertGreater(len(times), 2)
            offsets, bbox, count = converter.decode_state(source, root / "frames", stream, times, False)
            self.assertEqual(count, len(times))
            with Image.open(root / "frames/frame_0000.png") as image:
                self.assertEqual(image.getpixel((0, 0))[3], 0)
            with Image.open(root / f"frames/frame_{count - 1:04d}.png") as image:
                black = image.getpixel((29 - offsets[-1][0], 29 - offsets[-1][1]))
                self.assertGreaterEqual(black[3], 250)
                self.assertLess(max(black[:3]), 10)

    def test_real_alpha_webm_round_trip_and_failed_staging_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames = root / "source-frames"
            frames.mkdir()
            noise = random.Random(7)
            for index in range(6):
                image = Image.new("RGBA", (64, 64))
                for y in range(16, 48):
                    for x in range(16, 48):
                        image.putpixel((x, y), (noise.randrange(256), noise.randrange(256), noise.randrange(256), 255))
                image.save(frames / f"frame_{index:04d}.png")
            webm = root / "fixture.webm"
            subprocess.run([
                "ffmpeg", "-v", "error", "-framerate", "5",
                "-i", str(frames / "frame_%04d.png"), "-c:v", "libvpx-vp9",
                "-lossless", "1", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", str(webm),
            ], check=True, capture_output=True, timeout=60)
            self.assertGreater(webm.stat().st_size, 1000)
            sources = root / "sources"
            sources.mkdir()
            for token, state in converter.STATE_MAP:
                shutil.copyfile(webm, sources / f"fixture-{token}.webm")
            output = root / "pet"
            with contextlib.redirect_stdout(io.StringIO()):
                manifest = converter.run(sources, "procedural-test", output)
            self.assertTrue(manifest["native_timing"])
            self.assertEqual(manifest["schema_version"], 2)
            for state, info in manifest["states"].items():
                self.assertEqual(info["count"], 6)
                self.assertEqual(info["frame_times_ms"], [0, 200, 400, 600, 800, 1000])
                self.assertEqual(len(info["frame_offsets"]), 6)
                self.assertGreater(info["duration"], info["frame_times_ms"][-1])
                with Image.open(output / "frames" / state / "frame_0000.png") as image:
                    self.assertEqual(image.getpixel((0, 0))[3], 0)
                    self.assertEqual(image.getchannel("A").getextrema()[1], 255)
                    self.assertLess(image.width * image.height, 64 * 64)
            sentinel = (output / "manifest.json").read_bytes()
            failed = root / "failed"
            with patch.object(converter, "decode_state", side_effect=ValueError("fixture error")), \
                 contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                converter.run(sources, "failed", failed)
            self.assertFalse(failed.exists())
            self.assertEqual(list(root.glob(".ark-build-*")), [])
            self.assertEqual((output / "manifest.json").read_bytes(), sentinel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
