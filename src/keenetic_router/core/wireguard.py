"""Parse WireGuard client profiles and import them into KeeneticOS.

Private and preshared keys are intentionally absent from summaries, logs, and
dry-run command previews.  Applying a profile is allowed only over SSH because
Telnet would expose those keys as plaintext on the local network.
"""

import base64
from dataclasses import dataclass, field
import ipaddress
from pathlib import Path
import re

from keenetic_router.core.router import discover_wireguard_tunnels


KEY_PATTERN = re.compile(r'^[A-Za-z0-9+/]{43}=$')
SAFE_INTERFACE_PATTERN = re.compile(r'^Wireguard\d+$', re.IGNORECASE)


@dataclass(frozen=True)
class WireGuardPeer:
    """Normalized settings for one ``[Peer]`` section."""

    public_key: str
    preshared_key: str | None
    allowed_ips: tuple[str, ...]
    endpoint: str | None
    persistent_keepalive: int | None


@dataclass(frozen=True)
class WireGuardProfile:
    """Normalized WireGuard client configuration safe for Keenetic import."""

    private_key: str
    addresses: tuple[str, ...]
    dns_servers: tuple[str, ...]
    mtu: int | None
    peers: tuple[WireGuardPeer, ...]

    @property
    def summary(self):
        """Return a non-secret mapping suitable for CLI and desktop previews."""
        endpoints = tuple(peer.endpoint for peer in self.peers if peer.endpoint)
        allowed_count = sum(len(peer.allowed_ips) for peer in self.peers)
        return {
            'addresses': self.addresses,
            'dns_servers': self.dns_servers,
            'peer_count': len(self.peers),
            'endpoints': endpoints,
            'allowed_ip_count': allowed_count,
            'mtu': self.mtu,
        }


@dataclass(frozen=True)
class TunnelImportResult:
    """Outcome of planning or applying a WireGuard tunnel."""

    interface: str
    applied: bool
    command_count: int
    warnings: tuple[str, ...] = field(default_factory=tuple)
    preview: tuple[str, ...] = field(default_factory=tuple)


class WireGuardConfigError(ValueError):
    """Raised when a WireGuard profile cannot be safely interpreted."""


class WireGuardImportError(RuntimeError):
    """Raised when KeeneticOS rejects a planned tunnel command."""


def _validate_key(value, label):
    """Validate a 32-byte WireGuard key without returning decoded bytes."""
    value = value.strip()
    try:
        decoded = base64.b64decode(value, validate=True)
    except Exception as error:
        raise WireGuardConfigError(f'{label}: некорректный Base64-ключ') from error
    if len(decoded) != 32 or not KEY_PATTERN.fullmatch(value):
        raise WireGuardConfigError(f'{label}: ожидается WireGuard-ключ длиной 44 символа')
    return value


def _split_csv(values):
    """Split repeated comma-separated configuration values in stable order."""
    result = []
    for value in values:
        for item in value.split(','):
            candidate = item.strip()
            if candidate and candidate not in result:
                result.append(candidate)
    return tuple(result)


def _parse_sections(text):
    """Parse INI-like WireGuard data while preserving repeated Peer sections."""
    interface = None
    peers = []
    current = None
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip().lower()
            if section == 'interface':
                if interface is not None:
                    raise WireGuardConfigError('Конфигурация содержит несколько секций [Interface]')
                interface = {}
                current = interface
            elif section == 'peer':
                current = {}
                peers.append(current)
            else:
                raise WireGuardConfigError(f'Строка {line_number}: неизвестная секция [{section}]')
            continue
        if current is None or '=' not in line:
            raise WireGuardConfigError(f'Строка {line_number}: ожидается параметр Key = Value')
        key, value = line.split('=', 1)
        normalized_key = key.strip().lower()
        current.setdefault(normalized_key, []).append(value.strip())
    if interface is None:
        raise WireGuardConfigError('Не найдена секция [Interface]')
    if not peers:
        raise WireGuardConfigError('Не найдена ни одна секция [Peer]')
    return interface, peers


def parse_wireguard_config(text):
    """Validate WireGuard configuration text and return a normalized profile.

    Args:
        text: Contents of a standard WireGuard ``.conf`` file or QR code.

    Raises:
        WireGuardConfigError: If required keys, addresses, or peers are invalid.
    """
    interface, peer_sections = _parse_sections(text)
    private_values = interface.get('privatekey', [])
    if len(private_values) != 1:
        raise WireGuardConfigError('[Interface] должен содержать один PrivateKey')
    private_key = _validate_key(private_values[0], 'PrivateKey')

    addresses = _split_csv(interface.get('address', []))
    if not addresses:
        raise WireGuardConfigError('[Interface] должен содержать Address')
    normalized_addresses = []
    for address in addresses:
        try:
            normalized_addresses.append(str(ipaddress.ip_interface(address)))
        except ValueError as error:
            raise WireGuardConfigError(f'Некорректный Address: {address}') from error

    dns_servers = _split_csv(interface.get('dns', []))
    mtu = None
    if interface.get('mtu'):
        try:
            mtu = int(interface['mtu'][-1])
        except ValueError as error:
            raise WireGuardConfigError('MTU должен быть целым числом') from error
        if not 576 <= mtu <= 9000:
            raise WireGuardConfigError('MTU должен быть от 576 до 9000')

    peers = []
    for index, values in enumerate(peer_sections, start=1):
        public_values = values.get('publickey', [])
        if len(public_values) != 1:
            raise WireGuardConfigError(f'[Peer] #{index} должен содержать один PublicKey')
        public_key = _validate_key(public_values[0], f'PublicKey peer #{index}')
        preshared_values = values.get('presharedkey', [])
        if len(preshared_values) > 1:
            raise WireGuardConfigError(f'[Peer] #{index} содержит несколько PresharedKey')
        preshared_key = (
            _validate_key(preshared_values[0], f'PresharedKey peer #{index}')
            if preshared_values
            else None
        )
        allowed = _split_csv(values.get('allowedips', []))
        normalized_allowed = []
        for network in allowed:
            try:
                normalized_allowed.append(str(ipaddress.ip_network(network, strict=False)))
            except ValueError as error:
                raise WireGuardConfigError(f'Некорректный AllowedIPs: {network}') from error
        endpoint_values = values.get('endpoint', [])
        if len(endpoint_values) > 1:
            raise WireGuardConfigError(f'[Peer] #{index} содержит несколько Endpoint')
        endpoint = endpoint_values[0].strip() if endpoint_values else None
        keepalive = None
        if values.get('persistentkeepalive'):
            try:
                keepalive = int(values['persistentkeepalive'][-1])
            except ValueError as error:
                raise WireGuardConfigError('PersistentKeepalive должен быть целым числом') from error
            if not 0 <= keepalive <= 65535:
                raise WireGuardConfigError('PersistentKeepalive вне допустимого диапазона')
        peers.append(
            WireGuardPeer(
                public_key=public_key,
                preshared_key=preshared_key,
                allowed_ips=tuple(normalized_allowed),
                endpoint=endpoint,
                persistent_keepalive=keepalive,
            )
        )
    return WireGuardProfile(
        private_key=private_key,
        addresses=tuple(normalized_addresses),
        dns_servers=dns_servers,
        mtu=mtu,
        peers=tuple(peers),
    )


def load_wireguard_file(path):
    """Read and parse a UTF-8 WireGuard configuration file."""
    config_path = Path(path).expanduser()
    try:
        return parse_wireguard_config(config_path.read_text(encoding='utf-8-sig'))
    except OSError as error:
        raise WireGuardConfigError(f'Не удалось прочитать {config_path}: {error}') from error


def load_wireguard_qr(path):
    """Decode a WireGuard QR image and return its normalized profile.

    Raises:
        WireGuardConfigError: If Pillow/zxing cannot read a QR code or the QR
            payload is not a valid WireGuard configuration.
    """
    try:
        from PIL import Image
        import zxingcpp
    except ImportError as error:
        raise WireGuardConfigError('Для QR установи зависимости Pillow и zxing-cpp') from error
    try:
        with Image.open(Path(path).expanduser()) as image:
            barcode = zxingcpp.read_barcode(image, formats=zxingcpp.BarcodeFormat.QRCode)
    except OSError as error:
        raise WireGuardConfigError(f'Не удалось открыть изображение QR: {error}') from error
    if barcode is None or not barcode.text.strip():
        raise WireGuardConfigError('На изображении не найден читаемый QR-код')
    return parse_wireguard_config(barcode.text)


def next_wireguard_interface(client):
    """Return the first free ``WireguardN`` name discovered on the router."""
    short_to_full, _inverse = discover_wireguard_tunnels(client)
    used = {
        int(match.group(1))
        for full_name in short_to_full.values()
        if (match := re.fullmatch(r'Wireguard(\d+)', full_name, re.IGNORECASE))
    }
    index = 0
    while index in used:
        index += 1
    return f'Wireguard{index}'


def _safe_description(value):
    """Normalize a short display name accepted by the Keenetic CLI."""
    cleaned = re.sub(r'[^0-9A-Za-zА-Яа-яЁё_. -]+', '-', str(value).strip())[:64].strip()
    return cleaned or 'WireGuard VPN'


def _build_commands(profile, interface, description, via):
    """Build executable and redacted command plans for a new tunnel."""
    if not SAFE_INTERFACE_PATTERN.fullmatch(interface):
        raise WireGuardConfigError('Имя интерфейса должно выглядеть как Wireguard2')
    warnings = []
    commands = [f'interface {interface}', f'description "{_safe_description(description)}"']
    preview = list(commands)
    commands.append(f'wireguard private-key {profile.private_key}')
    preview.append('wireguard private-key ***')

    ipv4_addresses = [ipaddress.ip_interface(value) for value in profile.addresses if ':' not in value]
    if not ipv4_addresses:
        raise WireGuardConfigError('В конфигурации нет IPv4 Address, нужного текущему менеджеру маршрутов')
    address = ipv4_addresses[0]
    commands.append(f'ip address {address.ip} {address.network.netmask}')
    preview.append(commands[-1])
    if len(profile.addresses) > 1:
        warnings.append('В Keenetic импортирован только первый IPv4 Address')
    if profile.dns_servers:
        warnings.append('DNS из WireGuard-конфига не меняет DNS домашней сети автоматически')
    if profile.mtu is not None:
        warnings.append('MTU из конфигурации пока не применяется автоматически')

    for peer in profile.peers:
        commands.append(f'wireguard peer {peer.public_key}')
        preview.append('wireguard peer <public-key>')
        if peer.endpoint:
            commands.append(f'endpoint {peer.endpoint}')
            preview.append(commands[-1])
        ipv4_allowed = [ipaddress.ip_network(value) for value in peer.allowed_ips if ':' not in value]
        for network in ipv4_allowed:
            commands.append(f'allow-ips {network.network_address} {network.netmask}')
            preview.append(commands[-1])
        if any(':' in value for value in peer.allowed_ips):
            warnings.append('IPv6 AllowedIPs пропущены; текущая маршрутизация проекта работает с IPv4')
        if peer.persistent_keepalive is not None:
            commands.append(f'keepalive-interval {peer.persistent_keepalive}')
            preview.append(commands[-1])
        if peer.preshared_key:
            commands.append(f'preshared-key {peer.preshared_key}')
            preview.append('preshared-key ***')
        if via:
            commands.append(f'connect via {via}')
            preview.append(commands[-1])
        commands.append('exit')
        preview.append('exit')
    commands.extend(['up', 'exit', 'system configuration save'])
    preview.extend(['up', 'exit', 'system configuration save'])
    return commands, preview, tuple(dict.fromkeys(warnings))


def import_wireguard_profile(
    client,
    profile,
    *,
    description='WireGuard VPN',
    via='ISP',
    interface=None,
    dry_run=False,
):
    """Plan or apply one new WireGuard interface over authenticated SSH.

    Args:
        client: Connected Keenetic client. Applying requires SSH.
        profile: Parsed :class:`WireGuardProfile`.
        description: Human-readable tunnel name.
        via: Existing Keenetic uplink used to reach peer endpoints.
        interface: Optional free ``WireguardN`` identifier.
        dry_run: Return a redacted plan without changing KeeneticOS.

    Raises:
        WireGuardImportError: If Telnet is used, the interface already exists,
            or KeeneticOS rejects a command.  A newly created partial interface
            is removed on failure.
    """
    selected_interface = interface or next_wireguard_interface(client)
    existing, _inverse = discover_wireguard_tunnels(client)
    if selected_interface.lower() in {value.lower() for value in existing.values()}:
        raise WireGuardImportError(f'{selected_interface} уже существует; выбери новый интерфейс')
    commands, preview, warnings = _build_commands(
        profile, selected_interface, description, str(via).strip()
    )
    if dry_run:
        return TunnelImportResult(selected_interface, False, len(commands), warnings, tuple(preview))
    if getattr(client, 'transport', None) != 'ssh':
        raise WireGuardImportError('Импорт приватного ключа запрещён через незашифрованный Telnet')

    context_depth = 0
    try:
        for command in commands:
            output = client.command(command)
            if command.startswith('interface '):
                context_depth = 1
            elif command.startswith('wireguard peer '):
                context_depth = 2
            elif command == 'exit' and context_depth:
                context_depth -= 1
            if 'error' in output.lower():
                raise WireGuardImportError(f'KeeneticOS отклонил команду «{preview[commands.index(command)]}»')
    except Exception as error:
        try:
            while context_depth:
                client.command('exit')
                context_depth -= 1
            client.command(f'no interface {selected_interface}')
            client.command('system configuration save')
        except Exception:
            pass
        if isinstance(error, WireGuardImportError):
            raise
        raise WireGuardImportError(f'Импорт {selected_interface} прерван: {type(error).__name__}') from error
    return TunnelImportResult(selected_interface, True, len(commands), warnings, tuple(preview))


def _run_management_commands(client, commands):
    """Execute non-secret interface management commands with error checks."""
    for command in commands:
        output = client.command(command)
        if 'error' in output.lower():
            raise WireGuardImportError(f'KeeneticOS отклонил команду «{command}»')


def rename_wireguard_tunnel(client, interface, description):
    """Rename an existing WireGuard interface and save KeeneticOS config.

    Args:
        client: Authenticated Keenetic command client.
        interface: Existing technical id such as ``Wireguard1``.
        description: New user-facing name.

    Returns:
        Sanitized name stored on the router.
    """
    if not SAFE_INTERFACE_PATTERN.fullmatch(str(interface)):
        raise WireGuardConfigError('Некорректный интерфейс WireGuard')
    cleaned = _safe_description(description)
    _run_management_commands(
        client,
        [
            f'interface {interface}',
            f'description "{cleaned}"',
            'exit',
            'system configuration save',
        ],
    )
    return cleaned


def set_wireguard_tunnel_enabled(client, interface, enabled):
    """Bring an existing WireGuard interface up or down and persist it."""
    if not SAFE_INTERFACE_PATTERN.fullmatch(str(interface)):
        raise WireGuardConfigError('Некорректный интерфейс WireGuard')
    action = 'up' if enabled else 'down'
    _run_management_commands(
        client,
        [
            f'interface {interface}',
            action,
            'exit',
            'system configuration save',
        ],
    )
    return action


def delete_wireguard_tunnel(client, interface):
    """Delete one explicitly selected WireGuard interface and save config."""
    if not SAFE_INTERFACE_PATTERN.fullmatch(str(interface)):
        raise WireGuardConfigError('Некорректный интерфейс WireGuard')
    _run_management_commands(
        client,
        [f'no interface {interface}', 'system configuration save'],
    )
