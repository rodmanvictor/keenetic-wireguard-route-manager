"""Selectable rucens service catalog with optional DNS follow-up domains."""

from dataclasses import dataclass
import ipaddress
import re

from keenetic_router.core.router import (
    add_route_smart,
    create_router_client,
    discover_wireguard_tunnels,
    normalize_tunnel_name,
)
from keenetic_router.services.inventory import RUCENS_API, RUCENS_RAW, fetch_text, parse_bat_routes
from keenetic_router.services.registry import (
    add_managed_domain,
    find_managed_domain,
    inventory_services,
    list_managed_domains,
)
from keenetic_router.services.sync import sync_domains


# Only explicit, well-known product domains belong here. An absent mapping is
# intentional: guessing domains from a rucens service label would be unsafe.
SERVICE_DOMAINS = {
    'anthropic': ('anthropic.com',),
    'chatgpt': ('chatgpt.com', 'chat.openai.com'),
    'claude': ('claude.ai',),
    'discord': ('discord.com',),
    'gemini': ('gemini.google.com',),
    'notion': ('notion.so',),
    'telegram': ('telegram.org',),
    'tiktok': ('tiktok.com',),
    'twitter': ('x.com',),
    'youtube': ('youtube.com',),
}


@dataclass
class CatalogAddSummary:
    """Outcome counters for one selected rucens service import."""

    added: int = 0
    unchanged: int = 0
    errors: int = 0
    watched_domains: int = 0


@dataclass
class InventoryDomainSummary:
    """Counters returned while linking recovered services to DNS watches."""

    registered: int = 0
    existing: int = 0
    skipped_unknown: int = 0
    skipped_ambiguous: int = 0


def reconcile_inventory_domains():
    """Create DNS watches for known single-tunnel rucens inventory services.

    Reverse inventory stores exact CIDR ownership independently from recurring
    DNS subscriptions. This reconciliation links only explicit
    :data:`SERVICE_DOMAINS` mappings and only when every live route for that
    service uses one numbered WireGuard interface. It never contacts or changes
    the router.
    """
    summary = InventoryDomainSummary()
    for service in inventory_services():
        if service['source_kind'] != 'rucens':
            continue
        domains = SERVICE_DOMAINS.get(service['source_name'])
        if not domains:
            summary.skipped_unknown += 1
            continue
        interfaces = {
            item.strip()
            for item in (service['interfaces'] or '').split(',')
            if item.strip()
        }
        if len(interfaces) != 1:
            summary.skipped_ambiguous += 1
            continue
        interface = next(iter(interfaces))
        match = re.fullmatch(r'Wireguard(\d+)', interface, flags=re.IGNORECASE)
        if not match:
            summary.skipped_ambiguous += 1
            continue
        tunnel = f'wg{match.group(1)}'
        for domain in domains:
            if find_managed_domain(domain) is not None:
                summary.existing += 1
                continue
            _, created = add_managed_domain(
                domain,
                tunnel,
                source=f'rucens:{service["source_name"]}',
            )
            if created:
                summary.registered += 1
    return summary


def available_services():
    """Return the current alphabetized service names published by rucens."""
    entries = fetch_text(RUCENS_API)
    import json

    return sorted(item['name'][:-4] for item in json.loads(entries) if item['name'].endswith('.bat'))


def parse_selection(value, available_count):
    """Parse comma- or whitespace-separated one-based catalog indexes.

    Raises:
        ValueError: When the selection contains an invalid or out-of-range index.
    """
    tokens = [token for token in re.split(r'[\s,]+', value.strip()) if token]
    if not tokens:
        raise ValueError('Выбери хотя бы один номер.')
    indexes = []
    for token in tokens:
        if not token.isdigit() or not 1 <= int(token) <= available_count:
            raise ValueError(f'Номер {token!r} вне списка.')
        index = int(token) - 1
        if index not in indexes:
            indexes.append(index)
    return indexes


def selected_service_domains(services, tunnel):
    """Register known DNS follow-up domains and return their database rows."""
    registered = []
    for service in services:
        for domain in SERVICE_DOMAINS.get(service, ()):
            canonical, _ = add_managed_domain(domain, tunnel, source=f'rucens:{service}')
            row = next(item for item in list_managed_domains() if item['domain'] == canonical)
            registered.append(row)
    return registered


def add_catalog_services(services, tunnel):
    """Apply selected rucens ranges and register their known DNS follow-ups.

    The rucens CIDRs and DNS records remain separate sources. The function
    updates Keenetic only through the selected tunnel, then records DNS domains
    for later six-hour synchronization.
    """
    summary = CatalogAddSummary()
    service_routes = {
        service: parse_bat_routes(fetch_text(RUCENS_RAW.format(service=service)))
        for service in services
    }
    client = None
    try:
        client = create_router_client()
        short_to_full, full_to_short = discover_wireguard_tunnels(client)
        short_name = normalize_tunnel_name(tunnel, short_to_full, full_to_short)
        if short_name not in short_to_full:
            raise ValueError(f'Туннель {tunnel} не найден.')
        interface = short_to_full[short_name]
        for service in services:
            for network in service_routes[service]:
                address, prefix = network.split('/')
                mask = str(ipaddress.ip_network(network).netmask)
                success, detail = add_route_smart(client, address, mask, interface)
                if not success:
                    summary.errors += 1
                elif 'Добавлен' in detail or 'Заменён' in detail:
                    summary.added += 1
                else:
                    summary.unchanged += 1
        if summary.added:
            client.command('system configuration save')
    finally:
        if client is not None:
            client.disconnect()

    watched = selected_service_domains(services, short_name)
    summary.watched_domains = len(watched)
    if watched:
        dns_summary = sync_domains(watched)
        summary.added += dns_summary.added
        summary.unchanged += dns_summary.unchanged
        summary.errors += dns_summary.errors
    return summary
