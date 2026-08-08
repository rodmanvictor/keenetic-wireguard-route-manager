#!/usr/bin/env python3
"""Build the current platform's standalone ``packetech-cli`` command."""

from pathlib import Path
import subprocess
import sys


def main():
    """Run PyInstaller with deterministic project-local output folders."""
    root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        '-m',
        'PyInstaller',
        '--noconfirm',
        '--clean',
        '--onefile',
        '--name',
        'PackeTech-CLI' if sys.platform == 'win32' else 'packetech-cli',
        '--distpath',
        str(root / 'dist' / 'cli'),
        '--workpath',
        str(root / 'build' / 'pyinstaller'),
        '--specpath',
        str(root / 'build'),
        str(root / 'scripts' / 'packetech-cli-entry.py'),
    ]
    subprocess.run(command, cwd=root, check=True)


if __name__ == '__main__':
    main()
