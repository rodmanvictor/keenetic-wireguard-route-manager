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
    desktop = DIST / 'desktop' / 'packetech'
    cli = DIST / 'cli' / 'packetech-cli'
    missing = [str(path.relative_to(ROOT)) for path in (desktop, cli) if not path.is_file()]
    if missing:
        raise FileNotFoundError(f'Сначала соберите: {", ".join(missing)}')
    return desktop, cli


def _desktop_entry() -> str:
    """Return the freedesktop launcher installed by the Debian package."""
    return '''[Desktop Entry]
Type=Application
Name=PackeTech
Comment=Выбранные сайты через WireGuard
Exec=packetech
Icon=paketych
Terminal=false
Categories=Network;
StartupNotify=true
StartupWMClass=PackeTech
'''


def _unified_launcher(gui_relative_path: str) -> str:
    """Return a shell dispatcher for one build-specific GUI location."""
    return f'''#!/bin/sh
if [ "$#" -eq 0 ] || [ "$1" = "desktop" ] || [ "$1" = "gui" ]; then
    [ "$#" -eq 0 ] || shift
    exec "$(dirname "$0")/{gui_relative_path}" "$@"
fi
PACKETECH_PROG_NAME=packetech exec "$(dirname "$0")/packetech-cli" "$@"
'''


def build_deb(desktop: Path, cli: Path, version: str) -> Path:
    """Build a root-owned Debian package and return its final path."""
    staging = ROOT / 'build' / 'debian' / 'packetech'
    if staging.exists():
        shutil.rmtree(staging)
    control = staging / 'DEBIAN'
    control.mkdir(parents=True)
    control_text = f'''Package: packetech
Version: {version}
Section: net
Priority: optional
Architecture: amd64
Maintainer: Victor Rodin
Depends: libgtk-3-0 | libgtk-3-0t64, libsecret-1-0
Conflicts: paketych
Replaces: paketych
Provides: paketych
Installed-Size: {(desktop.stat().st_size + cli.stat().st_size) // 1024}
Description: Выбранные сайты через WireGuard на Keenetic
 PackeTech добавляет домены и IP-маршруты, импортирует WireGuard,
 автоматически включает SSH через Telnet и обновляет DNS-маршруты.
'''
    (control / 'control').write_text(control_text, encoding='utf-8')

    _copy(desktop, staging / 'usr/lib/packetech/packetech-gui', 0o755)
    _copy(cli, staging / 'usr/bin/packetech-cli', 0o755)
    legacy_cli = staging / 'usr/bin/kwan'
    legacy_cli.symlink_to('packetech-cli')
    launcher = staging / 'usr/bin/packetech'
    launcher.write_text(
        _unified_launcher('../lib/packetech/packetech-gui'),
        encoding='utf-8',
    )
    launcher.chmod(0o755)
    compatibility_link = staging / 'usr/bin/paketych'
    compatibility_link.symlink_to('packetech')
    desktop_entry = staging / 'usr/share/applications/packetech.desktop'
    desktop_entry.parent.mkdir(parents=True, exist_ok=True)
    desktop_entry.write_text(_desktop_entry(), encoding='utf-8')
    desktop_entry.chmod(0o644)

    for icon in sorted((ROOT / 'assets/icons/hicolor').glob('*x*/apps/paketych.png')):
        relative = icon.relative_to(ROOT / 'assets/icons/hicolor')
        _copy(icon, staging / 'usr/share/icons/hicolor' / relative, 0o644)

    for unit in ('paketych-sync.service', 'paketych-sync.timer'):
        _copy(
            ROOT / 'integrations/systemd/user' / unit,
            staging / 'usr/lib/systemd/user' / unit,
            0o644,
        )
    _copy(ROOT / 'README.md', staging / 'usr/share/doc/packetech/README.md', 0o644)
    _copy(ROOT / 'LICENSE', staging / 'usr/share/doc/packetech/copyright', 0o644)
    for directory in staging.rglob('*'):
        if directory.is_dir():
            directory.chmod(0o755)

    RELEASE.mkdir(parents=True, exist_ok=True)
    output = RELEASE / f'packetech_{version}_amd64.deb'
    subprocess.run(
        ['dpkg-deb', '--root-owner-group', '--build', str(staging), str(output)],
        check=True,
    )
    return output


def build_portable(desktop: Path, cli: Path, version: str) -> Path:
    """Create a tar.gz with two runnable files and a short launch guide."""
    staging = ROOT / 'build' / 'portable' / 'packetech'
    if staging.parent.exists():
        shutil.rmtree(staging.parent)
    staging.mkdir(parents=True)
    _copy(desktop, staging / 'lib/packetech/packetech-gui', 0o755)
    _copy(cli, staging / 'packetech-cli', 0o755)
    launcher = staging / 'packetech'
    launcher.write_text(
        _unified_launcher('lib/packetech/packetech-gui'),
        encoding='utf-8',
    )
    launcher.chmod(0o755)
    (staging / 'README.txt').write_text(
        'PackeTech для Linux x86-64\n\n'
        'GUI: дважды щёлкните packetech или запустите ./packetech\n'
        'CLI: ./packetech --help\n'
        'TUI: ./packetech tui\n\n'
        'Настройки: ~/.config/keenetic-route-manager/config.json\n'
        'База: ~/.local/share/keenetic-route-manager/route-sync.sqlite3\n',
        encoding='utf-8',
    )
    RELEASE.mkdir(parents=True, exist_ok=True)
    output = RELEASE / f'packetech-{version}-linux-x86_64.tar.gz'
    with tarfile.open(output, 'w:gz') as archive:
        archive.add(staging, arcname='packetech')
    return output


def write_checksums(paths: list[Path]) -> Path:
    """Write SHA-256 checksums for release verification."""
    output = RELEASE / 'SHA256SUMS-linux.txt'
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
