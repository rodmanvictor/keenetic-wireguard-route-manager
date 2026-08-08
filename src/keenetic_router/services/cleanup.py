"""Deliberate removal of route-inventory entries marked as unclassified."""

from datetime import datetime, timezone
import ipaddress
import json

from keenetic_router.core.router import create_router_client, route_delete_command
from keenetic_router.services.registry import (
    connect,
    database_path,
    mark_route_absent,
    release_domain_route_claims,
)


def unclassified_routes():
    """Return live routes whose only active claim is ``preserved:unclassified``."""
    with connect() as connection:
        return connection.execute(
            '''SELECT route_networks.id, route_networks.network, route_networks.interface
               FROM route_networks
               WHERE route_networks.present_on_router = 1
                 AND EXISTS (
                     SELECT 1 FROM route_claims
                     WHERE route_claims.route_id = route_networks.id
                       AND route_claims.active = 1
                       AND route_claims.source_kind = 'preserved'
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM route_claims
                     WHERE route_claims.route_id = route_networks.id
                       AND route_claims.active = 1
                       AND route_claims.source_kind != 'preserved'
                 )
               ORDER BY route_networks.network'''
        ).fetchall()


def backup_routes(routes):
    """Write a recoverable JSON list of exact routes before deleting them."""
    backup_dir = database_path().parent / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    path = backup_dir / f'unclassified-routes-{timestamp}.json'
    payload = {
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'purpose': 'Routes deleted by explicit user request after reverse inventory',
        'routes': [{'network': row['network'], 'interface': row['interface']} for row in routes],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def _mark_absent(route_id):
    """Record a router-confirmed deletion immediately, so batches are resumable."""
    with connect() as connection:
        connection.execute(
            'UPDATE route_networks SET present_on_router = 0 WHERE id = ?', (route_id,)
        )


def purge_unclassified_routes(progress=None, limit=None):
    """Delete only freshly inventoried unclassified routes in a resumable batch.

    Side effects:
        Writes a JSON backup, removes selected routes from Keenetic, saves the
        router configuration, and marks each successfully removed row absent in
        SQLite immediately. A limit keeps a slow Telnet connection from losing
        the result of a long operation. Callers must obtain an explicit
        confirmation before use.
    """
    routes = unclassified_routes()
    if limit is not None:
        routes = routes[:limit]
    if not routes:
        return {'requested': 0, 'removed': 0, 'failed': 0, 'backup': None, 'remaining': 0}
    backup = backup_routes(routes)
    client = create_router_client()
    removed = []
    failed = []
    try:
        for index, route in enumerate(routes, start=1):
            network = ipaddress.ip_network(route['network'], strict=False)
            output = client.command(route_delete_command(network, route['interface']))
            if 'error' in output.lower():
                failed.append(route)
            else:
                removed.append(route)
                _mark_absent(route['id'])
            if progress and (index % 10 == 0 or index == len(routes)):
                progress(index, len(routes), len(removed), len(failed))

        if removed:
            client.command('system configuration save')
    finally:
        client.disconnect()

    return {
        'requested': len(routes),
        'removed': len(removed),
        'failed': len(failed),
        'backup': str(backup),
        'remaining': len(unclassified_routes()),
    }


def purge_domain_routes(domain):
    """Remove exact DNS routes that became orphaned after disabling a domain.

    Args:
        domain: Managed domain whose ``dns-domain`` ownership is being released.

    Returns:
        Mapping with ``requested``, ``removed`` and ``failed`` counters.

    Side effects:
        Deactivates the domain's route claims, removes only routes without any
        remaining active exact owners, saves Keenetic configuration and marks
        successful deletions absent in SQLite. Shared routes are never selected.
    """
    routes = release_domain_route_claims(domain)
    if not routes:
        return {'requested': 0, 'removed': 0, 'failed': 0}
    client = create_router_client()
    removed = 0
    failed = 0
    try:
        for route in routes:
            network = ipaddress.ip_network(route['network'], strict=False)
            output = client.command(route_delete_command(network, route['interface']))
            if 'error' in output.lower():
                failed += 1
                continue
            mark_route_absent(route['id'])
            removed += 1
        if removed:
            client.command('system configuration save')
    finally:
        client.disconnect()
    return {'requested': len(routes), 'removed': removed, 'failed': failed}
