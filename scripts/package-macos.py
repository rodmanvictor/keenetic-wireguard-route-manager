#!/usr/bin/env python3
"""Create a native PackeTech DMG for the current macOS architecture.

The disk image contains the graphical ``PackeTech.app`` bundle and an
``Applications`` shortcut. The standalone synchronizer is embedded into the
bundle so the app can register its six-hour LaunchAgent after onboarding.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import tomllib


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
RELEASE = DIST / 'release'


def _version() -> str:
    """Return the application version declared in ``pyproject.toml``."""
    with (ROOT / 'pyproject.toml').open('rb') as stream:
        return tomllib.load(stream)['project']['version']


def _architecture() -> str:
    """Return a stable release suffix for the native runner architecture."""
    machine = platform.machine().lower()
    if machine in {'arm64', 'aarch64'}:
        return 'arm64'
    if machine in {'x86_64', 'amd64'}:
        return 'x86_64'
    raise RuntimeError(f'Неподдерживаемая архитектура macOS: {machine}')


def _require_builds() -> tuple[Path, Path]:
    """Return the native app bundle and CLI or raise a clear build error.

    Raises:
        FileNotFoundError: If PyInstaller has not produced either build.
    """
    application = DIST / 'desktop' / 'PackeTech.app'
    cli = DIST / 'cli' / 'kwan'
    missing = [str(path.relative_to(ROOT)) for path in (application, cli) if not path.exists()]
    if missing:
        raise FileNotFoundError(f'Сначала соберите: {", ".join(missing)}')
    return application, cli


def build_dmg(application: Path, cli: Path, version: str, architecture: str) -> Path:
    """Create an ad-hoc-signed DMG and return its path.

    Args:
        application: Native PyInstaller ``PackeTech.app`` bundle.
        cli: Native standalone route synchronizer.
        version: Semantic version without a ``v`` prefix.
        architecture: Stable ``arm64`` or ``x86_64`` suffix.

    Side effects:
        Replaces the architecture-specific staging directory, signs the copied
        app bundle ad hoc, and invokes the native ``hdiutil`` packager.
    """
    staging = ROOT / 'build' / f'macos-dmg-{architecture}'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    packaged_app = staging / 'PackeTech.app'
    shutil.copytree(application, packaged_app, symlinks=True)
    embedded_cli = packaged_app / 'Contents' / 'MacOS' / 'kwan'
    shutil.copy2(cli, embedded_cli)
    embedded_cli.chmod(0o755)
    (staging / 'Applications').symlink_to('/Applications')
    (staging / 'ПРОЧТИ МЕНЯ.txt').write_text(
        'PACKETECH ДЛЯ macOS\n\n'
        '1. Перетащите PackeTech.app в Applications.\n'
        '2. В Applications нажмите по PackeTech правой кнопкой и выберите «Открыть».\n'
        '3. Подтвердите первый запуск: сборка бесплатная и пока не нотарифицирована Apple.\n\n'
        'Не запускайте приложение прямо из DMG: фоновое обновление должно ссылаться '
        'на постоянную копию в Applications.\n',
        encoding='utf-8',
    )

    subprocess.run(
        ['codesign', '--force', '--deep', '--sign', '-', str(packaged_app)],
        check=True,
    )
    RELEASE.mkdir(parents=True, exist_ok=True)
    output = RELEASE / f'packetech-{version}-macos-{architecture}.dmg'
    subprocess.run(
        [
            'hdiutil',
            'create',
            '-volname',
            'PackeTech',
            '-srcfolder',
            str(staging),
            '-ov',
            '-format',
            'UDZO',
            str(output),
        ],
        check=True,
    )
    return output


def write_checksum(artifact: Path, architecture: str) -> Path:
    """Write an architecture-specific SHA-256 checksum file."""
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    output = RELEASE / f'SHA256SUMS-macos-{architecture}.txt'
    output.write_text(f'{digest}  {artifact.name}\n', encoding='ascii')
    return output


def main() -> None:
    """Package the current native macOS build and print generated paths."""
    application, cli = _require_builds()
    architecture = _architecture()
    artifact = build_dmg(application, cli, _version(), architecture)
    checksum = write_checksum(artifact, architecture)
    print(artifact)
    print(checksum)


if __name__ == '__main__':
    main()
