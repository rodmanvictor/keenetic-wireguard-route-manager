#!/usr/bin/env python3
"""Native messaging host for Keenetic Chrome extension."""

import json
import re
import struct
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / 'src'
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from keenetic_router.core.router import ROUTER_HOST
from keenetic_router.services.registry import (
    add_managed_domain,
    domain_addresses,
    find_managed_domain,
    list_managed_domains,
    split_sources,
)
from keenetic_router.services.sync import sync_domains

MAX_DOMAINS = 200


def read_message():
    raw_len = sys.stdin.buffer.read(4)
    if len(raw_len) == 0:
        return None
    if len(raw_len) < 4:
        raise RuntimeError('Invalid message length header')
    msg_len = struct.unpack('<I', raw_len)[0]
    data = sys.stdin.buffer.read(msg_len)
    if len(data) < msg_len:
        raise RuntimeError('Invalid message body')
    return json.loads(data.decode('utf-8'))


def send_message(message):
    payload = json.dumps(message, ensure_ascii=False).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('<I', len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def normalize_domain(value):
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    if '://' in text:
        try:
            parsed = urlparse(text)
            host = parsed.hostname
        except Exception:
            return None
    else:
        host = text

    if not host:
        return None

    host = host.strip().lower().rstrip('.')
    if host in {'localhost', '127.0.0.1', '::1'}:
        return None

    try:
        host = host.encode('idna').decode('ascii')
    except Exception:
        return None

    if len(host) > 253:
        return None

    label_re = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')
    labels = host.split('.')
    if len(labels) < 2:
        return None
    for label in labels:
        if not label_re.match(label):
            return None

    return host


def handle_add_routes(request):
    """Register Chrome as a source and synchronize the requested domains.

    The native host intentionally delegates route changes to the shared sync
    service. This keeps Chrome, CLI, TUI and desktop behavior identical and
    records every browser-added domain for later review.
    """
    tunnel = request.get('tunnel')
    domains_in = request.get('domains')

    if not isinstance(tunnel, str) or not re.match(r'^wg\d*$', tunnel):
        return {'ok': False, 'error': 'Invalid tunnel. Expected format wgN'}

    if not isinstance(domains_in, list):
        return {'ok': False, 'error': 'domains must be array'}

    normalized = []
    seen = set()
    for item in domains_in:
        dom = normalize_domain(item)
        if dom and dom not in seen:
            seen.add(dom)
            normalized.append(dom)

    if len(normalized) == 0:
        return {'ok': False, 'error': 'No valid domains'}

    if len(normalized) > MAX_DOMAINS:
        return {'ok': False, 'error': f'Too many domains (>{MAX_DOMAINS})'}

    try:
        for domain in normalized:
            add_managed_domain(domain, tunnel, source='chrome')
        rows = [
            row for row in list_managed_domains()
            if row['domain'] in normalized
        ]
        sync_summary = sync_domains(rows)
        results = []
        for row in rows:
            results.append(
                {
                    'domain': row['domain'],
                    'ips': [item['address'] for item in domain_addresses(row['id'])],
                    'sources': list(split_sources(row['sources'])),
                }
            )

        return {
            'ok': sync_summary.status != 'failed',
            'router': ROUTER_HOST,
            'tunnel': tunnel,
            'source': 'chrome',
            'results': results,
            'summary': {
                'domains_total': len(rows),
                'ips_total': sum(len(item['ips']) for item in results),
                'added': sync_summary.added,
                'unchanged': sync_summary.unchanged,
                'errors': sync_summary.errors,
                'status': sync_summary.status,
            },
        }
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


def handle_domain_status(request):
    """Return whether a domain is tracked and which interfaces claimed it."""
    domain = normalize_domain(request.get('domain'))
    if not domain:
        return {'ok': False, 'error': 'Invalid domain'}
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
    action = request.get('action')
    if action == 'ping':
        return {'ok': True, 'message': 'pong'}
    if action == 'get_domain_status':
        return handle_domain_status(request)
    if action == 'add_routes_for_domains':
        return handle_add_routes(request)
    return {'ok': False, 'error': 'Unknown action'}


def main():
    while True:
        req = read_message()
        if req is None:
            break
        resp = handle_request(req)
        send_message(resp)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        send_message({'ok': False, 'error': f'host-fatal: {exc}'})
