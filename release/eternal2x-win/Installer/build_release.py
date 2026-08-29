"""Regenerate the release folders and refresh update/latest.json.

Run this before publishing. It copies the runtime files into
release/eternal2x-mac and release/eternal2x-win, zips them, and writes the
zip checksums into the update metadata so the auto-updater can verify what it
downloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = {"eternal2x-mac": "macos", "eternal2x-win": "windows"}

# What ships to users. Tests, release artefacts and dev tooling stay behind.
PAYLOAD = ["Pipeline", "Stages", "Installer", "VERSION", "README.md",
           "requirements.txt"]
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo"}

RELEASE_URL = ("https://github.com/Alitleis123/Eternal2x.com/releases/download/"
               "v{version}/{name}.zip")


def read_version() -> str:
    return (REPO_ROOT / "VERSION").read_text(encoding="utf-8-sig").strip()


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for child in sorted(src.iterdir()):
            if child.name in SKIP_DIRS or child.suffix in SKIP_SUFFIXES:
                continue
            _copy(child, dst / child.name)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def build_folder(name: str) -> Path:
    dest = REPO_ROOT / "release" / name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for item in PAYLOAD:
        source = REPO_ROOT / item
        if source.exists():
            _copy(source, dest / item)
    return dest


def zip_folder(folder: Path) -> Path:
    archive = folder.with_suffix(".zip")
    if archive.exists():
        archive.unlink()
    shutil.make_archive(str(folder), "zip", root_dir=folder.parent,
                        base_dir=folder.name)
    return archive


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Eternal2x release.")
    parser.add_argument("--no-zip", action="store_true",
                        help="Refresh the release folders without zipping.")
    args = parser.parse_args()

    version = read_version()
    print(f"Building Eternal2x {version}")

    meta = {"version": version}
    for name, key in PLATFORMS.items():
        folder = build_folder(name)
        print(f"  {name}: {sum(1 for _ in folder.rglob('*') if _.is_file())} files")
        if args.no_zip:
            continue
        archive = zip_folder(folder)
        meta[key] = {
            "url": RELEASE_URL.format(version=version, name=name),
            "sha256": sha256(archive),
        }
        print(f"  {archive.name}: {meta[key]['sha256'][:16]}...")

    if not args.no_zip:
        meta_path = REPO_ROOT / "update" / "latest.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        # Plain UTF-8, no BOM: the updater decodes this over the network.
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {meta_path.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
