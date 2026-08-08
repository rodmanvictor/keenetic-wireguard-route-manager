#!/usr/bin/env python3
"""Build the current platform's standalone Chrome Native Messaging helper."""

from pathlib import Path
import subprocess
import sys


def main():
    """Run PyInstaller with a stable platform-specific helper filename."""
    root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        '-m',
        'PyInstaller',
        '--noconfirm',
        '--clean',
        '--onefile',
        '--name',
        'PackeTech-Chrome-Host' if sys.platform == 'win32' else 'packetech-chrome-host',
        '--distpath',
        str(root / 'dist' / 'chrome-host'),
        '--workpath',
        str(root / 'build' / 'pyinstaller-chrome-host'),
        '--specpath',
        str(root / 'build'),
        str(root / 'scripts' / 'packetech-chrome-host-entry.py'),
    ]
    subprocess.run(command, cwd=root, check=True)


if __name__ == '__main__':
    main()
