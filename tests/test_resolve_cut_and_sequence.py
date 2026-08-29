"""Sequence stage: cut the clip at markers, then shrink each piece to one frame.

Two layers here:
  1. strict=True  -- the real Resolve API surface. Proves what happens live.
  2. strict=False -- split/resize assumed to work. Proves the stage's own logic.
"""

from __future__ import annotations

import sys

import pytest

from Stages import resolve_cut_and_sequence as rcs


def run_main(monkeypatch, argv=()):
    monkeypatch.setattr(sys, "argv", ["resolve_cut_and_sequence"] + list(argv))
    rcs.main()


def mark(item, frames, prefix="[DSU] seg"):
    for i, f in enumerate(frames):
        item.AddMarker(f, "Blue", f"{prefix} {i:03d}", "", 1, "")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def test_markers_to_frames_sorts_and_dedupes():
    assert rcs._markers_to_frames({30: {}, 10: {}, 20: {}}) == [10, 20, 30]


def test_markers_to_frames_skips_unparseable_keys():
    assert rcs._markers_to_frames({"10": {}, "abc": {}, 5: {}}) == [5, 10]


def test_markers_to_frames_on_empty():
    assert rcs._markers_to_frames({}) == []
    assert rcs._markers_to_frames(None) == []


# --------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------

def test_no_markers_is_a_clean_no_op(monkeypatch, install_fake_resolve, capsys):
    install_fake_resolve([(0, 100)])
    run_main(monkeypatch)
    assert "No markers found" in capsys.readouterr().out


def test_markers_outside_the_clip_are_ignored(monkeypatch, install_fake_resolve, capsys):
    """A marker at frame 0 or at the clip's last frame cannot produce a cut."""
    _r, _tl, items, _ = install_fake_resolve([(0, 50)], strict=False)
    mark(items[0], [0, 49, 50, 200])
    run_main(monkeypatch)
    assert "No valid cut frames" in capsys.readouterr().out


def test_raises_outside_resolve(no_resolve):
    with pytest.raises(RuntimeError, match="Could not import DaVinciResolveScript"):
        rcs._get_resolve()


# --------------------------------------------------------------------------
# what actually happens inside real Resolve
# --------------------------------------------------------------------------

def test_split_reports_failure_against_the_real_api_surface(install_fake_resolve):
    """Resolve exposes no way to split a timeline clip from Python.

    `_split_at_frame` probes `Timeline.SplitClip` / `Timeline.SplitClips`, neither
    of which exists in the Resolve scripting API. Against the real surface every
    split silently reports False.
    """
    _r, timeline, items, _ = install_fake_resolve([(0, 100)], strict=True)
    assert rcs._split_at_frame(timeline, items[0], 50) is True, (
        "no working split path exists on the real Resolve API, so Sequence "
        "cannot cut anything -- the timeline is left untouched"
    )


def test_one_frame_resize_against_the_real_api_surface(install_fake_resolve):
    """TimelineItem has no SetEnd / SetEndFrame / SetClipProperty in Resolve."""
    _r, _tl, items, _ = install_fake_resolve([(0, 100)], strict=True)
    assert rcs._set_duration_one_frame(items[0]) is True, (
        "TimelineItem exposes none of SetEnd/SetEndFrame/SetClipProperty in "
        "Resolve, so clips are never shrunk to one frame"
    )


def test_sequence_end_to_end_on_the_real_api_surface(monkeypatch, install_fake_resolve,
                                                     capsys):
    """The headline check: run Sequence exactly as the button does, live-faithful."""
    _r, timeline, items, _ = install_fake_resolve([(0, 100)], strict=True)
    mark(items[0], [10, 20, 30, 40])
    run_main(monkeypatch)

    out = capsys.readouterr().out
    track = timeline.GetItemListInTrack("video", 1)
    assert len(track) == 5, (
        f"expected 4 cuts to yield 5 clips, timeline still has {len(track)}. "
        f"Stage reported: {out.strip()}"
    )


# --------------------------------------------------------------------------
# stage logic, assuming the API calls land
# --------------------------------------------------------------------------

def test_splits_at_every_interior_marker(monkeypatch, install_fake_resolve, capsys):
    _r, timeline, items, _ = install_fake_resolve([(0, 100)], strict=False)
    mark(items[0], [10, 20, 30])
    run_main(monkeypatch)

    assert timeline.split_calls == [10, 20, 30]
    assert "split ok: 3" in capsys.readouterr().out


def test_marker_frames_are_offset_by_clip_start(monkeypatch, install_fake_resolve):
    """Clip markers are clip-relative; cuts are absolute timeline frames."""
    _r, timeline, items, _ = install_fake_resolve([(0, 100)], strict=False)
    # Put the clip at timeline frame 500 with markers at clip-relative 10/20.
    items[0]._start = 500
    timeline._tracks[1] = [items[0]]
    mark(items[0], [10, 20])
    run_main(monkeypatch)

    assert timeline.split_calls == [510, 520], (
        f"cuts landed at {timeline.split_calls}; markers must be mapped through "
        "the clip's timeline start"
    )


def test_every_resulting_clip_becomes_one_frame(monkeypatch, install_fake_resolve, capsys):
    """The stated purpose of Sequence: 1-frame segments for interpolation control."""
    _r, timeline, items, _ = install_fake_resolve([(0, 100)], strict=False)
    mark(items[0], [25, 50, 75])
    run_main(monkeypatch)

    durations = [i.GetDuration() for i in timeline.GetItemListInTrack("video", 1)]
    assert durations == [1, 1, 1, 1], (
        f"clip durations after Sequence: {durations}; all should be 1. "
        f"Stage reported: {capsys.readouterr().out.strip()}"
    )


def test_does_not_touch_clips_from_other_media(monkeypatch, install_fake_resolve):
    """A neighbouring clip from a different source must be left alone."""
    from tests.fake_resolve import FakeMediaPoolItem, FakeTimelineItem

    _r, timeline, items, _mpi = install_fake_resolve([(0, 100)], strict=False)
    other_mpi = FakeMediaPoolItem(name="other.mov", file_path="/media/other.mov")
    neighbour = FakeTimelineItem(100, 60, other_mpi, strict=False)
    timeline.add_item(neighbour, track=1)

    mark(items[0], [25, 50])
    run_main(monkeypatch)

    assert neighbour.GetDuration() == 60, "an unrelated clip was resized"


def test_reports_counts_accurately(monkeypatch, install_fake_resolve, capsys):
    _r, _tl, items, _ = install_fake_resolve([(0, 100)], strict=False)
    mark(items[0], [10, 20, 30])
    run_main(monkeypatch)
    out = capsys.readouterr().out
    assert "Cut at 3 markers" in out
    assert "split ok: 3" in out


def test_duplicate_markers_produce_one_cut(monkeypatch, install_fake_resolve):
    _r, timeline, items, _ = install_fake_resolve([(0, 100)], strict=False)
    mark(items[0], [30])
    run_main(monkeypatch)
    assert timeline.split_calls == [30]
