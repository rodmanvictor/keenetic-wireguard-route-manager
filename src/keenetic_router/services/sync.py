"""Resolve managed domains and apply new IPv4 routes to Keenetic."""

from dataclasses import dataclass

from keenetic_router.core.router import (
    add_route_smart,
    create_router_client,
    discover_wireguard_tunnels,
    normalize_tunnel_name,
    resolve_domain,
)
from keenetic_router.services.registry import (
    finish_run,
    list_managed_domains,
    record_event,
    record_domain_route,
    record_resolved_address,
    start_run,
)


@dataclass
class SyncSummary:
    """Counters and status returned by one route synchronization run."""

    status: str
    added: int = 0
    unchanged: int = 0
    errors: int = 0


def sync_domains(domains=None, dry_run=False):
    """Synchronize managed domains with the router.

    Only newly observed IPv4 addresses are added. Previously known addresses
    are intentionally retained in this first version to avoid deleting a
    working route after a temporary DNS or CDN change.
    """
    selected = [row for row in (domains or list_managed_domains()) if row['enabled']]
    run_id = start_run()
    summary = SyncSummary(status='success')
    if not selected:
        finish_run(run_id, 'success')
        return summary

    client = None
    try:
        if not dry_run:
            client = create_router_client()
            short_to_full, full_to_short = discover_wireguard_tunnels(client)
        else:
            short_to_full, full_to_short = {}, {}

        for domain in selected:
            addresses = resolve_domain(domain['domain'])
            if not addresses:
                summary.errors += 1
                record_event(run_id, domain['id'], 'resolve-error', None, 'DNS не вернул IPv4-адреса')
                continue

            tunnel = normalize_tunnel_name(domain['tunnel'], short_to_full, full_to_short)
            if not dry_run and tunnel not in short_to_full:
                summary.errors += 1
                record_event(run_id, domain['id'], 'tunnel-error', None, f'Туннель {domain["tunnel"]} не найден')
                continue

            for address in addresses:
                if dry_run:
                    record_event(run_id, domain['id'], 'resolved', address, 'Проверка без изменения роутера')
                    summary.unchanged += 1
                    continue

                success, detail = add_route_smart(client, address, '255.255.255.255', short_to_full[tunnel])
                if success:
                    record_resolved_address(domain['id'], address)
                    record_domain_route(domain['domain'], address, short_to_full[tunnel])
                    action = 'added' if 'Добавлен' in detail or 'Заменён' in detail else 'unchanged'
                    record_event(run_id, domain['id'], action, address, detail)
                    if action == 'added':
                        summary.added += 1
                    else:
                        summary.unchanged += 1
                else:
                    summary.errors += 1
                    record_event(run_id, domain['id'], 'route-error', address, detail)

        if not dry_run and summary.added:
            client.command('system configuration save')
        summary.status = 'success' if not summary.errors else 'partial'
        finish_run(run_id, summary.status, summary.added, summary.unchanged)
    except Exception as error:
        summary.status = 'failed'
        summary.errors += 1
        finish_run(run_id, summary.status, summary.added, summary.unchanged, str(error))
    finally:
        if client is not None:
            client.disconnect()
    return summary
