"""Regroup stage: close gaps so the 1-frame segments form a continuous sequence."""

from __future__ import annotations

import sys

import pytest

from Stages import resolve_regroup as rg


def run_main(monkeypatch, argv=()):
    monkeypatch.setattr(sys, "argv", ["resolve_regroup"] + list(argv))
    rg.main()


def layout(timeline, track=1):
    return [(i.GetStart(), i.GetDuration())
            for i in timeline.GetItemListInTrack("video", track)]


# --------------------------------------------------------------------------
# gap maths
# --------------------------------------------------------------------------

def test_gap_map_on_a_contiguous_track():
    clips = [(0, 10, None), (10, 10, None), (20, 10, None)]
    assert rg._gap_map(clips) == []


def test_gap_map_finds_each_gap():
    clips = [(0, 10, None), (15, 10, None), (30, 10, None)]
    # gap of 5 before frame 15, gap of 5 before frame 30
    assert rg._gap_map(clips) == [(15, 5), (30, 5)]


def test_gap_map_ignores_a_non_zero_start():
    """A track starting at frame 100 has no leading gap to close."""
    clips = [(100, 10, None), (120, 10, None)]
    assert rg._gap_map(clips) == [(120, 10)]


def test_shift_frame_before_any_gap_is_unchanged():
    assert rg._shift_frame(5, [(15, 5), (30, 5)]) == 5


def test_shift_frame_after_gaps_accumulates():
    gaps = [(15, 5), (30, 5)]
    assert rg._shift_frame(20, gaps) == 15   # one gap of 5 removed
    assert rg._shift_frame(35, gaps) == 25   # both gaps removed


def test_shift_frame_with_no_gaps():
    assert rg._shift_frame(42, []) == 42


# --------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------

def test_raises_outside_resolve(no_resolve):
    with pytest.raises(RuntimeError, match="Could not import DaVinciResolveScript"):
        rg._get_resolve()


def test_empty_track_is_a_clean_no_op(monkeypatch, install_fake_resolve, capsys):
    from tests.fake_resolve import (FakeBmdModule, FakeProject, FakeProjectManager,
                                    FakeResolve, FakeTimeline)
    monkeypatch.setitem(
        sys.modules, "DaVinciResolveScript",
        FakeBmdModule(FakeResolve(FakeProjectManager(FakeProject(FakeTimeline())))))
    run_main(monkeypatch)
    assert "No clips found" in capsys.readouterr().out


# --------------------------------------------------------------------------
# what actually happens inside real Resolve
# --------------------------------------------------------------------------

def test_set_start_against_the_real_api_surface(install_fake_resolve):
    """Resolve's TimelineItem has no SetStart / SetStartFrame."""
    _r, _tl, items, _ = install_fake_resolve([(0, 10)], strict=True)
    assert rg._safe_set_start(items[0], 5) is True, (
        "TimelineItem exposes neither SetStart nor SetStartFrame in Resolve, so "
        "Regroup can never move a clip"
    )


def test_regroup_end_to_end_on_the_real_api_surface(monkeypatch, install_fake_resolve,
                                                    capsys):
    """Run Regroup exactly as the button does, against the live API surface."""
    _r, timeline, _items, _ = install_fake_resolve(
        [(0, 5), (20, 5), (40, 5)], strict=True)
    run_main(monkeypatch)

    out = capsys.readouterr().out
    assert layout(timeline) == [(0, 5), (5, 5), (10, 5)], (
        f"timeline after Regroup: {layout(timeline)}; gaps were not closed. "
        f"Stage reported: {out.strip()}"
    )


# --------------------------------------------------------------------------
# stage logic, assuming SetStart lands
# --------------------------------------------------------------------------

def test_closes_all_gaps(monkeypatch, install_fake_resolve):
    _r, timeline, _items, _ = install_fake_resolve(
        [(0, 5), (20, 5), (40, 5)], strict=False)
    run_main(monkeypatch)
    assert layout(timeline) == [(0, 5), (5, 5), (10, 5)]


def test_already_contiguous_track_is_left_alone(monkeypatch, install_fake_resolve, capsys):
    _r, timeline, _items, _ = install_fake_resolve(
        [(0, 5), (5, 5), (10, 5)], strict=False)
    run_main(monkeypatch)
    assert layout(timeline) == [(0, 5), (5, 5), (10, 5)]
    assert "moved 0" in capsys.readouterr().out


def test_preserves_the_track_start_offset(monkeypatch, install_fake_resolve):
    """Regrouping must not drag the sequence back to frame 0."""
    _r, timeline, _items, _ = install_fake_resolve(
        [(100, 5), (120, 5), (140, 5)], strict=False)
    run_main(monkeypatch)
    assert layout(timeline) == [(100, 5), (105, 5), (110, 5)]


def test_one_frame_segments_pack_tightly(monkeypatch, install_fake_resolve):
    """The realistic post-Sequence case: many 1-frame clips with gaps between."""
    clips = [(i * 10, 1) for i in range(12)]
    _r, timeline, _items, _ = install_fake_resolve(clips, strict=False)
    run_main(monkeypatch)
    assert layout(timeline) == [(i, 1) for i in range(12)]


def test_reports_how_many_clips_moved(monkeypatch, install_fake_resolve, capsys):
    _r, _tl, _items, _ = install_fake_resolve([(0, 5), (20, 5), (40, 5)], strict=False)
    run_main(monkeypatch)
    out = capsys.readouterr().out
    assert "Regrouped 3 clips" in out
    assert "moved 2" in out


def test_track_flag_selects_the_track(monkeypatch, install_fake_resolve):
    from tests.fake_resolve import FakeTimelineItem
    _r, timeline, _items, mpi = install_fake_resolve([(0, 5), (20, 5)], strict=False)
    v2 = FakeTimelineItem(0, 5, mpi, strict=False)
    v2b = FakeTimelineItem(30, 5, mpi, strict=False)
    timeline.add_item(v2, track=2)
    timeline.add_item(v2b, track=2)

    run_main(monkeypatch, ["--track", "2"])

    assert layout(timeline, 2) == [(0, 5), (5, 5)], "track 2 should have been regrouped"
    assert layout(timeline, 1) == [(0, 5), (20, 5)], "track 1 should be untouched"


# --------------------------------------------------------------------------
# markers must follow the clips
# --------------------------------------------------------------------------

def test_dsu_markers_shift_with_the_clips(monkeypatch, install_fake_resolve):
    """If markers do not follow, Upscale gates interpolation on the wrong frames."""
    _r, timeline, _items, _ = install_fake_resolve(
        [(0, 5), (20, 5), (40, 5)], strict=False)
    timeline.AddMarker(20, "Blue", "[DSU] seg 001", "", 5, "")
    timeline.AddMarker(40, "Blue", "[DSU] seg 002", "", 5, "")

    run_main(monkeypatch)

    assert sorted(timeline.GetMarkers()) == [5, 10], (
        f"markers at {sorted(timeline.GetMarkers())}; they should track the clips "
        "to 5 and 10"
    )


def test_non_dsu_markers_are_left_where_they_are(monkeypatch, install_fake_resolve):
    _r, timeline, _items, _ = install_fake_resolve(
        [(0, 5), (20, 5)], strict=False)
    timeline.AddMarker(20, "Green", "user marker", "", 1, "")
    run_main(monkeypatch)
    assert 20 in timeline.GetMarkers(), "a user's own marker was moved"


def test_marker_metadata_survives_the_move(monkeypatch, install_fake_resolve):
    _r, timeline, _items, _ = install_fake_resolve([(0, 5), (20, 5)], strict=False)
    timeline.AddMarker(20, "Red", "[DSU] seg 001", "len 5 frames", 5, "")
    run_main(monkeypatch)

    moved = timeline.GetMarkers()[5]
    assert moved["color"] == "Red"
    assert moved["note"] == "len 5 frames"
    assert moved["duration"] == 5


def test_marker_move_does_not_collide_when_shifting_left(monkeypatch,
                                                         install_fake_resolve):
    """Several markers shifting left in sequence must not overwrite each other."""
    clips = [(i * 10, 1) for i in range(6)]
    _r, timeline, _items, _ = install_fake_resolve(clips, strict=False)
    for i in range(1, 6):
        timeline.AddMarker(i * 10, "Blue", f"[DSU] seg {i:03d}", "", 1, "")

    run_main(monkeypatch)

    frames = sorted(timeline.GetMarkers())
    assert frames == [1, 2, 3, 4, 5], f"markers ended up at {frames}, expected 1..5"
