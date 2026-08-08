"""Cross-platform storage for non-secret router profiles.

Only connection coordinates are persisted.  Administrator passwords stay in
the process memory and are requested by the CLI or desktop application for
each session.
"""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sys


@dataclass(frozen=True)
class RouterProfile:
    """Connection coordinates for one Keenetic router.

    Attributes:
        name: Local profile name.  The first public release uses ``default``.
        host: LAN address, IP, or directly reachable KeenDNS hostname.
        user: KeeneticOS administrator login.
        ssh_port: SSH server TCP port.
        telnet_port: Telnet server TCP port.
        preferred_transport: Last transport proven by onboarding diagnostics.
    """

    name: str = 'default'
    host: str = '192.168.1.1'
    user: str = 'admin'
    ssh_port: int = 22
    telnet_port: int = 23
    preferred_transport: str = 'auto'

    def validate(self):
        """Return a validated copy suitable for network operations.

        Raises:
            ValueError: If a required field, port, or transport is invalid.
        """
        host = self.host.strip()
        user = self.user.strip()
        if not host or any(character.isspace() for character in host):
            raise ValueError('Введите IP-адрес или имя роутера без пробелов')
        if not user:
            raise ValueError('Введите логин администратора Keenetic')
        for label, port in (('SSH', self.ssh_port), ('Telnet', self.telnet_port)):
            if not 1 <= int(port) <= 65535:
                raise ValueError(f'Порт {label} должен быть от 1 до 65535')
        if self.preferred_transport not in {'auto', 'ssh', 'telnet'}:
            raise ValueError('Неизвестный транспорт подключения')
        return RouterProfile(
            name=self.name.strip() or 'default',
            host=host,
            user=user,
            ssh_port=int(self.ssh_port),
            telnet_port=int(self.telnet_port),
            preferred_transport=self.preferred_transport,
        )


def config_directory():
    """Return the native user configuration directory for this application."""
    override = os.getenv('KEENETIC_ROUTE_MANAGER_CONFIG_DIR')
    if override:
        return Path(override).expanduser()
    if os.name == 'nt':
        root = Path(os.getenv('APPDATA') or Path.home() / 'AppData' / 'Roaming')
        return root / 'KeeneticRouteManager'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'KeeneticRouteManager'
    root = Path(os.getenv('XDG_CONFIG_HOME') or Path.home() / '.config')
    return root / 'keenetic-route-manager'


def config_path():
    """Return the JSON profile path without creating it."""
    return config_directory() / 'config.json'


def environment_profile():
    """Build a backward-compatible profile from existing ``ROUTER_*`` ENV."""
    return RouterProfile(
        host=os.getenv('ROUTER_HOST', '192.168.1.1'),
        user=os.getenv('ROUTER_USER', 'admin'),
        ssh_port=int(os.getenv('ROUTER_SSH_PORT', '22')),
        telnet_port=int(os.getenv('ROUTER_PORT', '23')),
        preferred_transport='ssh'
        if os.getenv('ROUTER_USE_SSH', 'false').lower() == 'true'
        else 'auto',
    ).validate()


def load_profile():
    """Load the default saved profile or fall back to environment settings.

    Raises:
        ValueError: If a saved JSON file exists but is malformed.
    """
    path = config_path()
    if not path.exists():
        return environment_profile()
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        profile_data = payload.get('profiles', {}).get(payload.get('default', 'default'))
        if not isinstance(profile_data, dict):
            raise ValueError('В конфигурации не найден профиль по умолчанию')
        return RouterProfile(**profile_data).validate()
    except (OSError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f'Не удалось прочитать {path}: {error}') from error


def save_profile(profile):
    """Persist one validated non-secret profile and return the written path.

    Side effects:
        Creates the native configuration directory with user-only permissions
        where the operating system supports POSIX modes.
    """
    validated = profile.validate()
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    payload = {'version': 1, 'default': validated.name, 'profiles': {validated.name: asdict(validated)}}
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)
    return path


def environment_password():
    """Return a legacy ENV password, or an empty string when none is set."""
    return os.getenv('ROUTER_PASS', '')
