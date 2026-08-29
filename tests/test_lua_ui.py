"""Drive the real Resolve UI script (Installer/Eternal2x.lua) under a Lua runtime.

These tests run the actual Lua, click the actual buttons, and inspect the exact
shell command the plugin would hand to Python. That is the step that normally
requires opening Resolve.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa", reason="lupa provides the Lua runtime")
from lupa import LuaRuntime  # noqa: E402

HARNESS = Path(__file__).resolve().parent / "lua_harness.lua"


@pytest.fixture
def lua():
    rt = LuaRuntime(unpack_returned_tuples=True)
    return rt


@pytest.fixture
def installed(tmp_path, repo_root):
    """Install the plugin the way Installer/install_eternal2x.py does.

    Returns (comp_dir, plugin_root). `comp_dir` is Resolve's Scripts/Comp folder:
    it receives the launcher plus the config. `plugin_root` is where the user
    keeps the checkout.
    """
    plugin_root = tmp_path / "Eternal2x"
    shutil.copytree(repo_root / "Installer", plugin_root / "Installer")
    shutil.copytree(repo_root / "Stages", plugin_root / "Stages")
    shutil.copytree(repo_root / "Pipeline", plugin_root / "Pipeline")
    (plugin_root / "VERSION").write_text("0.2.0\n")

    comp = tmp_path / "Comp"
    comp.mkdir()
    shutil.copy2(plugin_root / "Installer" / "Eternal2xLauncher.lua", comp / "Eternal2x.lua")
    (comp / "Eternal2x.conf").write_text(
        f"repo_root={plugin_root}\n"
        f"python=/usr/bin/python3\n"
        f"update_url=https://example.com/latest.json\n"
        "auto_update=false\n",
        encoding="utf-8",
    )
    return comp, plugin_root


def load(lua, script: Path, clip="/media/shot.mov"):
    H = lua.eval(f'dofile("{HARNESS}")')
    H.load(str(script), clip)
    return H


# --------------------------------------------------------------------------
# UI wiring
# --------------------------------------------------------------------------

def test_ui_script_loads(lua, repo_root):
    H = load(lua, repo_root / "Installer" / "Eternal2x.lua")
    assert H.window is not None


def test_every_documented_control_exists(lua, repo_root):
    H = load(lua, repo_root / "Installer" / "Eternal2x.lua")
    ids = set(H.widget_ids().split(","))
    for expected in ("DetectBtn", "CutFrameBtn", "RegroupBtn", "UpscaleBtn",
                     "UpdateBtn", "SensSlider", "Status", "AutoUpdateCB"):
        assert expected in ids, f"missing control {expected}; have {sorted(ids)}"


def test_every_button_has_a_handler(lua, repo_root):
    H = load(lua, repo_root / "Installer" / "Eternal2x.lua")
    handlers = set(H.handler_ids().split(","))
    for expected in ("DetectBtn.Clicked", "CutFrameBtn.Clicked", "RegroupBtn.Clicked",
                     "UpscaleBtn.Clicked", "UpdateBtn.Clicked",
                     "SensSlider.ValueChanged", "AutoUpdateCB.Clicked"):
        assert expected in handlers, f"no handler for {expected}; have {sorted(handlers)}"


def test_slider_label_tracks_the_slider(lua, repo_root):
    H = load(lua, repo_root / "Installer" / "Eternal2x.lua")
    H.set_slider("SensSlider", 65)
    assert "0.65" in H.text_of("SensLabel")


def test_slider_default_matches_the_config_default(lua, repo_root):
    from Pipeline.config import UpscaleConfig
    H = load(lua, repo_root / "Installer" / "Eternal2x.lua")
    assert H.widgets["SensSlider"].Value / 100.0 == pytest.approx(UpscaleConfig().sensitivity)


# --------------------------------------------------------------------------
# the install -> launch chain
# --------------------------------------------------------------------------

def test_launcher_finds_and_runs_the_ui_script(lua, installed):
    comp, _plugin_root = installed
    H = load(lua, comp / "Eternal2x.lua")
    assert H.window is not None, (
        "the launcher did not reach the UI script; printed: "
        + "; ".join(H.prints.values() if hasattr(H.prints, "values") else [])
    )


def test_launcher_reports_a_missing_config(lua, tmp_path, repo_root):
    comp = tmp_path / "Comp"
    comp.mkdir()
    shutil.copy2(repo_root / "Installer" / "Eternal2xLauncher.lua", comp / "Eternal2x.lua")
    H = load(lua, comp / "Eternal2x.lua")
    printed = " ".join(str(v) for v in dict(H.prints).values())
    assert "Missing repo_root" in printed


def test_buttons_run_from_the_plugin_root_after_a_real_install(lua, installed):
    """A clicked button must cd into the folder that actually holds `Stages/`.

    The installer writes Eternal2x.conf next to the *launcher* in Resolve's
    Comp folder, but the launcher then dofile()s the UI script from
    repo_root/Installer/. The UI script re-derives its config from its own
    directory, finds no Eternal2x.conf there, and falls back to that directory
    as the repo root -- so it cds into repo_root/Installer, where `Stages` does
    not exist.
    """
    comp, plugin_root = installed
    H = load(lua, comp / "Eternal2x.lua")
    H.click("CutFrameBtn")

    cmd = H.last_command()
    assert cmd is not None, "clicking Sequence ran no command at all"
    assert f'"{plugin_root}"' in cmd, (
        f"button ran: {cmd}\n"
        f"expected it to cd into {plugin_root} (which contains Stages/), "
        f"not {plugin_root}/Installer"
    )


def test_configured_python_interpreter_is_used(lua, installed):
    comp, _ = installed
    H = load(lua, comp / "Eternal2x.lua")
    H.click("CutFrameBtn")
    cmd = H.last_command()
    assert "/usr/bin/python3" in cmd, (
        f"the interpreter chosen by the installer was ignored; command was: {cmd}"
    )


def test_version_from_the_plugin_root_shows_in_the_title(lua, installed):
    comp, _ = installed
    H = load(lua, comp / "Eternal2x.lua")
    title = H.widgets["SubTitle"].Text
    assert "0.2.0" in title, f"version not resolved; subtitle reads {title!r}"


def test_update_url_from_the_config_is_used(lua, installed):
    comp, _ = installed
    H = load(lua, comp / "Eternal2x.lua")
    H.click("UpdateBtn")
    cmd = H.last_command()
    assert cmd is not None and "example.com/latest.json" in cmd, (
        f"Check for Updates did not use the configured URL; status: {H.status()!r}, "
        f"command: {cmd!r}"
    )


# --------------------------------------------------------------------------
# command construction (loading the UI script directly, config alongside)
# --------------------------------------------------------------------------

@pytest.fixture
def direct(tmp_path, repo_root):
    """Load Installer/Eternal2x.lua with a config sitting next to it."""
    root = tmp_path / "Eternal2x"
    shutil.copytree(repo_root / "Installer", root / "Installer")
    shutil.copytree(repo_root / "Stages", root / "Stages")
    shutil.copytree(repo_root / "Pipeline", root / "Pipeline")
    (root / "VERSION").write_text("0.2.0\n")
    (root / "Installer" / "Eternal2x.conf").write_text(
        f"repo_root={root}\n"
        f"python={sys.executable}\n"
        f"update_url=https://example.com/latest.json\n"
        "auto_update=false\n"
    )
    return root


def test_detect_button_passes_the_clip_path_and_sensitivity(lua, direct):
    H = load(lua, direct / "Installer" / "Eternal2x.lua", clip="/media/shot.mov")
    H.set_slider("SensSlider", 35)
    H.click("DetectBtn")

    cmd = H.last_command()
    assert "-m Stages.resolve_detect_markers" in cmd
    assert "/media/shot.mov" in cmd
    assert "--sensitivity 0.3500" in cmd


def test_each_button_invokes_its_own_stage(lua, direct):
    expected = {
        "CutFrameBtn": "Stages.resolve_cut_and_sequence",
        "RegroupBtn": "Stages.resolve_regroup",
        "UpscaleBtn": "Stages.resolve_upscale_interpolate",
        "UpdateBtn": "Stages.resolve_update",
    }
    for button, module in expected.items():
        H = load(lua, direct / "Installer" / "Eternal2x.lua")
        H.click(button)
        cmd = H.last_command()
        assert f"-m {module}" in cmd, f"{button} ran {cmd!r}"


def test_every_stage_the_ui_calls_actually_exists(lua, direct, repo_root):
    """No button may point at a module that is not shipped."""
    for button in ("DetectBtn", "CutFrameBtn", "RegroupBtn", "UpscaleBtn", "UpdateBtn"):
        H = load(lua, direct / "Installer" / "Eternal2x.lua")
        H.click(button)
        cmd = H.last_command()
        module = cmd.split("-m ")[1].split()[0]
        rel = Path(module.replace(".", "/") + ".py")
        assert (repo_root / rel).exists(), f"{button} calls missing module {module}"


def test_status_reports_success_when_the_stage_exits_zero(lua, direct):
    H = load(lua, direct / "Installer" / "Eternal2x.lua")
    H.exit_code = 0
    H.click("RegroupBtn")
    assert "finished" in H.status()


def test_status_reports_failure_when_the_stage_exits_nonzero(lua, direct):
    H = load(lua, direct / "Installer" / "Eternal2x.lua")
    H.exit_code = 1
    H.click("RegroupBtn")
    assert "failed" in H.status().lower(), f"status was {H.status()!r}"


def test_clip_path_is_quoted_so_spaces_survive(lua, direct):
    H = load(lua, direct / "Installer" / "Eternal2x.lua",
             clip="/media/My Footage/shot 01.mov")
    H.click("DetectBtn")
    assert '"/media/My Footage/shot 01.mov"' in H.last_command()


def test_upscale_button_forwards_the_sensitivity(lua, direct):
    H = load(lua, direct / "Installer" / "Eternal2x.lua")
    H.set_slider("SensSlider", 80)
    H.click("UpscaleBtn")
    assert "--sensitivity 0.8000" in H.last_command()


def test_auto_update_toggle_persists_to_the_config(lua, direct):
    H = load(lua, direct / "Installer" / "Eternal2x.lua")
    H.widgets["AutoUpdateCB"].Checked = True
    H.window.On["AutoUpdateCB"].Clicked({})

    conf = (direct / "Installer" / "Eternal2x.conf").read_text()
    assert "auto_update=true" in conf
    assert f"repo_root={direct}" in conf, "saving the toggle corrupted repo_root"
    assert "update_url=https://example.com/latest.json" in conf, (
        "saving the toggle dropped the update URL"
    )


def test_the_command_the_ui_builds_actually_runs(lua, direct):
    """Take the exact string the UI would hand to the shell and run it."""
    H = load(lua, direct / "Installer" / "Eternal2x.lua")
    H.click("RegroupBtn")
    cmd = H.last_command()

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    combined = result.stdout + result.stderr
    for missing in ("No module named 'Stages'", "No module named 'Pipeline'"):
        assert missing not in combined, (
            f"the UI's command cannot find the plugin modules.\ncommand: {cmd}\n{combined}"
        )
    assert "Could not import DaVinciResolveScript" in combined, (
        f"expected the stage to reach its Resolve check.\ncommand: {cmd}\n{combined}"
    )
