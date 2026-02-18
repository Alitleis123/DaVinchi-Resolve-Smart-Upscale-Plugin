from __future__ import annotations

from pathlib import Path
import shutil
import sys


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    src_lua = repo_root / "Installer" / "Eternal2x.lua"

    if not src_lua.exists():
        print(f"Missing UI script: {src_lua}")
        return 1

    dest_dir = (
        Path.home()
        / "Library"
        / "Application Support"
        / "Blackmagic Design"
        / "DaVinci Resolve"
        / "Fusion"
        / "Scripts"
        / "Comp"
    )

    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_lua = dest_dir / "Eternal2x.lua"
    shutil.copy2(src_lua, dest_lua)

    venv_python = repo_root / ".venv" / "bin" / "python"
    python_path = venv_python if venv_python.exists() else shutil.which("python3") or "python3"

    conf_path = dest_dir / "Eternal2x.conf"
    conf_path.write_text(
        f"repo_root={repo_root}\npython={python_path}\n",
        encoding="utf-8",
    )

    print("Installed Eternal2x script panel.")
    print(f"Script: {dest_lua}")
    print(f"Config: {conf_path}")
    print("Restart Resolve to see Workspace > Scripts > Eternal2x.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
