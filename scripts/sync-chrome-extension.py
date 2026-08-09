#!/usr/bin/env python3
"""Synchronize Chrome extension assets and packaged resources.

The editable extension lives under ``integrations/chrome/extension`` while
PyInstaller reads the mirrored package directory.  This command also installs
the adaptive mascot icons already produced for desktop sizes, preventing the
two copies and Chrome toolbar artwork from drifting apart.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "integrations" / "chrome" / "extension"
PACKAGE = ROOT / "src" / "keenetic_router" / "chrome_extension"
ICON_ROOT = ROOT / "assets" / "icons" / "hicolor"


def render_toolbar_icon(size: int, target: Path) -> None:
    """Render the white route mark with supersampling for crisp small edges."""
    supersampling = 8
    canvas_size = size * supersampling
    unit = canvas_size / 24
    image = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    stroke = max(1, round(2.5 * unit))

    def point(x: float, y: float) -> tuple[int, int]:
        """Convert a point in the shared 24-unit icon grid to pixels."""
        return round(x * unit), round(y * unit)

    center_x, center_y = point(5, 5)
    radius = round(2 * unit)
    draw.ellipse(
        (center_x - radius, center_y - radius, center_x + radius, center_y + radius),
        fill="white",
    )

    # Rounded route: down from the source, around one corner, then to the arrow.
    route = [point(5, 8), point(5, 10)]
    for step in range(1, 9):
        angle = 180 - (90 * step / 8)
        radians = math.radians(angle)
        route.append(point(9 + 4 * math.cos(radians), 10 + 4 * math.sin(radians)))
    route.append(point(17, 14))
    draw.line(route, fill="white", width=stroke, joint="curve")
    draw.line([point(13, 10), point(17, 14), point(13, 18)], fill="white", width=stroke, joint="curve")

    image.resize((size, size), Image.Resampling.LANCZOS).save(target, optimize=True)


def main() -> None:
    """Refresh adaptive icons and make the package copy byte-identical."""
    for size in (16, 32, 48, 128):
        source_icon = ICON_ROOT / f"{size}x{size}" / "apps" / "paketych.png"
        target_icon = SOURCE / "icons" / f"icon{size}.png"
        shutil.copy2(source_icon, target_icon)

    for size in (16, 32, 48):
        render_toolbar_icon(size, SOURCE / "icons" / f"toolbar{size}.png")

    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    shutil.copytree(SOURCE, PACKAGE)
    print(f"Chrome extension synchronized: {SOURCE} -> {PACKAGE}")


if __name__ == "__main__":
    main()
