# Eternal2x test suite

Runs the whole plugin without opening DaVinci Resolve.

```bash
./test.sh                  # everything (creates .venv on first run)
./test.sh -k markers       # just the marker tests
./test.sh -x               # stop at the first failure
./test.sh tests/test_lua_ui.py -v
```

## How it manages to test Resolve stages

`tests/fake_resolve.py` implements the Resolve scripting API — Resolve,
ProjectManager, Project, Timeline, TimelineItem, MediaPoolItem — and is
installed into `sys.modules` as `DaVinciResolveScript`, which is exactly the
module the stages import. The stages cannot tell the difference.

The fake is deliberately **honest about what Resolve does not have**. It has a
`strict` flag:

| `strict` | Behaviour | What it proves |
|----------|-----------|----------------|
| `True` (default) | Only methods the real Resolve API exposes | What happens when you click the button for real |
| `False` | Also adds `TimelineItem.SetStart`/`SetEnd`/`SetClipProperty`, `Timeline.SplitClip`, `Timeline.GetSelectedItems` | Whether the stage's own logic is correct, assuming those calls worked |

That split is why a stage can have all its arithmetic tests pass and still fail
its `..._on_the_real_api_surface` test: the logic is right, but the API call it
depends on does not exist.

## How the Lua UI is tested

`tests/lua_harness.lua` stubs Fusion's `UIManager` / `UIDispatcher` and a
Resolve object tree, then loads the real `Installer/Eternal2x.lua` under an
embedded Lua runtime (`lupa`). Tests click real buttons and inspect the exact
shell command the plugin would run — including running that command for real to
confirm it resolves the `Stages` package.

`tests/test_installer.py` performs a full install into a temporary HOME, so the
install → launch → click chain is covered end to end.

## Videos

`make_video` (in `conftest.py`) writes lossless clips where the exact set of
moving frames is known, so motion scores can be asserted frame by frame rather
than eyeballed.

## Layout

| File | Covers |
|------|--------|
| `test_frame_detect.py` | segment thresholding, merging, filtering, CLI |
| `test_motion_score.py` | tile parsing, scorers, video → scores → segments |
| `test_resolve_detect_markers.py` | Detect: marker placement, re-runs, frame mapping |
| `test_resolve_cut_and_sequence.py` | Sequence: cutting at markers, 1-frame segments |
| `test_resolve_regroup.py` | Regroup: gap closing, marker shifting |
| `test_resolve_upscale_interpolate.py` | Upscale: 2x, interpolation gating |
| `test_resolve_update.py` | auto-update over a real local HTTP server |
| `test_installer.py` | install locations, config contents, launcher wiring |
| `test_lua_ui.py` | the Lua panel, button handlers, command construction |
| `test_packaging.py` | release parity, update metadata, file encodings |
