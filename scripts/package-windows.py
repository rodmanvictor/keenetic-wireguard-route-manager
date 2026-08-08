#!/usr/bin/env python3
"""Create a portable Windows x86-64 release archive.

The archive contains the graphical application, the standalone synchronization
command, and a short Russian launch guide. Both executables are built on a
native Windows GitHub Actions runner and need no separately installed Python.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import tomllib


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
RELEASE = DIST / 'release'


def _version() -> str:
    """Return the application version declared in ``pyproject.toml``."""
    with (ROOT / 'pyproject.toml').open('rb') as stream:
        return tomllib.load(stream)['project']['version']


def _require_builds() -> tuple[Path, Path]:
    """Return Windows GUI and CLI executables or raise a clear build error.

    Raises:
        FileNotFoundError: If PyInstaller has not produced either executable.
    """
    desktop = DIST / 'desktop' / 'paketych.exe'
    cli = DIST / 'cli' / 'kwan.exe'
    missing = [str(path.relative_to(ROOT)) for path in (desktop, cli) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f'Сначала соберите: {", ".join(missing)}')
    return desktop, cli


def build_archive(desktop: Path, cli: Path, version: str) -> Path:
    """Create the Windows ZIP and return its path.

    Args:
        desktop: Frozen graphical application produced on Windows.
        cli: Frozen console synchronizer produced on Windows.
        version: Semantic application version without a ``v`` prefix.

    Side effects:
        Replaces the Windows staging directory and release archive.
    """
    staging = ROOT / 'build' / 'portable-windows' / 'Пакетыч'
    if staging.parent.exists():
        shutil.rmtree(staging.parent)
    staging.mkdir(parents=True)
    shutil.copy2(desktop, staging / 'Пакетыч.exe')
    shutil.copy2(cli, staging / 'kwan.exe')
    (staging / 'ПРОЧТИ МЕНЯ.txt').write_text(
        'ПАКЕТЫЧ ДЛЯ WINDOWS 10 И 11\n\n'
        '1. Запустите «Пакетыч.exe».\n'
        '2. Если Windows покажет SmartScreen, нажмите «Подробнее» → «Выполнить в любом случае».\n'
        '3. Введите адрес, логин и пароль администратора Keenetic.\n\n'
        'Не переносите один EXE отдельно: kwan.exe нужен для обновления маршрутов каждые 6 часов.\n'
        'Настройки: %APPDATA%\\KeeneticRouteManager\\config.json\n'
        'База: %LOCALAPPDATA%\\KeeneticRouteManager\\route-sync.sqlite3\n',
        encoding='utf-8-sig',
    )
    RELEASE.mkdir(parents=True, exist_ok=True)
    base = RELEASE / f'paketych-{version}-windows-x86_64'
    archive = Path(shutil.make_archive(str(base), 'zip', staging.parent, staging.name))
    return archive


def write_checksum(archive: Path) -> Path:
    """Write a release-safe SHA-256 file whose name cannot clash with Linux."""
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    output = RELEASE / 'SHA256SUMS-windows.txt'
    output.write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    return output


def main() -> None:
    """Package both Windows executables and print generated artifact paths."""
    desktop, cli = _require_builds()
    archive = build_archive(desktop, cli, _version())
    checksum = write_checksum(archive)
    print(archive)
    print(checksum)


if __name__ == '__main__':
    main()
