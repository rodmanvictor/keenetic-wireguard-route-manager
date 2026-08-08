"""Read current Keenetic routes and attribute them to published service lists."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import ipaddress
import json
import urllib.request

from keenetic_router.core.router import (
    create_router_client,
    parse_wireguard_routes_output,
)
from keenetic_router.services.registry import inventory_summary, store_route_inventory


RUCENS_API = 'https://api.github.com/repos/vitalygashkov/rucens/contents/bat'
RUCENS_RAW = 'https://raw.githubusercontent.com/vitalygashkov/rucens/main/bat/{service}.bat'
GOOGLE_RANGES = 'https://www.gstatic.com/ipranges/goog.json'
TELEGRAM_RANGES = 'https://core.telegram.org/resources/cidr.txt'


def fetch_text(url):
    """Download one public source file with a stable User-Agent and timeout."""
    request = urllib.request.Request(url, headers={'User-Agent': 'keenetic-route-inventory/1.0'})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode('utf-8')


def router_routes():
    """Return unique IPv4/IPv6 WireGuard routes from the live Keenetic."""
    client = create_router_client()
    try:
        outputs = (
            client.command('show ip route'),
            client.command('show ipv6 route'),
        )
    finally:
        client.disconnect()
    routes = [
        (route['network'], route['interface'])
        for output in outputs
        for route in parse_wireguard_routes_output(output)
    ]
    return list(dict.fromkeys(routes))


def parse_bat_routes(text):
    """Extract CIDR networks from one rucens Windows route batch file."""
    networks = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[:2] == ['route', 'add'] and parts[3].lower() == 'mask':
            try:
                networks.append(str(ipaddress.ip_network(f'{parts[2]}/{parts[4]}', strict=False)))
            except ValueError:
                continue
    return networks


def collected_claims(networks):
    """Return exact source claims for the current router networks.

    Exact matches are deliberately used during initial reverse engineering.
    A containing CIDR is useful context but is not strong enough evidence to
    assign ownership automatically.
    """
    known = set(networks)
    claims = defaultdict(list)
    services = [item['name'][:-4] for item in json.loads(fetch_text(RUCENS_API)) if item['name'].endswith('.bat')]

    def download_service(service):
        return service, parse_bat_routes(fetch_text(RUCENS_RAW.format(service=service)))

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(download_service, service) for service in services]
        for future in as_completed(futures):
            service, service_networks = future.result()
            for network in service_networks:
                if network in known:
                    claims[network].append({'kind': 'rucens', 'name': service, 'confidence': 'exact'})

    for item in json.loads(fetch_text(GOOGLE_RANGES)).get('prefixes', []):
        for key in ('ipv4Prefix', 'ipv6Prefix'):
            network = item.get(key)
            if network in known:
                claims[network].append(
                    {'kind': 'published', 'name': 'google', 'confidence': 'exact'}
                )
    for line in fetch_text(TELEGRAM_RANGES).splitlines():
        network = line.strip()
        if network in known:
            claims[network].append({'kind': 'published', 'name': 'telegram', 'confidence': 'exact'})
    return claims


def import_current_inventory():
    """Reverse-engineer current routes into SQLite without changing Keenetic."""
    routes = router_routes()
    claims = collected_claims([network for network, _ in routes])
    store_route_inventory(routes, claims)
    stored = inventory_summary()
    unclassified = int(stored['unclassified'] or 0)
    return {
        'routes': len(routes),
        'attributed': len(routes) - unclassified,
        'shared': int(stored['shared'] or 0),
        'unclassified': unclassified,
    }
