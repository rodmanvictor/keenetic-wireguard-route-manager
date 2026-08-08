#!/usr/bin/env python3
"""Build a native standalone ``kwan`` command for the current platform.

The script deliberately performs a native build: Windows, macOS, and Linux
executables are produced on their corresponding GitHub Actions runners.
"""

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
        'kwan',
        '--distpath',
        str(root / 'dist' / 'cli'),
        '--workpath',
        str(root / 'build' / 'pyinstaller'),
        '--specpath',
        str(root / 'build'),
        str(root / 'scripts' / 'kwan-entry.py'),
    ]
    subprocess.run(command, cwd=root, check=True)


if __name__ == '__main__':
    main()
