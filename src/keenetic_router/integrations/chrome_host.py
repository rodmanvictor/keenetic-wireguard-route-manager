"""Native Messaging host used by the PackeTech Chrome extension.

Chrome starts this module as a separate process. It loads the same saved router
profile and SQLite registry as the desktop application, so the extension never
asks for credentials, database paths, or technical WireGuard interface names.
"""

from __future__ import annotations

import json
import re
import struct
import sys

from keenetic_router.core.profiles import load_profile
from keenetic_router.core.router import (
    configure_runtime_connection,
    create_router_client,
    discover_wireguard_tunnel_details,
)
from keenetic_router.services.registry import (
    add_managed_domain,
    domain_addresses,
    find_managed_domain,
    list_managed_domains,
    normalize_domain,
    split_sources,
)
from keenetic_router.services.sync import sync_domains


MAX_DOMAINS = 200
TUNNEL_PATTERN = re.compile(r'^wg\d+$')
_PROFILE = None


def read_message():
    """Read and decode one length-prefixed JSON message from Chrome.

    Returns:
        A decoded JSON value, or ``None`` when Chrome closes stdin.

    Raises:
        RuntimeError: If the native-messaging frame is incomplete.
        json.JSONDecodeError: If the payload is not valid UTF-8 JSON.
    """
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        return None
    if len(raw_length) < 4:
        raise RuntimeError('Invalid message length header')
    message_length = struct.unpack('<I', raw_length)[0]
    data = sys.stdin.buffer.read(message_length)
    if len(data) < message_length:
        raise RuntimeError('Invalid message body')
    return json.loads(data.decode('utf-8'))


def send_message(message):
    """Encode and write one native-messaging response to Chrome."""
    payload = json.dumps(message, ensure_ascii=False).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('<I', len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def configure_saved_router():
    """Load the desktop profile and configure this helper process.

    Returns:
        The validated saved router profile.

    Raises:
        RuntimeError: If PackeTech has not stored an administrator password yet.

    Side effects:
        Configures the shared router-client factory for the helper process.
    """
    global _PROFILE
    profile = load_profile()
    if not profile.password:
        raise RuntimeError('Сначала подключитесь к роутеру в приложении PackeTech')
    configure_runtime_connection(
        profile.host,
        profile.user,
        profile.password,
        transport=profile.preferred_transport if profile.preferred_transport != 'auto' else 'ssh',
        ssh_port=profile.ssh_port,
        telnet_port=profile.telnet_port,
    )
    _PROFILE = profile
    return profile


def choose_tunnel(requested=None):
    """Return a usable ``wgN`` tunnel without requiring browser settings.

    Args:
        requested: Optional tunnel supplied by an older extension build.

    Returns:
        A short tunnel identifier. Existing managed domains are preferred;
        otherwise live Keenetic interfaces are inspected and an active one wins.

    Raises:
        RuntimeError: If no WireGuard interface exists on the router.
        ValueError: If an explicitly requested identifier is malformed.
    """
    if requested is not None:
        candidate = str(requested).strip().lower()
        if not TUNNEL_PATTERN.fullmatch(candidate):
            raise ValueError('Некорректный WireGuard-туннель')
        return candidate

    existing = [row for row in list_managed_domains() if row['enabled']]
    if existing:
        return sorted(existing, key=lambda row: row['updated_at'], reverse=True)[0]['tunnel']

    client = create_router_client()
    try:
        details = discover_wireguard_tunnel_details(client)
    finally:
        client.disconnect()
    active = sorted(name for name, tunnel in details.items() if tunnel.status == 'up')
    available = active or sorted(details)
    if not available:
        raise RuntimeError('На роутере не найден WireGuard-профиль')
    return available[0]


def handle_add_routes(request):
    """Register Chrome ownership and synchronize valid requested domains."""
    domains_in = request.get('domains')
    if not isinstance(domains_in, list):
        return {'ok': False, 'error': 'Список доменов не передан'}

    normalized = []
    seen = set()
    for item in domains_in:
        try:
            domain = normalize_domain(item)
        except ValueError:
            continue
        if domain not in seen:
            seen.add(domain)
            normalized.append(domain)
    if not normalized:
        return {'ok': False, 'error': 'Не найден корректный домен'}
    if len(normalized) > MAX_DOMAINS:
        return {'ok': False, 'error': f'Слишком много доменов: максимум {MAX_DOMAINS}'}

    try:
        tunnel = choose_tunnel(request.get('tunnel'))
        for domain in normalized:
            add_managed_domain(domain, tunnel, source='chrome')
        rows = [row for row in list_managed_domains() if row['domain'] in normalized]
        summary = sync_domains(rows)
        results = [
            {
                'domain': row['domain'],
                'ips': [item['address'] for item in domain_addresses(row['id'])],
                'sources': list(split_sources(row['sources'])),
            }
            for row in rows
        ]
        return {
            'ok': summary.status != 'failed',
            'router': _PROFILE.host if _PROFILE else '',
            'tunnel': tunnel,
            'source': 'chrome',
            'results': results,
            'summary': {
                'domains_total': len(rows),
                'ips_total': sum(len(item['ips']) for item in results),
                'added': summary.added,
                'unchanged': summary.unchanged,
                'errors': summary.errors,
                'status': summary.status,
            },
        }
    except Exception as error:
        return {'ok': False, 'error': str(error)}


def handle_domain_status(request):
    """Return the shared registry state for one browser domain."""
    try:
        domain = normalize_domain(request.get('domain'))
    except ValueError:
        return {'ok': False, 'error': 'Некорректный домен'}
    row = find_managed_domain(domain)
    if row is None:
        return {'ok': True, 'domain': domain, 'tracked': False, 'sources': [], 'ips': []}
    return {
        'ok': True,
        'domain': domain,
        'tracked': bool(row['enabled']),
        'sources': list(split_sources(row['sources'])),
        'ips': [item['address'] for item in domain_addresses(row['id'])],
        'tunnel': row['tunnel'],
    }


def handle_request(request):
    """Dispatch one decoded extension request without exposing credentials."""
    action = request.get('action') if isinstance(request, dict) else None
    if action == 'ping':
        return {'ok': True, 'message': 'pong'}
    if action == 'get_domain_status':
        return handle_domain_status(request)
    if action == 'add_routes_for_domains':
        return handle_add_routes(request)
    return {'ok': False, 'error': 'Неизвестная команда расширения'}


def main():
    """Serve Chrome until the native-messaging channel closes."""
    try:
        configure_saved_router()
    except Exception as error:
        send_message({'ok': False, 'error': str(error)})
        return
    while True:
        request = read_message()
        if request is None:
            break
        send_message(handle_request(request))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        send_message({'ok': False, 'error': f'Помощник PackeTech остановлен: {error}'})
