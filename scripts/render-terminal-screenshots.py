#!/usr/bin/env python3
"""Render README screenshots from the real PackeTech CLI and TUI output.

The script executes the source-checkout launchers, strips terminal control
sequences, and places their output into a consistent dark terminal frame.  It
does not connect to a router and therefore cannot expose saved credentials.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs' / 'images'
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
FONT_PATH = Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf')
FONT_BOLD_PATH = Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf')


def _run(command: list[str]) -> list[str]:
    """Return clean terminal lines produced by one safe local command.

    Args:
        command: Executable and arguments relative to the project checkout.

    Returns:
        Captured stdout lines without ANSI escape sequences.

    Raises:
        subprocess.CalledProcessError: If the command cannot render its output.
    """
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [ANSI.sub('', line).rstrip() for line in result.stdout.splitlines()]


def _render(filename: str, command_label: str, lines: list[str], *, height: int) -> None:
    """Draw one terminal window around captured application output.

    Args:
        filename: PNG filename below ``docs/images``.
        command_label: Shell command shown above the captured output.
        lines: Captured application output.
        height: Final image height in pixels.

    Side effects:
        Replaces the target PNG with a deterministic 1280-pixel-wide image.
    """
    width = 1280
    image = Image.new('RGB', (width, height), '#080d0a')
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 24, width - 24, height - 24), 22, fill='#101713', outline='#304036', width=2)
    draw.rounded_rectangle((24, 24, width - 24, 86), 22, fill='#18221c')
    draw.rectangle((24, 64, width - 24, 86), fill='#18221c')

    for index, color in enumerate(('#ff6b5f', '#ffcc4a', '#b8f34a')):
        x = 58 + index * 30
        draw.ellipse((x, 45, x + 14, 59), fill=color)
    title_font = ImageFont.truetype(str(FONT_BOLD_PATH), 19)
    body_font = ImageFont.truetype(str(FONT_PATH), 20)
    bold_font = ImageFont.truetype(str(FONT_BOLD_PATH), 20)
    draw.text((width // 2, 52), 'PackeTech Terminal', font=title_font, fill='#9aa69e', anchor='mm')

    x = 58
    y = 112
    draw.text((x, y), '$', font=bold_font, fill='#b8f34a')
    draw.text((x + 28, y), command_label, font=body_font, fill='#f3f7f4')
    y += 46
    for line in lines:
        if y > height - 58:
            break
        font = bold_font if line.startswith('PackeTech') else body_font
        color = '#b8f34a' if line.startswith('PackeTech') else '#d5ddd7'
        draw.text((x, y), line, font=font, fill=color)
        y += 29

    OUTPUT.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT / filename, optimize=True)


def main() -> None:
    """Capture both terminal surfaces and write their README screenshots."""
    cli_lines = _run([str(ROOT / 'bin' / 'packetech'), '--help'])
    tui_lines = _run(
        [
            str(ROOT / '.venv-build' / 'bin' / 'python'),
            '-c',
            (
                'from keenetic_router.apps.tui import render_header, render_menu; '
                'render_header(); render_menu()'
            ),
        ]
    )
    _render('packetech-cli.png', 'packetech --help', cli_lines, height=980)
    _render('packetech-tui.png', 'packetech tui', tui_lines, height=570)
    print(OUTPUT / 'packetech-cli.png')
    print(OUTPUT / 'packetech-tui.png')


if __name__ == '__main__':
    main()
