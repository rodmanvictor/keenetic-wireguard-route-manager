"""Platform-native setup for six-hour route synchronization."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys


@dataclass(frozen=True)
class TimerSetupResult:
    """Outcome of one best-effort background synchronization setup.

    Attributes:
        enabled: Whether the native operating-system scheduler confirmed setup.
        detail: Short user-facing explanation without credentials.
    """

    enabled: bool
    detail: str


def user_systemd_directory() -> Path:
    """Return the current user's writable systemd unit directory."""
    root = Path(os.getenv('XDG_CONFIG_HOME') or Path.home() / '.config')
    return root / 'systemd' / 'user'


def find_kwan_executable() -> Path | None:
    """Find the standalone synchronizer beside a package or source checkout."""
    override = os.getenv('PAKETYCH_KWAN_PATH')
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    installed = shutil.which('kwan')
    if installed:
        return Path(installed)
    sibling_name = 'kwan.exe' if os.name == 'nt' else 'kwan'
    sibling = Path(sys.executable).resolve().with_name(sibling_name)
    if sibling.is_file():
        return sibling
    project = Path(__file__).resolve().parents[3]
    source_launcher = project / 'bin' / 'kwan'
    return source_launcher if source_launcher.is_file() else None


def write_user_units(cli_path: Path, directory: Path | None = None) -> tuple[Path, Path]:
    """Write idempotent systemd units pointing at one absolute CLI executable.

    Args:
        cli_path: Existing standalone ``kwan`` executable or source launcher.
        directory: Optional test or custom unit directory.

    Returns:
        Paths to the service and timer units.

    Raises:
        ValueError: If the executable path does not exist or contains a quote.

    Side effects:
        Creates or replaces two files in the user's systemd configuration.
    """
    resolved = cli_path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f'Не найден CLI PackeTech: {resolved}')
    if '"' in str(resolved):
        raise ValueError('Путь к CLI содержит неподдерживаемую кавычку')
    target = directory or user_systemd_directory()
    target.mkdir(parents=True, exist_ok=True)
    service = target / 'paketych-sync.service'
    timer = target / 'paketych-sync.timer'
    service.write_text(
        '[Unit]\n'
        'Description=PackeTech: обновление доменных маршрутов Keenetic\n'
        'Wants=network-online.target\n'
        'After=network-online.target\n\n'
        '[Service]\n'
        'Type=oneshot\n'
        f'ExecStart="{resolved}" sync\n',
        encoding='utf-8',
    )
    timer.write_text(
        '[Unit]\n'
        'Description=PackeTech: обновлять маршруты каждые 6 часов\n\n'
        '[Timer]\n'
        'OnBootSec=10min\n'
        'OnUnitActiveSec=6h\n'
        'Persistent=true\n'
        'Unit=paketych-sync.service\n\n'
        '[Install]\n'
        'WantedBy=timers.target\n',
        encoding='utf-8',
    )
    service.chmod(0o644)
    timer.chmod(0o644)
    return service, timer


def enable_windows_task(cli_path: Path) -> TimerSetupResult:
    """Create the current user's six-hour Windows Scheduled Task.

    Args:
        cli_path: Existing standalone ``kwan.exe`` executable.

    Returns:
        A non-raising result with the Task Scheduler outcome.

    Side effects:
        Removes the legacy ``Paketych route sync`` task and replaces the
        current user's ``PackeTech route sync`` scheduled task.
    """
    resolved = cli_path.expanduser().resolve()
    if not resolved.is_file():
        return TimerSetupResult(False, f'CLI для фонового обновления не найден: {resolved}')
    task_command = subprocess.list2cmdline([str(resolved), 'sync'])
    try:
        subprocess.run(
            [
                'schtasks.exe',
                '/Delete',
                '/F',
                '/TN',
                'Paketych route sync',
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        subprocess.run(
            [
                'schtasks.exe',
                '/Create',
                '/F',
                '/SC',
                'HOURLY',
                '/MO',
                '6',
                '/TN',
                'PackeTech route sync',
                '/TR',
                task_command,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return TimerSetupResult(False, f'Автообновление не включено: {error}')
    return TimerSetupResult(True, 'Автообновление включено через Планировщик Windows')


def macos_launch_agents_directory() -> Path:
    """Return the current user's native macOS LaunchAgents directory."""
    return Path.home() / 'Library' / 'LaunchAgents'


def write_macos_launch_agent(cli_path: Path, directory: Path | None = None) -> Path:
    """Write a six-hour macOS LaunchAgent for the standalone synchronizer.

    Args:
        cli_path: Existing native ``kwan`` executable embedded in the app.
        directory: Optional test or custom LaunchAgents directory.

    Returns:
        Path to the written property-list file.

    Raises:
        ValueError: If the CLI executable does not exist.

    Side effects:
        Creates or replaces ``ru.rodman.packetech.sync.plist``.
    """
    resolved = cli_path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f'Не найден CLI PackeTech: {resolved}')
    target = directory or macos_launch_agents_directory()
    target.mkdir(parents=True, exist_ok=True)
    agent = target / 'ru.rodman.packetech.sync.plist'
    payload = {
        'Label': 'ru.rodman.packetech.sync',
        'ProgramArguments': [str(resolved), 'sync'],
        'RunAtLoad': True,
        'StartInterval': 6 * 60 * 60,
    }
    agent.write_bytes(plistlib.dumps(payload, sort_keys=True))
    agent.chmod(0o644)
    return agent


def enable_macos_launch_agent(cli_path: Path) -> TimerSetupResult:
    """Install and bootstrap the current user's macOS LaunchAgent.

    Args:
        cli_path: Existing native ``kwan`` executable embedded in PackeTech.

    Returns:
        A non-raising result with the ``launchctl`` outcome.

    Side effects:
        Replaces and reloads the user's PackeTech LaunchAgent.
    """
    try:
        agent = write_macos_launch_agent(cli_path)
        domain = f'gui/{os.getuid()}'
        subprocess.run(
            ['launchctl', 'bootout', domain, str(agent)],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        subprocess.run(
            ['launchctl', 'bootstrap', domain, str(agent)],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return TimerSetupResult(False, f'Автообновление не включено: {error}')
    return TimerSetupResult(True, 'Автообновление включено через LaunchAgent macOS')


def enable_background_sync() -> TimerSetupResult:
    """Install six-hour synchronization using the current operating system.

    Returns:
        A non-raising result. Desktop onboarding remains usable without a
        supported scheduler or without a discoverable standalone CLI.
    """
    cli = find_kwan_executable()
    if cli is None:
        return TimerSetupResult(False, 'CLI для фонового обновления не найден')
    if os.name == 'nt':
        return enable_windows_task(cli)
    if sys.platform == 'darwin':
        return enable_macos_launch_agent(cli)
    if not sys.platform.startswith('linux'):
        return TimerSetupResult(False, 'Автообновление пока недоступно в этой системе')
    try:
        write_user_units(cli)
        subprocess.run(
            ['systemctl', '--user', 'daemon-reload'],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        subprocess.run(
            ['systemctl', '--user', 'enable', '--now', 'paketych-sync.timer'],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return TimerSetupResult(False, f'Автообновление не включено: {error}')
    return TimerSetupResult(True, 'Автообновление включено: каждые 6 часов')


def enable_user_timer() -> TimerSetupResult:
    """Return the cross-platform setup result under the legacy public name."""
    return enable_background_sync()
