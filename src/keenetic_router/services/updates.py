"""Safe GitHub Release discovery and download helpers.

The desktop application never replaces its own executable.  It downloads the
native package published by the project, verifies SHA-256, and hands the file
to the operating system so the user remains in control of installation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
from typing import Callable, Iterable
from urllib.request import Request, urlopen

from keenetic_router import __version__


REPOSITORY = 'rodmanvictor/packetech'
LATEST_RELEASE_API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class ReleaseAsset:
    """One downloadable file attached to a GitHub Release."""

    name: str
    url: str
    size: int = 0
    digest: str = ''


@dataclass(frozen=True)
class UpdateInfo:
    """Resolved update for the current platform, if one is available."""

    current_version: str
    latest_version: str
    release_url: str
    asset: ReleaseAsset | None
    checksum_asset: ReleaseAsset | None
    available: bool


def parse_version(value: str) -> tuple[int, ...]:
    """Convert a release tag to a comparable numeric tuple.

    Non-numeric suffixes are ignored because PackeTech only offers stable
    releases through the ``latest`` endpoint.
    """
    match = re.match(r'^v?(\d+(?:\.\d+)*)', (value or '').strip())
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split('.'))


def is_newer_version(latest: str, current: str = __version__) -> bool:
    """Return whether ``latest`` is numerically newer than ``current``."""
    latest_parts = parse_version(latest)
    current_parts = parse_version(current)
    if not latest_parts or not current_parts:
        return False
    width = max(len(latest_parts), len(current_parts))
    return latest_parts + (0,) * (width - len(latest_parts)) > (
        current_parts + (0,) * (width - len(current_parts))
    )


def _normalized_platform(system: str | None = None, machine: str | None = None):
    """Return release naming tokens for a supported operating system."""
    system_name = (system or platform.system()).lower()
    architecture = (machine or platform.machine()).lower()
    if architecture in {'amd64', 'x64'}:
        architecture = 'x86_64'
    elif architecture == 'aarch64':
        architecture = 'arm64'
    if system_name == 'linux' and architecture == 'x86_64':
        return 'linux', 'x86_64'
    if system_name == 'windows' and architecture == 'x86_64':
        return 'windows', 'x86_64'
    if system_name in {'darwin', 'macos'} and architecture in {'arm64', 'x86_64'}:
        return 'macos', architecture
    return system_name, architecture


def select_release_assets(
    assets: Iterable[ReleaseAsset],
    version: str,
    *,
    system: str | None = None,
    machine: str | None = None,
) -> tuple[ReleaseAsset | None, ReleaseAsset | None]:
    """Choose the native package and checksum list for one platform."""
    os_name, architecture = _normalized_platform(system, machine)
    clean_version = version.removeprefix('v')
    if os_name == 'linux' and architecture == 'x86_64':
        package_name = f'packetech_{clean_version}_amd64.deb'
        checksum_name = 'SHA256SUMS-linux.txt'
    elif os_name == 'windows' and architecture == 'x86_64':
        package_name = f'packetech-{clean_version}-windows-x86_64.zip'
        checksum_name = 'SHA256SUMS-windows.txt'
    elif os_name == 'macos' and architecture in {'arm64', 'x86_64'}:
        package_name = f'packetech-{clean_version}-macos-{architecture}.dmg'
        checksum_name = f'SHA256SUMS-macos-{architecture}.txt'
    else:
        return None, None
    by_name = {asset.name: asset for asset in assets}
    return by_name.get(package_name), by_name.get(checksum_name)


def fetch_latest_release(
    *,
    current_version: str = __version__,
    timeout: float = 6,
    system: str | None = None,
    machine: str | None = None,
) -> UpdateInfo:
    """Read the latest public GitHub Release and resolve its native package."""
    request = Request(
        LATEST_RELEASE_API,
        headers={
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': f'PackeTech/{current_version}',
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    latest_version = str(payload.get('tag_name', '')).removeprefix('v')
    assets = [
        ReleaseAsset(
            name=str(item.get('name', '')),
            url=str(item.get('browser_download_url', '')),
            size=int(item.get('size') or 0),
            digest=str(item.get('digest') or ''),
        )
        for item in payload.get('assets', [])
    ]
    asset, checksum_asset = select_release_assets(
        assets,
        latest_version,
        system=system,
        machine=machine,
    )
    return UpdateInfo(
        current_version=current_version,
        latest_version=latest_version,
        release_url=str(payload.get('html_url', '')),
        asset=asset,
        checksum_asset=checksum_asset,
        available=is_newer_version(latest_version, current_version),
    )


def _download(url: str, destination: Path, callback: ProgressCallback | None = None):
    """Stream one HTTPS URL to disk and optionally report byte progress."""
    request = Request(url, headers={'User-Agent': f'PackeTech/{__version__}'})
    with urlopen(request, timeout=30) as response, destination.open('wb') as output:
        total = int(response.headers.get('Content-Length') or 0)
        received = 0
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            received += len(chunk)
            if callback:
                callback(received, total)


def _expected_checksum(contents: str, filename: str) -> str:
    """Extract the exact file checksum from a standard SHA256SUMS document."""
    for line in contents.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and parts[1].lstrip('*') == filename:
            return parts[0].lower()
    return ''


def file_sha256(path: Path) -> str:
    """Calculate a lowercase SHA-256 digest without loading the file at once."""
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def download_update(
    update: UpdateInfo,
    *,
    directory: Path | None = None,
    callback: ProgressCallback | None = None,
) -> Path:
    """Download and verify the selected release package.

    Raises:
        RuntimeError: When no compatible package or verifiable SHA-256 exists.
    """
    if update.asset is None:
        raise RuntimeError('Для этой системы пока нет готовой сборки PackeTech.')
    target_directory = directory or (Path.home() / 'Downloads')
    target_directory.mkdir(parents=True, exist_ok=True)
    target = target_directory / update.asset.name
    partial = target.with_suffix(target.suffix + '.part')
    try:
        _download(update.asset.url, partial, callback)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    api_expected = ''
    if update.asset.digest.startswith('sha256:'):
        api_expected = update.asset.digest.removeprefix('sha256:').lower()
    documented = ''
    if update.checksum_asset is not None:
        checksum_path = target_directory / f'.{update.checksum_asset.name}.part'
        try:
            _download(update.checksum_asset.url, checksum_path)
            documented = _expected_checksum(
                checksum_path.read_text(encoding='utf-8'),
                update.asset.name,
            )
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        finally:
            checksum_path.unlink(missing_ok=True)
    if api_expected and documented and api_expected != documented:
        partial.unlink(missing_ok=True)
        raise RuntimeError('GitHub вернул разные контрольные суммы. Обновление отменено.')
    expected = api_expected or documented
    if not expected:
        partial.unlink(missing_ok=True)
        raise RuntimeError('GitHub не отдал контрольную сумму файла. Обновление отменено.')
    actual = file_sha256(partial)
    if actual != expected:
        partial.unlink(missing_ok=True)
        raise RuntimeError('Контрольная сумма не совпала. Повреждённый файл удалён.')
    partial.replace(target)
    return target


def open_downloaded_update(path: Path, *, system: str | None = None):
    """Open the verified package using the native operating-system handler."""
    system_name = (system or platform.system()).lower()
    if system_name == 'windows':
        os.startfile(path)  # type: ignore[attr-defined]
    elif system_name in {'darwin', 'macos'}:
        subprocess.Popen(['open', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path)])


def installation_hint(system: str | None = None) -> str:
    """Explain the final user-controlled installation step for the current OS."""
    system_name = (system or platform.system()).lower()
    if system_name == 'windows':
        return 'Откроется ZIP. Закройте PackeTech и замените старую папку новой.'
    if system_name in {'darwin', 'macos'}:
        return 'Откроется DMG. Перетащите PackeTech в папку «Программы» с заменой.'
    return 'Откроется системный установщик DEB. Подтвердите обновление пакета.'
