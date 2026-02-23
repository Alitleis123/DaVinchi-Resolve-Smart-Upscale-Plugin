from __future__ import annotations

from pathlib import Path
import shutil


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    dist_root = repo_root / "dist" / "Eternal2x"

    if dist_root.exists():
        shutil.rmtree(dist_root)

    dist_root.mkdir(parents=True, exist_ok=True)

    # Copy runtime files
    shutil.copy2(repo_root / "Installer" / "Eternal2x.lua", dist_root / "Eternal2x.lua")
    shutil.copytree(repo_root / "Stages", dist_root / "Stages")
    shutil.copytree(repo_root / "Pipeline", dist_root / "Pipeline")

    readme = dist_root / "README-DragDrop.txt"
    readme.write_text(
        "Eternal2x Drag & Drop Install\n"
        "\n"
        "1) Copy the entire Eternal2x folder into Resolve's Scripts/Comp folder.\n"
        "2) Restart Resolve.\n"
        "3) Open Workspace -> Scripts -> Eternal2x.\n"
        "\n"
        "Resolve Scripts/Comp locations:\n"
        "macOS: ~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Comp/\n"
        "Windows: %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Fusion\\Scripts\\Comp\\\n",
        encoding="utf-8",
    )

    print(f"Built drag & drop package at: {dist_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
