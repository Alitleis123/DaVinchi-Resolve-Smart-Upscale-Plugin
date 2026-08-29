"""Release hygiene: do the shipped copies match the source, and is metadata sane?

These catch the class of bug where a fix exists in the repo but never reaches
users because the release folder or update metadata was not regenerated.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

PACKAGED = ("Pipeline", "Stages", "Installer", "VERSION", "README.md", "requirements.txt")
RELEASES = ("eternal2x-mac", "eternal2x-win")


def read_version(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").strip()


# --------------------------------------------------------------------------
# encoding
# --------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "VERSION",
    "update/latest.json",
    "release/eternal2x-mac/VERSION",
    "release/eternal2x-win/VERSION",
])
def test_shipped_text_files_have_no_byte_order_mark(repo_root, rel):
    """A UTF-8 BOM breaks both the version parser and the JSON update feed."""
    path = repo_root / rel
    if not path.exists():
        pytest.skip(f"{rel} not present")
    head = path.read_bytes()[:3]
    assert head != b"\xef\xbb\xbf", (
        f"{rel} starts with a UTF-8 BOM. Rewrite it as plain UTF-8 "
        "(PowerShell's Set-Content/Out-File adds this by default)."
    )


def test_published_update_metadata_is_parseable(repo_root):
    """This is the exact file the auto-updater fetches; it has to load."""
    raw = (repo_root / "update" / "latest.json").read_bytes().decode("utf-8")
    json.loads(raw)  # matches _download_json's decode path exactly


# --------------------------------------------------------------------------
# update metadata contents
# --------------------------------------------------------------------------

def test_update_metadata_lists_every_platform(repo_root):
    meta = json.loads((repo_root / "update" / "latest.json").read_text(encoding="utf-8-sig"))
    for key in ("windows", "macos"):
        assert key in meta, f"latest.json has no entry for {key}"
        assert meta[key].get("url", "").startswith("https://")
        assert re.fullmatch(r"[0-9a-f]{64}", meta[key].get("sha256", "").lower()), (
            f"{key} sha256 is not a 64-char hex digest"
        )


def test_update_metadata_version_matches_the_repo_version(repo_root):
    meta = json.loads((repo_root / "update" / "latest.json").read_text(encoding="utf-8-sig"))
    assert meta["version"] == read_version(repo_root / "VERSION"), (
        "latest.json advertises a different version than VERSION; users either "
        "never see the update or re-download it forever"
    )


def test_update_urls_reference_the_advertised_version(repo_root):
    meta = json.loads((repo_root / "update" / "latest.json").read_text(encoding="utf-8-sig"))
    version = meta["version"]
    for key in ("windows", "macos"):
        assert version in meta[key]["url"], (
            f"{key} download URL {meta[key]['url']} does not mention version {version}"
        )


# --------------------------------------------------------------------------
# release folder parity
# --------------------------------------------------------------------------

@pytest.mark.parametrize("release", RELEASES)
def test_release_version_matches_the_repo(repo_root, release):
    rel_version = repo_root / "release" / release / "VERSION"
    if not rel_version.exists():
        pytest.skip(f"{release} not built")
    assert read_version(rel_version) == read_version(repo_root / "VERSION")


@pytest.mark.parametrize("release", RELEASES)
def test_release_code_matches_the_repo_source(repo_root, release):
    """Every packaged .py must be byte-identical to the file it was copied from."""
    base = repo_root / "release" / release
    if not base.exists():
        pytest.skip(f"{release} not built")

    drift = []
    for pkg in ("Pipeline", "Stages", "Installer"):
        for shipped in sorted((base / pkg).rglob("*.py")):
            source = repo_root / shipped.relative_to(base)
            if not source.exists():
                drift.append(f"{shipped.relative_to(base)} (no longer in repo)")
            elif source.read_bytes() != shipped.read_bytes():
                drift.append(str(shipped.relative_to(base)))

    assert not drift, (
        f"{release} is stale; these files differ from the repo: {drift}. "
        "Re-run the release build before publishing."
    )


@pytest.mark.parametrize("release", RELEASES)
def test_release_ships_every_module_the_ui_invokes(repo_root, release):
    base = repo_root / "release" / release
    if not base.exists():
        pytest.skip(f"{release} not built")

    lua = (repo_root / "Installer" / "Eternal2x.lua").read_text(encoding="utf-8")
    for module in re.findall(r'"(Stages\.[a-z_]+)"', lua):
        rel = Path(module.replace(".", "/") + ".py")
        assert (base / rel).exists(), f"{release} is missing {module}, which a button calls"


@pytest.mark.parametrize("release", RELEASES)
def test_release_includes_the_lua_scripts(repo_root, release):
    base = repo_root / "release" / release
    if not base.exists():
        pytest.skip(f"{release} not built")
    for name in ("Eternal2x.lua", "Eternal2xLauncher.lua"):
        assert (base / "Installer" / name).exists(), f"{release} is missing {name}"


# --------------------------------------------------------------------------
# source sanity
# --------------------------------------------------------------------------

def test_every_python_file_compiles(repo_root):
    broken = []
    for py in sorted(repo_root.rglob("*.py")):
        if any(part in {".venv", "build", "dist", "__pycache__"} for part in py.parts):
            continue
        try:
            ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError as exc:
            broken.append(f"{py.relative_to(repo_root)}: {exc}")
    assert not broken, broken


def test_declared_requirements_cover_what_the_code_imports(repo_root):
    declared = {
        line.split("==")[0].split(">=")[0].strip().lower()
        for line in (repo_root / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    alias = {"cv2": "opencv-python", "numpy": "numpy"}
    needed = set()
    for py in (repo_root / "Stages").rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        for mod, pkg in alias.items():
            if re.search(rf"^\s*import {mod}\b|^\s*from {mod}\b", src, re.M):
                needed.add(pkg)
    missing = needed - declared
    assert not missing, f"requirements.txt is missing {missing}"


def test_readme_documents_the_buttons_the_ui_actually_has(repo_root):
    lua = (repo_root / "Installer" / "Eternal2x.lua").read_text(encoding="utf-8")
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    button_ids = set(re.findall(r'ui:Button\{ID="(\w+)"', lua))
    labels = {
        "DetectBtn": "Detect",
        "CutFrameBtn": "Sequence",
        "RegroupBtn": "Regroup",
        "UpscaleBtn": "Upscale",
        "UpdateBtn": "Check for Updates",
    }
    for bid in button_ids:
        label = labels.get(bid)
        if label:
            assert label in readme, f"README does not mention the {label} button"
