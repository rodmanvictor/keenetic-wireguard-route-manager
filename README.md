# Keenetic Route Manager

Открытое приложение для выборочной маршрутизации сайтов и IP-адресов через WireGuard на роутерах Keenetic.

Один и тот же Python-код работает как:

- самостоятельная команда `kwan` для Windows, macOS и Linux;
- desktop-приложение с подключением к роутеру, доменами, IP и импортом WireGuard;
- локальный шестичасовой синхронизатор DNS-маршрутов;
- ядро Chrome-расширения для быстрого добавления текущего сайта.

## Первый запуск

После установки или распаковки нативной сборки:

```bash
kwan setup
```

Программа попросит пароль скрытым вводом, проверит SSH и Telnet и сохранит только адрес, логин и порты. Если SSH выключен, она подключится по Telnet, выполнит `service ssh`, сохранит конфигурацию и проверит реальный вход по SSH.

Если компоненты SSH или WireGuard отсутствуют:

```bash
kwan setup --install-components --confirm-reboot
```

`components commit` может обновить KeeneticOS и перезагрузить роутер, поэтому без явного подтверждения эта операция не запускается.

Импорт VPN:

```bash
kwan tunnel import --file provider.conf
kwan tunnel import --file provider.conf --confirm
kwan tunnel import --qr provider-qr.png --confirm
```

Первый вызов только проверяет конфигурацию. Приватные ключи передаются на Keenetic исключительно по SSH и не выводятся в журнал.

Добавление маршрутов:

```bash
kwan add chatgpt.com --tunnel wg1
kwan add 203.0.113.15 --tunnel wg1
kwan list
kwan sync
```

Desktop-приложение запускается командой `keenetic-desktop` или готовым приложением из GitHub Release.

## Установка из исходников

Требуется Python 3.10 или новее:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/kwan setup
```

В Windows путь к Python внутри окружения будет `.venv\Scripts\python.exe`.

Нативные архивы CLI и desktop для трёх платформ собираются автоматически при публикации тега `v*`.

## Безопасность и совместимость

- Пароль администратора не сохраняется в пользовательском JSON.
- Аргумента `--password` нет: для автоматизации используется `--password-env`.
- Telnet служит только для первичного запуска SSH и медленного аварийного режима.
- WireGuard-конфиги и QR никогда не импортируются через Telnet.
- Установка компонентов зависит от модели, свободной памяти, версии KeeneticOS и доступа роутера в интернет.
- Текущая версия управляет IPv4-маршрутами. IPv6, DNS и MTU из WireGuard-профиля не применяются автоматически.

Полная документация: [docs/README.md](docs/README.md).

## Разработка

```bash
python -m pip install -r requirements-dev.txt -e .
npm run test:python
npm run docs:check
python scripts/build-cli.py
```

Проект распространяется по лицензии [MIT](LICENSE).
