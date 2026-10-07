#!/usr/bin/env python3
"""Build an explicitly allowlisted source candidate; never publish remotely."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile
import zipfile

REPO = Path(__file__).resolve().parents[2]


def allowed(path):
    parts = path.parts
    if any(part.startswith(".") or part == "__pycache__" for part in parts):
        return False
    if path.as_posix() in {"README.md", "NOTICE.md", "CHANGELOG.md", "VERSION"}:
        return True
    if parts[0] == "docs":
        return path.suffix == ".md"
    if parts[0] != "ark-codex-skill":
        return False
    if len(parts) > 4 and parts[1:4] == ("assets", "deskpet-app", "pets"):
        return (len(parts) > 5 and parts[4] == "予愿安洁莉娜"
                and path.suffix in {".png", ".webm", ".json"})
    if "pets" in parts:
        return False
    return path.suffix in {".py", ".pyw", ".md", ".bat"} or path.name in {"requirements.txt", "requirements-tools.txt"}


def build(out, repo=REPO):
    repo, out = Path(repo).resolve(), Path(out).resolve()
    if out.exists() or out == repo or out.is_relative_to(repo):
        raise ValueError("Choose a new output directory outside the source repository")
    version = (repo / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?", version):
        raise ValueError("Invalid release version")
    files = []
    for path in sorted(repo.rglob("*")):
        relative = path.relative_to(repo)
        if path.is_file() and allowed(relative):
            if path.is_symlink() or not path.resolve().is_relative_to(repo):
                raise ValueError("Release source contains a link outside the repository")
            files.append((path, relative))
    required = ["README.md", "NOTICE.md", "CHANGELOG.md", "VERSION", "ark-codex-skill/SKILL.md",
                "ark-codex-skill/assets/deskpet-app/main.py",
                "ark-codex-skill/assets/deskpet-app/behavior_support.py",
                "ark-codex-skill/assets/deskpet-app/library_support.py",
                "ark-codex-skill/assets/deskpet-app/library_channel.py"]
    selected = {relative.as_posix() for _, relative in files}
    if not set(required) <= selected:
        raise ValueError("Incomplete source candidate")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".release-", dir=out.parent) as temporary:
        stage = Path(temporary) / "candidate"
        stage.mkdir()
        name = f"Ark-Codex-Skill-{version}-source.zip"
        archive = stage / name
        manifest = []
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipper:
            for path, relative in files:
                data = path.read_bytes()
                entry = zipfile.ZipInfo(f"Ark-codex-skill-{version}/{relative.as_posix()}", date_time=(2026, 10, 5, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                zipper.writestr(entry, data)
                manifest.append(dict(path=relative.as_posix(), bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
        with zipfile.ZipFile(archive) as zipper:
            if zipper.testzip() is not None or len(zipper.namelist()) != len(files):
                raise ValueError("Source ZIP validation failed")
        index = stage / "FILES.json"
        index.write_text(json.dumps(dict(version=version, files=manifest), ensure_ascii=False, indent=2), encoding="utf-8")
        sums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in (archive, index))
        (stage / "SHA256SUMS.txt").write_text(sums, encoding="ascii")
        if out.exists():
            raise FileExistsError("Release output appeared during build")
        stage.rename(out)
    return dict(version=version, files=len(files), zip=str(out / name), bytes=(out / name).stat().st_size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = build(args.out)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Build failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
