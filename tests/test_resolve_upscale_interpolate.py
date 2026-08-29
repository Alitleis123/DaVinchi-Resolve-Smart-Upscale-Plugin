"""Upscale + Interpolate: 2x on everything, optical flow only where there is motion."""

from __future__ import annotations

import sys

import pytest

from Stages import resolve_upscale_interpolate as up


def run_main(monkeypatch, argv=()):
    monkeypatch.setattr(sys, "argv", ["resolve_upscale_interpolate"] + list(argv))
    up.main()


def props_of(item):
    return dict(item.GetProperty())


# --------------------------------------------------------------------------
# range maths
# --------------------------------------------------------------------------

def test_overlaps():
    assert up._overlaps(0, 10, 5, 15)
    assert up._overlaps(5, 15, 0, 10)
    assert up._overlaps(0, 10, 10, 20), "touching at one frame counts as overlap"
    assert not up._overlaps(0, 10, 11, 20)
    assert not up._overlaps(11, 20, 0, 10)


def test_ranges_from_markers_uses_duration():
    markers = {10: {"name": "[DSU] seg 000", "duration": 5}}
    assert up._ranges_from_markers(markers, 0) == [(10, 14)]


def test_ranges_from_markers_applies_base_offset():
    markers = {10: {"name": "[DSU] seg 000", "duration": 5}}
    assert up._ranges_from_markers(markers, 100) == [(110, 114)]


def test_ranges_from_markers_are_sorted():
    markers = {
        30: {"name": "[DSU] c", "duration": 1},
        10: {"name": "[DSU] a", "duration": 1},
        20: {"name": "[DSU] b", "duration": 1},
    }
    assert up._ranges_from_markers(markers, 0) == [(10, 10), (20, 20), (30, 30)]


def test_ranges_from_markers_skips_foreign_markers():
    markers = {
        10: {"name": "[DSU] seg 000", "duration": 5},
        50: {"name": "my own marker", "duration": 5},
    }
    assert up._ranges_from_markers(markers, 0) == [(10, 14)]


def test_ranges_from_markers_treats_zero_duration_as_one_frame():
    assert up._ranges_from_markers({7: {"name": "[DSU] x", "duration": 0}}, 0) == [(7, 7)]


def test_ranges_from_markers_on_empty():
    assert up._ranges_from_markers({}, 0) == []
    assert up._ranges_from_markers(None, 0) == []


def test_ranges_from_markers_ignores_markers_without_a_name():
    """A marker with no name is not a [DSU] marker and must not gate interpolation."""
    markers = {10: {"duration": 5}, 20: {"name": None, "duration": 5}}
    assert up._ranges_from_markers(markers, 0) == [], (
        "markers whose name is missing or non-string slip through the [DSU] filter"
    )


# --------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------

def test_raises_outside_resolve(no_resolve):
    with pytest.raises(RuntimeError, match="Could not import DaVinciResolveScript"):
        up._get_resolve()


def test_no_markers_anywhere_is_a_clean_no_op(monkeypatch, install_fake_resolve, capsys):
    install_fake_resolve([(0, 100)], strict=False)
    run_main(monkeypatch)
    assert "No [DSU] markers found" in capsys.readouterr().out


# --------------------------------------------------------------------------
# what actually happens inside real Resolve
# --------------------------------------------------------------------------

def test_super_scale_value_is_one_resolve_accepts(install_fake_resolve):
    """Resolve's "Super Scale" takes 1/2/3/4/Auto. "2x" is rejected."""
    _r, _tl, items, mpi = install_fake_resolve([(0, 10)], strict=True)
    assert up._set_clip_property(items[0], "Super Scale", "2x") is True, (
        'Resolve rejects "2x" for Super Scale; the accepted value for 2x is "2". '
        f"Attempted writes: {mpi.set_calls}"
    )


def test_upscale_end_to_end_on_the_real_api_surface(monkeypatch, install_fake_resolve,
                                                    capsys):
    _r, timeline, items, mpi = install_fake_resolve([(0, 1), (1, 1), (2, 1)], strict=True)
    timeline.AddMarker(0, "Blue", "[DSU] seg 000", "", 1, "")
    run_main(monkeypatch)

    out = capsys.readouterr().out
    assert mpi.GetClipProperty("Super Scale") == "2", (
        f"Super Scale never took effect. Writes attempted: {mpi.set_calls}. "
        f"Stage reported: {out.strip()}"
    )


def test_interpolation_is_gated_per_clip_not_per_source(monkeypatch, install_fake_resolve,
                                                        capsys):
    """Every 1-frame segment shares one media pool item, so per-clip gating collapses.

    TimelineItem has no SetClipProperty in Resolve, so `_set_clip_property` falls
    through to the *media pool item* -- which all the segments share. Each write
    overwrites the last, and the final clip processed decides the retime mode for
    the entire source.
    """
    _r, timeline, items, mpi = install_fake_resolve(
        [(0, 1), (1, 1), (2, 1), (3, 1)], strict=True)
    # Motion on the first two clips only.
    timeline.AddMarker(0, "Blue", "[DSU] seg 000", "", 2, "")

    run_main(monkeypatch)

    retime_writes = [v for k, v in mpi.set_calls if k == "Retime Process"]
    assert len(set(retime_writes)) <= 1, (
        f"the shared media pool item received conflicting retime settings "
        f"{retime_writes}; per-clip interpolation gating cannot work when every "
        f"segment writes to the same source. Stage reported: "
        f"{capsys.readouterr().out.strip()}"
    )


# --------------------------------------------------------------------------
# stage logic, assuming per-clip properties land
# --------------------------------------------------------------------------

def test_every_clip_gets_upscaled(monkeypatch, install_fake_resolve, capsys):
    _r, timeline, items, _ = install_fake_resolve(
        [(0, 1), (1, 1), (2, 1)], strict=False)
    timeline.AddMarker(0, "Blue", "[DSU] seg 000", "", 1, "")
    run_main(monkeypatch)

    assert all(props_of(i).get("Super Scale") for i in items)
    assert "Upscale applied to 3 clips" in capsys.readouterr().out


def test_optical_flow_only_on_clips_inside_a_marker_range(monkeypatch,
                                                          install_fake_resolve, capsys):
    """The core promise: motion -> Optical Flow, static -> Nearest."""
    _r, timeline, items, _ = install_fake_resolve(
        [(0, 1), (1, 1), (2, 1), (3, 1), (4, 1)], strict=False)
    # Motion covers timeline frames 1-2 only.
    timeline.AddMarker(1, "Blue", "[DSU] seg 000", "", 2, "")

    run_main(monkeypatch)

    modes = [props_of(i).get("Retime Process") for i in items]
    assert modes == ["Nearest", "Optical Flow", "Optical Flow", "Nearest", "Nearest"], (
        f"retime modes: {modes}. Stage reported: {capsys.readouterr().out.strip()}"
    )


def test_counts_are_reported(monkeypatch, install_fake_resolve, capsys):
    _r, timeline, items, _ = install_fake_resolve(
        [(0, 1), (1, 1), (2, 1), (3, 1)], strict=False)
    timeline.AddMarker(0, "Blue", "[DSU] seg 000", "", 2, "")
    run_main(monkeypatch)
    out = capsys.readouterr().out
    assert "Interpolation on: 2, off: 2" in out, out


def test_clip_markers_take_priority_over_timeline_markers(monkeypatch,
                                                          install_fake_resolve):
    _r, timeline, items, _ = install_fake_resolve([(0, 4)], strict=False)
    items[0].AddMarker(0, "Blue", "[DSU] on clip", "", 2, "")
    timeline.AddMarker(3, "Blue", "[DSU] on timeline", "", 1, "")

    run_main(monkeypatch)
    assert props_of(items[0]).get("Retime Process") == "Optical Flow"


def test_falls_back_to_timeline_markers(monkeypatch, install_fake_resolve):
    _r, timeline, items, _ = install_fake_resolve([(0, 1), (5, 1)], strict=False)
    timeline.AddMarker(5, "Blue", "[DSU] seg 000", "", 1, "")

    run_main(monkeypatch)
    modes = [props_of(i).get("Retime Process") for i in items]
    assert modes == ["Nearest", "Optical Flow"]


def test_recomputes_from_video_when_there_are_no_markers(monkeypatch,
                                                         install_fake_resolve, make_video):
    """--video is the documented fallback when the timeline has no markers."""
    path = make_video(n_frames=40, motion_frames=tuple(range(10, 20)))
    _r, _tl, items, _ = install_fake_resolve([(i, 1) for i in range(40)], strict=False)

    run_main(monkeypatch, ["--video", str(path), "--sensitivity", "0.02"])

    modes = [props_of(i).get("Retime Process") for i in items]
    assert "Optical Flow" in modes, "recompute produced no motion ranges"
    assert modes[15] == "Optical Flow"
    assert modes[0] == "Nearest"


def test_track_flag_is_honoured(monkeypatch, install_fake_resolve):
    from tests.fake_resolve import FakeTimelineItem
    _r, timeline, items, mpi = install_fake_resolve([(0, 1)], strict=False)
    v2 = FakeTimelineItem(0, 1, mpi, strict=False)
    timeline.add_item(v2, track=2)
    timeline.AddMarker(0, "Blue", "[DSU] seg 000", "", 1, "")

    run_main(monkeypatch, ["--track", "2"])

    assert props_of(v2).get("Super Scale"), "track 2 clip was not processed"
    assert not props_of(items[0]).get("Super Scale"), "track 1 clip should be untouched"
