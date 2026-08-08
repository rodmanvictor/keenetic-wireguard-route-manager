#!/usr/bin/env python3
"""Build the current platform's PackeTech desktop application.

PyInstaller produces the Linux and Windows executable. On macOS the supported
``flet build macos`` pipeline produces the native ``.app`` bundle. Neither
result requires a separately installed Python runtime.
"""

from pathlib import Path
import os
import platform
import shutil
import subprocess
import sys


def main() -> None:
    """Run the supported current-platform build with deterministic paths."""
    root = Path(__file__).resolve().parents[1]
    if sys.platform == 'darwin':
        _build_macos(root)
        return
    separator = ';' if sys.platform == 'win32' else ':'
    application_name = 'PackeTech' if sys.platform == 'win32' else 'packetech'
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
        str(root / 'src' / 'desktop_app.py'),
    ]
    subprocess.run(command, cwd=root, check=True)


def _build_macos(root: Path) -> None:
    """Build a native macOS bundle through Flet's supported Flutter pipeline.

    Args:
        root: Repository root containing ``pyproject.toml`` and the app module.

    Side effects:
        Generates the platform icon in the Flet assets directory and replaces
        ``dist/desktop`` with a native ``PackeTech.app`` bundle.
    """
    from PIL import Image

    icon_source = root / 'assets' / 'branding' / 'paketych-icon.png'
    icon_target = root / 'assets' / 'icon_macos.png'
    with Image.open(icon_source) as icon:
        icon.resize((1024, 1024), Image.Resampling.NEAREST).save(icon_target)

    default_arch = 'arm64' if platform.machine().lower() in {'arm64', 'aarch64'} else 'x64'
    architecture = os.getenv('PACKETECH_MACOS_ARCH', default_arch)
    command = [
        shutil.which('flet') or str(Path(sys.executable).with_name('flet')),
        'build',
        'macos',
        '.',
        '--module-name',
        'desktop_app',
        '--project',
        'packetech',
        '--artifact',
        'PackeTech',
        '--product',
        'PackeTech',
        '--org',
        'ru.rodman',
        '--bundle-id',
        'ru.rodman.packetech',
        '--description',
        'Выбранные сайты через WireGuard на Keenetic',
        '--output',
        'dist/desktop',
        '--python-version',
        '3.12',
        '--arch',
        architecture,
        '--no-rich-output',
        '--yes',
    ]
    subprocess.run(command, cwd=root, check=True)


if __name__ == '__main__':
    main()
