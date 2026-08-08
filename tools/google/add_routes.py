#!/usr/bin/env python3
"""
Добавить все IP-диапазоны Google через WireGuard туннель
Для доступа к Gemini, YouTube, Google Services
"""

import sys
import os
import time

# Добавляем путь к модулю
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from keenetic_router.core.router import (
    ROUTER_HOST,
    ROUTER_USE_SSH,
    create_router_client,
    discover_wireguard_tunnels,
    normalize_tunnel_name,
    parse_wireguard_routes_output,
    prefix_to_mask,
)

# Все IPv4 диапазоны Google (из https://www.gstatic.com/ipranges/goog.json)
GOOGLE_PREFIXES = [
    "8.8.4.0/24",
    "8.8.8.0/24",
    "8.34.208.0/20",
    "8.35.192.0/20",
    "8.228.0.0/14",
    "8.232.0.0/14",
    "8.236.0.0/15",
    "23.236.48.0/20",
    "23.251.128.0/19",
    "34.0.0.0/15",
    "34.2.0.0/16",
    "34.3.0.0/23",
    "34.3.3.0/24",
    "34.3.4.0/24",
    "34.3.8.0/21",
    "34.3.16.0/20",
    "34.3.32.0/19",
    "34.3.64.0/18",
    "34.4.0.0/14",
    "34.8.0.0/13",
    "34.16.0.0/12",
    "34.32.0.0/11",
    "34.64.0.0/10",
    "34.128.0.0/10",
    "35.184.0.0/13",
    "35.192.0.0/14",
    "35.196.0.0/15",
    "35.198.0.0/16",
    "35.199.0.0/17",
    "35.199.128.0/18",
    "35.200.0.0/13",
    "35.208.0.0/12",
    "35.224.0.0/12",
    "35.240.0.0/13",
    "35.252.0.0/14",
    "64.15.112.0/20",
    "64.233.160.0/19",
    "66.102.0.0/20",
    "66.249.64.0/19",
    "70.32.128.0/19",
    "72.14.192.0/18",
    "74.114.24.0/21",
    "74.125.0.0/16",
    "104.154.0.0/15",
    "104.196.0.0/14",
    "104.237.160.0/19",
    "107.167.160.0/19",
    "107.178.192.0/18",
    "108.59.80.0/20",
    "108.170.192.0/18",
    "108.177.0.0/17",
    "130.211.0.0/16",
    "136.22.2.0/23",
    "136.22.4.0/23",
    "136.22.8.0/22",
    "136.22.160.0/20",
    "136.22.176.0/21",
    "136.22.184.0/23",
    "136.22.186.0/24",
    "136.23.48.0/20",
    "136.23.64.0/18",
    "136.64.0.0/11",
    "136.107.0.0/16",
    "136.108.0.0/14",
    "136.112.0.0/13",
    "136.120.0.0/22",
    "136.124.0.0/15",
    "142.250.0.0/15",
    "146.148.0.0/17",
    "162.120.128.0/17",
    "162.216.148.0/22",
    "162.222.176.0/21",
    "172.110.32.0/21",
    "172.217.0.0/16",
    "172.253.0.0/16",
    "173.194.0.0/16",
    "173.255.112.0/20",
    "192.104.160.0/23",
    "192.158.28.0/22",
    "192.178.0.0/15",
    "193.186.4.0/24",
    "199.36.154.0/23",
    "199.36.156.0/24",
    "199.192.112.0/22",
    "199.223.232.0/21",
    "207.175.0.0/16",
    "207.223.160.0/20",
    "208.65.152.0/22",
    "208.68.108.0/22",
    "208.81.188.0/22",
    "208.117.224.0/19",
    "209.85.128.0/17",
    "216.58.192.0/19",
    "216.73.80.0/20",
    "216.239.32.0/19",
    "216.252.220.0/22",
]


def cidr_to_mask(cidr):
    """Преобразовать CIDR в маску"""
    prefix = int(cidr.split('/')[1])
    return prefix_to_mask(prefix)


def get_existing_routes(keenetic):
    """Получить существующие маршруты"""
    output = keenetic.command('show ip route')
    return parse_wireguard_routes_output(output)


def add_route(keenetic, ip, mask, interface):
    """Добавить маршрут"""
    cmd = f'ip route {ip} {mask} 0.0.0.0 {interface}'
    result = keenetic.command(cmd)
    return 'error' not in result.lower()


def delete_route(keenetic, ip, mask, interface):
    """Удалить маршрут"""
    cmd = f'no ip route {ip} {mask} {interface}'
    result = keenetic.command(cmd)
    return 'error' not in result.lower()


def save_config(keenetic):
    """Сохранить конфигурацию"""
    result = keenetic.command('system configuration save')
    return 'done' in result.lower() or 'ok' in result.lower() or 'Saving' in result


def main():
    # Выбор туннеля
    tunnel = 'wg0'
    if len(sys.argv) > 1:
        tunnel = sys.argv[1]

    print(f"╔═══════════════════════════════════════════════════════════╗")
    print(f"║     Добавление всех IP-диапазонов Google                  ║")
    print(f"║     Туннель: {tunnel}")
    print(f"╚═══════════════════════════════════════════════════════════╝")
    print()

    # Подключение к роутеру
    print("📡 Подключение к роутеру...")
    try:
        kt = create_router_client()
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        sys.exit(1)

    print(f"✅ Подключено к {ROUTER_HOST}")

    # Обновление карты туннелей
    TUNNEL_INTERFACES, TUNNEL_FULL_NAMES = discover_wireguard_tunnels(kt)

    print(f"📡 Доступные туннели: {TUNNEL_INTERFACES}")

    if tunnel not in TUNNEL_INTERFACES:
        print(f"❌ Туннель {tunnel} не найден!")
        print(f"Доступные туннели: {list(TUNNEL_INTERFACES.keys())}")
        sys.exit(1)

    interface = TUNNEL_INTERFACES[tunnel]
    print(f"✅ Туннель: {interface}")
    print()

    # Получение существующих маршрутов
    print("📋 Получение существующих маршрутов...")
    existing_routes = get_existing_routes(kt)
    existing_set = set()
    for route in existing_routes:
        if interface in route.get('interface', ''):
            existing_set.add((route['network'].split('/')[0], route['network'].split('/')[1] if '/' in route['network'] else '255.255.255.255'))

    # Добавление маршрутов
    print(f"🚀 Добавление {len(GOOGLE_PREFIXES)} маршрутов Google...")
    print()

    added = 0
    skipped = 0
    errors = 0

    for i, cidr in enumerate(GOOGLE_PREFIXES, 1):
        ip, prefix = cidr.split('/')
        mask = cidr_to_mask(cidr)

        # Проверка существующего маршрута
        if (ip, mask) in existing_set:
            print(f"  ⏭️  [{i:3d}/{len(GOOGLE_PREFIXES)}] {cidr:<20} — уже есть")
            skipped += 1
            continue

        # Добавление
        if add_route(kt, ip, mask, interface):
            print(f"  ✅ [{i:3d}/{len(GOOGLE_PREFIXES)}] {cidr:<20} — добавлен")
            added += 1
        else:
            print(f"  ❌ [{i:3d}/{len(GOOGLE_PREFIXES)}] {cidr:<20} — ошибка")
            errors += 1

        # Небольшая задержка для стабильности
        if i % 10 == 0:
            time.sleep(0.5)

    # Сохранение конфигурации
    print()
    print("💾 Сохранение конфигурации...")
    if save_config(kt):
        print("✅ Конфигурация сохранена")
    else:
        print("⚠️  Не удалось сохранить конфигурацию")

    # Итоги
    print()
    print("╔═══════════════════════════════════════════════════════════╗")
    print(f"║  ИТОГО: {len(GOOGLE_PREFIXES)} маршрутов                              ║")
    print(f"║  ✅ Добавлено: {added:<3}                                           ║")
    print(f"║  ⏭️  Пропущено: {skipped:<3}                                           ║")
    print(f"║  ❌ Ошибок: {errors:<3}                                              ║")
    print("╚═══════════════════════════════════════════════════════════╝")
    print()
    print("📝 Для проверки:")
    print(f"   kwtui → пункт 3 (Показать все маршруты)")
    print("   или: kwan list")
    print()


if __name__ == '__main__':
    main()
