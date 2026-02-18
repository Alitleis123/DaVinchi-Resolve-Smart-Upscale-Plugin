from __future__ import annotations

import argparse
from datetime import datetime
from typing import List, Tuple


def _get_resolve():
    try:
        import DaVinciResolveScript as bmd  # type: ignore
    except Exception as exc:
        raise RuntimeError("Could not import DaVinciResolveScript. Run inside Resolve.") from exc
    resolve = bmd.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError("Could not connect to Resolve.")
    return resolve


def _pick_target(timeline):
    if hasattr(timeline, "GetSelectedItems"):
        items = timeline.GetSelectedItems()
        if items:
            if isinstance(items, dict):
                return next(iter(items.values())), "clip"
            if isinstance(items, list):
                return items[0], "clip"
    if hasattr(timeline, "GetCurrentVideoItem"):
        item = timeline.GetCurrentVideoItem()
        if item:
            return item, "clip"
    return timeline, "timeline"


def _markers_to_frames(marker_dict) -> List[Tuple[int, int]]:
    ranges = []
    for frame_id, info in (marker_dict or {}).items():
        try:
            start = int(frame_id)
        except Exception:
            continue
        duration = int((info or {}).get("duration", 1) or 1)
        if duration < 1:
            duration = 1
        end = start + duration - 1
        ranges.append((start, end))
    ranges.sort()
    return ranges


def _expand_ranges(ranges: List[Tuple[int, int]]) -> List[int]:
    frames: List[int] = []
    for start, end in ranges:
        if end < start:
            continue
        frames.extend(range(start, end + 1))
    return frames


def main():
    parser = argparse.ArgumentParser(
        description="Cut at current markers and generate 1-frame clips in a new timeline."
    )
    parser.add_argument(
        "--timeline_name",
        default=None,
        help="Optional name for the new timeline (default: Eternal2x_Frames_YYYYmmdd_HHMMSS)",
    )
    args = parser.parse_args()

    resolve = _get_resolve()
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        raise RuntimeError("No active project.")
    timeline = project.GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError("No active timeline.")

    target, target_type = _pick_target(timeline)

    marker_dict = target.GetMarkers() if hasattr(target, "GetMarkers") else {}
    if not marker_dict:
        print("No markers found on selected clip/timeline.")
        return

    ranges = _markers_to_frames(marker_dict)
    if not ranges:
        print("Markers present but no usable ranges.")
        return

    if target_type != "clip":
        print("No selected clip; cannot map markers to source frames.")
        return

    mpi = target.GetMediaPoolItem()
    if mpi is None:
        print("Selected clip has no media pool item.")
        return

    clip_start = int(target.GetStart())
    left_offset = int(target.GetLeftOffset() or 0)
    clip_duration = int(target.GetDuration())

    # Marker frameIds on a clip are relative to clip start.
    marker_frames = _expand_ranges(ranges)
    source_frames = []
    for f in marker_frames:
        if f < 0 or f >= clip_duration:
            continue
        source_frames.append(left_offset + f)

    if not source_frames:
        print("Markers did not map to any frames inside the clip.")
        return

    media_pool = project.GetMediaPool()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = args.timeline_name or f"Eternal2x_Frames_{ts}"
    new_tl = media_pool.CreateEmptyTimeline(name)
    if new_tl is None:
        raise RuntimeError("Failed to create new timeline.")

    # Append one-frame clips sequentially.
    record_frame = int(new_tl.GetStartFrame())
    clip_infos = []
    for src in source_frames:
        clip_infos.append(
            {
                "mediaPoolItem": mpi,
                "startFrame": int(src),
                "endFrame": int(src + 1),
                "mediaType": 1,
                "trackIndex": 1,
                "recordFrame": record_frame,
            }
        )
        record_frame += 1

    media_pool.AppendToTimeline(clip_infos)
    project.SetCurrentTimeline(new_tl)

    print(f"Created timeline '{name}' with {len(source_frames)} one-frame clips.")


if __name__ == "__main__":
    main()
