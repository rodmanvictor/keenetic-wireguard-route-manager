"""Offline tests for pure route-core helpers."""

import os
import base64
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from keenetic_router.core.router import (
    clear_runtime_connection,
    full_interface_name,
    is_ip_address,
    normalize_route_network,
    normalize_tunnel_name,
    parse_wireguard_routes_output,
    parse_wireguard_tunnel_details,
    resolve_domain,
    route_add_command,
    route_delete_command,
)
from keenetic_router.core.onboarding import bootstrap_router, parse_component_states
from keenetic_router.core.profiles import RouterProfile, load_profile, save_profile
from keenetic_router.core.scheduler import (
    enable_macos_launch_agent,
    enable_windows_task,
    write_macos_launch_agent,
    write_user_units,
)
from keenetic_router.core.wireguard import (
    delete_wireguard_tunnel,
    import_wireguard_profile,
    load_wireguard_qr,
    parse_wireguard_config,
    rename_wireguard_tunnel,
    set_wireguard_tunnel_enabled,
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
    normalize_domain,
    split_sources,
    store_route_inventory,
)
from keenetic_router.services.catalog import parse_selection, reconcile_inventory_domains
from keenetic_router.services.favicons import favicon_url
from keenetic_router.apps.desktop import RouteDesktop
from keenetic_router.apps.launcher import main as packetech_main, terminal_main


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

    def test_parses_user_assigned_wireguard_descriptions(self):
        """Keenetic descriptions remain attached to their technical ids."""
        details = parse_wireguard_tunnel_details(
            '''
            Interface, name = "Wireguard0"
              id: Wireguard0
              interface-name: Wireguard0
              type: Wireguard
              description: Home VPN
            Interface, name = "Wireguard1"
              id: Wireguard1
              interface-name: Wireguard1
              type: Wireguard
              description: Travel VPN
            '''
        )
        self.assertEqual(details['wg0'].display_name, 'Home VPN')
        self.assertEqual(details['wg1'].display_name, 'Travel VPN')
        self.assertEqual(details['wg0'].status, 'unknown')

    def test_parses_live_wireguard_state(self):
        """The VPN manager can distinguish an enabled and disabled profile."""
        details = parse_wireguard_tunnel_details(
            '''
            id: Wireguard0
            description: Home VPN
            link: down
            status: down
            id: Wireguard1
            description: Travel VPN
            link: up
            status: up
            '''
        )
        self.assertEqual(details['wg0'].status, 'down')
        self.assertEqual(details['wg1'].status, 'up')


class DualStackRouteTests(unittest.TestCase):
    """Verify family-aware DNS, normalization, parsing, and CLI commands."""

    def test_accepts_ipv4_ipv6_hosts_and_networks(self):
        """Manual route input recognizes both address families and CIDRs."""
        self.assertTrue(is_ip_address('203.0.113.7'))
        self.assertTrue(is_ip_address('2001:db8::7'))
        self.assertTrue(is_ip_address('2001:db8::/48'))
        self.assertFalse(is_ip_address('example.com'))

    def test_builds_family_specific_keenetic_commands(self):
        """Keenetic receives dotted IPv4 masks and prefixed IPv6 networks."""
        ipv4 = normalize_route_network('203.0.113.7')
        ipv6 = normalize_route_network('2001:db8::7')
        self.assertEqual(
            route_add_command(ipv4, 'Wireguard1'),
            'ip route 203.0.113.7 255.255.255.255 0.0.0.0 Wireguard1',
        )
        self.assertEqual(
            route_add_command(ipv6, 'Wireguard1'),
            'ipv6 route 2001:db8::7/128 Wireguard1',
        )
        self.assertEqual(
            route_delete_command(ipv6, 'Wireguard1'),
            'no ipv6 route 2001:db8::7/128 Wireguard1',
        )

    def test_resolver_keeps_a_and_aaaa_answers(self):
        """A domain subscription receives deduplicated A and AAAA addresses."""
        answers = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2001:db8::7', 0, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('203.0.113.7', 0)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2001:db8::7', 0, 0, 0)),
        ]
        with patch('socket.getaddrinfo', return_value=answers):
            self.assertEqual(resolve_domain('example.com'), ['203.0.113.7', '2001:db8::7'])

    def test_parses_structured_ipv6_wireguard_routes(self):
        """The Keenetic IPv6 status format becomes normal inventory rows."""
        routes = parse_wireguard_routes_output(
            '''
            route6:
              destination: 2001:db8::7/128
              gateway: ::
              interface: Wireguard1
              metric: 1000
              static: yes
            route6:
              destination: fd00::2/128
              interface: Wireguard1
              metric: 256
              static: no
            route6:
              destination: ::/0
              interface: Wireguard1
              metric: 1000
              static: yes
            '''
        )
        self.assertEqual(
            routes,
            [{'network': '2001:db8::7/128', 'interface': 'Wireguard1', 'priority': '1000'}],
        )


class DomainInputTests(unittest.TestCase):
    """Accept website addresses without forcing users to edit pasted text."""

    def test_extracts_domain_from_full_url(self):
        """Scheme, port, path, query, and fragment are discarded safely."""
        self.assertEqual(
            normalize_domain(' https://ChatGPT.com:443/share/test?q=1#answer '),
            'chatgpt.com',
        )

    def test_extracts_domain_from_bare_address_with_path(self):
        """A browser address without a scheme is accepted too."""
        self.assertEqual(normalize_domain('example.com/some/page'), 'example.com')


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

    def test_shared_ipv6_dns_route_uses_128_and_keeps_both_owners(self):
        """IPv6 DNS ownership has the same shared-route protection as IPv4."""
        add_managed_domain('one.example', 'wg1', source='chrome')
        add_managed_domain('two.example', 'wg1', source='desktop')
        record_domain_route('one.example', '2001:db8::7', 'Wireguard1')
        record_domain_route('two.example', '2001:db8::7', 'Wireguard1')

        self.assertEqual(release_domain_route_claims('one.example'), [])
        orphaned = release_domain_route_claims('two.example')
        self.assertEqual([row['network'] for row in orphaned], ['2001:db8::7/128'])

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
    """Verify portable local router profile persistence."""

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

    def test_profile_round_trip_contains_saved_password(self):
        """Saved profiles retain credentials and restrict the JSON on POSIX."""
        profile = RouterProfile(
            host='192.168.50.1',
            user='operator',
            preferred_transport='ssh',
            password='local-test-password',
        )
        path = save_profile(profile)
        self.assertEqual(load_profile(), profile)
        payload = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(payload['profiles']['default']['password'], 'local-test-password')
        if os.name != 'nt':
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


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


class DesktopBootstrapTests(unittest.TestCase):
    """Verify first-run recovery without opening a Flet window or router."""

    def test_existing_registry_skips_reverse_inventory(self):
        """A populated local database is not replaced during every login."""
        app = RouteDesktop.__new__(RouteDesktop)
        with (
            patch('keenetic_router.apps.desktop.list_managed_domains', return_value=[{'id': 1}]),
            patch('keenetic_router.apps.desktop.import_current_inventory') as importer,
        ):
            self.assertEqual(app._bootstrap_inventory_if_needed(), '')
        importer.assert_not_called()

    def test_empty_registry_recovers_routes_and_known_domains(self):
        """An empty installed build imports router ownership on first login."""
        app = RouteDesktop.__new__(RouteDesktop)
        with (
            patch('keenetic_router.apps.desktop.list_managed_domains', return_value=[]),
            patch(
                'keenetic_router.apps.desktop.import_current_inventory',
                return_value={'routes': 840},
            ),
            patch(
                'keenetic_router.apps.desktop.reconcile_inventory_domains',
                return_value=SimpleNamespace(registered=11),
            ),
        ):
            note = app._bootstrap_inventory_if_needed()
        self.assertEqual(note, 'Найдено маршрутов: 840 · восстановлено доменов: 11')


class SchedulerTests(unittest.TestCase):
    """Verify native background schedule commands without changing the host."""

    def test_user_timer_points_to_absolute_cli_and_six_hour_interval(self):
        """Generated units retain a spaced path and the requested interval."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cli = root / 'PackeTech CLI' / 'packetech-cli'
            cli.parent.mkdir()
            cli.write_text('#!/bin/sh\n', encoding='utf-8')
            service, timer = write_user_units(cli, root / 'units')
            self.assertIn(f'ExecStart="{cli.resolve()}" sync', service.read_text(encoding='utf-8'))
            self.assertIn('OnUnitActiveSec=6h', timer.read_text(encoding='utf-8'))

    def test_windows_task_runs_packetech_cli_every_six_hours(self):
        """Task Scheduler receives the frozen CLI path and six-hour interval."""
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / 'PackeTech' / 'PackeTech-CLI.exe'
            cli.parent.mkdir()
            cli.write_bytes(b'MZ')
            with patch('keenetic_router.core.scheduler.subprocess.run') as run:
                result = enable_windows_task(cli)
            self.assertTrue(result.enabled)
            self.assertEqual(run.call_count, 2)
            self.assertIn('Paketych route sync', run.call_args_list[0].args[0])
            command = run.call_args_list[1].args[0]
            self.assertEqual(command[0], 'schtasks.exe')
            self.assertIn('6', command)
            self.assertIn('PackeTech route sync', command)
            self.assertIn('PackeTech-CLI.exe', command[-1])

    def test_macos_launch_agent_runs_packetech_cli_every_six_hours(self):
        """LaunchAgent stores the absolute CLI path and six-hour interval."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cli = root / 'PackeTech.app' / 'Contents' / 'MacOS' / 'packetech-cli'
            cli.parent.mkdir(parents=True)
            cli.write_text('#!/bin/sh\n', encoding='utf-8')
            agent = write_macos_launch_agent(cli, root / 'LaunchAgents')
            payload = agent.read_text(encoding='utf-8')
            self.assertIn(str(cli.resolve()), payload)
            self.assertIn('<integer>21600</integer>', payload)
            self.assertIn('ru.rodman.packetech.sync', payload)

    def test_macos_launch_agent_bootstraps_current_gui_domain(self):
        """macOS scheduling reloads the user agent without raising on bootout."""
        with tempfile.TemporaryDirectory() as directory:
            cli = Path(directory) / 'packetech-cli'
            cli.write_text('#!/bin/sh\n', encoding='utf-8')
            with (
                patch(
                    'keenetic_router.core.scheduler.write_macos_launch_agent',
                    return_value=Path(directory) / 'agent.plist',
                ),
                patch(
                    'keenetic_router.core.scheduler.os.getuid',
                    return_value=501,
                    create=True,
                ),
                patch('keenetic_router.core.scheduler.subprocess.run') as run,
            ):
                result = enable_macos_launch_agent(cli)
            self.assertTrue(result.enabled)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(
                run.call_args_list[1].args[0][:3],
                ['launchctl', 'bootstrap', 'gui/501'],
            )


class BrandedLauncherTests(unittest.TestCase):
    """Route the PackeTech command to GUI, CLI, and TUI surfaces."""

    def test_no_arguments_open_desktop(self):
        """A plain ``packetech`` command remains the graphical workflow."""
        with patch('keenetic_router.apps.desktop.run') as desktop:
            packetech_main([])
        desktop.assert_called_once_with()

    def test_regular_subcommand_opens_cli_with_branded_program_name(self):
        """Network subcommands use CLI while keeping the PackeTech name."""
        observed = []

        def capture():
            observed.extend(sys.argv)

        with patch('keenetic_router.apps.cli.main', side_effect=capture) as cli:
            packetech_main(['status'])
        cli.assert_called_once_with()
        self.assertEqual(observed, ['packetech', 'status'])

    def test_tui_subcommand_opens_interactive_menu(self):
        """The branded ``tui`` subcommand opens the interactive menu."""
        with patch('keenetic_router.apps.tui.main') as tui:
            packetech_main(['tui'])
        tui.assert_called_once_with()

    def test_linux_wrapper_can_preserve_unified_command_name(self):
        """The packaged shell dispatcher keeps ``packetech`` in CLI help."""
        observed = []

        def capture():
            observed.extend(sys.argv)

        with (
            patch.dict(os.environ, {'PACKETECH_PROG_NAME': 'packetech'}),
            patch('keenetic_router.apps.cli.main', side_effect=capture),
        ):
            terminal_main(['status'])
        self.assertEqual(observed, ['packetech', 'status'])


class FaviconTests(unittest.TestCase):
    """Verify safe URL construction for desktop site icons."""

    def test_favicon_url_normalizes_domain_and_requests_64_pixels(self):
        """The external service receives only a validated hostname and size."""
        self.assertEqual(
            favicon_url('ChatGPT.COM.'),
            'https://www.google.com/s2/favicons?domain=chatgpt.com&sz=64',
        )

    def test_favicon_url_rejects_input_without_a_domain(self):
        """An arbitrary non-network value cannot enter the image query."""
        with self.assertRaises(ValueError):
            favicon_url('not a website')


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
        Address = 10.42.0.2/24, fd00::2/128
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
        self.assertIn('ipv6 address fd00::2/128', preview)
        self.assertIn('allow-ips :: 0', preview)
        self.assertFalse(any('IPv6' in warning for warning in result.warnings))

    def test_qr_image_round_trip(self):
        """A WireGuard QR image decodes to the same non-secret summary."""
        import qrcode

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'wireguard.png')
            qrcode.make(self.sample_config()).save(path)
            profile = load_wireguard_qr(path)
        self.assertEqual(profile.addresses, ('10.42.0.2/24', 'fd00::2/128'))
        self.assertEqual(profile.peers[0].endpoint, 'vpn.example.com:51820')

    def test_named_profile_management_uses_explicit_interface_commands(self):
        """Rename, disable, enable, and delete plans stay scoped to one VPN."""

        class FakeClient:
            def __init__(self):
                self.commands = []

            def command(self, command, timeout=60):
                self.commands.append(command)
                return 'Core::Configurator: Done.'

        client = FakeClient()
        saved = rename_wireguard_tunnel(client, 'Wireguard1', 'Домашний VPN')
        set_wireguard_tunnel_enabled(client, 'Wireguard1', False)
        set_wireguard_tunnel_enabled(client, 'Wireguard1', True)
        delete_wireguard_tunnel(client, 'Wireguard1')
        self.assertEqual(saved, 'Домашний VPN')
        self.assertIn('description "Домашний VPN"', client.commands)
        self.assertIn('down', client.commands)
        self.assertIn('up', client.commands)
        self.assertIn('no interface Wireguard1', client.commands)


if __name__ == '__main__':
    unittest.main()
