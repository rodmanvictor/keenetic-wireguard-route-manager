#!/usr/bin/env python3
"""Cross-platform command-line interface for Keenetic route management."""

import argparse
from dataclasses import replace
import getpass
import os
import sys
from keenetic_router.core.router import (
    create_router_client,
    discover_wireguard_tunnels,
    is_ip_address,
    normalize_tunnel_name,
    parse_wireguard_routes_output,
    prefix_to_mask,
    resolve_domain,
    add_route_smart,
)
from keenetic_router.core.onboarding import (
    RouterBootstrapError,
    bootstrap_router,
    inspect_components,
    install_components,
)
from keenetic_router.core.profiles import (
    environment_password,
    load_profile,
    save_profile,
)
from keenetic_router.core.wireguard import (
    import_wireguard_profile,
    load_wireguard_file,
    load_wireguard_qr,
)
from keenetic_router.services.registry import (
    add_managed_domain,
    find_managed_domain,
    list_managed_domains,
    recent_events,
    record_domain_route,
    record_resolved_address,
    remove_managed_domain,
    source_label,
    split_sources,
)
from keenetic_router.services.sync import sync_domains
from keenetic_router.services.inventory import import_current_inventory
from keenetic_router.services.registry import inventory_summary, lookup_route_owners
from keenetic_router.services.cleanup import purge_domain_routes, purge_unclassified_routes, unclassified_routes

# Карты туннелей обновляются динамически при подключении
TUNNEL_INTERFACES = {}
TUNNEL_FULL_NAMES = {}


def _profile_from_args(args):
    """Merge CLI connection overrides into the saved default profile."""
    profile = load_profile()
    updates = {}
    if getattr(args, 'host', None):
        updates['host'] = args.host
    if getattr(args, 'user', None):
        updates['user'] = args.user
    if getattr(args, 'ssh_port', None):
        updates['ssh_port'] = args.ssh_port
    if getattr(args, 'telnet_port', None):
        updates['telnet_port'] = args.telnet_port
    return replace(profile, **updates).validate()


def _password_from_args(args, profile):
    """Read a router password from ENV, the saved profile, or a hidden prompt."""
    variable = getattr(args, 'password_env', None)
    if variable:
        password = os.getenv(variable, '')
        if not password:
            raise RouterBootstrapError(f'Переменная окружения {variable} пуста')
        return password
    password = environment_password()
    if password:
        return password
    if profile.password:
        return profile.password
    if not sys.stdin.isatty():
        raise RouterBootstrapError(
            'Нужен интерактивный ввод пароля или --password-env ИМЯ_ПЕРЕМЕННОЙ'
        )
    return getpass.getpass('Пароль администратора Keenetic: ')


def ensure_connection(args, *, auto_enable_ssh=True, save=True):
    """Run onboarding once for a CLI command and activate its working transport."""
    existing = getattr(args, '_bootstrap_report', None)
    if existing is not None:
        return existing
    profile = _profile_from_args(args)
    password = _password_from_args(args, profile)
    report = bootstrap_router(profile, password, auto_enable_ssh=auto_enable_ssh)
    selected_profile = replace(
        profile,
        preferred_transport=report.transport or 'auto',
        password=password,
    )
    if save:
        save_profile(selected_profile)
    args._bootstrap_report = report
    args._router_password = password
    return report


def print_report(report):
    """Render onboarding diagnostics without exposing credentials."""
    icons = {'ok': '✅', 'warning': '⚠️', 'error': '❌'}
    print(f'Роутер: {report.profile.host} · транспорт: {report.transport or "нет"}')
    for step in report.steps:
        print(f'  {icons.get(step.status, "·")} {step.detail}')
    if report.tunnels:
        tunnels = ', '.join(
            f'{report.tunnel_labels.get(short, full)} — {short} ({full})'
            for short, full in report.tunnels.items()
        )
        print(f'  WireGuard: {tunnels}')
    else:
        print('  WireGuard-туннели пока не настроены.')


def refresh_tunnel_maps(keenetic):
    """Обновить глобальные карты туннелей после подключения"""
    global TUNNEL_INTERFACES, TUNNEL_FULL_NAMES
    TUNNEL_INTERFACES, TUNNEL_FULL_NAMES = discover_wireguard_tunnels(keenetic)
    return TUNNEL_INTERFACES, TUNNEL_FULL_NAMES


def add_route(keenetic, ip, mask, tunnel, description=''):
    """Добавить маршрут через WireGuard"""
    interface = TUNNEL_INTERFACES[tunnel]
    cmd = f'ip route {ip} {mask} 0.0.0.0 {interface}'
    result = keenetic.command(cmd)

    if description:
        print(f"   📝 Описание: {description}")

    return result


def delete_route(keenetic, ip, mask, interface):
    """Удалить маршрут"""
    cmd = f'no ip route {ip} {mask} {interface}'
    return keenetic.command(cmd)


def list_routes(keenetic):
    """Показать все маршруты через WireGuard"""
    return parse_wireguard_routes_output(keenetic.command('show ip route'))


def save_config(keenetic):
    result = keenetic.command('system configuration save')
    return 'done' in result.lower() or 'ok' in result.lower()


def cmd_add(args):
    """Добавить IP/домен в маршруты"""
    report = ensure_connection(args)
    kt = create_router_client()

    try:
        print(f"✅ Подключено к {report.profile.host} по {report.transport.upper()}")
        refresh_tunnel_maps(kt)

        tunnel = normalize_tunnel_name(args.tunnel, TUNNEL_INTERFACES, TUNNEL_FULL_NAMES)
        if tunnel not in TUNNEL_INTERFACES:
            available = ', '.join(TUNNEL_INTERFACES.keys()) if TUNNEL_INTERFACES else 'не найдены'
            print(f"❌ Неверный туннель. Доступны: {available}")
            return

        targets = []
        for target in args.target:
            if is_ip_address(target):
                targets.append((target, 'IP'))
            else:
                try:
                    domain, created = add_managed_domain(target, tunnel, source='cli')
                    print(f"{'✅ Добавлен' if created else '↻ Обновлён'} в автообновление: {domain}")
                except ValueError as error:
                    print(f"❌ {target}: {error}")
                    continue
                print(f"🔍 Резолвим домен: {target}")
                ips = resolve_domain(target)
                if ips:
                    targets.extend((ip, f'DNS:{domain}') for ip in ips)
                    print(f"   Найдено IP: {len(ips)}")
                else:
                    print(f"   ⚠️  Не найдено IP для {target}")

        if not targets:
            print("❌ Нет IP-адресов для добавления")
            return

        added = 0
        for ip, source in targets:
            mask = '255.255.255.255' if '/' not in ip else None

            if mask is None:
                ip, prefix = ip.split('/')
                mask = prefix_to_mask(int(prefix))

            # Умное добавление с проверкой дубликатов
            interface = TUNNEL_INTERFACES[tunnel]
            success, message = add_route_smart(kt, ip, mask, interface)

            if success:
                print(f"   ✅ {ip} → {tunnel.upper()} ({message})")
                added += 1
                if source.startswith('DNS:'):
                    domain = source.removeprefix('DNS:')
                    row = find_managed_domain(domain)
                    if row is not None:
                        record_resolved_address(row['id'], ip)
                        record_domain_route(domain, ip, interface)
            else:
                print(f"   ❌ {ip}: {message}")

        if added > 0:
            print("\n💾 Сохранение конфигурации...")
            if save_config(kt):
                print("✅ Конфигурация сохранена")
            else:
                print("⚠️  Возможно, конфигурация не сохранена")

        print(f"\n🎉 Добавлено {added} маршрутов через {tunnel.upper()}")

    finally:
        kt.disconnect()


def cmd_watch_list(args):
    """Show the domains that will be re-resolved by scheduled synchronization."""
    domains = list_managed_domains()
    if not domains:
        print('Список автообновления пока пуст.')
        return
    print(f"{'Домен':<34} {'Туннель':<9} {'Источник':<24} {'Последний DNS'}")
    print('-' * 104)
    for domain in domains:
        state = 'вкл' if domain['enabled'] else 'выкл'
        sources = ', '.join(source_label(item) for item in split_sources(domain['sources'])) or '—'
        print(
            f"{domain['domain']:<34} {domain['tunnel']:<9} {sources:<24} "
            f"{domain['last_resolved_at'] or 'ещё не обновлялся'} ({state})"
        )


def cmd_watch_remove(args):
    """Stop recurring updates for a domain while retaining its audit history."""
    ensure_connection(args)
    if remove_managed_domain(args.domain):
        cleanup = purge_domain_routes(args.domain)
        print(
            f'⏸️ Автообновление отключено: {args.domain}. '
            f'Удалено маршрутов: {cleanup["removed"]}; общие маршруты сохранены.'
        )
    else:
        print(f'⚠️ Домен не найден: {args.domain}')


def cmd_sync(args):
    """Resolve all managed domains and add their current routes now."""
    if not args.dry_run:
        ensure_connection(args)
    summary = sync_domains(dry_run=args.dry_run)
    prefix = 'Проверено' if args.dry_run else 'Обновлено'
    print(f'{prefix}: добавлено {summary.added}, без изменений {summary.unchanged}, ошибок {summary.errors}.')
    if summary.status == 'failed':
        sys.exit(1)


def cmd_inventory_import(args):
    """Import current Keenetic routes and exact public-source attributions into SQLite."""
    ensure_connection(args)
    result = import_current_inventory()
    from keenetic_router.services.catalog import reconcile_inventory_domains

    domains = reconcile_inventory_domains()
    print(
        f"Инвентаризация: маршрутов {result['routes']}, точно сопоставлено {result['attributed']}, "
        f"общих {result['shared']}, сохранено как неопознанные {result['unclassified']}; "
        f"DNS-подписок добавлено {domains.registered}."
    )


def cmd_inventory_summary(args):
    """Show the stored reverse-engineering inventory summary without router access."""
    summary = inventory_summary()
    if not summary or not summary['routes']:
        print('Инвентаризация ещё не выполнена: запусти `kwan inventory import`.')
        return
    print(
        f"Маршрутов: {summary['routes']}; общих: {summary['shared'] or 0}; "
        f"неопознанных и защищённых от автоудаления: {summary['unclassified'] or 0}."
    )


def cmd_inventory_lookup(args):
    """Show all known route owners for an IPv4 address without changing routes."""
    try:
        owners = lookup_route_owners(args.address)
    except ValueError:
        print('Введите корректный IPv4-адрес.')
        return
    if not owners:
        print('В инвентаризации не найден маршрут, покрывающий этот IP.')
        return
    for owner in owners:
        print(
            f"{owner['network']} через {owner['interface']} — "
            f"{owner['source_kind']}:{owner['source_name']} ({owner['confidence']})"
        )


def cmd_inventory_purge(args):
    """Delete only routes explicitly confirmed as unclassified after inventory."""
    if args.limit is not None and args.limit < 1:
        print('Параметр --limit должен быть положительным числом.')
        sys.exit(2)
    routes = unclassified_routes()
    if args.dry_run:
        print(f'Будет удалено {len(routes)} неопознанных маршрутов. Роутер не изменён.')
        return
    if not args.confirm:
        print('Для удаления нужен флаг --confirm. Сначала можно выполнить --dry-run.')
        sys.exit(2)
    ensure_connection(args)

    def report(done, total, removed, failed):
        print(f'  [{done}/{total}] удалено {removed}, ошибок {failed}')

    result = purge_unclassified_routes(progress=report, limit=args.limit)
    print(
        f"Готово: запрошено {result['requested']}, подтверждённо удалено {result['removed']}, "
        f"ошибок {result['failed']}, в очереди осталось {result['remaining']}."
    )
    if result['backup']:
        print(f"Резервная копия: {result['backup']}")


def cmd_remove(args):
    """Удалить маршрут"""
    report = ensure_connection(args)
    kt = create_router_client()

    try:
        print(f"✅ Подключено к {report.profile.host} по {report.transport.upper()}")
        refresh_tunnel_maps(kt)

        tunnel = normalize_tunnel_name(args.tunnel, TUNNEL_INTERFACES, TUNNEL_FULL_NAMES) if args.tunnel else None
        routes = list_routes(kt)

        removed = 0
        for route in routes:
            iface_lower = route['interface'].lower()
            full_name = TUNNEL_INTERFACES.get(tunnel, '').lower() if tunnel else ''

            if args.target:
                if args.target in route['network']:
                    if tunnel is None or tunnel in iface_lower or full_name in iface_lower:
                        ip, prefix = route['network'].split('/') if '/' in route['network'] else (route['network'], '32')
                        mask = prefix_to_mask(int(prefix))
                        delete_route(kt, ip, mask, route['interface'])
                        print(f"   ❌ Удалён: {route['network']}")
                        removed += 1
            else:
                if tunnel and (tunnel in iface_lower or full_name in iface_lower):
                    ip, prefix = route['network'].split('/') if '/' in route['network'] else (route['network'], '32')
                    mask = prefix_to_mask(int(prefix))
                    delete_route(kt, ip, mask, route['interface'])
                    print(f"   ❌ Удалён: {route['network']}")
                    removed += 1

        if removed > 0:
            print("\n💾 Сохранение конфигурации...")
            save_config(kt)
            print("✅ Конфигурация сохранена")

        print(f"\n🎉 Удалено {removed} маршрутов")

    finally:
        kt.disconnect()


def cmd_list(args):
    """Показать маршруты"""
    ensure_connection(args)
    kt = create_router_client()

    try:
        refresh_tunnel_maps(kt)

        routes = list_routes(kt)

        print("\n📋 Маршруты через WireGuard:\n")
        print(f"{'Сеть':<20} {'Туннель':<15} {'Приоритет'}")
        print("-" * 50)

        for route in routes:
            print(f"{route['network']:<20} {route['interface']:<15} {route['priority']}")

        print("-" * 50)
        print(f"Всего: {len(routes)} маршрутов")

    finally:
        kt.disconnect()


def cmd_clear(args):
    """Очистить все маршруты WireGuard"""
    ensure_connection(args)
    kt = create_router_client()

    try:
        refresh_tunnel_maps(kt)
        print("⚠️  Удаление всех маршрутов WireGuard...")

        routes = list_routes(kt)
        for route in routes:
            network = route['network']
            if '/' in network:
                ip, prefix = network.split('/')
                mask = prefix_to_mask(int(prefix))
            else:
                ip = network
                mask = '255.255.255.255'

            delete_route(kt, ip, mask, route['interface'])
            print(f"   ❌ {network}")

        print("\n💾 Сохранение конфигурации...")
        save_config(kt)
        print("✅ Готово")

    finally:
        kt.disconnect()


def _component_summary(states):
    """Return a short user-facing state for SSH and WireGuard components."""
    lines = []
    for name, label in (('ssh', 'Сервер SSH'), ('wireguard', 'WireGuard')):
        state = states.get(name)
        if state is None:
            lines.append(f'  ❌ {label}: недоступен для этой модели/версии')
        elif state.installed:
            lines.append(f'  ✅ {label}: установлен ({state.installed_version})')
        else:
            lines.append(f'  ⚠️ {label}: доступен, но не установлен')
    return lines


def cmd_setup(args):
    """Run first-use diagnostics and optionally install KeeneticOS components."""
    report = ensure_connection(args, auto_enable_ssh=not args.no_enable_ssh)
    print_report(report)
    client = create_router_client()
    try:
        states = inspect_components(client)
        print('\nКомпоненты KeeneticOS:')
        print('\n'.join(_component_summary(states)))
        missing = [
            name
            for name in ('ssh', 'wireguard')
            if states.get(name) is not None and not states[name].installed
        ]
        if not args.install_components or not missing:
            if missing:
                print('\nДля автоматической установки: kwan setup --install-components --confirm-reboot')
            return
        if not args.confirm_reboot:
            print('❌ Установка компонентов требует --confirm-reboot: Keenetic может обновиться и перезагрузиться.')
            sys.exit(2)
        result = install_components(client, missing)
        if result.queued:
            print(f'✅ Передано на установку: {", ".join(result.queued)}')
        for error in result.errors:
            print(f'❌ {error}')
        if result.reboot_expected:
            print('KeeneticOS применяет компоненты. Роутер может перезагрузиться; после запуска снова выполни `kwan setup`.')
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


def cmd_status(args):
    """Diagnose both transports and component availability without enabling services."""
    report = ensure_connection(args, auto_enable_ssh=False, save=False)
    print_report(report)
    client = create_router_client()
    try:
        print('\nКомпоненты KeeneticOS:')
        print('\n'.join(_component_summary(inspect_components(client))))
    finally:
        client.disconnect()


def cmd_tunnel_import(args):
    """Preview or import a standard WireGuard configuration or QR image."""
    report = ensure_connection(args)
    profile = load_wireguard_qr(args.qr) if args.qr else load_wireguard_file(args.file)
    summary = profile.summary
    print(
        f'Конфигурация: адреса {", ".join(summary["addresses"])}; '
        f'пиров {summary["peer_count"]}; AllowedIPs {summary["allowed_ip_count"]}.'
    )
    if summary['endpoints']:
        print(f'Endpoint: {", ".join(summary["endpoints"])}')
    client = create_router_client()
    try:
        result = import_wireguard_profile(
            client,
            profile,
            description=args.name,
            via=args.via,
            interface=args.interface,
            dry_run=not args.confirm,
        )
    finally:
        client.disconnect()
    if not args.confirm:
        print(f'Проверка успешна: будет создан {result.interface}, команд {result.command_count}. Роутер не изменён.')
        print('Для применения повтори команду с --confirm.')
    else:
        print(f'✅ Создан {result.interface} через {report.transport.upper()}; конфигурация сохранена.')
    for warning in result.warnings:
        print(f'⚠️ {warning}')
    if args.show_plan:
        print('\nБезопасный план команд (ключи скрыты):')
        for command in result.preview:
            print(f'  {command}')


def main():
    """Parse command-line arguments and run one isolated user operation."""
    parser = argparse.ArgumentParser(
        description='Пакетыч — выбранные сайты через WireGuard',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Примеры использования:
  %(prog)s setup                              # Первый запуск и автоматическое включение SSH
  %(prog)s --host 192.168.1.1 setup           # Другой адрес роутера
  %(prog)s status                             # Диагностика без изменения сервисов
  %(prog)s add 8.8.8.8 --tunnel wg0           # Добавить IP через wg0
  %(prog)s add google.com --tunnel wg1        # Добавить домен (все IP)
  %(prog)s add 192.168.0.0/24 --tunnel wg1    # Добавить подсеть
  %(prog)s tunnel import --file vpn.conf      # Проверить WireGuard-конфиг
  %(prog)s tunnel import --qr vpn.png         # Проверить QR-код WireGuard
  %(prog)s list                               # Показать все маршруты
  %(prog)s remove 8.8.8.8                     # Удалить маршрут
  %(prog)s remove --tunnel wg0                # Удалить все из wg0
  %(prog)s clear                              # Удалить все маршруты WG
  %(prog)s watch list                         # Показать домены автообновления
  %(prog)s sync                               # Запустить автообновление вручную
  %(prog)s inventory import                   # Сопоставить текущие маршруты с источниками
        ''',
    )

    connection = parser.add_argument_group('подключение к Keenetic')
    connection.add_argument('--host', help='IP-адрес или имя роутера')
    connection.add_argument('--user', help='Логин администратора')
    connection.add_argument('--ssh-port', type=int, help='Порт SSH, по умолчанию 22')
    connection.add_argument('--telnet-port', type=int, help='Порт Telnet, по умолчанию 23')
    connection.add_argument(
        '--password-env',
        metavar='VAR',
        help='Взять пароль из переменной окружения VAR; пароль в аргументах не принимается',
    )

    subparsers = parser.add_subparsers(dest='command', help='Команды')

    setup_parser = subparsers.add_parser('setup', help='Первое подключение и подготовка роутера')
    setup_parser.add_argument('--no-enable-ssh', action='store_true', help='Не запускать service ssh через Telnet')
    setup_parser.add_argument(
        '--install-components',
        action='store_true',
        help='Установить отсутствующие компоненты SSH/WireGuard',
    )
    setup_parser.add_argument(
        '--confirm-reboot',
        action='store_true',
        help='Разрешить components commit и возможную перезагрузку роутера',
    )
    setup_parser.set_defaults(func=cmd_setup)

    status_parser = subparsers.add_parser('status', help='Проверить транспорт, компоненты и туннели')
    status_parser.set_defaults(func=cmd_status)

    add_parser = subparsers.add_parser('add', help='Добавить маршрут')
    add_parser.add_argument('target', nargs='+', help='IP, домен или подсеть (CIDR)')
    add_parser.add_argument('--tunnel', '-t', required=True, help='WireGuard туннель (например wg0 или Wireguard0)')
    add_parser.set_defaults(func=cmd_add)

    remove_parser = subparsers.add_parser('remove', help='Удалить маршрут')
    remove_parser.add_argument('target', nargs='?', help='IP или домен для удаления')
    remove_parser.add_argument('--tunnel', '-t', help='Туннель для удаления всех маршрутов')
    remove_parser.set_defaults(func=cmd_remove)

    list_parser = subparsers.add_parser('list', help='Показать маршруты')
    list_parser.set_defaults(func=cmd_list)

    clear_parser = subparsers.add_parser('clear', help='Очистить все маршруты WG')
    clear_parser.set_defaults(func=cmd_clear)

    watch_parser = subparsers.add_parser('watch', help='Управлять доменами автообновления')
    watch_subparsers = watch_parser.add_subparsers(dest='watch_command', required=True)
    watch_list_parser = watch_subparsers.add_parser('list', help='Показать добавленные домены')
    watch_list_parser.set_defaults(func=cmd_watch_list)
    watch_remove_parser = watch_subparsers.add_parser('remove', help='Отключить автообновление домена')
    watch_remove_parser.add_argument('domain')
    watch_remove_parser.set_defaults(func=cmd_watch_remove)

    sync_parser = subparsers.add_parser('sync', help='Запустить автообновление сейчас')
    sync_parser.add_argument('--dry-run', action='store_true', help='Только проверить DNS и журнал')
    sync_parser.set_defaults(func=cmd_sync)

    tunnel_parser = subparsers.add_parser('tunnel', help='Управлять WireGuard-туннелями')
    tunnel_subparsers = tunnel_parser.add_subparsers(dest='tunnel_command', required=True)
    tunnel_import_parser = tunnel_subparsers.add_parser(
        'import', help='Импортировать стандартный .conf или QR-код'
    )
    source_group = tunnel_import_parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--file', help='Путь к WireGuard .conf')
    source_group.add_argument('--qr', help='Путь к PNG/JPEG с WireGuard QR-кодом')
    tunnel_import_parser.add_argument('--name', default='WireGuard VPN', help='Название подключения')
    tunnel_import_parser.add_argument('--via', default='ISP', help='Интерфейс выхода к VPN-серверу')
    tunnel_import_parser.add_argument('--interface', help='Свободное имя, например Wireguard2')
    tunnel_import_parser.add_argument('--confirm', action='store_true', help='Применить проверенную конфигурацию')
    tunnel_import_parser.add_argument('--show-plan', action='store_true', help='Показать команды со скрытыми ключами')
    tunnel_import_parser.set_defaults(func=cmd_tunnel_import)

    inventory_parser = subparsers.add_parser('inventory', help='Обратная инвентаризация существующих маршрутов')
    inventory_subparsers = inventory_parser.add_subparsers(dest='inventory_command', required=True)
    inventory_import_parser = inventory_subparsers.add_parser('import', help='Обновить снимок маршрутов и источников')
    inventory_import_parser.set_defaults(func=cmd_inventory_import)
    inventory_summary_parser = inventory_subparsers.add_parser('summary', help='Показать итог снимка')
    inventory_summary_parser.set_defaults(func=cmd_inventory_summary)
    inventory_lookup_parser = inventory_subparsers.add_parser('lookup', help='Найти всех владельцев IP')
    inventory_lookup_parser.add_argument('address')
    inventory_lookup_parser.set_defaults(func=cmd_inventory_lookup)
    inventory_purge_parser = inventory_subparsers.add_parser('purge-unclassified', help='Удалить неопознанные маршруты')
    inventory_purge_parser.add_argument('--dry-run', action='store_true', help='Только показать количество')
    inventory_purge_parser.add_argument('--confirm', action='store_true', help='Подтвердить удаление')
    inventory_purge_parser.add_argument(
        '--limit', type=int, default=None,
        help='Удалить не больше указанного числа маршрутов за один запуск',
    )
    inventory_purge_parser.set_defaults(func=cmd_inventory_purge)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except (RouterBootstrapError, ValueError, RuntimeError, OSError) as error:
        print(f'❌ {error}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
