# Eternal2x (DaVinci Resolve Smart Upscale)

Eternal2x is a creator-friendly smart upscale workflow for DaVinci Resolve. It detects motion, lets you refine cut points via timeline markers, and then runs a clean, minimal pipeline to prep clips for 2x upscale and interpolation. The UI is intentionally simple: 4 buttons and 1 slider.

## What It Does
- Detects motion and places clearly labeled `[DSU]` markers on the selected clip or timeline for quick preview and manual adjustment.
- Cuts at marker positions and converts resulting clips into 1-frame segments (for precise interpolation control).
- Regroups the timeline to remove gaps and make the sequence continuous.
- Runs a final pass: fixed 2x upscale + interpolation gated by sensitivity.

## UI
- Buttons: `Detect`, `Sequence`, `Regroup`, `Upscale and Interpolate`, `Check for Updates`
- Slider: `Interpolate Sensitivity` (higher = less interpolation, lower = more)

## Install (One-Time EXE/App)
1. Run the installer executable once:
   - Windows: `Eternal2xInstaller.exe`
   - macOS: `Eternal2xInstaller.app` (or packaged executable)
2. The installer writes Eternal2x into Resolve scripts:
   - Windows: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Comp\`
   - macOS: `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Comp/`
3. Restart Resolve.
4. Open: `Workspace -> Scripts -> Eternal2x`

## Auto-Update Behavior
- Goal: install once, no manual copy/reinstall for normal updates.
- Eternal2x checks cloud metadata at startup (`update/latest.json` in this repo).
- If a newer version exists for your platform, it downloads and applies update files.
- You can also trigger this manually using `Check for Updates` in the plugin UI.
- After an update is applied, restart Resolve to load the new version.
- Re-run installer only if install files are missing or repo path changes.

## Quick Start
1. Open a timeline and select the clip you want to process.
2. Open `Workspace -> Scripts -> Eternal2x`.
3. Click `Detect` and adjust any markers that need fine-tuning.
4. Click `Sequence` to generate 1-frame segments at marker positions.
5. Click `Regroup` to remove gaps and make the sequence continuous.
6. Set `Interpolate Sensitivity` and click `Upscale and Interpolate`.

## How It Works (Under the Hood)
- Motion scores are computed per frame from the clip.
- Segments above the sensitivity threshold are merged and filtered to avoid tiny bursts.
- Marker positions (after manual edits) are the source of truth for cutting.
- Upscale is fixed at 2x for safety and consistency in the MVP.

## Questions
Email `Justlighttbusiness@gmail.com`
