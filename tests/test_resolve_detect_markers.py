"""Detect stage: places [DSU] markers in Resolve. Run headlessly against the fake."""

from __future__ import annotations

import json
import sys

import pytest

from Stages import resolve_detect_markers as rdm


def run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["resolve_detect_markers"] + argv)
    rdm.main()


def write_segments(tmp_path, segments, fps=30.0):
    path = tmp_path / "segments.json"
    path.write_text(json.dumps({
        "settings": {"sensitivity": 0.2, "min_segment_frames": 4, "merge_gap_frames": 2},
        "fps": fps,
        "frame_count": 100,
        "segments": segments,
    }))
    return path


SEGS = [
    {"start": 10, "end": 19, "length": 10},
    {"start": 40, "end": 45, "length": 6},
]


# --------------------------------------------------------------------------
# environment guards
# --------------------------------------------------------------------------

def test_raises_a_clear_error_outside_resolve(no_resolve):
    with pytest.raises(RuntimeError, match="Could not import DaVinciResolveScript"):
        rdm._get_resolve()


def test_raises_when_resolve_has_no_project(monkeypatch, tmp_path, install_fake_resolve):
    from tests.fake_resolve import FakeBmdModule, FakeProjectManager, FakeResolve
    monkeypatch.setitem(sys.modules, "DaVinciResolveScript",
                        FakeBmdModule(FakeResolve(FakeProjectManager(None))))
    seg_file = write_segments(tmp_path, SEGS)
    with pytest.raises(RuntimeError, match="No active project"):
        run_main(monkeypatch, ["--segments", str(seg_file)])


def test_raises_when_project_has_no_timeline(monkeypatch, tmp_path):
    from tests.fake_resolve import (FakeBmdModule, FakeProject, FakeProjectManager,
                                    FakeResolve)
    monkeypatch.setitem(sys.modules, "DaVinciResolveScript",
                        FakeBmdModule(FakeResolve(FakeProjectManager(FakeProject(None)))))
    seg_file = write_segments(tmp_path, SEGS)
    with pytest.raises(RuntimeError, match="No active timeline"):
        run_main(monkeypatch, ["--segments", str(seg_file)])


# --------------------------------------------------------------------------
# target selection
# --------------------------------------------------------------------------

def test_picks_the_selected_clip_when_selection_api_exists(install_fake_resolve):
    _r, timeline, items, _ = install_fake_resolve([(0, 100), (100, 50)], strict=False,
                                                  selected_index=1)
    target, kind = rdm._pick_target(timeline)
    assert kind == "clip"
    assert target is items[1]


def test_falls_back_to_current_video_item(install_fake_resolve):
    """Resolve has no GetSelectedItems; the fallback path is the one that runs live."""
    _r, timeline, items, _ = install_fake_resolve([(0, 100)], strict=True)
    target, kind = rdm._pick_target(timeline)
    assert kind == "clip"
    assert target is items[0]


def test_falls_back_to_timeline_when_no_clip(install_fake_resolve):
    from tests.fake_resolve import FakeTimeline
    timeline = FakeTimeline(strict=True)
    target, kind = rdm._pick_target(timeline)
    assert kind == "timeline"
    assert target is timeline


# --------------------------------------------------------------------------
# marker placement
# --------------------------------------------------------------------------

def test_places_one_marker_per_segment(monkeypatch, tmp_path, install_fake_resolve, capsys):
    _r, _tl, items, _ = install_fake_resolve([(0, 100)])
    run_main(monkeypatch, ["--segments", str(write_segments(tmp_path, SEGS))])

    markers = items[0].GetMarkers()
    assert sorted(markers) == [10, 40]
    assert "Added 2 markers" in capsys.readouterr().out


def test_markers_carry_the_dsu_prefix_and_segment_range(monkeypatch, tmp_path,
                                                        install_fake_resolve):
    _r, _tl, items, _ = install_fake_resolve([(0, 100)])
    run_main(monkeypatch, ["--segments", str(write_segments(tmp_path, SEGS))])

    m = items[0].GetMarkers()[10]
    assert m["name"].startswith("[DSU]")
    assert "10-19" in m["name"]
    assert m["duration"] == 10, "marker duration must span the whole segment"
    assert "10 frames" in m["note"]


def test_marker_colour_is_configurable(monkeypatch, tmp_path, install_fake_resolve):
    _r, _tl, items, _ = install_fake_resolve([(0, 100)])
    run_main(monkeypatch, ["--segments", str(write_segments(tmp_path, SEGS)),
                           "--color", "Red"])
    assert items[0].GetMarkers()[10]["color"] == "Red"


def test_empty_segments_is_a_no_op(monkeypatch, tmp_path, install_fake_resolve, capsys):
    _r, _tl, items, _ = install_fake_resolve([(0, 100)])
    run_main(monkeypatch, ["--segments", str(write_segments(tmp_path, []))])
    assert items[0].GetMarkers() == {}
    assert "Nothing to mark" in capsys.readouterr().out


# --------------------------------------------------------------------------
# re-running Detect
# --------------------------------------------------------------------------

def test_rerun_replaces_old_dsu_markers_instead_of_stacking(monkeypatch, tmp_path,
                                                            install_fake_resolve, capsys):
    _r, _tl, items, _ = install_fake_resolve([(0, 100)])
    seg_file = write_segments(tmp_path, SEGS)
    run_main(monkeypatch, ["--segments", str(seg_file)])

    seg_file.write_text(json.dumps({"segments": [{"start": 60, "end": 70, "length": 11}]}))
    capsys.readouterr()
    run_main(monkeypatch, ["--segments", str(seg_file)])

    out = capsys.readouterr().out
    assert sorted(items[0].GetMarkers()) == [60], "old [DSU] markers should be gone"
    assert "Removed 2 old markers" in out


def test_rerun_preserves_the_users_own_markers(monkeypatch, tmp_path, install_fake_resolve):
    """A user's hand-placed markers must survive a re-Detect."""
    _r, _tl, items, _ = install_fake_resolve([(0, 100)])
    clip = items[0]
    clip.AddMarker(5, "Green", "my note", "keep me", 1, "")
    clip.AddMarker(80, "Yellow", "chapter 2", "", 1, "")

    run_main(monkeypatch, ["--segments", str(write_segments(tmp_path, SEGS))])

    markers = clip.GetMarkers()
    assert 5 in markers and 80 in markers, "user markers were deleted"
    assert markers[5]["name"] == "my note"


def test_marker_collision_with_a_user_marker_is_reported(monkeypatch, tmp_path,
                                                         install_fake_resolve, capsys):
    """Resolve refuses a second marker on an occupied frame; the count must reflect that."""
    _r, _tl, items, _ = install_fake_resolve([(0, 100)])
    items[0].AddMarker(10, "Green", "user marker", "", 1, "")

    run_main(monkeypatch, ["--segments", str(write_segments(tmp_path, SEGS))])

    out = capsys.readouterr().out
    assert "Added 1 markers" in out, (
        "a marker that Resolve rejected must not be counted as added; got: " + out.strip()
    )


# --------------------------------------------------------------------------
# frame mapping
# --------------------------------------------------------------------------

def test_markers_land_on_the_right_frames_for_a_trimmed_clip(monkeypatch, tmp_path,
                                                             install_fake_resolve):
    """Segment indices are source-media frames, so a trimmed clip must be offset.

    Detect analyses the *source file*, so segment 10 means source frame 10. The
    stage writes AddMarker(10) directly. On a clip trimmed to start at source
    frame 500, that marker should sit at source frame 510 -- not 10, which is
    outside the clip entirely.
    """
    _r, _tl, items, _ = install_fake_resolve([(0, 100, 500)])  # left_offset = 500
    clip = items[0]
    assert clip.GetLeftOffset() == 500

    run_main(monkeypatch, ["--segments", str(write_segments(tmp_path, SEGS))])

    placed = sorted(clip.GetMarkers())
    assert placed == [510, 540], (
        f"markers placed at {placed}; expected them offset by the clip's left offset "
        "(500). Detect ignores trim, so on a trimmed clip every marker is misplaced."
    )


def test_video_path_flow_computes_segments_directly(monkeypatch, install_fake_resolve,
                                                    make_video, capsys):
    """The Detect button's real path: --video, not --segments."""
    _r, _tl, items, _ = install_fake_resolve([(0, 60)])
    path = make_video(n_frames=60, motion_frames=tuple(range(20, 32)))

    run_main(monkeypatch, ["--video", str(path), "--sensitivity", "0.02"])

    markers = items[0].GetMarkers()
    assert markers, "Detect on a clip with obvious motion produced no markers"
    assert all(v["name"].startswith("[DSU]") for v in markers.values())
    assert "Added" in capsys.readouterr().out


def test_sensitivity_flag_changes_how_much_is_detected(monkeypatch, install_fake_resolve,
                                                       make_video):
    """The slider has to actually do something."""
    path = make_video(n_frames=60, motion_frames=tuple(range(10, 50)))

    _r, _tl, items_low, _ = install_fake_resolve([(0, 60)])
    run_main(monkeypatch, ["--video", str(path), "--sensitivity", "0.01"])
    low_count = len(items_low[0].GetMarkers())

    _r2, _tl2, items_high, _ = install_fake_resolve([(0, 60)])
    run_main(monkeypatch, ["--video", str(path), "--sensitivity", "0.95"])
    high_count = len(items_high[0].GetMarkers())

    assert low_count > 0
    assert high_count == 0, "a near-max sensitivity should suppress detection"
