#!/usr/bin/env python3
"""Prepare adaptive PNG assets from approved transparent brand masters.

The large mascot is retained for documentation and onboarding.  The compact
portrait is exported twice: with the cable lamp for medium and large surfaces,
and as a tighter face crop for Linux icon-theme sizes up to 64 pixels.

Args:
    --mascot-source: Transparent RGBA master with the full courier artwork.
    --icon-source: Transparent RGBA master with the compact portrait artwork.

Side effects:
    Replaces generated branding assets under ``assets/`` and packaged runtime
    copies under ``src/keenetic_router/assets``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / 'assets' / 'branding'
HICOLOR = ROOT / 'assets' / 'icons' / 'hicolor'
PACKAGE_ASSETS = ROOT / 'src' / 'keenetic_router' / 'assets'
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def _clean_transparency(image: Image.Image) -> Image.Image:
    """Return RGBA artwork with residual magenta spill made transparent."""
    rgba = image.convert('RGBA')
    cleaned = []
    pixels = (
        rgba.get_flattened_data()
        if hasattr(rgba, 'get_flattened_data')
        else rgba.getdata()
    )
    for red, green, blue, alpha in pixels:
        magenta = (
            red > 120
            and blue > 120
            and red > green * 1.45
            and blue > green * 1.35
            and abs(red - blue) < 95
        )
        cleaned.append((red, green, blue, 0 if magenta else alpha))
    rgba.putdata(cleaned)
    return rgba


def _square_artwork(
    image: Image.Image,
    size: int,
    *,
    padding: float,
    compact_face: bool = False,
) -> Image.Image:
    """Crop visible artwork, center it on a square, and resize with hard pixels.

    Args:
        image: Transparent source artwork.
        size: Final square side in pixels.
        padding: Empty border as a fraction of the destination side.
        compact_face: Exclude the lamp-side area for tiny icon-theme exports.

    Returns:
        A transparent square RGBA image.

    Raises:
        ValueError: If the supplied image contains no visible pixels.
    """
    source = _clean_transparency(image)
    bounds = source.getchannel('A').getbbox()
    if bounds is None:
        raise ValueError('Source artwork has no visible pixels')
    left, top, right, bottom = bounds
    if compact_face:
        width = right - left
        right = left + round(width * 0.78)
    artwork = source.crop((left, top, right, bottom))
    usable = max(1, round(size * (1 - 2 * padding)))
    scale = min(usable / artwork.width, usable / artwork.height)
    target = (max(1, round(artwork.width * scale)), max(1, round(artwork.height * scale)))
    resized = artwork.resize(target, Image.Resampling.NEAREST)
    canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(resized, ((size - target[0]) // 2, (size - target[1]) // 2))
    return canvas


def _save(image: Image.Image, path: Path) -> None:
    """Write one optimized RGBA PNG and create its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format='PNG', optimize=True)


def _preview(mascot: Image.Image, icon: Image.Image) -> Image.Image:
    """Build a dark presentation sheet for visual size verification."""
    width, height = 1440, 760
    canvas = Image.new('RGB', (width, height), '#0B0E0C')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype('DejaVuSans.ttf', 24)
    small_font = ImageFont.truetype('DejaVuSans.ttf', 18)
    draw.text((56, 42), 'ПАКЕТЫЧ · АДАПТИВНЫЙ ЛОГОТИП', fill='#B8F34A', font=font)
    draw.text((56, 82), 'Крупный маскот', fill='#899487', font=small_font)
    large = _square_artwork(mascot, 500, padding=0.04)
    canvas.paste(large, (24, 130), large)

    x = 540
    for size in (256, 128, 64, 48, 32, 24, 16):
        display = max(size, 64)
        adaptive = _square_artwork(icon, size, padding=0.06, compact_face=size <= 64)
        if display != size:
            adaptive = adaptive.resize((display, display), Image.Resampling.NEAREST)
        canvas.paste(adaptive, (x, 180 + (256 - display) // 2), adaptive)
        label = f'{size} px'
        draw.text((x, 470), label, fill='#F2F6EE', font=small_font)
        x += display + 18
    draw.text(
        (610, 550),
        'В малых размерах остаются лицо, фуражка и усы;\nлампа возвращается с 128 px.',
        fill='#899487',
        font=small_font,
        spacing=8,
    )
    return canvas


def main() -> None:
    """Parse source paths and generate every checked-in branding derivative."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--mascot-source', type=Path, required=True)
    parser.add_argument('--icon-source', type=Path, required=True)
    args = parser.parse_args()

    mascot_source = Image.open(args.mascot_source)
    icon_source = Image.open(args.icon_source)
    mascot = _square_artwork(mascot_source, 1024, padding=0.035)
    icon = _square_artwork(icon_source, 512, padding=0.055)
    tiny_icon = _square_artwork(icon_source, 256, padding=0.045, compact_face=True)

    _save(mascot, BRANDING / 'paketych-mascot.png')
    _save(icon, BRANDING / 'paketych-icon.png')
    _save(tiny_icon, BRANDING / 'paketych-icon-small.png')
    _save(icon, ROOT / 'assets' / 'icon.png')
    _save(mascot, PACKAGE_ASSETS / 'paketych-mascot.png')
    _save(icon, PACKAGE_ASSETS / 'paketych-icon.png')
    _save(tiny_icon, PACKAGE_ASSETS / 'paketych-icon-small.png')

    for size in ICON_SIZES:
        themed = _square_artwork(
            icon_source,
            size,
            padding=0.04 if size <= 64 else 0.055,
            compact_face=size <= 64,
        )
        _save(themed, HICOLOR / f'{size}x{size}' / 'apps' / 'paketych.png')

    _save(_preview(mascot_source, icon_source), BRANDING / 'paketych-size-preview.png')


if __name__ == '__main__':
    main()
