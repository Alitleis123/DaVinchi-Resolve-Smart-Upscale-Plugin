# Eternal2x (DaVinci Resolve Smart Upscale)

Eternal2x is a creator‑friendly smart upscale workflow for DaVinci Resolve. It detects motion, lets you refine cut points via timeline markers, and then runs a clean, minimal pipeline to prep clips for 2× upscale and interpolation. The UI is intentionally simple: 4 buttons and 1 slider.

## What It Does
- Detects motion and places clearly labeled `[DSU]` markers on the selected clip or timeline for quick preview and manual adjustment.
- Cuts at marker positions and converts resulting clips into 1‑frame segments (for precise interpolation control).
- Regroups the timeline to remove gaps and make the sequence continuous.
- Runs a final pass: fixed 2× upscale + interpolation gated by sensitivity.

## UI
- Buttons: `Detect`, `Sequence`, `Regroup`, `Upscale and Interpolate`
- Slider: `Interpolate Sensitivity` (higher = less interpolation, lower = more)

## Install (Workspace Panel)
Option A — Installer (terminal):
1. Run:
   - `./.venv/bin/python Installer/install_eternal2x.py`
2. Restart Resolve.
3. Open: `Workspace → Scripts → Eternal2x`

Option B — Drag & Drop (no terminal):
1. Build the drag‑and‑drop package:
   - `./.venv/bin/python Installer/build_dragdrop.py`
2. Copy the generated folder `dist/Eternal2x` into Resolve’s Scripts/Comp folder.
3. Restart Resolve.
4. Open: `Workspace → Scripts → Eternal2x`

## Quick Start
1. Open a timeline and select the clip you want to process.
2. Open `Workspace → Scripts → Eternal2x`.
3. Click `Detect` and adjust any markers that need fine‑tuning.
4. Click `Sequence` to generate 1‑frame segments at marker positions.
5. Click `Regroup` to remove gaps and make the sequence continuous.
6. Set `Interpolate Sensitivity` and click `Upscale and Interpolate`.

## How It Works (Under the Hood)
- Motion scores are computed per frame from the clip.
- Segments above the sensitivity threshold are merged and filtered to avoid tiny bursts.
- Marker positions (after manual edits) are the source of truth for cutting.
- Upscale is fixed at 2× for safety and consistency in the MVP.

## Repo Commands
- Detect from a video and write segments:
  - `./.venv/bin/python -m Stages.frame_detect --video "PATH/TO/CLIP.mp4" --out "segments.json" --scores_out "scores.json"`
- Place markers from segments:
  - `./.venv/bin/python -m Stages.resolve_detect_markers --segments "segments.json"`

## Questions
Email `Justlighttbusiness@gmail.com`
