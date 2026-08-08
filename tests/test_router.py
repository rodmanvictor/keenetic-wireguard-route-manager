"""Offline tests for pure route-core helpers."""

import os
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keenetic_router.core.router import clear_runtime_connection, full_interface_name, normalize_tunnel_name
from keenetic_router.core.onboarding import bootstrap_router, parse_component_states
from keenetic_router.core.profiles import RouterProfile, load_profile, save_profile
from keenetic_router.core.wireguard import (
    import_wireguard_profile,
    load_wireguard_qr,
    parse_wireguard_config,
)
from keenetic_router.services.registry import (
    add_managed_domain,
    application_data_directory,
    inventory_summary,
    inventory_services,
    list_managed_domains,
    lookup_route_owners,
    remove_managed_domain,
    record_domain_route,
    release_domain_route_claims,
    split_sources,
    store_route_inventory,
)
from keenetic_router.services.catalog import parse_selection, reconcile_inventory_domains


class TunnelNameTests(unittest.TestCase):
    """Verify conversion between Keenetic short and full interface names."""

    def setUp(self):
        """Create a representative tunnel map without contacting a router."""
        self.short_to_full = {'wg1': 'Wireguard1'}
        self.full_to_short = {'Wireguard1': 'wg1'}

    def test_normalizes_short_and_full_identifiers(self):
        """Both accepted identifiers resolve to the short CLI identifier."""
        self.assertEqual(
            normalize_tunnel_name('wg1', self.short_to_full, self.full_to_short),
            'wg1',
        )
        self.assertEqual(
            normalize_tunnel_name('Wireguard1', self.short_to_full, self.full_to_short),
            'wg1',
        )

    def test_resolves_full_interface_name(self):
        """A full Keenetic name is returned for route commands."""
        self.assertEqual(
            full_interface_name('wg1', self.short_to_full, self.full_to_short),
            'Wireguard1',
        )


class DomainRegistryTests(unittest.TestCase):
    """Verify that subscriptions persist without talking to a router."""

    def setUp(self):
        """Point the registry to a temporary SQLite database."""
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.previous_database = os.environ.get('ROUTE_SYNC_DATABASE')
        os.environ['ROUTE_SYNC_DATABASE'] = os.path.join(self.temporary_directory.name, 'routes.sqlite3')

    def tearDown(self):
        """Restore the process environment after the isolated database test."""
        if self.previous_database is None:
            os.environ.pop('ROUTE_SYNC_DATABASE', None)
        else:
            os.environ['ROUTE_SYNC_DATABASE'] = self.previous_database
        self.temporary_directory.cleanup()

    def test_add_and_disable_domain_subscription(self):
        """A domain remains in history after its recurring updates are disabled."""
        domain, created = add_managed_domain('ChatGPT.COM.', 'wg1')
        self.assertEqual(domain, 'chatgpt.com')
        self.assertTrue(created)
        self.assertTrue(remove_managed_domain(domain))
        row = list_managed_domains()[0]
        self.assertEqual(row['domain'], 'chatgpt.com')
        self.assertEqual(row['enabled'], 0)

    def test_domain_keeps_independent_registration_sources(self):
        """Removing a temporary Chrome claim retains a permanent catalog claim."""
        domain, _ = add_managed_domain('example.com', 'wg1', source='chrome')
        add_managed_domain(domain, 'wg1', source='rucens:example')
        row = list_managed_domains()[0]
        self.assertEqual(set(split_sources(row['sources'])), {'chrome', 'rucens:example'})

        self.assertTrue(remove_managed_domain(domain, source='chrome'))
        row = list_managed_domains()[0]
        self.assertEqual(row['enabled'], 1)
        self.assertEqual(split_sources(row['sources']), ('rucens:example',))

    def test_shared_dns_route_is_orphaned_only_after_last_domain_is_released(self):
        """A shared IP survives the removal of either one of its domain owners."""
        add_managed_domain('one.example', 'wg1', source='chrome')
        add_managed_domain('two.example', 'wg1', source='desktop')
        record_domain_route('one.example', '203.0.113.7', 'Wireguard1')
        record_domain_route('two.example', '203.0.113.7', 'Wireguard1')

        self.assertEqual(release_domain_route_claims('one.example'), [])
        orphaned = release_domain_route_claims('two.example')
        self.assertEqual([row['network'] for row in orphaned], ['203.0.113.7/32'])

    def test_inventory_does_not_mark_managed_dns_route_unclassified(self):
        """A DNS-domain claim remains authoritative across reverse inventory."""
        add_managed_domain('one.example', 'wg1', source='chrome')
        record_domain_route('one.example', '203.0.113.9', 'Wireguard1')
        store_route_inventory([('203.0.113.9/32', 'Wireguard1')], {})
        self.assertEqual(inventory_summary()['unclassified'], 0)

    def test_route_inventory_keeps_multiple_owners(self):
        """One route can be attributed to more than one service source."""
        store_route_inventory(
            [('104.18.41.0/24', 'Wireguard1')],
            {
                '104.18.41.0/24': [
                    {'kind': 'rucens', 'name': 'chatgpt', 'confidence': 'exact'},
                    {'kind': 'rucens', 'name': 'deepl', 'confidence': 'exact'},
                ]
            },
        )
        self.assertEqual(inventory_summary()['shared'], 1)
        self.assertEqual(len(lookup_route_owners('104.18.41.42')), 2)
        self.assertEqual({service['source_name'] for service in inventory_services()}, {'chatgpt', 'deepl'})

    def test_known_inventory_service_becomes_single_tunnel_dns_watch(self):
        """Known rucens ownership seeds DNS watches without touching a router."""
        store_route_inventory(
            [('104.18.41.0/24', 'Wireguard1')],
            {
                '104.18.41.0/24': [
                    {'kind': 'rucens', 'name': 'chatgpt', 'confidence': 'exact'},
                ]
            },
        )
        summary = reconcile_inventory_domains()
        rows = list_managed_domains()
        self.assertEqual(summary.registered, 2)
        self.assertEqual({row['domain'] for row in rows}, {'chatgpt.com', 'chat.openai.com'})
        self.assertEqual({row['tunnel'] for row in rows}, {'wg1'})

        remove_managed_domain('chatgpt.com')
        second = reconcile_inventory_domains()
        disabled = next(row for row in list_managed_domains() if row['domain'] == 'chatgpt.com')
        self.assertEqual(second.registered, 0)
        self.assertEqual(disabled['enabled'], 0)

    def test_ambiguous_inventory_service_is_not_assigned_to_one_tunnel(self):
        """A service spanning tunnels requires a user choice instead of guessing."""
        claims = {
            '104.18.41.0/24': [
                {'kind': 'rucens', 'name': 'chatgpt', 'confidence': 'exact'},
            ],
            '104.18.42.0/24': [
                {'kind': 'rucens', 'name': 'chatgpt', 'confidence': 'exact'},
            ],
        }
        store_route_inventory(
            [
                ('104.18.41.0/24', 'Wireguard1'),
                ('104.18.42.0/24', 'Wireguard2'),
            ],
            claims,
        )
        summary = reconcile_inventory_domains()
        self.assertEqual(summary.skipped_ambiguous, 1)
        self.assertEqual(list_managed_domains(), [])

    def test_catalog_selection_accepts_spaces_commas_and_removes_duplicates(self):
        """TUI service selection stays convenient without duplicate imports."""
        self.assertEqual(parse_selection('1, 3 1', 5), [0, 2])
        with self.assertRaises(ValueError):
            parse_selection('6', 5)


class RouterProfileTests(unittest.TestCase):
    """Verify portable non-secret router profile persistence."""

    def setUp(self):
        """Use an isolated native-config replacement directory."""
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.previous_directory = os.environ.get('KEENETIC_ROUTE_MANAGER_CONFIG_DIR')
        os.environ['KEENETIC_ROUTE_MANAGER_CONFIG_DIR'] = self.temporary_directory.name

    def tearDown(self):
        """Restore the profile path override after each test."""
        if self.previous_directory is None:
            os.environ.pop('KEENETIC_ROUTE_MANAGER_CONFIG_DIR', None)
        else:
            os.environ['KEENETIC_ROUTE_MANAGER_CONFIG_DIR'] = self.previous_directory
        self.temporary_directory.cleanup()

    def test_profile_round_trip_contains_no_password_field(self):
        """Saved profiles retain coordinates but have no credential slot."""
        profile = RouterProfile(host='192.168.50.1', user='operator', preferred_transport='ssh')
        path = save_profile(profile)
        self.assertEqual(load_profile(), profile)
        self.assertNotIn('password', path.read_text(encoding='utf-8').lower())


class ApplicationDataTests(unittest.TestCase):
    """Verify that packaged applications select durable native data paths."""

    def test_frozen_linux_build_uses_xdg_data_instead_of_bundle(self):
        """A build without the source marker never stores SQLite in its bundle."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            bundle = Path(temporary_directory) / 'temporary-bundle'
            xdg_data = Path(temporary_directory) / 'xdg-data'
            with (
                patch('keenetic_router.services.registry.PROJECT_ROOT', bundle),
                patch('keenetic_router.services.registry.platform.system', return_value='Linux'),
                patch.dict(
                    os.environ,
                    {
                        'XDG_DATA_HOME': str(xdg_data),
                        'KEENETIC_ROUTE_MANAGER_DATA_DIR': '',
                    },
                    clear=False,
                ),
            ):
                self.assertEqual(
                    application_data_directory(),
                    xdg_data / 'keenetic-route-manager',
                )


class OnboardingParserTests(unittest.TestCase):
    """Verify component availability parsing without contacting KeeneticOS."""

    def test_component_list_distinguishes_installed_and_available(self):
        """Installed and optional component states remain distinct."""
        output = '''
        component:
             name: ssh
        installed: 2022.82-7
           queued: yes
          version: 2022.82-7
        component:
             name: wireguard
           queued: no
          version: 1.0.0
        '''
        states = parse_component_states(output)
        self.assertTrue(states['ssh'].installed)
        self.assertFalse(states['wireguard'].installed)

    def test_telnet_can_enable_and_verify_ssh(self):
        """A failed first SSH login falls back, starts SSH, and retries it."""

        class FakeClient:
            def __init__(self, transport):
                self.transport = transport
                self.commands = []
                self.closed = False

            def command(self, command, timeout=60):
                self.commands.append(command)
                if command == 'show interface':
                    return 'interface: Wireguard1\n(config)>'
                return 'Core::Configurator: Done.\n(config)>'

            def disconnect(self):
                self.closed = True

        telnet = FakeClient('telnet')
        ssh = FakeClient('ssh')
        with (
            patch('keenetic_router.core.onboarding._open_ssh', side_effect=[OSError('refused'), ssh]),
            patch('keenetic_router.core.onboarding._open_telnet', return_value=telnet),
            patch('keenetic_router.core.onboarding.port_is_open', return_value=True),
        ):
            report = bootstrap_router(RouterProfile(), 'secret', ssh_wait=1)
        clear_runtime_connection()
        self.assertEqual(report.transport, 'ssh')
        self.assertIn('service ssh', telnet.commands)
        self.assertIn('system configuration save', telnet.commands)
        self.assertTrue(telnet.closed)


class WireGuardImportTests(unittest.TestCase):
    """Verify parsing and redaction of standard WireGuard client profiles."""

    @staticmethod
    def sample_key(offset=0):
        """Return a syntactically valid deterministic 32-byte WireGuard key."""
        return base64.b64encode(bytes((index + offset) % 256 for index in range(32))).decode()

    def sample_config(self):
        """Return a representative one-peer client configuration."""
        return f'''
        [Interface]
        PrivateKey = {self.sample_key()}
        Address = 10.42.0.2/24
        DNS = 1.1.1.1

        [Peer]
        PublicKey = {self.sample_key(1)}
        PresharedKey = {self.sample_key(2)}
        AllowedIPs = 0.0.0.0/0, ::/0
        Endpoint = vpn.example.com:51820
        PersistentKeepalive = 25
        '''

    def test_config_is_normalized_and_secret_plan_is_redacted(self):
        """Dry-run output never exposes private or preshared keys."""
        profile = parse_wireguard_config(self.sample_config())

        class FakeClient:
            transport = 'ssh'

            def command(self, command, timeout=60):
                return '(config)>\n' if command == 'show interface' else 'Core::Configurator: Done.'

        result = import_wireguard_profile(FakeClient(), profile, description='Test VPN', dry_run=True)
        preview = '\n'.join(result.preview)
        self.assertEqual(result.interface, 'Wireguard0')
        self.assertNotIn(self.sample_key(), preview)
        self.assertNotIn(self.sample_key(2), preview)
        self.assertIn('private-key ***', preview)
        self.assertTrue(any('IPv6' in warning for warning in result.warnings))

    def test_qr_image_round_trip(self):
        """A WireGuard QR image decodes to the same non-secret summary."""
        import qrcode

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'wireguard.png')
            qrcode.make(self.sample_config()).save(path)
            profile = load_wireguard_qr(path)
        self.assertEqual(profile.addresses, ('10.42.0.2/24',))
        self.assertEqual(profile.peers[0].endpoint, 'vpn.example.com:51820')


if __name__ == '__main__':
    unittest.main()
