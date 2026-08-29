"""Awkward clips. None of these should crash, hang, or corrupt the output."""

from __future__ import annotations

import numpy as np
import pytest

from Pipeline.config import Eternal2xConfig
from Pipeline.dedupe import plan_from_scores
from Pipeline.render import SourceError, analyse_video, render_plan


def cfg(**kw):
    c = Eternal2xConfig(upscale_enabled=False)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def roundtrip(src, tmp_path, read_frames, name="out.avi", **kw):
    c = cfg(**kw)
    plan, _w, _h = analyse_video(src, c)
    result = render_plan(src, plan, tmp_path / name, c)
    return plan, result, read_frames(result.output)


# --------------------------------------------------------------------------
# tiny clips
# --------------------------------------------------------------------------

def test_single_frame_clip(make_anime, tmp_path, read_frames):
    plan, _r, frames = roundtrip(make_anime(holds=(1,)), tmp_path, read_frames)
    assert plan.source_frames == 1
    assert len(frames) == 1


def test_two_identical_frames(make_anime, tmp_path, read_frames):
    plan, _r, frames = roundtrip(make_anime(holds=(2,)), tmp_path, read_frames)
    assert plan.source_frames == 2
    assert len(frames) == 2


def test_two_different_frames(make_anime, tmp_path, read_frames):
    plan, _r, frames = roundtrip(make_anime(holds=(1, 1)), tmp_path, read_frames)
    assert len(frames) == 2


def test_three_frames_on_twos(make_anime, tmp_path, read_frames):
    _plan, _r, frames = roundtrip(make_anime(holds=(2, 1)), tmp_path, read_frames)
    assert len(frames) == 3


# --------------------------------------------------------------------------
# degenerate content
# --------------------------------------------------------------------------

def test_a_completely_static_shot_is_a_noop(make_anime, tmp_path):
    """One drawing held for the whole clip has no motion to recover."""
    plan, _w, _h = analyse_video(make_anime(holds=(30,)), cfg())
    assert plan.unique_drawings == 1
    assert plan.is_noop, "a static shot should not be rebuilt"


def test_a_black_clip_does_not_crash(tmp_path, read_frames):
    import cv2
    src = tmp_path / "black.avi"
    writer = cv2.VideoWriter(str(src), cv2.VideoWriter_fourcc(*"FFV1"), 24.0, (160, 120))
    for _ in range(20):
        writer.write(np.zeros((120, 160, 3), np.uint8))
    writer.release()

    plan, _w, _h = analyse_video(src, cfg())
    assert plan.is_noop


def test_pure_noise_is_treated_as_all_unique(tmp_path):
    """Every frame differs, so there is nothing to de-duplicate."""
    import cv2
    rng = np.random.default_rng(11)
    src = tmp_path / "noise.avi"
    writer = cv2.VideoWriter(str(src), cv2.VideoWriter_fourcc(*"FFV1"), 24.0, (160, 120))
    for _ in range(20):
        writer.write(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8))
    writer.release()

    plan, _w, _h = analyse_video(src, cfg())
    assert plan.base_hold == 1
    assert plan.is_noop


# --------------------------------------------------------------------------
# awkward dimensions and rates
# --------------------------------------------------------------------------

@pytest.mark.parametrize("size", [(64, 48), (161, 121), (320, 180)])
def test_unusual_dimensions_are_preserved(make_anime, tmp_path, read_frames, size):
    """Output must match whatever the source actually decoded to.

    Video codecs quietly round odd dimensions to even, so the source may not be
    the size that was requested. What matters is that the rebuild does not
    change it again.
    """
    import cv2
    src = make_anime(holds=(2,) * 6, size=size, step=3)
    cap = cv2.VideoCapture(str(src))
    source_size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                   int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()

    _plan, result, frames = roundtrip(src, tmp_path, read_frames, name=f"o{size[0]}.avi")
    assert len(frames) == 12
    assert (result.width, result.height) == source_size


def test_the_lossless_sequence_keeps_odd_dimensions_exactly(tmp_path, read_frames):
    """PNG has no even-dimension requirement, which video codecs do."""
    import cv2
    frames = []
    rng = np.random.default_rng(3)
    tex = cv2.GaussianBlur(rng.integers(0, 255, (121, 161), dtype=np.uint8), (0, 0), 2.0)
    for drawing in range(6):
        M = np.float32([[1, 0, drawing * 3], [0, 1, 0]])
        shifted = cv2.warpAffine(np.dstack([tex] * 3), M, (161, 121),
                                 borderMode=cv2.BORDER_REPLICATE)
        frames.extend([shifted] * 2)

    seq_in = tmp_path / "src"
    seq_in.mkdir()
    for i, frame in enumerate(frames):
        cv2.imwrite(str(seq_in / f"f{i:04d}.png"), frame)

    # Feed the sequence back through as a video the analyser can open.
    src = tmp_path / "odd.avi"
    writer = cv2.VideoWriter(str(src), cv2.VideoWriter_fourcc(*"FFV1"), 24.0, (161, 121))
    for frame in frames:
        writer.write(frame)
    writer.release()

    c = cfg()
    plan, _w, _h = analyse_video(src, c)
    result = render_plan(src, plan, tmp_path / "seq_out", c)
    assert result.is_sequence
    out = read_frames(result.output)
    assert len(out) == 12
    # Whatever the decoder handed us, the sequence writes it back unchanged.
    assert out[0].shape[:2] == (result.height, result.width)


@pytest.mark.parametrize("fps", [12.0, 23.976, 25.0, 29.97, 60.0])
def test_various_frame_rates_are_preserved(make_anime, tmp_path, read_frames, fps):
    src = make_anime(holds=(2,) * 6, fps=fps)
    plan, result, _frames = roundtrip(src, tmp_path, read_frames, name=f"o{int(fps)}.avi")
    assert result.fps == pytest.approx(fps, rel=0.02)


def test_upscale_doubles_whatever_the_source_is(make_anime, tmp_path, read_frames):
    import cv2
    src = make_anime(holds=(2,) * 4, size=(162, 122), step=3)
    cap = cv2.VideoCapture(str(src))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    _plan, result, frames = roundtrip(src, tmp_path, read_frames,
                                      upscale_enabled=True, upscale_factor=2)
    assert (result.width, result.height) == (w * 2, h * 2)
    assert frames[0].shape[:2] == (h * 2, w * 2)


# --------------------------------------------------------------------------
# unusual timing
# --------------------------------------------------------------------------

def test_very_long_hold_among_short_ones(make_anime, tmp_path, read_frames):
    src = make_anime(holds=(2, 2, 40, 2, 2))
    plan, _r, frames = roundtrip(src, tmp_path, read_frames)
    assert plan.base_hold == 2
    assert len(frames) == plan.source_frames


def test_wildly_mixed_timing(make_anime, tmp_path, read_frames):
    src = make_anime(holds=(1, 5, 2, 3, 1, 8, 2, 2, 4))
    plan, _r, frames = roundtrip(src, tmp_path, read_frames)
    assert len(frames) == plan.source_frames


def test_a_clip_that_is_one_long_hold_then_motion(make_anime, tmp_path, read_frames):
    src = make_anime(holds=(20, 2, 2, 2, 2))
    plan, _r, frames = roundtrip(src, tmp_path, read_frames)
    assert len(frames) == plan.source_frames


def test_on_threes_with_a_stray_two(make_anime, tmp_path, read_frames):
    src = make_anime(holds=(3, 3, 2, 3, 3, 3))
    plan, _r, _frames = roundtrip(src, tmp_path, read_frames)
    assert plan.base_hold == 3


# --------------------------------------------------------------------------
# thresholds
# --------------------------------------------------------------------------

def test_an_absurdly_high_threshold_finds_one_drawing(make_anime, tmp_path):
    plan, _w, _h = analyse_video(make_anime(holds=(2,) * 10),
                                 cfg(duplicate_threshold=0.99))
    assert plan.unique_drawings == 1


def test_a_zero_threshold_treats_everything_as_unique(make_anime, tmp_path):
    plan, _w, _h = analyse_video(make_anime(holds=(2,) * 10),
                                 cfg(duplicate_threshold=0.0))
    assert plan.is_noop


def test_forcing_a_hold_larger_than_the_clip(make_anime, tmp_path, read_frames):
    src = make_anime(holds=(2, 2))
    c = cfg(force_base_hold=99)
    plan, _w, _h = analyse_video(src, c)
    result = render_plan(src, plan, tmp_path / "o.avi", c)
    assert result.frames_written == plan.source_frames


# --------------------------------------------------------------------------
# broken input
# --------------------------------------------------------------------------

def test_a_missing_file(tmp_path):
    with pytest.raises(SourceError):
        analyse_video(tmp_path / "nope.avi", cfg())


def test_a_file_that_is_not_a_video(tmp_path):
    junk = tmp_path / "notavideo.avi"
    junk.write_bytes(b"this is not a video" * 100)
    with pytest.raises(SourceError):
        analyse_video(junk, cfg())


def test_an_empty_file(tmp_path):
    empty = tmp_path / "empty.avi"
    empty.write_bytes(b"")
    with pytest.raises(SourceError):
        analyse_video(empty, cfg())


def test_planning_with_no_scores():
    plan = plan_from_scores([], 24.0, threshold=0.004)
    assert plan.source_frames == 0
    assert plan.output_frames == 0
    assert plan.stretch == 1.0
