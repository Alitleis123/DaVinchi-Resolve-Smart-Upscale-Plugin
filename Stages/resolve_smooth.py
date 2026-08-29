"""Analyse the selected clip, rebuild it smoothly, and put the result back.

This is what the panel's buttons run. With --analyse it only measures the clip
and reports what it would do, which is fast and changes nothing. Without it,
the clip is rendered, imported and appended to the timeline.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Optional

from Pipeline import resolve_bridge as bridge
from Pipeline.config import Eternal2xConfig
from Pipeline.render import SourceError, analyse_video, render_plan


class StatusFile:
    """Progress the panel can poll while the render runs in the background.

    Rendering takes far longer than a UI click, so the stage is launched
    detached and reports here instead of blocking Resolve's interface. Writes
    go to a temporary file and are then moved into place, so a half-written
    file is never read.
    """

    def __init__(self, path: Optional[str]) -> None:
        self.path = Path(path) if path else None
        self.stage = ""
        self.fraction = 0.0
        self.message = ""

    def write(self, *, done: bool = False, ok: bool = False,
              message: Optional[str] = None) -> None:
        if self.path is None:
            return
        if message is not None:
            # The panel parses this file with simple pattern matching, so keep
            # the text on one line and free of quotes and backslashes.
            self.message = " ".join(str(message).split()).replace('"', "'").replace("\\", "/")
        payload = {
            "stage": self.stage,
            "fraction": round(self.fraction, 4),
            "message": self.message,
            "done": done,
            "ok": ok,
            "updated": time.time(),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload), encoding="utf-8")
            temp.replace(self.path)
        except OSError:
            pass  # progress reporting must never break the render

    def progress(self, stage: str, fraction: float) -> None:
        self.stage = stage
        self.fraction = fraction
        self.write()


def _progress_printer(status: "StatusFile"):
    """Print progress sparingly: Resolve's console is slow to draw."""
    state = {"last": 0.0, "stage": ""}

    def report(stage: str, fraction: float) -> None:
        now = time.time()
        status.progress(stage, fraction)
        if stage != state["stage"]:
            state["stage"] = stage
            state["last"] = 0.0
        if fraction >= 1.0 or now - state["last"] >= 1.0:
            state["last"] = now
            print(f"  {stage}: {fraction * 100:.0f}%", flush=True)

    return report


# png    lossless image sequence; always readable by Resolve, many files
# mp4    H.264; compact and universally readable, but lossy
# avi    FFV1; lossless single file, though Resolve may not import it
FORMATS = {"png": "", "mp4": ".mp4", "avi": ".avi"}


def _output_path(source: Path, output_dir: Optional[str], fmt: str) -> Path:
    base = Path(output_dir) if output_dir else source.parent / "Eternal2x"
    base.mkdir(parents=True, exist_ok=True)
    suffix = FORMATS.get(fmt, "")
    stem = f"{source.stem}_smooth"

    def taken(path: Path) -> bool:
        if not path.exists():
            return False
        return any(path.iterdir()) if path.is_dir() else True

    target = base / f"{stem}{suffix}"
    n = 1
    while taken(target):
        n += 1
        target = base / f"{stem}_{n:02d}{suffix}"
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild the selected Resolve clip with smooth motion."
    )
    parser.add_argument("--analyse", action="store_true",
                        help="Only measure the clip and report; change nothing.")
    parser.add_argument("--video", default=None,
                        help="Process this file instead of the Resolve selection.")
    parser.add_argument("--output-dir", default=None,
                        help="Where to write the result (default: an Eternal2x "
                             "folder beside the source).")
    parser.add_argument("--format", default="png", choices=sorted(FORMATS),
                        help="png: lossless image sequence (default). "
                             "mp4: compact H.264 file. "
                             "avi: lossless FFV1 file.")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Duplicate-detection threshold override.")
    parser.add_argument("--base-hold", type=int, default=0,
                        help="Force the hold pattern (2 = on 2s). 0 auto-detects.")
    parser.add_argument("--quality", default=None, choices=["fast", "better", "best"],
                        help="Interpolation quality.")
    parser.add_argument("--no-interpolate", action="store_true",
                        help="De-duplicate only, without generating in-betweens.")
    parser.add_argument("--no-upscale", action="store_true",
                        help="Skip the 2x upscale.")
    parser.add_argument("--json", action="store_true",
                        help="Emit a machine-readable summary.")
    parser.add_argument("--status-file", default=None,
                        help="Write progress here so the panel can poll it.")
    return parser


def config_from_args(args) -> Eternal2xConfig:
    cfg = Eternal2xConfig()
    if args.threshold is not None:
        cfg.duplicate_threshold = args.threshold
    if args.base_hold:
        cfg.force_base_hold = args.base_hold
    if args.quality:
        cfg.quality = args.quality
    cfg.interpolate_enabled = not args.no_interpolate
    # The upscale is Resolve's job when it can do it, so the renderer works at
    # source resolution and Super Scale is applied to the imported clip.
    cfg.upscale_enabled = False
    cfg.upscale_factor = 1 if args.no_upscale else 2
    return cfg


def main() -> int:
    args = build_parser().parse_args()
    cfg = config_from_args(args)
    summary: dict = {"ok": False}
    status = StatusFile(args.status_file)
    status.write(message="Starting")

    resolve = None
    project = timeline = None
    if args.video:
        source = Path(args.video)
    else:
        try:
            resolve = bridge.connect()
            project, timeline = bridge.current_timeline(resolve)
            source = bridge.clip_source_path(bridge.selected_clip(timeline))
        except bridge.ResolveError as exc:
            print(f"Error: {exc}")
            status.write(done=True, ok=False, message=str(exc))
            return 2

    if not source.exists():
        message = f"The clip's media is missing: {source.name}"
        print(f"Error: {message}")
        status.write(done=True, ok=False, message=message)
        return 2

    print(f"Source: {source.name}")
    progress = _progress_printer(status)

    try:
        plan, width, height = analyse_video(source, cfg, progress=progress)
    except SourceError as exc:
        print(f"Error: {exc}")
        status.write(done=True, ok=False, message=str(exc))
        return 2

    print(plan.describe())
    summary.update({"source": str(source), "width": width, "height": height,
                    "plan": plan.to_dict()})

    if plan.is_noop:
        print("Nothing to do: this clip has no duplicated frames.")
        print("It is either live action or already animated on 1s.")
        summary["ok"] = True
        summary["skipped"] = "no duplicate frames"
        status.write(done=True, ok=True,
                     message="No duplicate frames. This clip is already on 1s.")
        if args.json:
            print(json.dumps(summary))
        return 0

    if args.analyse:
        print("Analysis only. Nothing was changed.")
        summary["ok"] = True
        status.write(done=True, ok=True, message=plan.describe())
        if args.json:
            print(json.dumps(summary))
        return 0

    output = _output_path(source, args.output_dir, args.format)
    print(f"Rendering to: {output}")
    try:
        result = render_plan(source, plan, output, cfg, progress=progress)
    except SourceError as exc:
        print(f"Error: {exc}")
        status.write(done=True, ok=False, message=str(exc))
        return 2

    print(f"Wrote {result.frames_written} frames at {result.fps:.3f} fps.")
    summary["render"] = result.to_dict()

    if resolve is None:
        print("Done. Import the result into Resolve when you are ready.")
        summary["ok"] = True
        status.write(done=True, ok=True, message=f"Rendered to {result.output.name}.")
        if args.json:
            print(json.dumps(summary))
        return 0

    media_item, imported = bridge.import_media(project, result.output,
                                               frame_count=result.frames_written,
                                               fps=result.fps)
    print(("Imported: " if imported else "Import failed: ") + imported.detail)
    summary["import"] = {"ok": imported.ok, "detail": imported.detail}

    if not imported:
        print(f"The render is fine and is waiting at: {result.output}")
        print("Drag it into your media pool to finish.")
        summary["ok"] = True
        status.write(done=True, ok=True,
                     message=f"Rendered, but Resolve would not import it. "
                             f"Drag in {result.output.name} to finish.")
        if args.json:
            print(json.dumps(summary))
        return 0

    if cfg.upscale_factor > 1:
        studio = bridge.is_studio(resolve)
        if studio is False:
            print("Skipping upscale: Super Scale needs DaVinci Resolve Studio.")
            summary["upscale"] = {"ok": False, "detail": "not Studio"}
        else:
            scaled = bridge.set_super_scale(media_item, cfg.upscale_factor)
            print(("Upscale: " if scaled else "Upscale not applied: ") + scaled.detail)
            summary["upscale"] = {"ok": scaled.ok, "detail": scaled.detail}

    appended = bridge.append_to_timeline(project, media_item)
    print(("Timeline: " if appended else "Timeline not updated: ") + appended.detail)
    summary["append"] = {"ok": appended.ok, "detail": appended.detail}

    summary["ok"] = True
    print("Done.")
    status.write(done=True, ok=True,
                 message=f"Done. {plan.unique_drawings} drawings rebuilt into "
                         f"{result.frames_written} smooth frames.")
    if args.json:
        print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
