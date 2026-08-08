#!/usr/bin/env python3
"""Create installable and portable Linux x86-64 release artifacts.

The Debian package installs the GUI, standalone CLI, adaptive hicolor icons,
desktop entry, and an optional six-hour user timer.  The portable archive keeps
the two executables and a short launch guide without changing the host system.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile
import tomllib


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
RELEASE = DIST / 'release'


def _copy(source: Path, destination: Path, mode: int | None = None) -> None:
    """Copy one release file, creating parents and optionally setting its mode."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if mode is not None:
        destination.chmod(mode)


def _version() -> str:
    """Return the application version declared in ``pyproject.toml``."""
    with (ROOT / 'pyproject.toml').open('rb') as stream:
        return tomllib.load(stream)['project']['version']


def _require_builds() -> tuple[Path, Path]:
    """Return desktop and CLI executables or raise a clear build error."""
    desktop = DIST / 'desktop' / 'paketych'
    cli = DIST / 'cli' / 'kwan'
    missing = [str(path.relative_to(ROOT)) for path in (desktop, cli) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f'Сначала соберите: {", ".join(missing)}')
    return desktop, cli


def _desktop_entry() -> str:
    """Return the freedesktop launcher installed by the Debian package."""
    return '''[Desktop Entry]
Type=Application
Name=Пакетыч
Comment=Выбранные сайты через WireGuard
Exec=paketych
Icon=paketych
Terminal=false
Categories=Network;
StartupNotify=true
StartupWMClass=Пакетыч
'''


def build_deb(desktop: Path, cli: Path, version: str) -> Path:
    """Build a root-owned Debian package and return its final path."""
    staging = ROOT / 'build' / 'debian' / 'paketych'
    if staging.exists():
        shutil.rmtree(staging)
    control = staging / 'DEBIAN'
    control.mkdir(parents=True)
    control_text = f'''Package: paketych
Version: {version}
Section: net
Priority: optional
Architecture: amd64
Maintainer: Viktor Rodin
Depends: libgtk-3-0 | libgtk-3-0t64, libsecret-1-0
Installed-Size: {(desktop.stat().st_size + cli.stat().st_size) // 1024}
Description: Выбранные сайты через WireGuard на Keenetic
 Пакетыч добавляет домены и IP-маршруты, импортирует WireGuard,
 автоматически включает SSH через Telnet и обновляет DNS-маршруты.
'''
    (control / 'control').write_text(control_text, encoding='utf-8')

    _copy(desktop, staging / 'usr/lib/paketych/paketych', 0o755)
    _copy(cli, staging / 'usr/bin/kwan', 0o755)
    link = staging / 'usr/bin/paketych'
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to('../lib/paketych/paketych')
    launcher = staging / 'usr/share/applications/paketych.desktop'
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(_desktop_entry(), encoding='utf-8')
    launcher.chmod(0o644)

    for icon in sorted((ROOT / 'assets/icons/hicolor').glob('*x*/apps/paketych.png')):
        relative = icon.relative_to(ROOT / 'assets/icons/hicolor')
        _copy(icon, staging / 'usr/share/icons/hicolor' / relative, 0o644)

    for unit in ('paketych-sync.service', 'paketych-sync.timer'):
        _copy(
            ROOT / 'integrations/systemd/user' / unit,
            staging / 'usr/lib/systemd/user' / unit,
            0o644,
        )
    _copy(ROOT / 'README.md', staging / 'usr/share/doc/paketych/README.md', 0o644)
    _copy(ROOT / 'LICENSE', staging / 'usr/share/doc/paketych/copyright', 0o644)
    for directory in staging.rglob('*'):
        if directory.is_dir():
            directory.chmod(0o755)

    RELEASE.mkdir(parents=True, exist_ok=True)
    output = RELEASE / f'paketych_{version}_amd64.deb'
    subprocess.run(
        ['dpkg-deb', '--root-owner-group', '--build', str(staging), str(output)],
        check=True,
    )
    return output


def build_portable(desktop: Path, cli: Path, version: str) -> Path:
    """Create a tar.gz with two runnable files and a short launch guide."""
    staging = ROOT / 'build' / 'portable' / 'paketych'
    if staging.parent.exists():
        shutil.rmtree(staging.parent)
    staging.mkdir(parents=True)
    _copy(desktop, staging / 'paketych', 0o755)
    _copy(cli, staging / 'kwan', 0o755)
    (staging / 'README.txt').write_text(
        'Пакетыч для Linux x86-64\n\n'
        'GUI: дважды щёлкните paketych или запустите ./paketych\n'
        'CLI: ./kwan --help\n\n'
        'Настройки: ~/.config/keenetic-route-manager/config.json\n'
        'База: ~/.local/share/keenetic-route-manager/route-sync.sqlite3\n',
        encoding='utf-8',
    )
    RELEASE.mkdir(parents=True, exist_ok=True)
    output = RELEASE / f'paketych-{version}-linux-x86_64.tar.gz'
    with tarfile.open(output, 'w:gz') as archive:
        archive.add(staging, arcname='paketych')
    return output


def write_checksums(paths: list[Path]) -> Path:
    """Write SHA-256 checksums for release verification."""
    output = RELEASE / 'SHA256SUMS'
    lines = []
    for path in paths:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f'{digest}  {path.name}')
    output.write_text('\n'.join(lines) + '\n', encoding='ascii')
    return output


def main() -> None:
    """Build both Linux package formats from the current native binaries."""
    desktop, cli = _require_builds()
    version = _version()
    artifacts = [build_deb(desktop, cli, version), build_portable(desktop, cli, version)]
    checksum = write_checksums(artifacts)
    for path in (*artifacts, checksum):
        print(path)


if __name__ == '__main__':
    main()
