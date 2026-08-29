"""The installer: where files land and whether the config it writes is usable."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from Installer import install_eternal2x as inst


def read_conf(path: Path) -> dict:
    conf = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip()
    return conf


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


# --------------------------------------------------------------------------
# install locations
# --------------------------------------------------------------------------

def test_comp_dir_matches_the_documented_mac_path(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    expected = (fake_home / "Library" / "Application Support" / "Blackmagic Design"
                / "DaVinci Resolve" / "Fusion" / "Scripts" / "Comp")
    assert inst._resolve_comp_dir() == expected


def test_comp_dir_matches_the_documented_windows_path(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    got = inst._resolve_comp_dir()
    assert got.parts[-6:] == ("Blackmagic Design", "DaVinci Resolve", "Fusion",
                              "Scripts", "Comp")[-6:] or got.name == "Comp"
    assert "Blackmagic Design" in str(got)


def test_comp_dir_requires_appdata_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)
    with pytest.raises(RuntimeError, match="APPDATA"):
        inst._resolve_comp_dir()


def test_prefers_a_project_venv_interpreter(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n")
    assert inst._pick_python(tmp_path) == str(venv_python)


def test_falls_back_to_a_system_interpreter(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    picked = inst._pick_python(tmp_path)
    assert picked and Path(picked).name.startswith("python")


# --------------------------------------------------------------------------
# a full install
# --------------------------------------------------------------------------

def test_install_writes_launcher_and_config(fake_home, monkeypatch, capsys, repo_root):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert inst.main() == 0

    comp = inst._resolve_comp_dir()
    assert (comp / "Eternal2x.lua").exists(), "launcher was not installed"
    assert (comp / "Eternal2x.conf").exists(), "config was not written"


def test_installed_config_has_every_key_the_ui_reads(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    inst.main()
    conf = read_conf(inst._resolve_comp_dir() / "Eternal2x.conf")
    for key in ("repo_root", "python", "update_url", "auto_update"):
        assert key in conf, f"config is missing {key}; the UI reads it"


def test_installed_repo_root_contains_the_stages_package(fake_home, monkeypatch):
    """`repo_root` must be the folder a `python -m Stages.x` call can run from."""
    monkeypatch.setattr(sys, "platform", "darwin")
    inst.main()
    conf = read_conf(inst._resolve_comp_dir() / "Eternal2x.conf")
    root = Path(conf["repo_root"])
    assert (root / "Stages" / "__init__.py").exists(), (
        f"repo_root={root} does not contain the Stages package"
    )
    assert (root / "Pipeline" / "config.py").exists()


def test_the_installed_config_actually_runs_a_stage(fake_home, monkeypatch):
    """Use the installed repo_root + python to invoke a stage, as the UI does."""
    monkeypatch.setattr(sys, "platform", "darwin")
    inst.main()
    conf = read_conf(inst._resolve_comp_dir() / "Eternal2x.conf")

    result = subprocess.run(
        [conf["python"], "-m", "Stages.resolve_regroup"],
        cwd=conf["repo_root"], capture_output=True, text=True,
    )
    combined = result.stdout + result.stderr
    assert "No module named 'Stages'" not in combined, combined


def test_installed_update_url_is_https_and_points_at_latest_json(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    inst.main()
    conf = read_conf(inst._resolve_comp_dir() / "Eternal2x.conf")
    assert conf["update_url"].startswith("https://")
    assert conf["update_url"].endswith("latest.json")


def test_reinstall_is_idempotent(fake_home, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    inst.main()
    conf_path = inst._resolve_comp_dir() / "Eternal2x.conf"
    first = conf_path.read_text()
    inst.main()
    assert conf_path.read_text() == first


def test_install_reports_where_things_went(fake_home, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "darwin")
    inst.main()
    out = capsys.readouterr().out
    assert "Launcher:" in out and "Config:" in out
    assert "Restart Resolve" in out


# --------------------------------------------------------------------------
# the launcher the installer copies
# --------------------------------------------------------------------------

def test_the_installed_launcher_can_find_the_ui_script(fake_home, monkeypatch, repo_root):
    """The launcher forwards to repo_root/Installer/Eternal2x.lua -- it must exist."""
    monkeypatch.setattr(sys, "platform", "darwin")
    inst.main()
    conf = read_conf(inst._resolve_comp_dir() / "Eternal2x.conf")
    ui_script = Path(conf["repo_root"]) / "Installer" / "Eternal2x.lua"
    assert ui_script.exists(), f"launcher would look for {ui_script}, which is missing"


def test_the_launcher_hands_its_config_down_to_the_ui_script(fake_home, monkeypatch,
                                                             repo_root):
    """The config lives beside the launcher, the UI script lives elsewhere.

    Installer/Eternal2x.lua resolves paths relative to itself, so the launcher
    has to pass the config location down rather than let the UI guess. Without
    that handoff the UI treats its own Installer/ folder as the repo root, which
    has no Stages package and every button fails.
    """
    monkeypatch.setattr(sys, "platform", "darwin")
    inst.main()

    launcher = (repo_root / "Installer" / "Eternal2xLauncher.lua").read_text()
    ui = (repo_root / "Installer" / "Eternal2x.lua").read_text()

    assert "ETERNAL2X_CONF" in launcher, "launcher does not pass the config path down"
    assert "ETERNAL2X_CONF" in ui, "UI script does not read the passed-in config path"
