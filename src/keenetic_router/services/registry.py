"""SQLite storage for domains managed by the route synchronizer."""

import os
import platform
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DOMAIN_PATTERN = re.compile(r'^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')
SOURCE_PATTERN = re.compile(r'^[a-z][a-z0-9_.:-]{0,79}$')

SOURCE_LABELS = {
    'chrome': 'Chrome',
    'cli': 'CLI',
    'desktop': 'Desktop',
    'legacy': 'До инвентаризации',
    'terminal': 'Терминал',
}


def utc_now():
    """Return an ISO-8601 UTC timestamp for database audit fields."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def application_data_directory():
    """Return a persistent, platform-native application data directory.

    Source checkouts intentionally retain their historical ``var`` directory.
    Installed wheels and frozen desktop/CLI builds use the operating system's
    per-user data location so a temporary application bundle can never own the
    SQLite registry.
    """
    override = os.getenv('KEENETIC_ROUTE_MANAGER_DATA_DIR')
    if override:
        return Path(override).expanduser()
    if (PROJECT_ROOT / 'pyproject.toml').is_file():
        return PROJECT_ROOT / 'var'
    system = platform.system()
    if system == 'Windows':
        base = Path(os.getenv('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        return base / 'KeeneticRouteManager'
    if system == 'Darwin':
        return Path.home() / 'Library' / 'Application Support' / 'KeeneticRouteManager'
    base = Path(os.getenv('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    return base / 'keenetic-route-manager'


def database_path():
    """Return the configured persistent SQLite path and create its parent."""
    value = os.getenv('ROUTE_SYNC_DATABASE')
    path = Path(value).expanduser() if value else application_data_directory() / 'route-sync.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect():
    """Open, initialize, transactionally yield, and close the SQLite database.

    Raises:
        sqlite3.Error: If initialization or a caller query fails.  The active
            transaction is rolled back before the connection is closed.
    """
    connection = sqlite3.connect(database_path())
    connection.row_factory = sqlite3.Row
    connection.executescript(
        '''
        CREATE TABLE IF NOT EXISTS managed_domains (
            id INTEGER PRIMARY KEY,
            domain TEXT NOT NULL UNIQUE,
            tunnel TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS managed_domain_sources (
            id INTEGER PRIMARY KEY,
            domain_id INTEGER NOT NULL REFERENCES managed_domains(id),
            source_key TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            UNIQUE(domain_id, source_key)
        );
        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            added_count INTEGER NOT NULL DEFAULT 0,
            unchanged_count INTEGER NOT NULL DEFAULT 0,
            error_text TEXT
        );
        CREATE TABLE IF NOT EXISTS sync_events (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL REFERENCES sync_runs(id),
            domain_id INTEGER REFERENCES managed_domains(id),
            occurred_at TEXT NOT NULL,
            action TEXT NOT NULL,
            address TEXT,
            detail TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS resolved_addresses (
            domain_id INTEGER NOT NULL REFERENCES managed_domains(id),
            address TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY (domain_id, address)
        );
        CREATE TABLE IF NOT EXISTS route_networks (
            id INTEGER PRIMARY KEY,
            network TEXT NOT NULL,
            interface TEXT NOT NULL,
            present_on_router INTEGER NOT NULL DEFAULT 1,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            UNIQUE(network, interface)
        );
        CREATE TABLE IF NOT EXISTS route_claims (
            id INTEGER PRIMARY KEY,
            route_id INTEGER NOT NULL REFERENCES route_networks(id),
            source_kind TEXT NOT NULL,
            source_name TEXT NOT NULL,
            confidence TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            UNIQUE(route_id, source_kind, source_name)
        );
        '''
    )
    now = utc_now()
    connection.execute(
        '''INSERT INTO managed_domain_sources
               (domain_id, source_key, active, first_seen_at, last_seen_at)
           SELECT managed_domains.id, 'legacy', 1, ?, ?
           FROM managed_domains
           WHERE NOT EXISTS (
               SELECT 1 FROM managed_domain_sources
               WHERE managed_domain_sources.domain_id = managed_domains.id
           )''',
        (now, now),
    )
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def normalize_domain(value):
    """Extract, validate, and canonicalize a hostname or pasted website URL.

    Args:
        value: Bare hostname or URL containing a scheme, port, path, query, or
            fragment.

    Returns:
        Lowercase IDNA hostname without a trailing dot.

    Raises:
        ValueError: If no valid DNS hostname can be extracted.
    """
    text = str(value or '').strip()
    parsed = urlsplit(text if '://' in text else f'//{text}')
    try:
        domain = (parsed.hostname or '').strip().rstrip('.').lower()
    except ValueError as error:
        raise ValueError('Не удалось найти домен в адресе') from error
    try:
        domain = domain.encode('idna').decode('ascii')
    except UnicodeError as error:
        raise ValueError('Некорректное имя домена') from error
    if not DOMAIN_PATTERN.fullmatch(domain):
        raise ValueError('Не удалось найти домен в адресе')
    return domain


def normalize_source(source):
    """Validate and canonicalize a domain-registration source key.

    Args:
        source: Stable machine-readable key such as ``chrome`` or
            ``rucens:chatgpt``.

    Returns:
        Lowercase source key safe for storage and filtering.

    Raises:
        ValueError: If the key is empty or contains unsupported characters.
    """
    value = str(source or '').strip().lower()
    if not SOURCE_PATTERN.fullmatch(value):
        raise ValueError('Некорректный источник домена')
    return value


def source_label(source):
    """Return a short Russian-facing label for a stored source key."""
    source = normalize_source(source)
    if source.startswith('rucens:'):
        return f'rucens · {source.split(":", 1)[1]}'
    return SOURCE_LABELS.get(source, source)


def split_sources(value):
    """Convert a comma-separated SQLite aggregate into stable source keys."""
    return tuple(item for item in (value or '').split(',') if item)


def add_managed_domain(domain, tunnel, source='terminal'):
    """Create or update a recurring domain subscription.

    Returns a pair of the canonical domain and a flag indicating that a new
    row was created. The tunnel is retained as part of the subscription and
    the source is recorded independently, allowing one domain to be owned by
    several interfaces without losing provenance.
    """
    domain = normalize_domain(domain)
    source = normalize_source(source)
    now = utc_now()
    with connect() as connection:
        existing = connection.execute(
            'SELECT id FROM managed_domains WHERE domain = ?', (domain,)
        ).fetchone()
        connection.execute(
            '''INSERT INTO managed_domains (domain, tunnel, enabled, created_at, updated_at)
               VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(domain) DO UPDATE SET tunnel = excluded.tunnel,
                   enabled = 1, updated_at = excluded.updated_at''',
            (domain, tunnel, now, now),
        )
        domain_id = connection.execute(
            'SELECT id FROM managed_domains WHERE domain = ?', (domain,)
        ).fetchone()['id']
        connection.execute(
            '''INSERT INTO managed_domain_sources
                   (domain_id, source_key, active, first_seen_at, last_seen_at)
               VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(domain_id, source_key) DO UPDATE SET active = 1,
                   last_seen_at = excluded.last_seen_at''',
            (domain_id, source, now, now),
        )
    return domain, existing is None


def list_managed_domains():
    """Return domain subscriptions with active source keys in display order."""
    with connect() as connection:
        return connection.execute(
            '''SELECT managed_domains.*,
                      COALESCE(GROUP_CONCAT(DISTINCT managed_domain_sources.source_key), '') AS sources,
                      COUNT(DISTINCT resolved_addresses.address) AS address_count,
                      COUNT(DISTINCT CASE
                          WHEN route_networks.present_on_router = 1 THEN route_claims.route_id
                      END) AS inventory_route_count
               FROM managed_domains
               LEFT JOIN managed_domain_sources
                   ON managed_domain_sources.domain_id = managed_domains.id
                   AND managed_domain_sources.active = 1
               LEFT JOIN resolved_addresses
                   ON resolved_addresses.domain_id = managed_domains.id
               LEFT JOIN route_claims
                   ON managed_domain_sources.source_key =
                      route_claims.source_kind || ':' || route_claims.source_name
                   AND route_claims.active = 1
               LEFT JOIN route_networks
                   ON route_networks.id = route_claims.route_id
               GROUP BY managed_domains.id
               ORDER BY managed_domains.enabled DESC, managed_domains.domain ASC'''
        ).fetchall()


def domain_inventory_routes(domain_id):
    """Return live inventoried CIDRs claimed by a managed domain's sources."""
    with connect() as connection:
        return connection.execute(
            '''SELECT DISTINCT route_networks.network, route_networks.interface,
                      route_claims.source_kind, route_claims.source_name
               FROM managed_domain_sources
               JOIN route_claims
                   ON managed_domain_sources.source_key =
                      route_claims.source_kind || ':' || route_claims.source_name
                   AND route_claims.active = 1
               JOIN route_networks
                   ON route_networks.id = route_claims.route_id
                   AND route_networks.present_on_router = 1
               WHERE managed_domain_sources.domain_id = ?
                   AND managed_domain_sources.active = 1
               ORDER BY route_networks.network''',
            (domain_id,),
        ).fetchall()


def remove_managed_domain(domain, source=None):
    """Disable a whole subscription or release one of its active sources.

    Args:
        domain: Domain name accepted by :func:`normalize_domain`.
        source: Optional source key to deactivate. When omitted, every source
            and the whole subscription are disabled.

    Returns:
        ``True`` when the domain or requested active source existed.

    Side effects:
        Audit rows and resolved-address history are retained. Releasing one
        source disables the subscription only when no other active sources
        remain.
    """
    domain = normalize_domain(domain)
    source = normalize_source(source) if source else None
    with connect() as connection:
        row = connection.execute(
            'SELECT id FROM managed_domains WHERE domain = ?', (domain,)
        ).fetchone()
        if row is None:
            return False
        now = utc_now()
        if source is None:
            connection.execute(
                'UPDATE managed_domain_sources SET active = 0 WHERE domain_id = ?',
                (row['id'],),
            )
            connection.execute(
                'UPDATE managed_domains SET enabled = 0, updated_at = ? WHERE id = ?',
                (now, row['id']),
            )
            return True
        result = connection.execute(
            '''UPDATE managed_domain_sources SET active = 0, last_seen_at = ?
               WHERE domain_id = ? AND source_key = ? AND active = 1''',
            (now, row['id'], source),
        )
        active_count = connection.execute(
            'SELECT COUNT(*) AS total FROM managed_domain_sources WHERE domain_id = ? AND active = 1',
            (row['id'],),
        ).fetchone()['total']
        if not active_count:
            connection.execute(
                'UPDATE managed_domains SET enabled = 0, updated_at = ? WHERE id = ?',
                (now, row['id']),
            )
        return result.rowcount > 0


def domain_addresses(domain_id):
    """Return remembered IPv4 addresses for one managed domain, newest first."""
    with connect() as connection:
        return connection.execute(
            '''SELECT address, first_seen_at, last_seen_at
               FROM resolved_addresses WHERE domain_id = ?
               ORDER BY last_seen_at DESC, address ASC''',
            (domain_id,),
        ).fetchall()


def find_managed_domain(domain):
    """Return one normalized domain subscription with sources, or ``None``."""
    canonical = normalize_domain(domain)
    return next((row for row in list_managed_domains() if row['domain'] == canonical), None)


def start_run():
    """Create and return an audit row for a synchronization attempt."""
    with connect() as connection:
        cursor = connection.execute(
            'INSERT INTO sync_runs (started_at, status) VALUES (?, ?)',
            (utc_now(), 'running'),
        )
        return cursor.lastrowid


def finish_run(run_id, status, added_count=0, unchanged_count=0, error_text=None):
    """Finalize a synchronization audit row with its outcome counters."""
    with connect() as connection:
        connection.execute(
            '''UPDATE sync_runs SET finished_at = ?, status = ?, added_count = ?,
               unchanged_count = ?, error_text = ? WHERE id = ?''',
            (utc_now(), status, added_count, unchanged_count, error_text, run_id),
        )


def record_event(run_id, domain_id, action, address, detail):
    """Append one human-readable event to a synchronization run."""
    with connect() as connection:
        connection.execute(
            '''INSERT INTO sync_events (run_id, domain_id, occurred_at, action, address, detail)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (run_id, domain_id, utc_now(), action, address, detail),
        )


def record_resolved_address(domain_id, address):
    """Remember that an address was observed for a managed domain."""
    now = utc_now()
    with connect() as connection:
        connection.execute(
            '''INSERT INTO resolved_addresses (domain_id, address, first_seen_at, last_seen_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(domain_id, address) DO UPDATE SET last_seen_at = excluded.last_seen_at''',
            (domain_id, address, now, now),
        )
        connection.execute(
            'UPDATE managed_domains SET last_resolved_at = ?, updated_at = ? WHERE id = ?',
            (now, now, domain_id),
        )


def record_domain_route(domain, address, interface):
    """Claim an exact DNS route for a managed domain.

    Args:
        domain: Canonical managed domain name.
        address: Resolved IPv4 address without a prefix.
        interface: Full Keenetic interface name used by the route.

    Side effects:
        Upserts the ``/32`` route and an active ``dns-domain`` ownership claim.
        Existing claims from another domain or imported source are preserved.
    """
    network = f'{address}/32'
    now = utc_now()
    with connect() as connection:
        connection.execute(
            '''INSERT INTO route_networks
                   (network, interface, present_on_router, first_seen_at, last_seen_at)
               VALUES (?, ?, 1, ?, ?)
               ON CONFLICT(network, interface) DO UPDATE SET present_on_router = 1,
                   last_seen_at = excluded.last_seen_at''',
            (network, interface, now, now),
        )
        route_id = connection.execute(
            'SELECT id FROM route_networks WHERE network = ? AND interface = ?',
            (network, interface),
        ).fetchone()['id']
        connection.execute(
            '''INSERT INTO route_claims
                   (route_id, source_kind, source_name, confidence, active, first_seen_at, last_seen_at)
               VALUES (?, 'dns-domain', ?, 'exact', 1, ?, ?)
               ON CONFLICT(route_id, source_kind, source_name) DO UPDATE SET active = 1,
                   last_seen_at = excluded.last_seen_at''',
            (route_id, domain, now, now),
        )
        connection.execute(
            '''UPDATE route_claims SET active = 0, last_seen_at = ?
               WHERE route_id = ? AND source_kind = 'preserved' AND active = 1''',
            (now, route_id),
        )


def release_domain_route_claims(domain):
    """Deactivate one domain's route claims and return now-orphaned routes.

    A route is returned only when it is present on Keenetic and has no other
    active exact owner. The caller may then safely remove that route from the
    router and mark it absent. Shared DNS addresses and imported exact routes
    are therefore retained.
    """
    domain = normalize_domain(domain)
    now = utc_now()
    with connect() as connection:
        connection.execute(
            '''UPDATE route_claims SET active = 0, last_seen_at = ?
               WHERE source_kind = 'dns-domain' AND source_name = ? AND active = 1''',
            (now, domain),
        )
        return connection.execute(
            '''SELECT route_networks.id, route_networks.network, route_networks.interface
               FROM route_networks
               WHERE route_networks.present_on_router = 1
                 AND EXISTS (
                     SELECT 1 FROM route_claims
                     WHERE route_claims.route_id = route_networks.id
                       AND route_claims.source_kind = 'dns-domain'
                       AND route_claims.source_name = ?
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM route_claims
                     WHERE route_claims.route_id = route_networks.id
                       AND route_claims.active = 1
                 )
               ORDER BY route_networks.network''',
            (domain,),
        ).fetchall()


def mark_route_absent(route_id):
    """Mark one router-confirmed route deletion absent in the inventory."""
    with connect() as connection:
        connection.execute(
            'UPDATE route_networks SET present_on_router = 0 WHERE id = ?', (route_id,)
        )


def recent_runs(limit=8):
    """Return recent synchronization runs with newest first."""
    with connect() as connection:
        return connection.execute(
            'SELECT * FROM sync_runs ORDER BY id DESC LIMIT ?', (limit,)
        ).fetchall()


def recent_events(limit=20):
    """Return the latest domain-level synchronization events."""
    with connect() as connection:
        return connection.execute(
            '''SELECT sync_events.*, managed_domains.domain FROM sync_events
               LEFT JOIN managed_domains ON managed_domains.id = sync_events.domain_id
               ORDER BY sync_events.id DESC LIMIT ?''',
            (limit,),
        ).fetchall()


def store_route_inventory(routes, claims):
    """Store router routes and their many-to-many source claims.

    Args:
        routes: Iterable of ``(network, interface)`` values read from Keenetic.
        claims: Mapping from network text to iterable source claim mappings.

    Side effects:
        Updates SQLite inventory rows only. It never changes router routes.
    """
    now = utc_now()
    with connect() as connection:
        connection.execute('UPDATE route_networks SET present_on_router = 0')
        connection.execute(
            "UPDATE route_claims SET active = 0 WHERE source_kind != 'dns-domain'"
        )
        for network, interface in routes:
            connection.execute(
                '''INSERT INTO route_networks (network, interface, present_on_router, first_seen_at, last_seen_at)
                   VALUES (?, ?, 1, ?, ?)
                   ON CONFLICT(network, interface) DO UPDATE SET present_on_router = 1,
                       last_seen_at = excluded.last_seen_at''',
                (network, interface, now, now),
            )
            route_id = connection.execute(
                'SELECT id FROM route_networks WHERE network = ? AND interface = ?',
                (network, interface),
            ).fetchone()['id']
            source_claims = list(claims.get(network, []))
            if not source_claims:
                domain_claim = connection.execute(
                    '''SELECT 1 FROM route_claims
                       WHERE route_id = ? AND source_kind = 'dns-domain' AND active = 1
                       LIMIT 1''',
                    (route_id,),
                ).fetchone()
                if domain_claim is None:
                    source_claims = [
                        {'kind': 'preserved', 'name': 'unclassified', 'confidence': 'none'}
                    ]
            for claim in source_claims:
                connection.execute(
                    '''INSERT INTO route_claims (route_id, source_kind, source_name, confidence, active, first_seen_at, last_seen_at)
                       VALUES (?, ?, ?, ?, 1, ?, ?)
                       ON CONFLICT(route_id, source_kind, source_name) DO UPDATE SET active = 1,
                           confidence = excluded.confidence, last_seen_at = excluded.last_seen_at''',
                    (route_id, claim['kind'], claim['name'], claim['confidence'], now, now),
                )


def inventory_summary():
    """Return aggregate route ownership counts for the administration dashboard."""
    with connect() as connection:
        return connection.execute(
            '''SELECT COUNT(*) AS routes,
                      SUM(CASE WHEN preserved_count > 0 THEN 1 ELSE 0 END) AS unclassified,
                      SUM(CASE WHEN claim_count > 1 THEN 1 ELSE 0 END) AS shared
               FROM (
                   SELECT route_networks.id, COUNT(route_claims.id) AS claim_count,
                          SUM(CASE WHEN route_claims.source_kind = 'preserved' THEN 1 ELSE 0 END) AS preserved_count
                   FROM route_networks LEFT JOIN route_claims ON route_claims.route_id = route_networks.id
                       AND route_claims.active = 1
                   WHERE route_networks.present_on_router = 1
                   GROUP BY route_networks.id
               )'''
        ).fetchone()


def inventory_services():
    """Return recovered services, route counts, and claimed live interfaces."""
    with connect() as connection:
        return connection.execute(
            '''SELECT route_claims.source_kind, route_claims.source_name,
                      COUNT(DISTINCT route_claims.route_id) AS route_count,
                      GROUP_CONCAT(DISTINCT route_networks.interface) AS interfaces
               FROM route_claims JOIN route_networks ON route_networks.id = route_claims.route_id
               WHERE route_claims.active = 1 AND route_networks.present_on_router = 1
                   AND route_claims.source_kind != 'preserved'
               GROUP BY route_claims.source_kind, route_claims.source_name
               ORDER BY route_count DESC, route_claims.source_name ASC'''
        ).fetchall()


def lookup_route_owners(address):
    """Return active source claims for all stored routes containing an IPv4 address."""
    import ipaddress

    target = ipaddress.ip_address(address)
    rows = []
    with connect() as connection:
        candidates = connection.execute(
            '''SELECT route_networks.network, route_networks.interface, route_claims.source_kind,
                      route_claims.source_name, route_claims.confidence
               FROM route_networks LEFT JOIN route_claims ON route_claims.route_id = route_networks.id
                   AND route_claims.active = 1
               WHERE route_networks.present_on_router = 1'''
        ).fetchall()
    for row in candidates:
        try:
            if target in ipaddress.ip_network(row['network'], strict=False):
                rows.append(row)
        except ValueError:
            continue
    return rows
