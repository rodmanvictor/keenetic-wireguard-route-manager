# Командная строка и TUI

PackeTech можно использовать без графического окна: обычными командами или
через интерактивное меню.

![PackeTech CLI](../images/packetech-cli.png)

## Установка через Python

Для разработчиков и серверов с Python 3.10+:

```bash
python3 -m pip install "git+https://github.com/rodmanvictor/packetech.git"
```

После установки доступны единая команда `packetech` и отдельная
`packetech-cli`. На Windows и macOS готовые сборки используют имена, указанные
в [системных инструкциях](README.md).

## Первый вход

```bash
packetech setup
```

Команда спросит пароль администратора Keenetic и сохранит профиль. Пароль
нельзя передать обычным аргументом: так он не попадёт в историю shell.

Для автоматического скрипта используйте переменную окружения:

```bash
export ROUTER_PASSWORD='секрет'
packetech --password-env ROUTER_PASSWORD status
```

## Основные команды

| Команда | Что делает |
|---|---|
| `packetech status` | Проверяет подключение, SSH и WireGuard-профили |
| `packetech add example.com --tunnel wg1` | Добавляет домен и включает автообновление |
| `packetech list` | Показывает маршруты IPv4 и IPv6 |
| `packetech watch list` | Показывает отслеживаемые домены |
| `packetech sync` | Обновляет DNS-маршруты сейчас |
| `packetech remove example.com` | Отключает домен и безопасно снимает его маршруты |
| `packetech --help` | Показывает полный список команд |

## Интерактивное меню

```bash
packetech tui
```

![PackeTech TUI](../images/packetech-tui.png)

В TUI можно добавить домен, выбрать готовый сервис, запустить обновление и
посмотреть журнал. Это тот же реестр и то же сетевое ядро, что в графическом
приложении.

## Совместимость

Старые команды остаются рабочими в существующих установках, но новые инструкции
и скрипты должны использовать `packetech` или `packetech-cli`.

