"""Low-level KeeneticOS transports and route helpers.

The module keeps SSH and Telnet command handling in one place.  Public
applications may set an in-memory connection for the current process while
legacy local installations can continue to use ``ROUTER_*`` environment
variables.  Passwords configured at runtime are never written to disk here.
"""

import ipaddress
import logging
import os
import re
import socket
import time
from dataclasses import dataclass
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
    """Return whether a value is an IPv4/IPv6 address or CIDR network.

    Args:
        value: Text that may contain a host address or a network prefix.

    Returns:
        ``True`` for valid IPv4 and IPv6 values, otherwise ``False``.
    """
    try:
        text = str(value).strip()
        if '/' in text:
            ipaddress.ip_network(text, strict=False)
        else:
            ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def resolve_domain(domain):
    """Resolve all current IPv4 A and IPv6 AAAA addresses for a domain.

    Args:
        domain: DNS hostname accepted by the local system resolver.

    Returns:
        Stable tuple-like list ordered by IP version and numeric address.
        Duplicate resolver answers are removed.
    """
    addresses = set()
    try:
        for family, _type, _proto, _canonical, sockaddr in socket.getaddrinfo(
            domain,
            None,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        ):
            if family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            try:
                addresses.add(ipaddress.ip_address(sockaddr[0]))
            except ValueError:
                continue
    except socket.gaierror:
        pass
    return [
        str(address)
        for address in sorted(addresses, key=lambda item: (item.version, int(item)))
    ]


def normalize_route_network(address, mask=None):
    """Return one canonical IPv4 or IPv6 network for a route operation.

    Args:
        address: Host address or CIDR prefix.
        mask: Optional IPv4 dotted netmask retained for legacy callers. IPv6
            callers should include the prefix in ``address`` or omit it for a
            host ``/128`` route.

    Returns:
        :class:`ipaddress.IPv4Network` or :class:`ipaddress.IPv6Network`.

    Raises:
        ValueError: If the address/mask pair is malformed or combines an IPv6
            address with an IPv4 dotted mask.
    """
    text = str(address).strip()
    if '/' in text:
        return ipaddress.ip_network(text, strict=False)
    parsed = ipaddress.ip_address(text)
    if parsed.version == 4:
        return ipaddress.ip_network(f'{parsed}/{mask or 32}', strict=False)
    if mask not in {None, '', 128, '128'}:
        raise ValueError('Для IPv6 укажите длину префикса через /, например /64')
    return ipaddress.ip_network(f'{parsed}/128', strict=False)


def route_add_command(network, interface):
    """Build a KeeneticOS static-route command for either IP family.

    Args:
        network: Any value accepted by :func:`normalize_route_network`.
        interface: Full Keenetic interface name such as ``Wireguard1``.

    Returns:
        Executable KeeneticOS CLI command without secrets.
    """
    route = (
        network
        if isinstance(network, (ipaddress.IPv4Network, ipaddress.IPv6Network))
        else normalize_route_network(network)
    )
    if route.version == 4:
        return f'ip route {route.network_address} {route.netmask} 0.0.0.0 {interface}'
    return f'ipv6 route {route.with_prefixlen} {interface}'


def route_delete_command(network, interface):
    """Build a KeeneticOS route-removal command for either IP family."""
    route = (
        network
        if isinstance(network, (ipaddress.IPv4Network, ipaddress.IPv6Network))
        else normalize_route_network(network)
    )
    if route.version == 4:
        return f'no ip route {route.network_address} {route.netmask} {interface}'
    return f'no ipv6 route {route.with_prefixlen} {interface}'


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
    """Parse IPv4 tables or structured IPv6 route output from KeeneticOS.

    Args:
        output: Text returned by ``show ip route`` or ``show ipv6 route``.

    Returns:
        Unique mappings with canonical network, interface, and metric fields.
    """
    routes = []
    for line in str(output).splitlines():
        if 'Wireguard' in line or (' wg' in line.lower() and 'wireless' not in line.lower()):
            parts = line.split()
            if len(parts) >= 2 and '/' in parts[0]:
                network = parts[0]
                for i, part in enumerate(parts):
                    if 'Wireguard' in part or part.lower().startswith('wg'):
                        try:
                            canonical = str(ipaddress.ip_network(network, strict=False))
                        except ValueError:
                            break
                        routes.append({
                            'network': canonical,
                            'interface': part,
                            'priority': parts[i + 2] if len(parts) > i + 2 else '1000',
                        })
                        break

    for block in re.split(r'^\s*route6:\s*$', str(output), flags=re.MULTILINE):
        destination = re.search(r'^\s*destination:\s*(\S+)', block, flags=re.MULTILINE)
        interface = re.search(r'^\s*interface:\s*(\S+)', block, flags=re.MULTILINE)
        metric = re.search(r'^\s*metric:\s*(\S+)', block, flags=re.MULTILINE)
        if not destination or not interface or 'wireguard' not in interface.group(1).lower():
            continue
        try:
            parsed_network = ipaddress.ip_network(destination.group(1), strict=False)
        except ValueError:
            continue
        static = re.search(
            r'^\s*static:\s*(yes|no)',
            block,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        if parsed_network.prefixlen == 0 or (static and static.group(1).lower() != 'yes'):
            continue
        canonical = str(parsed_network)
        routes.append({
            'network': canonical,
            'interface': interface.group(1),
            'priority': metric.group(1) if metric else '1000',
        })

    unique = {}
    for route in routes:
        unique[(route['network'], route['interface'])] = route
    return list(unique.values())


@dataclass(frozen=True)
class WireGuardTunnel:
    """Human and technical identities of one Keenetic WireGuard interface.

    Attributes:
        short_name: Compact route identifier such as ``wg1``.
        interface: KeeneticOS identifier such as ``Wireguard1``.
        description: User-assigned name from KeeneticOS, possibly empty.
        status: Live interface state such as ``up`` or ``down``.
    """

    short_name: str
    interface: str
    description: str = ''
    status: str = 'unknown'

    @property
    def display_name(self):
        """Return the user-assigned name, falling back to the interface id."""
        return self.description or self.interface


def parse_wireguard_tunnel_details(output):
    """Parse interface identifiers and user descriptions from KeeneticOS.

    Args:
        output: Text returned by ``show interface``.

    Returns:
        Mapping of short identifiers to :class:`WireGuardTunnel` records.
        Every discovered numbered interface is retained even when it has no
        description.
    """
    descriptions = {}
    statuses = {}
    current_interface = None
    identity = re.compile(r'^id:\s*(\S+)\s*$', re.IGNORECASE)
    any_interface = re.compile(r'\bWireguard(\d+)\b', re.IGNORECASE)

    for raw_line in str(output).splitlines():
        line = raw_line.strip()
        match = identity.match(line)
        if match:
            interface_match = re.fullmatch(r'Wireguard(\d+)', match.group(1), re.IGNORECASE)
            current_interface = (
                f'Wireguard{interface_match.group(1)}' if interface_match else None
            )
            if current_interface:
                descriptions.setdefault(current_interface, '')
                statuses.setdefault(current_interface, 'unknown')
            continue
        if current_interface and line.lower().startswith('description:'):
            description = line.split(':', 1)[1].strip()
            if description:
                descriptions[current_interface] = description
            continue
        if current_interface and ': ' in line:
            key, value = line.split(': ', 1)
            if key.lower() in {'status', 'state', 'link'} and value.strip().lower() in {'up', 'down'}:
                if statuses[current_interface] == 'unknown' or key.lower() == 'status':
                    statuses[current_interface] = value.strip().lower()

    # Older KeeneticOS builds may omit the structured ``id`` line.  Preserve
    # the previous discovery behavior, but do not guess a human label.
    for match in any_interface.finditer(str(output)):
        interface = f'Wireguard{match.group(1)}'
        descriptions.setdefault(interface, '')
        statuses.setdefault(interface, 'unknown')

    details = {}
    for interface, description in descriptions.items():
        short = interface.lower().replace('wireguard', 'wg', 1)
        details[short] = WireGuardTunnel(
            short,
            interface,
            description,
            statuses.get(interface, 'unknown'),
        )
    return dict(sorted(details.items()))


def discover_wireguard_tunnel_details(keenetic):
    """Read live WireGuard identities, including names assigned by the user."""
    try:
        return parse_wireguard_tunnel_details(keenetic.command('show interface'))
    except Exception:
        return {}


def discover_wireguard_tunnels(keenetic):
    """Discover compatible short and full WireGuard interface mappings."""
    details = discover_wireguard_tunnel_details(keenetic)
    tunnels_short = {short: tunnel.interface for short, tunnel in details.items()}
    tunnels_full = {tunnel.interface: short for short, tunnel in details.items()}
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


def route_exists(keenetic, address, mask=None):
    """Return whether an exact IPv4/IPv6 WireGuard route already exists."""
    try:
        target = normalize_route_network(address, mask)
        command = 'show ip route' if target.version == 4 else 'show ipv6 route'
        for route in parse_wireguard_routes_output(keenetic.command(command)):
            if route['network'] == str(target):
                return True, route['interface']
        return False, None
    except (OSError, ValueError):
        return False, None


def add_route_smart(keenetic, address, mask, interface, *, existing_routes=None):
    """Add or move an exact IPv4/IPv6 route without creating duplicates.

    Args:
        keenetic: Connected router client.
        address: Host address or CIDR network.
        mask: Optional legacy IPv4 netmask; use ``None`` for IPv6/CIDR input.
        interface: Target full WireGuard interface name.
        existing_routes: Optional mutable ``network -> interface`` snapshot.
            Reusing one snapshot avoids downloading the full routing table for
            every DNS answer during a batch sync. Successful changes update it.

    Returns:
        Pair ``(success, human_message)``. An existing route on another
        interface is replaced; an identical route is left unchanged.
    """
    try:
        network = normalize_route_network(address, mask)
    except ValueError as error:
        return False, f'❌ Ошибка: {error}'
    network_text = network.with_prefixlen
    if existing_routes is None:
        exists, existing_interface = route_exists(keenetic, network_text)
    else:
        existing_interface = existing_routes.get(network_text)
        exists = existing_interface is not None

    if exists:
        # Нормализуем имена для сравнения
        existing_short = existing_interface.lower().replace('wireguard', 'wg')
        new_short = interface.lower().replace('wireguard', 'wg')

        if existing_short == new_short:
            # Маршрут уже есть на том же интерфейсе
            return True, f"⏭️  Уже есть в {existing_interface}"
        else:
            # Маршрут на другом интерфейсе - заменяем
            keenetic.command(route_delete_command(network, existing_interface))

            # Небольшая пауза перед добавлением нового
            time.sleep(0.3)

    # Добавляем новый маршрут
    result = keenetic.command(route_add_command(network, interface))

    if 'error' not in result.lower():
        if existing_routes is not None:
            existing_routes[network_text] = interface
        if exists:
            return True, f"🔄 Заменён: {existing_interface} → {interface}"
        else:
            return True, "✅ Добавлен"
    else:
        return False, f"❌ Ошибка: {result.strip()[:50]}"
