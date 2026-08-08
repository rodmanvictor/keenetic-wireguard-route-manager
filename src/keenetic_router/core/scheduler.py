"""Linux user-timer setup for six-hour route synchronization."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys


@dataclass(frozen=True)
class TimerSetupResult:
    """Outcome of one best-effort Linux user-timer setup.

    Attributes:
        enabled: Whether ``systemctl --user`` confirmed the timer activation.
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
    sibling = Path(sys.executable).resolve().with_name('kwan')
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
        raise ValueError(f'Не найден CLI Пакетыча: {resolved}')
    if '"' in str(resolved):
        raise ValueError('Путь к CLI содержит неподдерживаемую кавычку')
    target = directory or user_systemd_directory()
    target.mkdir(parents=True, exist_ok=True)
    service = target / 'paketych-sync.service'
    timer = target / 'paketych-sync.timer'
    service.write_text(
        '[Unit]\n'
        'Description=Пакетыч: обновление доменных маршрутов Keenetic\n'
        'Wants=network-online.target\n'
        'After=network-online.target\n\n'
        '[Service]\n'
        'Type=oneshot\n'
        f'ExecStart="{resolved}" sync\n',
        encoding='utf-8',
    )
    timer.write_text(
        '[Unit]\n'
        'Description=Пакетыч: обновлять маршруты каждые 6 часов\n\n'
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


def enable_user_timer() -> TimerSetupResult:
    """Install and enable six-hour synchronization on Linux when supported.

    Returns:
        A non-raising result.  Desktop onboarding remains usable on systems
        without systemd or without a discoverable standalone CLI.
    """
    if not sys.platform.startswith('linux'):
        return TimerSetupResult(False, 'Автообновление доступно только в Linux')
    cli = find_kwan_executable()
    if cli is None:
        return TimerSetupResult(False, 'CLI для фонового обновления не найден')
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
