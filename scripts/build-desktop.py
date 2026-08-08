#!/usr/bin/env python3
"""Build the current platform's PackeTech desktop application.

PyInstaller bundles the Python application, Flet desktop runtime, and packaged
brand assets. This path produces a native executable (and a macOS ``.app``
bundle) without requiring a separately installed Python runtime.
"""

from pathlib import Path
import subprocess
import sys


def main() -> None:
    """Run PyInstaller with deterministic current-platform output paths."""
    root = Path(__file__).resolve().parents[1]
    separator = ';' if sys.platform == 'win32' else ':'
    application_name = (
        'PackeTech' if sys.platform in {'win32', 'darwin'} else 'packetech'
    )
    macos_options = (
        ['--osx-bundle-identifier', 'ru.rodman.packetech']
        if sys.platform == 'darwin'
        else []
    )
    command = [
        sys.executable,
        '-m',
        'PyInstaller',
        '--noconfirm',
        '--clean',
        '--onefile',
        '--windowed',
        '--name',
        application_name,
        '--paths',
        str(root / 'src'),
        '--collect-all',
        'flet_desktop',
        '--icon',
        str(root / 'assets' / 'icons' / 'hicolor' / '512x512' / 'apps' / 'paketych.png'),
        '--add-data',
        f'{root / "src" / "keenetic_router" / "assets"}{separator}keenetic_router/assets',
        '--distpath',
        str(root / 'dist' / 'desktop'),
        '--workpath',
        str(root / 'build' / 'pyinstaller-desktop'),
        '--specpath',
        str(root / 'build'),
        *macos_options,
        str(root / 'src' / 'desktop_app.py'),
    ]
    subprocess.run(command, cwd=root, check=True)


if __name__ == '__main__':
    main()
