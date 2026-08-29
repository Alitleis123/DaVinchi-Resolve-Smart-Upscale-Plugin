"""Shared fixtures: repo on sys.path, a fake Resolve module, synthetic videos."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.fake_resolve import FakeBmdModule, build_session  # noqa: E402


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def install_fake_resolve(monkeypatch):
    """Install a fake `DaVinciResolveScript` module and return a session builder.

    Usage:
        resolve, timeline, items, mpi = install_fake_resolve([(0, 100)])
    """

    def _install(clips, *, strict: bool = True, selected_index: int = 0, **kwargs):
        resolve, timeline, items, mpi = build_session(
            clips, strict=strict, selected_index=selected_index, **kwargs
        )
        monkeypatch.setitem(sys.modules, "DaVinciResolveScript", FakeBmdModule(resolve))
        return resolve, timeline, items, mpi

    return _install


@pytest.fixture
def no_resolve(monkeypatch):
    """Simulate running outside Resolve: the import fails."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "DaVinciResolveScript":
            raise ImportError("No module named 'DaVinciResolveScript'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "DaVinciResolveScript", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)


# --------------------------------------------------------------------------
# Synthetic video generation
# --------------------------------------------------------------------------

def _write_video(path: Path, frames, fps: float = 30.0) -> Path:
    import cv2

    h, w = frames[0].shape[:2]
    # FFV1 in .avi is lossless, so motion scores are not polluted by codec noise.
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"FFV1"), fps, (w, h))
    if not writer.isOpened():
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    assert writer.isOpened(), "OpenCV could not open a video writer"
    for f in frames:
        writer.write(f)
    writer.release()
    return path


@pytest.fixture
def make_video(tmp_path):
    """Build a video whose motion is known exactly, frame by frame.

    `motion_frames` is the set of frame indices that differ from their
    predecessor; every other frame is a byte-for-byte repeat.
    """

    def _make(name: str = "clip.avi", n_frames: int = 60, motion_frames=(),
              fps: float = 30.0, size=(160, 120), amplitude: int = 200) -> Path:
        w, h = size
        motion = set(motion_frames)
        frames = []
        base = np.zeros((h, w, 3), dtype=np.uint8)
        base[:, :] = (30, 30, 30)
        current = base.copy()
        for i in range(n_frames):
            if i in motion:
                current = current.copy()
                # A bright block in a corner: localized, so the tile-based
                # "detail" scorer sees it strongly.
                y0 = (i * 7) % max(1, h - 40)
                x0 = (i * 11) % max(1, w - 40)
                current[y0:y0 + 40, x0:x0 + 40] = (amplitude, amplitude, amplitude)
            frames.append(current.copy())
        return _write_video(tmp_path / name, frames, fps=fps)

    return _make
