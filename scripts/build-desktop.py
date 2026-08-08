#!/usr/bin/env python3
"""Build the Linux desktop application as one self-contained executable.

PyInstaller bundles the Python application, Flet desktop runtime, and packaged
brand assets.  Unlike ``flet build linux``, this path does not require a local
Clang/GTK development toolchain.
"""

from pathlib import Path
import subprocess
import sys


def main() -> None:
    """Run PyInstaller with deterministic Linux desktop output paths."""
    root = Path(__file__).resolve().parents[1]
    separator = ';' if sys.platform == 'win32' else ':'
    command = [
        sys.executable,
        '-m',
        'PyInstaller',
        '--noconfirm',
        '--clean',
        '--onefile',
        '--windowed',
        '--name',
        'paketych',
        '--paths',
        str(root / 'src'),
        '--collect-all',
        'flet_desktop',
        '--add-data',
        f'{root / "src" / "keenetic_router" / "assets"}{separator}keenetic_router/assets',
        '--distpath',
        str(root / 'dist' / 'desktop'),
        '--workpath',
        str(root / 'build' / 'pyinstaller-desktop'),
        '--specpath',
        str(root / 'build'),
        str(root / 'src' / 'desktop_app.py'),
    ]
    subprocess.run(command, cwd=root, check=True)


if __name__ == '__main__':
    main()
