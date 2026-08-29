"""Motion scoring, driven by synthetic videos whose motion is known exactly."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from Pipeline.config import UpscaleConfig
from Stages.motion_score import (
    _parse_tile_grid,
    _preprocess,
    compute_motion_scores,
    score_detail,
    score_global,
)


def cfg(**kw) -> UpscaleConfig:
    c = UpscaleConfig()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


# --------------------------------------------------------------------------
# _parse_tile_grid
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (8, (8, 8)),
    ((4, 6), (4, 6)),
    ([4, 6], (4, 6)),
    ("8x8", (8, 8)),
    ("4X6", (4, 6)),
    ("4,6", (4, 6)),
    ("12", (12, 12)),
    (0, (1, 1)),
    (-5, (1, 1)),
    (None, (8, 8)),
])
def test_parse_tile_grid(value, expected):
    assert _parse_tile_grid(value) == expected


# --------------------------------------------------------------------------
# _preprocess
# --------------------------------------------------------------------------

def test_preprocess_returns_grayscale():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    out = _preprocess(frame, max_width=640)
    assert out.ndim == 2


def test_preprocess_downscales_wide_frames_preserving_aspect():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    out = _preprocess(frame, max_width=640)
    assert out.shape[1] == 640
    assert out.shape[0] == 360


def test_preprocess_leaves_small_frames_alone():
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    assert _preprocess(frame, max_width=640).shape == (120, 160)


# --------------------------------------------------------------------------
# scorers
# --------------------------------------------------------------------------

def test_identical_frames_score_zero():
    gray = np.full((120, 160), 40, dtype=np.uint8)
    assert score_global(gray, gray) == 0.0
    assert score_detail(gray, gray, 8) == 0.0


def test_scores_are_normalised_to_unit_range():
    black = np.zeros((120, 160), dtype=np.uint8)
    white = np.full((120, 160), 255, dtype=np.uint8)
    assert 0.0 <= score_global(black, white) <= 1.0
    assert 0.0 <= score_detail(black, white, 8) <= 1.0


def test_global_score_grows_with_change_magnitude():
    base = np.zeros((120, 160), dtype=np.uint8)
    small = base.copy(); small[0:10, 0:10] = 255
    large = base.copy(); large[0:60, 0:80] = 255
    assert score_global(base, small) < score_global(base, large)


def test_detail_score_beats_global_on_small_localised_motion():
    """The whole point of `detail` mode: catch a blink, not just a pan."""
    base = np.zeros((240, 320), dtype=np.uint8)
    moved = base.copy()
    moved[10:30, 10:30] = 255  # ~0.8% of the frame
    assert score_detail(base, moved, 8) > score_global(base, moved) * 3


def test_detail_score_is_symmetric():
    a = np.zeros((120, 160), dtype=np.uint8)
    b = a.copy(); b[10:40, 10:40] = 200
    assert score_detail(a, b, 8) == pytest.approx(score_detail(b, a, 8))


def test_detail_score_handles_grid_larger_than_frame():
    a = np.zeros((16, 16), dtype=np.uint8)
    b = a.copy(); b[0:4, 0:4] = 255
    assert score_detail(a, b, 32) > 0.0  # must not divide by zero


# --------------------------------------------------------------------------
# compute_motion_scores
# --------------------------------------------------------------------------

def test_missing_video_raises(tmp_path):
    with pytest.raises((FileNotFoundError, RuntimeError)):
        compute_motion_scores(tmp_path / "nope.avi", cfg())


def test_score_count_matches_frame_count(make_video):
    path = make_video(n_frames=40, motion_frames=(10, 11, 12))
    scores, _fps = compute_motion_scores(path, cfg())
    assert len(scores) == 40, "one score per frame"


def test_first_frame_scores_zero(make_video):
    path = make_video(n_frames=20, motion_frames=(5,))
    scores, _ = compute_motion_scores(path, cfg())
    assert scores[0] == 0.0


def test_fps_is_read_from_the_file(make_video):
    path = make_video(n_frames=20, fps=24.0)
    _, fps = compute_motion_scores(path, cfg())
    assert fps == pytest.approx(24.0, abs=0.5)


def test_static_video_scores_near_zero(make_video):
    path = make_video(n_frames=30, motion_frames=())
    scores, _ = compute_motion_scores(path, cfg())
    assert max(scores) < 0.01, f"static clip should not register motion, peak={max(scores)}"


def test_motion_lands_on_the_frames_that_actually_moved(make_video):
    """Scores must spike on the injected frames and nowhere else."""
    moving = {10, 11, 12, 25, 26}
    path = make_video(n_frames=40, motion_frames=tuple(sorted(moving)))
    scores, _ = compute_motion_scores(path, cfg())

    hot = {i for i, s in enumerate(scores) if s > 0.02}
    assert moving <= hot, f"missed motion on frames {sorted(moving - hot)}"
    assert not (hot - moving), f"false motion on frames {sorted(hot - moving)}"


def test_end_to_end_video_to_segments(make_video):
    """A video with one clear burst yields exactly one segment covering it."""
    from Stages.frame_detect import detect_motion_segments

    path = make_video(n_frames=60, motion_frames=tuple(range(20, 30)))
    c = cfg(sensitivity=0.02, min_segment_frames=4, merge_gap_frames=2)
    scores, _ = compute_motion_scores(path, c)
    segments = detect_motion_segments(scores, c)

    assert len(segments) == 1, [(s.start, s.end) for s in segments]
    assert segments[0].start == 20
    assert segments[0].end == 29


def test_global_mode_runs_end_to_end(make_video):
    path = make_video(n_frames=30, motion_frames=(15,))
    scores, _ = compute_motion_scores(path, cfg(motion_mode="global"))
    assert len(scores) == 30
    assert scores[15] > 0.0


def test_sample_every_n_preserves_score_count(make_video):
    path = make_video(n_frames=40, motion_frames=(20,))
    scores, _ = compute_motion_scores(path, cfg(sample_every_n=4))
    assert len(scores) == 40, "skipping frames must not change the score array length"


def test_sample_every_n_keeps_scores_comparable_to_sensitivity(make_video):
    """Sub-sampling must not silently change what the sensitivity slider means.

    `compute_motion_scores` divides each score by the number of frames grabbed,
    so the same clip at the same sensitivity yields far weaker scores when
    `sample_every_n > 1` -- the slider quietly stops meaning the same thing.
    """
    path = make_video(n_frames=60, motion_frames=tuple(range(20, 40)))
    full, _ = compute_motion_scores(path, cfg(sample_every_n=1))
    subsampled, _ = compute_motion_scores(path, cfg(sample_every_n=4))

    assert max(subsampled) > max(full) * 0.5, (
        f"sub-sampling deflated peak score from {max(full):.4f} to "
        f"{max(subsampled):.4f}; the sensitivity threshold no longer applies"
    )
