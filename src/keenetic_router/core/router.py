"""Low-level KeeneticOS transports and route helpers.

The module keeps SSH and Telnet command handling in one place.  Public
applications may set an in-memory connection for the current process while
legacy local installations can continue to use ``ROUTER_*`` environment
variables.  Passwords configured at runtime are never written to disk here.
"""

import os
import logging
import re
import socket
import time
from pathlib import Path


def load_dotenv_fallback(path=None):
    """Load simple KEY=VALUE pairs from a local .env file if python-dotenv is absent."""
    env_path = Path(path or Path(__file__).resolve().parents[3] / '.env')
    if not env_path.is_file():
        return

    try:
        raw = env_path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return

    for line in raw:
        text = line.strip()
        if not text or text.startswith('#') or '=' not in text:
            continue
        key, value = text.split('=', 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()
else:
    load_dotenv_fallback()

# Конфигурация из ENV
ROUTER_HOST = os.getenv('ROUTER_HOST', '192.168.1.1')
ROUTER_PORT = int(os.getenv('ROUTER_PORT', '23'))
ROUTER_USER = os.getenv('ROUTER_USER', 'admin')
ROUTER_PASS = os.getenv('ROUTER_PASS', '')
ROUTER_USE_SSH = os.getenv('ROUTER_USE_SSH', 'false').lower() == 'true'
ROUTER_SSH_PORT = int(os.getenv('ROUTER_SSH_PORT', '22'))

_RUNTIME_CONNECTION = None
ANSI_ESCAPE = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))')

# Paramiko otherwise prints full background-thread tracebacks for expected
# onboarding retries, bypassing the application's concise diagnostics.
logging.getLogger('paramiko.transport').setLevel(logging.CRITICAL)


def configure_runtime_connection(
    host,
    user,
    password,
    *,
    transport='ssh',
    ssh_port=22,
    telnet_port=23,
):
    """Set process-local router credentials used by shared services.

    Args:
        host: Router IPv4 address or hostname.
        user: KeeneticOS administrator login.
        password: Administrator password retained only in process memory.
        transport: ``ssh`` or ``telnet`` selected by onboarding diagnostics.
        ssh_port: SSH server TCP port.
        telnet_port: Telnet server TCP port.

    Raises:
        ValueError: If the transport is not supported.

    Side effects:
        Replaces the module-level runtime connection used by subsequent calls
        to :func:`create_router_client`.
    """
    if transport not in {'ssh', 'telnet'}:
        raise ValueError('Transport must be ssh or telnet')
    global _RUNTIME_CONNECTION
    _RUNTIME_CONNECTION = {
        'host': str(host).strip(),
        'user': str(user).strip(),
        'password': str(password),
        'transport': transport,
        'ssh_port': int(ssh_port),
        'telnet_port': int(telnet_port),
    }


def clear_runtime_connection():
    """Forget process-local credentials without changing saved profiles."""
    global _RUNTIME_CONNECTION
    _RUNTIME_CONNECTION = None


def runtime_connection_summary():
    """Return non-secret details about the active in-memory connection."""
    if _RUNTIME_CONNECTION is None:
        return None
    return {
        key: value
        for key, value in _RUNTIME_CONNECTION.items()
        if key != 'password'
    }


def strip_terminal_control(value):
    """Remove ANSI redraw sequences emitted by Keenetic interactive shells."""
    return ANSI_ESCAPE.sub('', value).replace('\r', '')


def create_telnet_client(host=ROUTER_HOST, port=ROUTER_PORT, user=ROUTER_USER, password=ROUTER_PASS,
                         send_char_delay=0.03, command_wait=1.5):
    """Создаёт и возвращает подключенный Telnet клиент"""
    client = KeeneticTelnet(host, port, user, password, send_char_delay, command_wait)
    client.connect()
    return client


def create_ssh_client(host=ROUTER_HOST, port=ROUTER_SSH_PORT, user=ROUTER_USER, password=ROUTER_PASS,
                      command_wait=1.5):
    """Создаёт и возвращает подключенный SSH клиент"""
    client = KeeneticSSH(host, port, user, password, command_wait)
    client.connect()
    return client


def create_router_client(
    host=None,
    port=None,
    *,
    user=None,
    password=None,
    use_ssh=None,
    ssh_port=None,
    telnet_port=None,
):
    """Create a connected client from runtime, explicit, or environment data.

    Args:
        host: Optional router address overriding every configured source.
        port: Backward-compatible override for the selected transport port.
        user: Optional administrator login.
        password: Optional administrator password.
        use_ssh: Explicit transport selector. ``None`` uses runtime or ENV.
        ssh_port: SSH port used when ``port`` is omitted.
        telnet_port: Telnet port used when ``port`` is omitted.

    Returns:
        Connected :class:`KeeneticSSH` or :class:`KeeneticTelnet` instance.

    Raises:
        OSError: When the router cannot be reached.
        RuntimeError: When the selected transport cannot be initialized.
    """
    runtime = _RUNTIME_CONNECTION or {}
    selected_host = host or runtime.get('host') or ROUTER_HOST
    selected_user = user or runtime.get('user') or ROUTER_USER
    selected_password = password if password is not None else runtime.get('password', ROUTER_PASS)
    selected_use_ssh = (
        use_ssh
        if use_ssh is not None
        else runtime.get('transport', 'ssh' if ROUTER_USE_SSH else 'telnet') == 'ssh'
    )
    selected_ssh_port = int(ssh_port or runtime.get('ssh_port') or ROUTER_SSH_PORT)
    selected_telnet_port = int(telnet_port or runtime.get('telnet_port') or ROUTER_PORT)

    if selected_use_ssh:
        return create_ssh_client(
            host=selected_host,
            port=int(port or selected_ssh_port),
            user=selected_user,
            password=selected_password,
            command_wait=1.0,
        )
    return create_telnet_client(
        host=selected_host,
        port=int(port or selected_telnet_port),
        user=selected_user,
        password=selected_password,
        send_char_delay=0.02,
        command_wait=0.45,
    )


class KeeneticTelnet:
    """Telnet клиент для KeeneticOS"""

    def __init__(self, host, port, user, password, send_char_delay=0.03, command_wait=1.5):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.send_char_delay = send_char_delay
        self.command_wait = command_wait
        self.sock = None
        self.transport = 'telnet'

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect((self.host, self.port))
        self._read_until(b'Login:')
        self.sock.send(self.user.encode() + b'\n')
        time.sleep(0.5)
        self._read_until(b'Password:')
        self.sock.send(self.password.encode() + b'\n')
        time.sleep(2)
        self.sock.recv(4096)

    def _read_until(self, prompt, timeout=5):
        data = b''
        start = time.time()
        while time.time() - start < timeout:
            try:
                chunk = self.sock.recv(1024)
                if chunk:
                    data += chunk
                    if prompt in data:
                        return data
            except socket.timeout:
                break
        return data

    def _send_slow(self, text):
        for char in text:
            self.sock.send(char.encode())
            time.sleep(self.send_char_delay)
        self.sock.send(b'\n')

    def command(self, cmd, timeout=60):
        """Execute one CLI command and return normalized terminal output.

        The reader waits until the router stays quiet for ``command_wait``.
        This handles both short configuration commands and large component
        listings without relying on a specific localized prompt.
        """
        self._send_slow(cmd)
        output = bytearray()
        started = time.monotonic()
        last_data = None
        self.sock.settimeout(0.1)
        while time.monotonic() - started < timeout:
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                output.extend(chunk)
                last_data = time.monotonic()
            except socket.timeout:
                if last_data is not None and time.monotonic() - last_data >= self.command_wait:
                    break
        self.sock.settimeout(10)
        return strip_terminal_control(output.decode('utf-8', errors='ignore'))

    def disconnect(self):
        if self.sock:
            self.sock.send(b'exit\n')
            self.sock.close()


class KeeneticSSH:
    """SSH клиент для KeeneticOS (быстрее Telnet)"""

    def __init__(self, host, port, user, password, command_wait=1.5):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.command_wait = command_wait
        self.client = None
        self.channel = None
        self.transport = 'ssh'

    def connect(self):
        try:
            import paramiko
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                timeout=10,
                allow_agent=False,
                look_for_keys=False
            )
            self.channel = self.client.invoke_shell()
            # Drain the complete greeting and prompt before the first command.
            deadline = time.monotonic() + 3
            last_data = None
            while time.monotonic() < deadline:
                if self.channel.recv_ready():
                    self.channel.recv(65536)
                    last_data = time.monotonic()
                    continue
                if last_data is not None and time.monotonic() - last_data >= 0.25:
                    break
                time.sleep(0.03)
        except ImportError:
            raise RuntimeError("paramiko not installed. Install: pip install paramiko")

    def command(self, cmd, timeout=60):
        """Execute one interactive CLI command and return normalized output."""
        if not self.channel:
            raise RuntimeError("Not connected")

        self.channel.send(cmd + '\n')
        output = bytearray()
        started = time.monotonic()
        last_data = None
        while time.monotonic() - started < timeout:
            if self.channel.recv_ready():
                chunk = self.channel.recv(65536)
                if not chunk:
                    break
                output.extend(chunk)
                last_data = time.monotonic()
                continue
            if last_data is not None and time.monotonic() - last_data >= self.command_wait:
                break
            time.sleep(0.03)
        return strip_terminal_control(output.decode('utf-8', errors='ignore'))

    def disconnect(self):
        if self.channel:
            self.channel.send('exit\n')
            time.sleep(0.5)
        if self.client:
            self.client.close()


def is_ip_address(value):
    """Проверяет является ли строка IP-адресом"""
    try:
        socket.inet_aton(value.split('/')[0])
        return True
    except socket.error:
        return False


def resolve_domain(domain):
    """Получает IP-адреса для домена"""
    ips = set()
    try:
        _, _, ip_list = socket.gethostbyname_ex(domain)
        ips.update(ip_list)
    except Exception:
        pass
    return sorted(ips)


def prefix_to_mask(prefix):
    """Конвертирует CIDR префикс в маску"""
    mask = (0xffffffff >> (32 - prefix)) << (32 - prefix)
    return '.'.join(str((mask >> (8 * i)) & 0xff) for i in range(3, -1, -1))


def parse_windows_route(line):
    """Парсит строку формата: route add 160.79.104.0 mask 255.255.254.0 0.0.0.0"""
    line = line.strip()
    if not line.lower().startswith('route add'):
        return None

    parts = line.split()
    if len(parts) >= 6 and parts[3] == 'mask':
        return {
            'ip': parts[2],
            'mask': parts[4],
            'gateway': parts[5] if len(parts) > 5 else '0.0.0.0'
        }
    return None


def parse_wireguard_routes_output(output):
    """Парсит вывод show ip route и возвращает WireGuard маршруты"""
    lines = output.split('\n')
    routes = []
    for line in lines:
        if 'Wireguard' in line or (' wg' in line.lower() and 'wireless' not in line.lower()):
            parts = line.split()
            if len(parts) >= 4:
                network = parts[0]
                for i, part in enumerate(parts):
                    if 'Wireguard' in part or part.lower().startswith('wg'):
                        routes.append({
                            'network': network,
                            'interface': part,
                            'priority': parts[i+2] if len(parts) > i+2 else '1000'
                        })
                        break
    return routes


def discover_wireguard_tunnels(keenetic):
    """Discover numbered WireGuard interfaces from ``show interface`` output."""
    tunnels_short = {}  # wg0 -> Wireguard0
    tunnels_full = {}   # Wireguard0 -> wg0

    try:
        output = keenetic.command('show interface')
        for line in output.split('\n'):
            line = line.strip()
            if 'Wireguard' in line:
                # Извлекаем имя интерфейса
                parts = line.split()
                for part in parts:
                    if re.fullmatch(r'Wireguard\d+', part, re.IGNORECASE):
                        short_name = part.lower().replace('wireguard', 'wg')
                        full_name = f'Wireguard{part[9:]}'
                        tunnels_short[short_name] = full_name
                        tunnels_full[full_name] = short_name
                        break
    except Exception:
        pass

    return tunnels_short, tunnels_full


def normalize_tunnel_name(name, short_to_full=None, full_to_short=None):
    """Return the short tunnel identifier used by the command interfaces.

    Args:
        name: User-provided identifier, such as ``wg1`` or ``Wireguard1``.
        short_to_full: Optional live mapping of short identifiers to Keenetic
            interface names.
        full_to_short: Optional inverse mapping returned by tunnel discovery.

    Returns:
        A short identifier such as ``wg1``. Unknown values are returned
        unchanged so that the caller can display a useful validation error.

    Side effects:
        None.
    """
    candidate = str(name).strip()
    candidate_lower = candidate.lower()

    for short_name, full_name in (short_to_full or {}).items():
        if candidate_lower in {short_name.lower(), full_name.lower()}:
            return short_name

    for full_name, short_name in (full_to_short or {}).items():
        if candidate_lower in {full_name.lower(), short_name.lower()}:
            return short_name

    if candidate_lower.startswith('wireguard'):
        return f"wg{candidate[9:]}"
    return candidate_lower if candidate_lower.startswith('wg') else candidate


def full_interface_name(name, short_to_full=None, full_to_short=None):
    """Resolve a user tunnel name to the full Keenetic interface name.

    Args:
        name: Short or full tunnel identifier.
        short_to_full: Live short-to-full mapping from tunnel discovery.
        full_to_short: Optional inverse mapping from tunnel discovery.

    Returns:
        The full interface name, for example ``Wireguard1``.

    Side effects:
        None.
    """
    short_name = normalize_tunnel_name(name, short_to_full, full_to_short)
    if short_to_full and short_name in short_to_full:
        return short_to_full[short_name]
    if short_name.lower().startswith('wireguard'):
        return short_name
    if short_name.lower().startswith('wg'):
        return f"Wireguard{short_name[2:]}"
    return short_name


def route_exists(keenetic, ip, mask):
    """Проверяет, существует ли уже маршрут для данного IP"""
    try:
        output = keenetic.command('show ip route')

        # Конвертируем маску в CIDR префикс
        mask_parts = mask.split('.')
        cidr_prefix = sum(bin(int(p)).count('1') for p in mask_parts)
        target_cidr = f"{ip}/{cidr_prefix}"

        for line in output.split('\n'):
            if 'Wireguard' in line or ' wg' in line.lower():
                # Извлекаем сеть из строки (первый столбец)
                parts = line.split()
                if len(parts) >= 1:
                    network = parts[0]  # Например "64.233.0.0/16"
                    if network == target_cidr:
                        # Маршрут найден, извлекаем интерфейс
                        for part in parts:
                            if 'Wireguard' in part or part.lower().startswith('wg'):
                                return True, part
        return False, None
    except Exception as e:
        return False, None


def add_route_smart(keenetic, ip, mask, interface):
    """
    Умное добавление маршрута с проверкой дубликатов.

    Если маршрут уже существует:
    - На том же интерфейсе → ничего не делаем (обновление не нужно)
    - На другом интерфейсе → удаляем старый, добавляем новый

    Возвращает: (success, message)
    """
    # Проверяем существует ли маршрут
    exists, existing_interface = route_exists(keenetic, ip, mask)

    if exists:
        # Нормализуем имена для сравнения
        existing_short = existing_interface.lower().replace('wireguard', 'wg')
        new_short = interface.lower().replace('wireguard', 'wg')

        if existing_short == new_short:
            # Маршрут уже есть на том же интерфейсе
            return True, f"⏭️  Уже есть в {existing_interface}"
        else:
            # Маршрут на другом интерфейсе - заменяем
            delete_cmd = f'no ip route {ip} {mask} {existing_interface}'
            keenetic.command(delete_cmd)

            # Небольшая пауза перед добавлением нового
            time.sleep(0.3)

    # Добавляем новый маршрут
    add_cmd = f'ip route {ip} {mask} 0.0.0.0 {interface}'
    result = keenetic.command(add_cmd)

    if 'error' not in result.lower():
        if exists:
            return True, f"🔄 Заменён: {existing_interface} → {interface}"
        else:
            return True, "✅ Добавлен"
    else:
        return False, f"❌ Ошибка: {result.strip()[:50]}"
