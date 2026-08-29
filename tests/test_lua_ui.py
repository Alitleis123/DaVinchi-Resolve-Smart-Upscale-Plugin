"""Drive the real panel (Installer/Eternal2x.lua) under a Lua runtime.

These tests load the actual UI script, click the actual buttons, and inspect
the exact shell command it hands to Python. That is the part that normally
needs Resolve open.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("lupa", reason="lupa provides the Lua runtime")
from lupa import LuaRuntime  # noqa: E402

HARNESS = Path(__file__).resolve().parent / "lua_harness.lua"


@pytest.fixture
def lua():
    return LuaRuntime(unpack_returned_tuples=True)


def _plugin_tree(dest: Path, repo_root: Path) -> Path:
    for name in ("Installer", "Stages", "Pipeline"):
        shutil.copytree(repo_root / name, dest / name)
    (dest / "VERSION").write_text("0.3.0\n")
    return dest


@pytest.fixture
def installed(tmp_path, repo_root):
    """A full install: launcher plus config in Comp, plugin tree elsewhere."""
    plugin_root = _plugin_tree(tmp_path / "Eternal2x", repo_root)
    comp = tmp_path / "Comp"
    comp.mkdir()
    shutil.copy2(plugin_root / "Installer" / "Eternal2xLauncher.lua", comp / "Eternal2x.lua")
    (comp / "Eternal2x.conf").write_text(
        f"repo_root={plugin_root}\n"
        f"python={sys.executable}\n"
        "update_url=https://example.com/latest.json\n"
        "auto_update=false\n",
        encoding="utf-8",
    )
    return comp, plugin_root


@pytest.fixture
def direct(tmp_path, repo_root):
    """The UI script with its config beside it, for exercising the panel itself."""
    root = _plugin_tree(tmp_path / "Eternal2x", repo_root)
    (root / "Installer" / "Eternal2x.conf").write_text(
        f"repo_root={root}\n"
        f"python={sys.executable}\n"
        "update_url=https://example.com/latest.json\n"
        "auto_update=false\n"
    )
    return root


def load(lua, script: Path, clip="/media/shot.mov"):
    H = lua.eval(f'dofile("{HARNESS}")')
    H.load(str(script), clip)
    return H


def ui_script(root: Path) -> Path:
    return root / "Installer" / "Eternal2x.lua"


# --------------------------------------------------------------------------
# structure
# --------------------------------------------------------------------------

def test_panel_loads(lua, direct):
    assert load(lua, ui_script(direct)).window is not None


def test_every_control_is_present(lua, direct):
    H = load(lua, ui_script(direct))
    ids = set(H.widget_ids().split(","))
    for expected in ("SmoothBtn", "AnalyseBtn", "RefreshBtn", "RefreshStatusBtn",
                     "CancelBtn", "UpdateBtn", "QualityCombo", "HoldCombo", "FormatCombo",
                     "UpscaleCB", "InterpCB", "AutoUpdateCB", "Status",
                     "Progress", "SourceLabel", "AnalysisLabel"):
        assert expected in ids, f"missing {expected}; have {sorted(ids)}"


def test_every_control_has_a_handler(lua, direct):
    H = load(lua, ui_script(direct))
    handlers = set(H.handler_ids().split(","))
    for expected in ("SmoothBtn.Clicked", "AnalyseBtn.Clicked", "RefreshBtn.Clicked",
                     "RefreshStatusBtn.Clicked", "CancelBtn.Clicked",
                     "UpdateBtn.Clicked", "QualityCombo.CurrentIndexChanged",
                     "HoldCombo.CurrentIndexChanged", "UpscaleCB.Clicked",
                     "InterpCB.Clicked", "AutoUpdateCB.Clicked"):
        assert expected in handlers, f"no handler for {expected}"


def test_quality_choices_match_what_the_stage_accepts(lua, direct):
    from Stages.resolve_smooth import build_parser
    H = load(lua, ui_script(direct))
    labels = [x.lower() for x in H.combo_items("QualityCombo").split(",")]

    accepted = None
    for action in build_parser()._actions:
        if "--quality" in action.option_strings:
            accepted = set(action.choices)
    assert accepted is not None
    assert set(labels) == accepted, f"panel offers {labels}, stage accepts {accepted}"


def test_output_format_choices_match_the_stage(lua, direct):
    from Stages.resolve_smooth import build_parser
    H = load(lua, ui_script(direct))
    assert H.combo_items("FormatCombo").count(",") == 2

    accepted = None
    for action in build_parser()._actions:
        if "--format" in action.option_strings:
            accepted = set(action.choices)
    H.click("AnalyseBtn")
    chosen = H.last_command().split("--format ")[1].split()[0]
    assert chosen in accepted


def test_the_default_output_format_is_lossless(lua, direct):
    H = load(lua, ui_script(direct))
    H.click("AnalyseBtn")
    assert "--format png" in H.last_command()


def test_output_format_selection_reaches_the_command(lua, direct):
    H = load(lua, ui_script(direct))
    H.set_combo("FormatCombo", 1)      # MP4
    H.click("AnalyseBtn")
    assert "--format mp4" in H.last_command()


def test_hold_pattern_choices_are_offered(lua, direct):
    H = load(lua, ui_script(direct))
    labels = H.combo_items("HoldCombo").split(",")
    assert labels == ["Auto detect", "On 1s", "On 2s", "On 3s"]


def test_the_version_is_shown(lua, direct):
    H = load(lua, ui_script(direct))
    assert "0.3.0" in H.widgets["SubTitle"].Text


def test_a_byte_order_mark_in_version_does_not_leak_into_the_title(lua, direct):
    (direct / "VERSION").write_bytes(b"\xef\xbb\xbf0.3.0\n")
    H = load(lua, ui_script(direct))
    assert "﻿" not in H.widgets["SubTitle"].Text
    assert "0.3.0" in H.widgets["SubTitle"].Text


# --------------------------------------------------------------------------
# the install chain
# --------------------------------------------------------------------------

def test_launcher_reaches_the_panel(lua, installed):
    comp, _ = installed
    assert load(lua, comp / "Eternal2x.lua").window is not None


def test_launcher_reports_a_missing_config(lua, tmp_path, repo_root):
    comp = tmp_path / "Comp"
    comp.mkdir()
    shutil.copy2(repo_root / "Installer" / "Eternal2xLauncher.lua", comp / "Eternal2x.lua")
    H = load(lua, comp / "Eternal2x.lua")
    assert "Missing repo_root" in " ".join(str(v) for v in dict(H.prints).values())


def test_buttons_run_from_the_folder_that_holds_the_code(lua, installed):
    """The whole install chain: config in Comp, code elsewhere, cd to the code."""
    comp, plugin_root = installed
    H = load(lua, comp / "Eternal2x.lua")
    H.click("AnalyseBtn")

    cmd = H.last_command()
    assert cmd is not None, "clicking Analyse ran nothing"
    assert f'"{plugin_root}"' in cmd, f"ran: {cmd}\nexpected a cd into {plugin_root}"


def test_the_configured_interpreter_is_used(lua, installed):
    comp, _ = installed
    H = load(lua, comp / "Eternal2x.lua")
    H.click("AnalyseBtn")
    assert sys.executable in H.last_command()


def test_the_version_survives_the_launcher(lua, installed):
    comp, _ = installed
    H = load(lua, comp / "Eternal2x.lua")
    assert "0.3.0" in H.widgets["SubTitle"].Text


def test_the_update_url_survives_the_launcher(lua, installed):
    comp, _ = installed
    H = load(lua, comp / "Eternal2x.lua")
    H.click("UpdateBtn")
    assert "example.com/latest.json" in (H.last_command() or "")


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def test_analyse_runs_the_stage_in_analyse_mode(lua, direct):
    H = load(lua, ui_script(direct))
    H.click("AnalyseBtn")
    cmd = H.last_command()
    assert "-m Stages.resolve_smooth" in cmd
    assert "--analyse" in cmd


def test_analyse_does_not_run_in_the_background(lua, direct):
    """It has to finish before the panel reads the result."""
    H = load(lua, ui_script(direct))
    H.click("AnalyseBtn")
    assert not H.last_command().rstrip().endswith("&")


def test_smooth_runs_in_the_background(lua, direct):
    """A render takes minutes; blocking here would freeze Resolve."""
    H = load(lua, ui_script(direct))
    H.click("SmoothBtn")
    cmd = H.last_command()
    assert "-m Stages.resolve_smooth" in cmd
    assert "--analyse" not in cmd
    assert cmd.rstrip().endswith("&") or "start " in cmd


def test_smooth_passes_a_status_file(lua, direct):
    H = load(lua, ui_script(direct))
    H.click("SmoothBtn")
    assert "--status-file" in H.last_command()


def test_quality_selection_reaches_the_command(lua, direct):
    H = load(lua, ui_script(direct))
    H.set_combo("QualityCombo", 2)      # Best
    H.click("AnalyseBtn")
    assert "--quality best" in H.last_command()


def test_hold_pattern_selection_reaches_the_command(lua, direct):
    H = load(lua, ui_script(direct))
    H.set_combo("HoldCombo", 2)         # On 2s
    H.click("AnalyseBtn")
    assert "--base-hold 2" in H.last_command()


def test_auto_hold_pattern_sends_no_override(lua, direct):
    H = load(lua, ui_script(direct))
    H.set_combo("HoldCombo", 0)         # Auto detect
    H.click("AnalyseBtn")
    assert "--base-hold" not in H.last_command()


def test_unchecking_upscale_reaches_the_command(lua, direct):
    H = load(lua, ui_script(direct))
    H.set_checkbox("UpscaleCB", False)
    H.click("AnalyseBtn")
    assert "--no-upscale" in H.last_command()


def test_unchecking_interpolate_reaches_the_command(lua, direct):
    H = load(lua, ui_script(direct))
    H.set_checkbox("InterpCB", False)
    H.click("AnalyseBtn")
    assert "--no-interpolate" in H.last_command()


def test_defaults_send_no_opt_out_flags(lua, direct):
    H = load(lua, ui_script(direct))
    H.click("AnalyseBtn")
    cmd = H.last_command()
    assert "--no-upscale" not in cmd and "--no-interpolate" not in cmd


def test_a_clip_path_with_spaces_is_quoted(lua, direct):
    H = load(lua, ui_script(direct), clip="/media/My Footage/shot 01.mov")
    assert "My Footage" in H.widgets["Meta"].Text


def test_every_module_the_panel_calls_exists(lua, direct, repo_root):
    for button in ("AnalyseBtn", "SmoothBtn", "UpdateBtn"):
        H = load(lua, ui_script(direct))
        H.click(button)
        module = H.last_command().split("-m ")[1].split()[0]
        assert (repo_root / Path(module.replace(".", "/") + ".py")).exists(), \
            f"{button} calls missing module {module}"


def test_the_command_the_panel_builds_actually_runs(lua, direct):
    """Run the panel's own command string and confirm it resolves the package."""
    H = load(lua, ui_script(direct))
    H.click("AnalyseBtn")
    cmd = H.last_command()

    subprocess.run(cmd, shell=True, capture_output=True, text=True)
    log = (direct / ".eternal2x_last_run.log")
    assert log.exists(), "the panel's command produced no log"
    text = log.read_text()
    for missing in ("No module named 'Stages'", "No module named 'Pipeline'"):
        assert missing not in text, f"the panel cannot reach the plugin modules:\n{text}"


# --------------------------------------------------------------------------
# source clip
# --------------------------------------------------------------------------

def test_the_selected_clip_is_shown_on_open(lua, direct):
    H = load(lua, ui_script(direct), clip="/media/scene 04.mov")
    assert "scene 04.mov" in H.widgets["SourceLabel"].Text


def test_refresh_picks_up_the_selection(lua, direct):
    H = load(lua, ui_script(direct), clip="/media/shot.mov")
    H.click("RefreshBtn")
    assert "shot.mov" in H.widgets["SourceLabel"].Text
    assert "Ready" in H.status()


# --------------------------------------------------------------------------
# progress reporting
# --------------------------------------------------------------------------

def write_status(root: Path, **fields):
    payload = {"stage": "Rendering", "fraction": 0.5, "message": "",
               "done": False, "ok": False, "updated": 0}
    payload.update(fields)
    (root / ".eternal2x_status.json").write_text(json.dumps(payload))


def test_progress_is_shown_while_running(lua, direct):
    H = load(lua, ui_script(direct))
    write_status(direct, stage="Rendering", fraction=0.5)
    H.click("RefreshStatusBtn")
    assert "50%" in H.widgets["Progress"].Text


def test_progress_bar_fills_as_it_goes(lua, direct):
    H = load(lua, ui_script(direct))
    filled = []
    for fraction in (0.1, 0.9):
        write_status(direct, fraction=fraction)
        H.click("RefreshStatusBtn")
        filled.append(H.widgets["Progress"].Text.count("█"))
    assert filled[1] > filled[0], "the progress bar did not grow"


def test_completion_message_is_surfaced(lua, direct):
    H = load(lua, ui_script(direct))
    write_status(direct, fraction=1.0, done=True, ok=True,
                 message="Done. 12 drawings rebuilt into 24 smooth frames.")
    H.click("RefreshStatusBtn")
    assert "12 drawings" in H.status()


def test_a_failure_is_surfaced(lua, direct):
    H = load(lua, ui_script(direct))
    write_status(direct, done=True, ok=False, message="The clip's media is missing.")
    H.click("RefreshStatusBtn")
    assert "media is missing" in H.status()


def test_buttons_are_disabled_while_a_render_runs(lua, direct):
    H = load(lua, ui_script(direct))
    H.click("SmoothBtn")
    assert not H.enabled("SmoothBtn"), "Smooth stayed clickable during a render"
    assert not H.enabled("AnalyseBtn")


def test_buttons_come_back_when_the_render_finishes(lua, direct):
    H = load(lua, ui_script(direct))
    H.click("SmoothBtn")
    write_status(direct, fraction=1.0, done=True, ok=True, message="Done.")
    H.click("RefreshStatusBtn")
    assert H.enabled("SmoothBtn")
    assert H.enabled("AnalyseBtn")


def test_reset_clears_a_stuck_run(lua, direct):
    H = load(lua, ui_script(direct))
    H.click("SmoothBtn")
    H.click("CancelBtn")
    assert H.enabled("SmoothBtn")
    assert H.widgets["Progress"].Text == ""
    assert not (direct / ".eternal2x_status.json").exists()


def test_refreshing_with_no_run_says_so(lua, direct):
    H = load(lua, ui_script(direct))
    H.click("RefreshStatusBtn")
    assert "No run in progress" in H.status()


# --------------------------------------------------------------------------
# settings persistence
# --------------------------------------------------------------------------

def test_settings_are_saved(lua, direct):
    H = load(lua, ui_script(direct))
    H.set_combo("QualityCombo", 2)
    H.set_combo("HoldCombo", 3)
    H.set_checkbox("UpscaleCB", False)

    conf = (direct / "Installer" / "Eternal2x.conf").read_text()
    assert "quality=best" in conf
    assert "base_hold=3" in conf
    assert "upscale=false" in conf


def test_saving_settings_keeps_the_rest_of_the_config(lua, direct):
    H = load(lua, ui_script(direct))
    H.set_checkbox("UpscaleCB", False)
    conf = (direct / "Installer" / "Eternal2x.conf").read_text()
    assert f"repo_root={direct}" in conf
    assert "update_url=https://example.com/latest.json" in conf


def test_saved_settings_are_restored_next_time(lua, direct):
    H = load(lua, ui_script(direct))
    H.set_combo("QualityCombo", 0)     # Fast
    H.set_combo("HoldCombo", 2)        # On 2s

    H2 = load(lua, ui_script(direct))
    H2.click("AnalyseBtn")
    cmd = H2.last_command()
    assert "--quality fast" in cmd
    assert "--base-hold 2" in cmd


def test_auto_update_toggle_persists(lua, direct):
    H = load(lua, ui_script(direct))
    H.set_checkbox("AutoUpdateCB", True)
    assert "auto_update=true" in (direct / "Installer" / "Eternal2x.conf").read_text()
