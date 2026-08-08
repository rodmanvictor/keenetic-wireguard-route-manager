"""Prepare PackeTech's unpacked Chrome extension from the desktop app.

Chrome deliberately requires one visible user confirmation for unpacked
extensions. PackeTech handles every safe step around that boundary: it detects
Chrome, copies versioned extension files to a stable user directory, registers
the native helper, opens ``chrome://extensions``, and reveals the exact folder
the user must select once.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from keenetic_router.core.profiles import config_directory


HOST_NAME = 'com.keenetic.router.host'
EXTENSION_ID = 'fggdjnagagddkbpglpnhhjopgcodnham'


@dataclass(frozen=True)
class ChromeBrowser:
    """One supported local Chromium-family browser installation."""

    name: str
    executable: Path
    native_hosts_directory: Path | None


@dataclass(frozen=True)
class ChromeInstallResult:
    """Paths and browser state produced by the installation preparation."""

    browser: ChromeBrowser
    extension_directory: Path
    native_manifest: Path
    host_executable: Path
    extension_id: str = EXTENSION_ID


def _browser_candidates(system=None):
    """Yield supported Chrome executable candidates for the current platform."""
    system = system or platform.system()
    home = Path.home()
    if system == 'Windows':
        roots = [
            Path(os.getenv('PROGRAMFILES', r'C:\Program Files')),
            Path(os.getenv('PROGRAMFILES(X86)', r'C:\Program Files (x86)')),
            Path(os.getenv('LOCALAPPDATA', home / 'AppData' / 'Local')),
        ]
        for root in roots:
            yield 'Google Chrome', root / 'Google/Chrome/Application/chrome.exe', None
        return
    if system == 'Darwin':
        yield (
            'Google Chrome',
            Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'),
            home / 'Library/Application Support/Google/Chrome/NativeMessagingHosts',
        )
        yield (
            'Google Chrome',
            home / 'Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            home / 'Library/Application Support/Google/Chrome/NativeMessagingHosts',
        )
        return
    config_root = Path(os.getenv('XDG_CONFIG_HOME') or home / '.config')
    commands = (
        ('Google Chrome', 'google-chrome-stable', config_root / 'google-chrome/NativeMessagingHosts'),
        ('Google Chrome', 'google-chrome', config_root / 'google-chrome/NativeMessagingHosts'),
        ('Chromium', 'chromium', config_root / 'chromium/NativeMessagingHosts'),
        ('Chromium', 'chromium-browser', config_root / 'chromium/NativeMessagingHosts'),
    )
    for name, command, native_directory in commands:
        resolved = shutil.which(command)
        if resolved:
            yield name, Path(resolved), native_directory


def detect_chrome(*, system=None):
    """Return the first supported installed Chrome browser, or ``None``."""
    for name, executable, native_directory in _browser_candidates(system):
        if executable.is_file():
            return ChromeBrowser(name, executable.resolve(), native_directory)
    return None


def _copy_resource_tree(source, destination):
    """Recursively copy an importlib resource tree into a real directory."""
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            _copy_resource_tree(item, target)
        else:
            target.write_bytes(item.read_bytes())


def _host_candidates(system=None):
    """Yield packaged native-host executables near known application layouts."""
    system = system or platform.system()
    current = Path(sys.executable).resolve()
    if system == 'Windows':
        yield current.with_name('PackeTech-Chrome-Host.exe')
        found = shutil.which('PackeTech-Chrome-Host.exe')
        if found:
            yield Path(found)
        return
    if system == 'Darwin':
        yield current.with_name('packetech-chrome-host')
        found = shutil.which('packetech-chrome-host')
        if found:
            yield Path(found)
        return
    yield current.with_name('packetech-chrome-host')
    yield current.parent.parent.parent / 'packetech-chrome-host'
    yield Path('/usr/lib/packetech/packetech-chrome-host')
    found = shutil.which('packetech-chrome-host')
    if found:
        yield Path(found)


def _development_host_launcher(destination):
    """Create a POSIX launcher for editable/source installations.

    Args:
        destination: Stable executable path under the user's config directory.

    Returns:
        The created launcher path.

    Raises:
        RuntimeError: On Windows, where Chrome requires a real executable.
    """
    if os.name == 'nt':
        raise RuntimeError('В этой сборке нет PackeTech-Chrome-Host.exe')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        '#!/bin/sh\n'
        f'exec "{Path(sys.executable).resolve()}" -m keenetic_router.integrations.chrome_host\n',
        encoding='utf-8',
    )
    destination.chmod(0o700)
    return destination


def find_native_host(*, system=None):
    """Locate a packaged helper or build a safe development launcher."""
    override = os.getenv('PACKETECH_CHROME_HOST')
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError(f'Не найден помощник Chrome: {path}')
        return path
    for candidate in _host_candidates(system):
        if candidate.is_file():
            return candidate.resolve()
    return _development_host_launcher(
        config_directory() / 'chrome' / 'bin' / 'packetech-chrome-host'
    )


def _write_windows_registration(manifest_path):
    """Register a per-user native messaging manifest in the Windows registry."""
    import winreg

    key_path = rf'Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, '', 0, winreg.REG_SZ, str(manifest_path))


def _native_manifest_path(browser, system):
    """Return the expected per-user native manifest path for one platform."""
    if system == 'Windows':
        return config_directory() / 'chrome' / 'native-messaging' / f'{HOST_NAME}.json'
    if browser.native_hosts_directory is None:
        raise RuntimeError('Не удалось определить папку Native Messaging')
    return browser.native_hosts_directory / f'{HOST_NAME}.json'


def inspect_chrome_extension(*, browser=None, system=None):
    """Return a verified existing installation, or ``None`` when incomplete."""
    system = system or platform.system()
    browser = browser or detect_chrome(system=system)
    if browser is None:
        return None
    extension_directory = config_directory() / 'chrome' / 'extension'
    extension_manifest = extension_directory / 'manifest.json'
    native_manifest = _native_manifest_path(browser, system)
    if not extension_manifest.is_file() or not native_manifest.is_file():
        return None
    try:
        extension_payload = json.loads(extension_manifest.read_text(encoding='utf-8'))
        native_payload = json.loads(native_manifest.read_text(encoding='utf-8'))
        host = Path(native_payload['path']).expanduser().resolve()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if extension_payload.get('key') is None or not host.is_file():
        return None
    if native_payload.get('allowed_origins') != [f'chrome-extension://{EXTENSION_ID}/']:
        return None
    return ChromeInstallResult(browser, extension_directory, native_manifest, host)


def prepare_chrome_extension(*, browser=None, host_executable=None, system=None):
    """Install local files and native-host registration for one browser.

    Args:
        browser: Optional detected browser override used by tests and diagnostics.
        host_executable: Optional absolute native-host path.
        system: Optional platform name override.

    Returns:
        :class:`ChromeInstallResult` with the exact folder the user must load.

    Raises:
        RuntimeError: If Chrome or the packaged helper cannot be found.

    Side effects:
        Replaces the managed extension directory and writes a per-user Chrome
        native-messaging manifest. On Windows, also updates the matching HKCU
        registry value.
    """
    system = system or platform.system()
    browser = browser or detect_chrome(system=system)
    if browser is None:
        raise RuntimeError('Google Chrome не найден на этом компьютере')
    host = Path(host_executable).resolve() if host_executable else find_native_host(system=system)
    if not host.is_file():
        raise RuntimeError(f'Не найден локальный помощник PackeTech: {host}')

    root = config_directory() / 'chrome'
    extension_directory = root / 'extension'
    if extension_directory.exists():
        shutil.rmtree(extension_directory)
    _copy_resource_tree(files('keenetic_router').joinpath('chrome_extension'), extension_directory)

    manifest_payload = {
        'name': HOST_NAME,
        'description': 'PackeTech Chrome helper',
        'path': str(host),
        'type': 'stdio',
        'allowed_origins': [f'chrome-extension://{EXTENSION_ID}/'],
    }
    native_manifest = _native_manifest_path(browser, system)
    native_manifest.parent.mkdir(parents=True, exist_ok=True)
    native_manifest.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    try:
        native_manifest.chmod(0o600)
    except OSError:
        pass
    if system == 'Windows':
        _write_windows_registration(native_manifest)
    return ChromeInstallResult(browser, extension_directory, native_manifest, host)


def open_chrome_extensions(browser):
    """Open Chrome's extension manager in the detected browser."""
    subprocess.Popen(
        [str(browser.executable), 'chrome://extensions/'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def reveal_extension_directory(path):
    """Open the extension folder in the native file manager."""
    path = Path(path).resolve()
    system = platform.system()
    if system == 'Windows':
        subprocess.Popen(['explorer.exe', str(path)])
    elif system == 'Darwin':
        subprocess.Popen(['open', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path)])
