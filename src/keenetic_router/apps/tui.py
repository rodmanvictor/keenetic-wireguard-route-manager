"""Small terminal dashboard for recurring Keenetic service routes."""

import os
import subprocess
from datetime import datetime, timedelta

from keenetic_router.services.registry import (
    add_managed_domain,
    inventory_services,
    list_managed_domains,
    recent_events,
    recent_runs,
    remove_managed_domain,
    source_label,
    split_sources,
)
from keenetic_router.services.registry import inventory_summary
from keenetic_router.services.sync import sync_domains
from keenetic_router.services.cleanup import purge_domain_routes
from keenetic_router.services.catalog import (
    SERVICE_DOMAINS,
    add_catalog_services,
    available_services,
    parse_selection,
    reconcile_inventory_domains,
)


class Colors:
    """ANSI escape sequences used to keep the terminal dashboard readable."""

    HEADER = '\033[95m'
    OK = '\033[92m'
    INFO = '\033[96m'
    WARN = '\033[93m'
    ERROR = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'


def clear_screen():
    """Clear the active terminal before rendering the next dashboard screen."""
    os.system('clear' if os.name != 'nt' else 'cls')


def next_scheduled_run(now=None):
    """Return the next six-hour calendar slot used by the local timer."""
    current = now or datetime.now().astimezone()
    candidate = current.replace(minute=0, second=0, microsecond=0)
    candidate = candidate.replace(hour=(candidate.hour // 6) * 6) + timedelta(hours=6)
    return candidate


def scheduler_next_run():
    """Return systemd's actual next timer time, if the local timer is enabled."""
    result = subprocess.run(
        ['systemctl', '--user', 'show', 'keenetic-route-sync.timer', '--property=NextElapseUSecRealtime', '--value'],
        capture_output=True,
        text=True,
        check=False,
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def pause():
    """Wait for the user before returning to the main menu."""
    input('\nНажмите Enter...')


def render_header():
    """Print the persistent dashboard heading and upcoming scheduled run."""
    print(f"{Colors.HEADER}{Colors.BOLD}Keenetic: маршруты сервисов{Colors.END}")
    next_run = scheduler_next_run()
    if next_run:
        print(f'Следующее плановое обновление: {next_run}')
    else:
        print(f"Следующее плановое обновление: {next_scheduled_run().strftime('%d.%m %H:%M')} (таймер ещё не включён)")
    print()


def render_menu():
    """Print the intentionally small set of everyday administration actions."""
    print('1. Добавить домен в автообновление')
    print('2. Быстро добавить сервисы из rucens')
    print('3. Показать сервисы и домены')
    print('4. Обновить сейчас')
    print('5. Статус и журнал')
    print('6. Отключить автообновление домена')
    print('0. Выход')


def select_domain_row(domain):
    """Return a domain database row by canonical name, or ``None`` if absent."""
    return next((row for row in list_managed_domains() if row['domain'] == domain), None)


def add_domain():
    """Register a domain and optionally apply its current addresses immediately."""
    domain_input = input('Домен, например chatgpt.com: ').strip()
    tunnel = input('Туннель [wg1]: ').strip() or 'wg1'
    try:
        domain, created = add_managed_domain(domain_input, tunnel, source='terminal')
    except ValueError as error:
        print(f'{Colors.ERROR}❌ {error}{Colors.END}')
        return

    print(f"{Colors.OK}{'✅ Добавлен' if created else '↻ Обновлён'}: {domain} → {tunnel}{Colors.END}")
    if input('Добавить текущие IP на роутер сейчас? [Y/n]: ').strip().lower() not in {'n', 'no', 'н'}:
        summary = sync_domains([select_domain_row(domain)])
        print(f'Маршруты: добавлено {summary.added}, без изменений {summary.unchanged}, ошибок {summary.errors}.')


def show_domains():
    """Render recovered services and new recurring-domain subscriptions."""
    reconcile_inventory_domains()
    services = inventory_services()
    domains = list_managed_domains()
    if services:
        print('Уже восстановлено из маршрутов:')
        print(f"{'Сервис':<28} {'Источник':<14} {'Маршрутов'}")
        print('-' * 60)
        for service in services:
            print(f"{service['source_name']:<28} {service['source_kind']:<14} {service['route_count']}")
    else:
        print('Существующие маршруты ещё не проинвентаризированы.')

    print('\nДомены, добавленные для регулярного DNS-обновления:')
    if not domains:
        print('— пока нет; добавь первый домен через пункт 1.')
        return
    print(f"{'Домен':<34} {'Туннель':<9} {'Источник':<24} {'Последний DNS'}")
    print('-' * 104)
    for domain in domains:
        status = '' if domain['enabled'] else ' (выключен)'
        sources = ', '.join(source_label(item) for item in split_sources(domain['sources'])) or '—'
        print(
            f"{domain['domain']:<34} {domain['tunnel']:<9} {sources:<24} "
            f"{domain['last_resolved_at'] or 'ещё не было'}{status}"
        )


def add_catalog_services_menu():
    """Let the user select one or more rucens services by display number."""
    try:
        services = available_services()
    except Exception as error:
        print(f'{Colors.ERROR}Не удалось загрузить каталог rucens: {error}{Colors.END}')
        return
    print('Готовые сервисы из rucens:')
    for index, service in enumerate(services, start=1):
        domains = ', '.join(SERVICE_DOMAINS.get(service, ())) or 'DNS-домен не задан'
        print(f'{index:>2}. {service:<16} — {domains}')
    raw_selection = input('\nНомера через пробел или запятую: ')
    try:
        selected = [services[index] for index in parse_selection(raw_selection, len(services))]
    except ValueError as error:
        print(f'{Colors.ERROR}❌ {error}{Colors.END}')
        return
    tunnel = input('Туннель [wg1]: ').strip() or 'wg1'
    print(f'Добавляю: {", ".join(selected)}...')
    try:
        summary = add_catalog_services(selected, tunnel)
    except Exception as error:
        print(f'{Colors.ERROR}❌ Не удалось применить список: {error}{Colors.END}')
        return
    print(
        f'{Colors.OK}Готово: добавлено {summary.added}, без изменений {summary.unchanged}, '
        f'ошибок {summary.errors}; DNS-наблюдение: {summary.watched_domains} домен(ов).{Colors.END}'
    )


def run_update():
    """Run an on-demand synchronization and print its concise summary."""
    summary = sync_domains()
    color = Colors.OK if summary.status == 'success' else Colors.WARN
    print(f'{color}Готово: добавлено {summary.added}, без изменений {summary.unchanged}, ошибок {summary.errors}.{Colors.END}')


def show_status_and_log():
    """Show latest synchronization result and recent domain-level events."""
    runs = recent_runs(1)
    if not runs:
        print('Обновлений ещё не было.')
    else:
        run = runs[0]
        print(f"Последнее обновление: {run['finished_at'] or run['started_at']} — {run['status']}")
        print(f"Добавлено: {run['added_count']}; без изменений: {run['unchanged_count']}")
        if run['error_text']:
            print(f"Ошибка: {run['error_text']}")

    events = recent_events(12)
    if events:
        print('\nПоследние изменения:')
        for event in events:
            target = event['domain'] or 'система'
            address = f" {event['address']}" if event['address'] else ''
            print(f"- {event['occurred_at']}: {target}{address} — {event['detail']}")

    inventory = inventory_summary()
    if inventory and inventory['routes']:
        print(
            f"\nКарта текущих маршрутов: {inventory['routes']} всего; "
            f"{inventory['shared'] or 0} общих; {inventory['unclassified'] or 0} сохранены как неопознанные."
        )


def disable_domain():
    """Disable recurring updates for one domain without deleting route history."""
    domain = input('Какой домен отключить: ').strip()
    try:
        removed = remove_managed_domain(domain)
    except ValueError as error:
        print(f'{Colors.ERROR}❌ {error}{Colors.END}')
        return
    if not removed:
        print('Домен не найден.')
        return
    cleanup = purge_domain_routes(domain)
    print(
        f'⏸️ Автообновление отключено. Удалено маршрутов: {cleanup["removed"]}; '
        f'общие маршруты сохранены.'
    )


def main():
    """Run the interactive everyday route-management dashboard."""
    while True:
        clear_screen()
        render_header()
        render_menu()
        choice = input('\nВыбор: ').strip()
        if choice == '1':
            add_domain()
        elif choice == '2':
            add_catalog_services_menu()
        elif choice == '3':
            show_domains()
        elif choice == '4':
            run_update()
        elif choice == '5':
            show_status_and_log()
        elif choice == '6':
            disable_domain()
        elif choice == '0':
            break
        else:
            print('Неверный пункт.')
        if choice != '0':
            pause()


if __name__ == '__main__':
    main()
