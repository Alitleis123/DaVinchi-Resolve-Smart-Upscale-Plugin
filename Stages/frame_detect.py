from dataclasses import dataclass
from typing import List
from Pipeline.config import UpscaleConfig

import argparse
import json


@dataclass
class Segment:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def merge_close_segments(segments: List[Segment], merge_gap_frames: int) -> List[Segment]:
    """Merge segments that are separated by <= merge_gap_frames."""
    if not segments:
        return []

    merged = [segments[0]]

    for seg in segments[1:]:
        last = merged[-1]
        gap = seg.start - last.end - 1

        if gap <= merge_gap_frames:
            last.end = max(last.end, seg.end)
        else:
            merged.append(seg)

    return merged


def filter_short_segments(segments: List[Segment], min_segment_frames: int) -> List[Segment]:
    """Remove segments shorter than min_segment_frames."""
    return [s for s in segments if s.length >= min_segment_frames]


def detect_motion_segments(scores: List[float], cfg: UpscaleConfig) -> List[Segment]:
    """
    scores: motion score per frame (higher = more motion)
    returns: segments of frames considered 'motion'
    """
    segments: List[Segment] = []

    threshold = cfg.sensitivity
    in_seg = False
    start = 0

    for i, s in enumerate(scores):
        is_motion = s >= threshold

        if is_motion and not in_seg:
            in_seg = True
            start = i

        elif (not is_motion) and in_seg:
            in_seg = False
            segments.append(Segment(start=start, end=i - 1))

    if in_seg:
        segments.append(Segment(start=start, end=len(scores) - 1))

    segments = merge_close_segments(segments, cfg.merge_gap_frames)
    segments = filter_short_segments(segments, cfg.min_segment_frames)

    return segments


def segments_to_dict(segments: List[Segment]) -> List[dict]:
    return [{"start": s.start, "end": s.end, "length": s.length} for s in segments]


def main():
    parser = argparse.ArgumentParser(
        description="Detect motion segments from per-frame motion scores."
    )

    parser.add_argument(
        "--scores",
        required=True,
        help="Comma-separated list of motion scores, e.g. 0.0,0.1,0.3,0.25",
    )
    parser.add_argument(
        "--out",
        default="segments.json",
        help="Output JSON path (default: segments.json)",
    )

    parser.add_argument("--sensitivity", type=float, default=None, help="Override cfg.sensitivity")
    parser.add_argument("--min_segment_frames", type=int, default=None, help="Override cfg.min_segment_frames")
    parser.add_argument("--merge_gap_frames", type=int, default=None, help="Override cfg.merge_gap_frames")

    args = parser.parse_args()

    scores = [float(x.strip()) for x in args.scores.split(",") if x.strip() != ""]

    cfg = UpscaleConfig()

    if args.sensitivity is not None:
        cfg.sensitivity = args.sensitivity
    if args.min_segment_frames is not None:
        cfg.min_segment_frames = args.min_segment_frames
    if args.merge_gap_frames is not None:
        cfg.merge_gap_frames = args.merge_gap_frames

    segments = detect_motion_segments(scores, cfg)

    payload = {
        "settings": {
            "sensitivity": cfg.sensitivity,
            "min_segment_frames": cfg.min_segment_frames,
            "merge_gap_frames": cfg.merge_gap_frames,
        },
        "segments": segments_to_dict(segments),
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Wrote {len(segments)} segments -> {args.out}")


if __name__ == "__main__":
    main()