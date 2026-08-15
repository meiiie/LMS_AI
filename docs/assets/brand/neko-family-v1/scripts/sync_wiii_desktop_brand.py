"""Synchronize the approved Neko Peek identity into Wiii Desktop.

The explicit --apply flag prevents accidental writes when the script is only
being inspected. Run the exporter and verifier before this script.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parents[3]
DESKTOP = REPOSITORY / "wiii-desktop"
PUBLIC = DESKTOP / "public"
TAURI_ICONS = DESKTOP / "src-tauri" / "icons"
PNG_DIR = ROOT / "logo" / "png"


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    print(f"Synced {source.relative_to(REPOSITORY)} -> {destination.relative_to(REPOSITORY)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write approved assets into Wiii Desktop")
    args = parser.parse_args()
    if not args.apply:
        raise SystemExit("Dry stop: pass --apply to synchronize Wiii Desktop brand assets")

    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_neko_family.py")],
        cwd=REPOSITORY,
        check=True,
    )

    _copy(ROOT / "mascot" / "neko-peek-master.png", PUBLIC / "wiii-mascot-full.png")
    _copy(PNG_DIR / "neko-peek-icon-180.png", PUBLIC / "apple-touch-icon.png")
    _copy(PNG_DIR / "neko-peek-icon-192.png", PUBLIC / "icon-192.png")
    _copy(PNG_DIR / "neko-peek-icon-512.png", PUBLIC / "icon-512.png")
    _copy(ROOT / "logo" / "neko-peek.ico", PUBLIC / "favicon.ico")
    _copy(PNG_DIR / "neko-peek-app-icon-master.png", TAURI_ICONS / "wiii-mascot-app-icon.png")

    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        raise SystemExit("npx was not found; cannot generate Tauri platform icons")
    subprocess.run(
        [
            npx,
            "tauri",
            "icon",
            str(PNG_DIR / "neko-peek-app-icon-master.png"),
            "--output",
            str(TAURI_ICONS),
        ],
        cwd=DESKTOP,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(DESKTOP / "scripts" / "render_wiii_installer_brand.py")],
        cwd=DESKTOP,
        check=True,
    )
    print("Wiii Desktop now uses the approved Neko Peek identity")


if __name__ == "__main__":
    main()
