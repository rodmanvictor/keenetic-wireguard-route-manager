#!/usr/bin/env python3
"""Create one universal PackeTech DMG for Apple Silicon and Intel Macs.

The disk image contains the graphical ``PackeTech.app`` bundle and an
``Applications`` shortcut. The standalone synchronizer is embedded into the
bundle so the app can register its six-hour LaunchAgent after onboarding.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
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


def _require_builds() -> tuple[Path, Path, Path]:
    """Return the universal app and both native CLIs or raise a clear error.

    Raises:
        FileNotFoundError: If Flet or PyInstaller has not produced every build.
    """
    application = DIST / 'desktop' / 'PackeTech.app'
    arm_cli = DIST / 'cli' / 'kwan-arm64'
    intel_cli = DIST / 'cli' / 'kwan-x86_64'
    required = (application, arm_cli, intel_cli)
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f'Сначала соберите: {", ".join(missing)}')
    return application, arm_cli, intel_cli


def build_dmg(application: Path, arm_cli: Path, intel_cli: Path, version: str) -> Path:
    """Create an ad-hoc-signed DMG and return its path.

    Args:
        application: Universal Flet ``PackeTech.app`` bundle.
        arm_cli: Native standalone route synchronizer for Apple Silicon.
        intel_cli: Native standalone route synchronizer for Intel.
        version: Semantic version without a ``v`` prefix.

    Side effects:
        Replaces the universal staging directory, embeds both CLI builds plus a
        tiny architecture selector, signs the app ad hoc, and invokes hdiutil.
    """
    staging = ROOT / 'build' / 'macos-dmg-universal'
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    packaged_app = staging / 'PackeTech.app'
    shutil.copytree(application, packaged_app, symlinks=True)
    executable_dir = packaged_app / 'Contents' / 'MacOS'
    embedded_arm_cli = executable_dir / 'kwan-arm64'
    embedded_intel_cli = executable_dir / 'kwan-x86_64'
    shutil.copy2(arm_cli, embedded_arm_cli)
    shutil.copy2(intel_cli, embedded_intel_cli)
    embedded_arm_cli.chmod(0o755)
    embedded_intel_cli.chmod(0o755)
    embedded_cli = executable_dir / 'kwan'
    embedded_cli.write_text(
        '#!/bin/sh\n'
        'case "$(uname -m)" in\n'
        '  arm64) exec "$(dirname "$0")/kwan-arm64" "$@" ;;\n'
        '  x86_64) exec "$(dirname "$0")/kwan-x86_64" "$@" ;;\n'
        '  *) echo "PackeTech: unsupported macOS architecture" >&2; exit 1 ;;\n'
        'esac\n',
        encoding='ascii',
    )
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
    output = RELEASE / f'packetech-{version}-macos-universal.dmg'
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


def write_checksum(artifact: Path) -> Path:
    """Write the universal macOS artifact's SHA-256 checksum file."""
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    output = RELEASE / 'SHA256SUMS-macos-universal.txt'
    output.write_text(f'{digest}  {artifact.name}\n', encoding='ascii')
    return output


def main() -> None:
    """Package the current native macOS build and print generated paths."""
    application, arm_cli, intel_cli = _require_builds()
    artifact = build_dmg(application, arm_cli, intel_cli, _version())
    checksum = write_checksum(artifact)
    print(artifact)
    print(checksum)


if __name__ == '__main__':
    main()
