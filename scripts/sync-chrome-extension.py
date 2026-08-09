#!/usr/bin/env python3
"""Synchronize Chrome extension assets and packaged resources.

The editable extension lives under ``integrations/chrome/extension`` while
PyInstaller reads the mirrored package directory.  This command also installs
the adaptive mascot icons already produced for desktop sizes, preventing the
two copies and Chrome toolbar artwork from drifting apart.
"""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "integrations" / "chrome" / "extension"
PACKAGE = ROOT / "src" / "keenetic_router" / "chrome_extension"
ICON_ROOT = ROOT / "assets" / "icons" / "hicolor"


def main() -> None:
    """Refresh adaptive icons and make the package copy byte-identical."""
    for size in (16, 32, 48, 128):
        source_icon = ICON_ROOT / f"{size}x{size}" / "apps" / "paketych.png"
        target_icon = SOURCE / "icons" / f"icon{size}.png"
        shutil.copy2(source_icon, target_icon)

    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    shutil.copytree(SOURCE, PACKAGE)
    print(f"Chrome extension synchronized: {SOURCE} -> {PACKAGE}")


if __name__ == "__main__":
    main()
