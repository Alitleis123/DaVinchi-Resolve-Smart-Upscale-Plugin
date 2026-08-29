"""Segment detection: the math that decides where markers go."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from Pipeline.config import UpscaleConfig
from Stages.frame_detect import (
    Segment,
    detect_motion_segments,
    filter_short_segments,
    merge_close_segments,
    segments_to_dict,
)


def cfg(**kw) -> UpscaleConfig:
    c = UpscaleConfig()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def as_pairs(segments):
    return [(s.start, s.end) for s in segments]


# --------------------------------------------------------------------------
# Segment
# --------------------------------------------------------------------------

def test_segment_length_is_inclusive():
    assert Segment(0, 0).length == 1
    assert Segment(10, 14).length == 5


# --------------------------------------------------------------------------
# merge_close_segments
# --------------------------------------------------------------------------

def test_merge_empty():
    assert merge_close_segments([], 2) == []


def test_merge_joins_segments_within_gap():
    # gap between end=4 and start=6 is 1 frame -> merged at gap tolerance 2
    got = merge_close_segments([Segment(0, 4), Segment(6, 9)], 2)
    assert as_pairs(got) == [(0, 9)]


def test_merge_keeps_segments_beyond_gap():
    # gap between end=4 and start=10 is 5 frames -> left alone
    got = merge_close_segments([Segment(0, 4), Segment(10, 14)], 2)
    assert as_pairs(got) == [(0, 4), (10, 14)]


def test_merge_gap_boundary_is_inclusive():
    # gap == merge_gap_frames merges; gap == merge_gap_frames + 1 does not
    assert as_pairs(merge_close_segments([Segment(0, 4), Segment(7, 9)], 2)) == [(0, 9)]
    assert as_pairs(merge_close_segments([Segment(0, 4), Segment(8, 9)], 2)) == [(0, 4), (8, 9)]


def test_merge_chains_three_segments():
    got = merge_close_segments([Segment(0, 2), Segment(4, 6), Segment(8, 10)], 2)
    assert as_pairs(got) == [(0, 10)]


def test_merge_handles_nested_segment():
    # a fully-contained later segment must not shrink the merged range
    got = merge_close_segments([Segment(0, 20), Segment(5, 8)], 2)
    assert as_pairs(got) == [(0, 20)]


def test_merge_does_not_mutate_its_input():
    """merge_close_segments must not corrupt the caller's segment objects.

    It builds `merged = [segments[0]]` and then writes `last.end = ...`, which
    reaches back into the list the caller passed in.
    """
    original = [Segment(0, 4), Segment(6, 9)]
    snapshot = as_pairs(original)
    merge_close_segments(original, 2)
    assert as_pairs(original) == snapshot, (
        "merge_close_segments mutated the Segment objects it was given"
    )


# --------------------------------------------------------------------------
# filter_short_segments
# --------------------------------------------------------------------------

def test_filter_drops_short_keeps_exact_minimum():
    segs = [Segment(0, 2), Segment(10, 13), Segment(20, 40)]  # lengths 3, 4, 21
    got = filter_short_segments(segs, 4)
    assert as_pairs(got) == [(10, 13), (20, 40)]


def test_filter_with_zero_minimum_keeps_all():
    segs = [Segment(0, 0), Segment(5, 5)]
    assert len(filter_short_segments(segs, 0)) == 2


# --------------------------------------------------------------------------
# detect_motion_segments
# --------------------------------------------------------------------------

def test_detect_on_empty_scores():
    assert detect_motion_segments([], cfg()) == []


def test_detect_all_below_threshold():
    scores = [0.01] * 50
    assert detect_motion_segments(scores, cfg(sensitivity=0.2)) == []


def test_detect_all_above_threshold_is_one_segment():
    scores = [0.9] * 50
    got = detect_motion_segments(scores, cfg(sensitivity=0.2))
    assert as_pairs(got) == [(0, 49)]


def test_detect_threshold_is_inclusive():
    # score exactly == sensitivity counts as motion
    scores = [0.0] * 5 + [0.2] * 10 + [0.0] * 5
    got = detect_motion_segments(scores, cfg(sensitivity=0.2, min_segment_frames=4))
    assert as_pairs(got) == [(5, 14)]


def test_detect_segment_running_to_last_frame_is_closed():
    scores = [0.0] * 10 + [0.9] * 10
    got = detect_motion_segments(scores, cfg(sensitivity=0.2, min_segment_frames=4))
    assert as_pairs(got) == [(10, 19)]


def test_detect_filters_tiny_burst():
    # a 2-frame burst, below min_segment_frames=4, is dropped
    scores = [0.0] * 10 + [0.9] * 2 + [0.0] * 10
    got = detect_motion_segments(scores, cfg(sensitivity=0.2, min_segment_frames=4,
                                             merge_gap_frames=0))
    assert got == []


def test_detect_merges_then_filters_in_that_order():
    """Two 2-frame bursts one frame apart survive as a merged 5-frame segment.

    Order matters: filtering first would delete both bursts before they had a
    chance to merge.
    """
    scores = [0.0] * 5 + [0.9] * 2 + [0.0] + [0.9] * 2 + [0.0] * 5
    got = detect_motion_segments(scores, cfg(sensitivity=0.2, min_segment_frames=4,
                                             merge_gap_frames=2))
    assert as_pairs(got) == [(5, 9)]


def test_detect_multiple_separated_segments():
    scores = ([0.0] * 5 + [0.9] * 6) * 2 + [0.0] * 5
    got = detect_motion_segments(scores, cfg(sensitivity=0.2, min_segment_frames=4,
                                             merge_gap_frames=2))
    assert as_pairs(got) == [(5, 10), (16, 21)]


def test_lower_sensitivity_detects_at_least_as_much():
    """Documented contract: lower sensitivity = more motion detected."""
    scores = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45] * 4
    counts = []
    for sens in (0.05, 0.15, 0.25, 0.35, 0.45):
        segs = detect_motion_segments(scores, cfg(sensitivity=sens, min_segment_frames=1,
                                                  merge_gap_frames=0))
        counts.append(sum(s.length for s in segs))
    assert counts == sorted(counts, reverse=True), (
        f"raising sensitivity should not increase detected frames, got {counts}"
    )


def test_segments_to_dict_shape():
    got = segments_to_dict([Segment(3, 7)])
    assert got == [{"start": 3, "end": 7, "length": 5}]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def test_cli_scores_to_segments_json(tmp_path, repo_root):
    out = tmp_path / "segments.json"
    scores = ",".join(["0.0"] * 5 + ["0.9"] * 6 + ["0.0"] * 5)
    result = subprocess.run(
        [sys.executable, "-m", "Stages.frame_detect",
         "--scores", scores, "--out", str(out),
         "--sensitivity", "0.2", "--min_segment_frames", "4"],
        cwd=repo_root, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text())
    assert payload["frame_count"] == 16
    assert payload["segments"] == [{"start": 5, "end": 10, "length": 6}]
    assert payload["settings"]["sensitivity"] == 0.2


def test_cli_requires_a_source(repo_root):
    result = subprocess.run(
        [sys.executable, "-m", "Stages.frame_detect"],
        cwd=repo_root, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "one of the arguments" in result.stderr


def test_cli_writes_scores_out(tmp_path, repo_root):
    out = tmp_path / "segments.json"
    scores_out = tmp_path / "scores.json"
    result = subprocess.run(
        [sys.executable, "-m", "Stages.frame_detect",
         "--scores", "0.0,0.5,0.5,0.5,0.5,0.0",
         "--out", str(out), "--scores_out", str(scores_out)],
        cwd=repo_root, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(scores_out.read_text())["scores"] == [0.0, 0.5, 0.5, 0.5, 0.5, 0.0]
