#!/usr/bin/env python3
"""
Импорт маршрутов из формата Windows route
Пример использования:
  python3 keenetic-import-routes.py routes.txt --tunnel wg1
"""

import argparse
import sys
import time

from keenetic_router.core.router import (
    ROUTER_HOST,
    create_telnet_client,
    discover_wireguard_tunnels,
    full_interface_name,
    normalize_tunnel_name,
    parse_windows_route,
)


def add_route(kt, ip, mask, interface):
    cmd = f'ip route {ip} {mask} 0.0.0.0 {interface}'
    result = kt.command(cmd)
    return 'error' not in result.lower()


def save_config(kt):
    result = kt.command('system configuration save')
    return 'done' in result.lower() or 'ok' in result.lower() or 'saving' in result.lower()


def main():
    parser = argparse.ArgumentParser(description='Импорт маршрутов из Windows route формата')
    parser.add_argument('file', help='Файл со списком маршрутов')
    parser.add_argument('--tunnel', '-t', required=True, help='WireGuard туннель (например wg0 или Wireguard0)')
    parser.add_argument('--dry-run', action='store_true', help='Только показать, не добавлять')
    args = parser.parse_args()

    routes = []
    try:
        with open(args.file, 'r', encoding='utf-8') as f:
            for line in f:
                route = parse_windows_route(line)
                if route:
                    routes.append(route)
    except FileNotFoundError:
        print(f"❌ Файл не найден: {args.file}")
        sys.exit(1)

    if not routes:
        print('❌ Не найдено маршрутов в файле')
        sys.exit(1)

    print(f"\n📋 Найдено маршрутов: {len(routes)}")

    if args.dry_run:
        print('🔍 DRY RUN - только просмотр:\n')
        for index, route in enumerate(routes[:20], 1):
            print(f"  {index}. {route['ip']} mask {route['mask']}")
        if len(routes) > 20:
            print(f"  ... и ещё {len(routes) - 20}")
        return

    print(f"⏳ Подключение к {ROUTER_HOST}...")

    kt = create_telnet_client(send_char_delay=0.03, command_wait=1.0)
    try:
        kt.connect()
        print('✅ Подключено\n')

        tunnel_interfaces, tunnel_full_names = discover_wireguard_tunnels(kt)
        tunnel = normalize_tunnel_name(args.tunnel, tunnel_interfaces, tunnel_full_names)
        if tunnel not in tunnel_interfaces:
            available = ', '.join(tunnel_interfaces.keys()) if tunnel_interfaces else 'не найдены'
            print(f"❌ Неверный туннель. Доступны: {available}")
            sys.exit(1)

        interface = full_interface_name(tunnel, tunnel_interfaces, tunnel_full_names)
        print(f"🎯 Туннель: {interface}\n")

        added = 0
        errors = 0

        for index, route in enumerate(routes, 1):
            ip = route['ip']
            mask = route['mask']

            if add_route(kt, ip, mask, interface):
                print(f"  ✅ [{index}/{len(routes)}] {ip}/{mask}")
                added += 1
            else:
                print(f"  ❌ [{index}/{len(routes)}] {ip}/{mask}")
                errors += 1

            if index % 10 == 0:
                time.sleep(0.5)

        if added > 0:
            print('\n💾 Сохранение конфигурации...')
            if save_config(kt):
                print('✅ Сохранено')

        print(f"\n{'=' * 50}")
        print(f"✅ Добавлено: {added}")
        print(f"❌ Ошибок: {errors}")
        print(f"{'=' * 50}")

    except Exception as exc:
        print(f'❌ Ошибка: {exc}')
        sys.exit(1)
    finally:
        kt.disconnect()


if __name__ == '__main__':
    main()
